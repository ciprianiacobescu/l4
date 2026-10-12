"""The click shell: parses options, builds the AppContext, delegates to `commands.dispatch`."""

import contextlib
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import click

from l4 import __version__, cancel
from l4.commands import dispatch
from l4.config.defaults import DEFAULT_REDACT_ENV, RUNNER_SECRET_ENV
from l4.context import AppContext
from l4.exitcodes import ExitCode, classify_exception
from l4.log import configure_logging
from l4.outcome import OUTCOME_COMMANDS, new_run_id, run_guarded, with_outcome
from l4.redact import Redactor


def redactor_for(environ: Mapping[str, str]) -> Redactor:
    """Before any config is read, redact the documented default variables (SPEC 3.2 `observability.redact_env`)."""
    return Redactor.from_env((*DEFAULT_REDACT_ENV, *RUNNER_SECRET_ENV), environ)


_COMMON_KEYS = ("config_path", "repo", "log_format", "verbose", "quiet")


def _common() -> list[click.Parameter]:
    return [
        click.Option(["--config", "config_path"], type=click.Path(dir_okay=False, path_type=Path),
                     help="Config file (default: <repo>/.l4/config.yaml)."),
        click.Option(["--repo"], type=click.Path(exists=True, file_okay=False, path_type=Path),
                     help="Repository root (default: the current directory)."),
        click.Option(["--log-format", "log_format"], type=click.Choice(["human", "json"]), default="human",
                     show_default=True, help="Console log format (stderr)."),
        click.Option(["-v", "verbose"], count=True, help="More output (repeatable)."),
        click.Option(["-q", "quiet"], count=True, help="Less output (repeatable)."),
    ]  # fmt: skip


def _opt(*names: str, **kw: Any) -> click.Option:
    return click.Option(list(names), **kw)


def _TOKEN_COMMAND() -> click.Option:  # noqa: N802 - a constant-like option factory
    return _opt(
        "--token-command", "token_command", envvar="L4_TOKEN_COMMAND", show_envvar=True,
        help="Command (no shell) that prints a new credential on its stdout; run once when the forge answers 401.",
    )  # fmt: skip


def _flag(*names: str, **kw: Any) -> click.Option:
    return click.Option(list(names), is_flag=True, **kw)


def _units() -> click.Option:
    return _opt("--unit", "units", multiple=True, help="Unit id (repeatable).")


def _unit(required: bool = False) -> click.Option:
    return _opt("--unit", "unit", required=required, help="Unit id.")


# command -> (help, parameter factory); handler keyword arguments are the parameter names
_SPECS: dict[str, tuple[str, Callable[[], list[click.Parameter]]]] = {
    "init": ("Adopt the harness in a repo.", lambda: [
        _opt("--ci", "ci", type=click.Choice(["github", "gitlab", "both"])),
        _opt("--framework", "framework", type=click.Choice(["openspec", "kiro"])),
        _flag("--vendor", "vendor"), _flag("--dry-run", "dry_run"), _flag("--force", "force"),
        _flag("--no-ci-edit", "no_ci_edit", help="Print the .gitlab-ci.yml include instead of writing it."),
        _opt("--harness", "harness", type=click.Path(exists=True, file_okay=False, path_type=Path),
             help="Harness checkout to vendor (default: the one l4 runs from)."),
        _opt("--harness-repo", "harness_repo", help="Fetch the harness at run time from this git URL, no .l4/vendor/."),
        _opt("--harness-commit", "harness_commit_pin",
             help="With --harness-repo: the commit to fetch (default: the running harness's)."),
    ]),
    "upgrade": ("Bring the vendored harness, the CI template and the shim up to the harness checkout.", lambda: [
        _opt("--harness", "harness", type=click.Path(exists=True, file_okay=False, path_type=Path),
             help="Harness checkout to vendor (default: the one l4 runs from)."),
        _flag("--dry-run", "dry_run"),
        _opt("--harness-commit", "harness_commit_pin",
             help="Fetched adoption: the commit to pin (default: the running harness's)."),
    ]),
    "doctor": ("Check environment, config, specs, git, forge, CI and state.", lambda: [
        _flag("--ci", "ci"), _flag("--live", "live"), _flag("--fix", "fix"), _unit(), _flag("--json", "as_json"),
        _flag("--adoption", "adoption", help="The repository's own rows and a dry run of the gates at HEAD."),
        _flag("--no-gates", "no_gates", help="With --adoption: skip the gate dry run (config rows only)."),
    ]),
    "plan": ("Detect units and compute the next action for each.", lambda: [
        _units(), _flag("--json", "as_json"), _flag("--probe", "probe"), _flag("--sweep", "sweep"),
        _flag("--detailed-exitcode", "detailed_exitcode"),
    ]),
    "run": ("Advance units through the lifecycle.", lambda: [
        _units(), _opt("--max-units", "max_units", type=int), _opt("--time-budget", "time_budget"),
        _flag("--dry-run", "dry_run"), _flag("--probe", "probe"),
    ]),
    "status": ("Show units, phases, open questions, last verdict and cool-downs.", lambda: [
        _unit(), _flag("--json", "as_json"), _flag("--rebuild", "rebuild"),
    ]),
    "probe": ("Run availability probes.", lambda: [
        click.Argument(["profiles"], nargs=-1), _opt("--role", "role"), _flag("--json", "as_json"),
        _flag("--no-cache", "no_cache"),
    ]),
    "verify": ("Run only the verifier on a unit.", lambda: [_unit(True), _flag("--dry-run", "dry_run")]),
    "archive": ("Run the done-gate and archive a unit.", lambda: [
        _unit(True), _flag("--retry", "retry", help="Try again an archive that failed on the same inputs."),
    ]),
    "questions": ("List, show, answer or accept questions of a unit.", lambda: [
        click.Argument(["words"], nargs=-1), _unit(), _opt("--text", "text"),
    ]),
    "lessons": ("Inspect and curate lessons.", lambda: [click.Argument(["words"], nargs=-1)]),
    "s1": ("S1 data set: export, canary, score, report, audit (M1.6).", lambda: [
        click.Argument(["words"], nargs=-1),
        _opt("--out", "out", type=click.Path(path_type=Path)),
        _opt("--source", "source", multiple=True, type=click.Path(exists=True, dir_okay=False, path_type=Path)),
        _opt("--also-repo", "also_repo", multiple=True,
             type=click.Path(exists=True, file_okay=False, path_type=Path), help="Further canary repositories."),
        _opt("--seed", "seed", type=int), _opt("--target", "target", type=int),
        _opt("--min-test", "min_test", type=int), _opt("--max-variants", "max_variants", type=int),
        _flag("--allow-gaps", "allow_gaps"),
        _opt("--test-command", "test_command"), _opt("--profile", "profile"),
        _opt("--dataset", "dataset", type=click.Path(path_type=Path)),
        _opt("--max-requests", "max_requests", type=int), _opt("--sample", "sample", type=int),
        _opt("--import", "import_file", type=click.Path(exists=True, dir_okay=False, path_type=Path)),
        _opt("--gate", "gate", type=click.Path(exists=True, dir_okay=False, path_type=Path)),
    ]),
    "simulate": ("Run the real state machine against fakes.", lambda: [
        click.Argument(["scenarios"], nargs=-1), _flag("--all", "all_scenarios"),
        _flag("--with-repo-config", "with_repo_config"), _flag("--keep", "keep"), _flag("--json", "as_json"),
    ]),
    "unlock": ("Release a lock.", lambda: [_unit(True), _flag("--force", "force")]),
    "resume": ("Leave halted/escalated and reset breaker counters (members only).", lambda: [
        _unit(True), _opt("--reason", "reason", required=True),
        _opt("--extend-iterations", "extend_iterations", type=int),
        _opt("--extend-cost", "extend_cost", type=float),
        _opt("--extend-fix-rounds", "extend_fix_rounds", type=int),
        _opt("--extend-feedback-rounds", "extend_feedback_rounds", type=int),
    ]),
    "setup gitlab": ("Make the GitLab project ready for the harness: token, secrets, schedule, runner check.", lambda: [
        _opt("--project", "project", required=True, help="Project id or path (group/name)."),
        _opt("--api-base", "api_base", help="GitLab API base (default: forge.gitlab.api_url, else from `origin`)."),
        _opt("--auth-env", "auth_env", default="GITLAB_TOKEN", show_default=True,
             help="Environment variable that holds the maintainer's credential."),
        _opt("--auth-scheme", "auth_scheme", type=click.Choice(["private-token", "bearer"]), default="private-token",
             show_default=True, help="How the credential is sent (bearer: a proxy such as Mintkey)."),
        _opt("--verify-base", "verify_base", help="GitLab API base where the new bot token is verified."),
        _flag("--rotate", "rotate", help="Create a new bot token and replace the variable."),
        _flag("--revoke-old", "revoke_old", help="With --rotate: revoke older tokens once the new one verifies."),
        _opt("--secret", "secret", multiple=True, help="NAME=ENVVAR: copy a secret into a masked variable (repeat)."),
        _opt("--cron", "cron", default="*/30 * * * *", show_default=True, help="Schedule of the l4 sweep."),
        _flag("--no-schedule", "no_schedule"), _flag("--no-pipeline", "no_pipeline"),
        _flag("--watch", "watch", help="Follow the check pipeline to its end."),
        _flag("--dry-run", "dry_run", help="Send only reads; say what would change."),
        _TOKEN_COMMAND(),
    ]),
    "setup github": ("Make the GitHub repository ready: permissions, environment, secrets, labels.", lambda: [
        _opt("--repo", "github_repo", help="owner/name (default: `origin`); a directory is the checkout."),
        _opt("--api-url", "api_url", help="GitHub API base (default: GITHUB_API_URL, else api.github.com)."),
        _opt("--token-env", "token_env", default="GH_TOKEN", show_default=True,
             help="Environment variable that holds a token with admin rights on the repository."),
        _opt("--secret", "secret", multiple=True,
             help="NAME=ENVVAR: seal a secret into the environment (repeat)."),
        _flag("--watch", "watch", help="Follow the dispatched run to its end."),
        _flag("--dry-run", "dry_run", help="Send only reads; say what would change."),
    ]),
    "ci render": ("Print generated CI files.", lambda: [
        _opt("--platform", "platform", required=True, type=click.Choice(["github", "gitlab"])),
    ]),
    "ci watch": ("Follow a GitLab pipeline or a GitHub run to its end.", lambda: [
        _opt("--project", "project", help="GitLab project id or path (group/name)."),
        _opt("--repo", "github_repo", help="GitHub owner/name: follow the newest run of l4.yml on --ref."),
        _opt("--api-url", "api_url", help="GitHub API base (default: GITHUB_API_URL, else api.github.com)."),
        _opt("--pipeline", "pipeline", type=int, help="Pipeline id (default: the latest of --ref)."),
        _opt("--ref", "ref", help="Branch whose latest pipeline to follow (default: the default branch)."),
        _opt("--api-base", "api_base", help="GitLab API base (default: forge.gitlab.api_url, else from `origin`)."),
        _opt("--auth-env", "auth_env", help="Credential variable (default GITLAB_TOKEN; GH_TOKEN for --repo)."),
        _opt("--auth-scheme", "auth_scheme", type=click.Choice(["private-token", "bearer"]), default="private-token",
             show_default=True, help="How the credential is sent."),
        _opt("--interval", "interval", default="15s", show_default=True),
        _opt("--timeout", "timeout", default="90m", show_default=True),
        _opt("--tail", "tail", type=int, default=0, show_default=True,
             help="Print the last N trace lines of each failed job."),
        _TOKEN_COMMAND(),
    ]),
    "ci render-child": ("Print the GitLab child pipeline.", lambda: [
        _opt("--plan", "plan", required=True, type=click.Path(dir_okay=False, path_type=Path)),
    ]),
    "ci map-exit": ("Translate an l4 exit code into the CI platform's convention.", lambda: [
        click.Argument(["code"], type=int),
    ]),
    "eval": ("Measure profiles on a fixed seed set, and compare two measurements (M1.14).", lambda: [
        _opt("--impl", "impl", multiple=True, help="Implementer profile to score (repeatable)."),
        _opt("--judge", "judge", multiple=True, help="Judge profile to score (repeatable)."),
        _opt("--ref-judge", "ref_judge", help="Fixed judge profile that ends an implementer cell in a verdict."),
        _units(),
        _opt("--k", "k", type=int, default=1, show_default=True, help="Repetitions of every cell."),
        _opt("--out", "out", type=click.Path(file_okay=False, path_type=Path), help="Directory of the run."),
        _opt("--cell-timeout", "cell_timeout", default="50m", show_default=True),
        _flag("--runner", "runner", help="Record that this machine is the CI runner."),
        _flag("--dry-run", "dry_run", help="Print the cell matrix; start nothing, write nothing."),
        _flag("--resume", "resume", help="Skip the cells of --out that already have a result for this seed set."),
        _opt("--idle-check", "idle_check", help="Command (no shell) run before each cell; exit 0 means start."),
        _opt("--idle-wait", "idle_wait", default="30m", show_default=True, help="How long to wait for --idle-check."),
        _flag("--warm-cache", "warm_cache", help="Warm the uv cache of the seed base project (needs the network)."),
        _opt("--seeds", "seeds", type=click.Path(file_okay=False, path_type=Path),
             help="Seed set directory (default: tests/eval/seeds of the harness checkout)."),
        _opt("--compare", "compare", type=click.Path(dir_okay=False, path_type=Path),
             help="Old scorecard.json to compare with; exit 15 when a profile regressed."),
        _opt("--new", "new", type=click.Path(dir_okay=False, path_type=Path),
             help="With --compare: the new scorecard.json (default: run first, then compare)."),
        _opt("--baseline-dir", "baseline_dir", type=click.Path(file_okay=False, path_type=Path),
             help="With --compare: pick the newest baseline there that matches the seed set."),
        _opt("--max-drop", "max_drop", type=float, default=0.20, show_default=True,
             help="Largest drop of a pass rate that does not regress."),
        _flag("--allow-seed-change", "allow_seed_change", help="Compare different seed sets (deltas only).",
        ),
        _flag("--require-all", "require_all", help="A profile missing from the new scorecard is a failure."),
        _flag("--json", "as_json"),
    ]),
}  # fmt: skip


# the commands that change a unit's branch or the forge: a signal or the end of their CI job stops them (W-D2)
_CANCELLABLE = frozenset({"run", "verify", "archive", "resume"})


def _build_app(options: Mapping[str, Any], environ: Mapping[str, str]) -> AppContext:
    repo = options["repo"] if options["repo"] is not None else Path.cwd()
    return AppContext(
        repo=Path(repo).resolve(),
        config_path=options["config_path"],
        log_format=options["log_format"],
        verbosity=options["verbose"] - options["quiet"],
        run_id=new_run_id(),
        environ=environ,
        redactor=redactor_for(environ),
    )


def _make_command(name: str, help_text: str, params: list[click.Parameter]) -> click.Command:
    own_dests = {param.name for param in params}

    def callback(**kwargs: Any) -> int:
        environ: Mapping[str, str] = click.get_current_context().obj
        slug = kwargs.pop("github_repo", None)
        if slug is not None and Path(slug).is_dir():  # the global meaning of `--repo`: the checkout
            kwargs["repo"], slug = Path(slug), None
        app = _build_app({k: kwargs.get(k) for k in _COMMON_KEYS}, environ)
        configure_logging(app)
        options = {k: v for k, v in kwargs.items() if k not in _COMMON_KEYS}
        if slug is not None or "github_repo" in own_dests:
            options["repo"] = slug

        def call():
            return dispatch(name, app, **options)

        guard = cancel.handlers() if name in _CANCELLABLE else contextlib.nullcontext()
        with guard:
            stop = cancel.start_watchdog(environ) if name in _CANCELLABLE else None
            try:
                result = with_outcome(app, call) if name in OUTCOME_COMMANDS else run_guarded(call)
            finally:
                if stop is not None:
                    stop()
        return int(result.code)

    # a command that takes `--repo owner/name` itself (`setup github`, `ci watch`) has one `--repo`: an existing
    # directory is the checkout (the global meaning), anything else is the GitHub repository
    own = {opt for param in params for opt in param.opts}
    common = [param for param in _common() if not own & set(param.opts)]
    return click.Command(name.split()[-1], params=[*common, *params], callback=callback, help=help_text)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="l4")
def cli() -> None:
    """L4 harness: level-4 agentic development."""


_GROUPS = {"ci": click.Group("ci", help="CI helpers."), "setup": click.Group("setup", help="Forge setup.")}
for _group in _GROUPS.values():
    cli.add_command(_group)
for _name, (_help, _params) in _SPECS.items():
    _command = _make_command(_name, _help, _params())
    _GROUPS.get(_name.split()[0], cli).add_command(_command) if " " in _name else cli.add_command(_command)


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        result = cli.main(args=args, prog_name="l4", standalone_mode=False, obj=env)
    except click.ClickException as exc:
        click.echo(f"Error: {redactor_for(env).redact_text(exc.format_message())}", err=True)
        return exc.exit_code
    except click.Abort:
        click.echo("Aborted.", err=True)
        return int(ExitCode.INTERNAL_ERROR)
    except Exception as exc:  # outside any handler (option parsing, context setup): still exit 1, redacted
        code, message = classify_exception(exc)
        click.echo(redactor_for(env).redact_text(message), err=True)
        return int(code)
    return int(result or 0)
