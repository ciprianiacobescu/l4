"""The click shell: parses options, builds the AppContext, delegates to `commands.dispatch`."""

import contextlib
import math
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import click

from l4 import __version__, cancel
from l4.commands import STUBS, dispatch
from l4.config.defaults import DEFAULT_REDACT_ENV, RUNNER_SECRET_ENV
from l4.context import AppContext
from l4.exitcodes import ExitCode, classify_exception
from l4.log import configure_logging
from l4.outcome import OUTCOME_COMMANDS, new_run_id, run_guarded, with_outcome
from l4.redact import Redactor
from l4.specs import feedback_help


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


NYI = "(not yet implemented) Exits 2."
REASON_HELP = (
    "Why the unit can continue. For a unit halted on a task, the implementer of that task also reads it "
    "(at most 300 characters)."
)
QUESTIONS_SHORT = "List and show open questions; accept or answer one on the unit branch (commits and pushes)."
QUESTIONS_HELP = (
    QUESTIONS_SHORT
    + """

Reads questions.md on the fetched unit branch on origin, never your work tree. accept and answer write one commit \
to that branch and push it (no force) with [skip ci]; the command then starts a run on the base branch, \
which takes the answer (--no-run skips that).

\b
l4 questions [list] [--unit U] [--json]        the open questions of one unit, or of every unit with a branch
l4 questions show Q-NNN --unit U [--json]      one question: what accept takes, the frozen paths it would unfreeze
l4 questions accept Q-NNN --unit U [--no-push] [--no-run]
                                               take the clarifier's suggestion as the answer
l4 questions answer Q-NNN --unit U --text TEXT [--no-push] [--no-run]
                                               write your answer (--text - reads standard input)
l4 questions answer Q-NNN --unit U --text TEXT --replace
                                               replace the answer of an answered verdict question (accept or reject);
                                               the old answer stays in the section

--no-push prints the diff and the commit message and writes nothing. A caller that is an agent (an agent marker \
in the environment, or standard input that is not a terminal) may write only a question of a kind in \
clarifier.auto_accept_kinds whose answer names no frozen path, unless clarifier.answer_by_agents is true on the \
base branch."""
)


MCP_SERVE_HELP = (
    "Serve L4 to an MCP client over stdio: tools to manage delivery plans and debug units.\n\n"
    "Started by the client (see `l4 mcp install`), not by hand. Every tool runs the l4 command it names in a "
    "repository this instance serves (--repo), as an agent (AI_AGENT=l4-mcp), so the rules of the CLI for agents "
    "hold. Only protocol messages go to standard output; logs go to standard error."
)


MCP_CLIENTS = ("claude-code", "cursor", "vscode", "kiro", "codex", "opencode")
MCP_INSTALL_HELP = (
    "Write the MCP configuration of a client. A user configuration starts `l4 mcp serve --repo <repository>`; "
    "--project (a file you commit) starts `l4 mcp serve` with no path, so each clone and worktree serves its own "
    "folder.\n\n"
    "Merges into the file, keeps every other server and the keys you added to the entry, writes atomically, refuses a "
    "file that does not parse, an entry of that name that serves another repository (use --name) and, with --project, "
    "a symlink in the repository. One "
    "entry per repository in a user configuration (l4-<folder>); --project writes the repository's own file. "
    "claude-code at user scope prints the documented `claude mcp add` command instead; vscode has --project only."
)


class _FiniteFloat(click.ParamType):
    """A float that is neither NaN nor infinite (`float("nan")` parses, and compares false with every limit)."""

    name = "float"

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            self.fail(f"{value!r} is not a valid float.", param, ctx)
        if not math.isfinite(number):
            self.fail(f"{value!r} is not a finite number.", param, ctx)
        return number


FINITE_FLOAT = _FiniteFloat()


def _opt(*names: str, **kw: Any) -> click.Option:
    return click.Option(list(names), **kw)


def _TOKEN_COMMAND() -> click.Option:  # noqa: N802 - a constant-like option factory
    return _opt(
        "--token-command", "token_command", envvar="L4_TOKEN_COMMAND", show_envvar=True,
        help="Command (no shell) that prints a new credential on its stdout; run once when the forge answers 401.",
    )  # fmt: skip


def _flag(*names: str, **kw: Any) -> click.Option:
    return click.Option(list(names), is_flag=True, **kw)


def _no_fetch() -> click.Option:
    return _flag("--no-fetch", "no_fetch", help="Read the local refs; fetch nothing from the forge.")


def _units() -> click.Option:
    return _opt("--unit", "units", multiple=True, help="Unit id (repeatable).")


def _unit(required: bool = False) -> click.Option:
    return _opt("--unit", "unit", required=required, help="Unit id.")


# command -> (help, parameter factory); handler keyword arguments are the parameter names
_SPECS: dict[str, tuple[str, Callable[[], list[click.Parameter]]]] = {
    "init": ("Adopt the harness in a repo.", lambda: [
        _opt("--ci", "ci", type=click.Choice(["github", "gitlab", "both"])),
        _opt("--framework", "framework", type=click.Choice(["openspec", "kiro"]),
             help="The spec framework (kiro is not yet implemented)."),
        _flag("--vendor", "vendor"), _flag("--dry-run", "dry_run", help=NYI), _flag("--force", "force"),
        _flag("--no-ci-edit", "no_ci_edit", help="Print the .gitlab-ci.yml include instead of writing it."),
        _opt("--harness", "harness", type=click.Path(exists=True, file_okay=False, path_type=Path),
             help="Harness checkout to vendor (default: the one l4 runs from)."),
        _opt("--harness-repo", "harness_repo", help="Fetch the harness at run time from this git URL, no .l4/vendor/."),
        _opt("--harness-commit", "harness_commit_pin",
             help="With --harness-repo or --action: the commit to pin (default: the running harness's)."),
        _opt("--harness-ref", "harness_ref",
             help="With --harness-repo or --action: a tag or branch, resolved once with git ls-remote and pinned as "
                  "its commit sha."),
        _flag("--action", "action", help="GitHub: the harness comes from the setup action, one pinned uses: line."),
        _opt("--action-repo", "action_repo", help="With --action: OWNER/REPO that holds the action (default: the "
                                                  "harness's own)."),
        _flag("--action-copy", "action_copy", help="With --action: keep a copy of the action in the repository "
                                                   "and fetch the harness with a deploy key."),
        _flag("--dependabot", "dependabot", help="With --action: add github-actions to .github/dependabot.yml."),
        _opt("--runner-tag", "runner_tag", multiple=True,
             help="With --action: run on a self-hosted runner with this tag (repeatable); default: GitHub-hosted."),
        _opt("--forge-token-env", "forge_token_env",
             help="With --action: forge.token_env, the secret the job reads the forge token from "
                  "(default: GITHUB_TOKEN, the workflow's own)."),
        _flag("--hold-existing", "hold_existing",
              help="Write the ids of the units found now as yolo.hold: none of them runs until you remove it."),
        _opt("--s1", "s1", type=click.Choice(["laya", "jev", "none"]), default="laya", show_default=True,
             help="The System One profile to write: laya (local, no key), jev (TypeSafe, TYPESAFE_API_KEY) or none."),
    ]),
    "upgrade": ("Bring the vendored harness, the CI template and the shim up to the harness checkout.", lambda: [
        _opt("--harness", "harness", type=click.Path(exists=True, file_okay=False, path_type=Path),
             help="Harness checkout to vendor (default: the one l4 runs from)."),
        _flag("--dry-run", "dry_run"),
        _opt("--harness-commit", "harness_commit_pin",
             help="Fetched or action adoption: the commit to pin (default: the running harness's)."),
        _opt("--harness-ref", "harness_ref",
             help="Fetched or action adoption: a tag or branch, resolved once with git ls-remote and pinned as its "
                  "commit sha."),
        _opt("--action-repo", "action_repo",
             help="Action adoption: OWNER/REPO that now holds the setup action, after the harness repository was "
                  "renamed or moved (GitHub does not redirect a `uses:` line); the pin moves there."),
    ]),
    "doctor": ("Check environment, config, specs, git, forge, CI and state.", lambda: [
        _flag("--ci", "ci"), _flag("--live", "live"), _flag("--fix", "fix"), _unit(), _flag("--json", "as_json"),
        _flag("--adoption", "adoption", help="The repository's own rows and a dry run of the gates at HEAD."),
        _flag("--no-gates", "no_gates", help="With --adoption: skip the gate dry run (config rows only)."),
    ]),
    "plan": ("Detect units and compute the next action for each.", lambda: [
        _units(), _flag("--json", "as_json"), _flag("--probe", "probe"), _flag("--sweep", "sweep"),
        _flag("--detailed-exitcode", "detailed_exitcode"), _no_fetch(),
    ]),
    "run": ("Advance units through the lifecycle.", lambda: [
        _units(), _opt("--max-units", "max_units", type=int), _opt("--time-budget", "time_budget", help=NYI),
        _flag("--dry-run", "dry_run"), _flag("--probe", "probe"), _no_fetch(),
    ]),
    "status": ("Show units, phases, open questions, last verdict and cool-downs.", lambda: [
        _unit(), _flag("--json", "as_json"), _flag("--rebuild", "rebuild", help=NYI),
        _flag("--events", "events", help="With --unit: the unit's ledger events (read only; --json: l4/events@1)."),
        _opt("--type", "event_type", help="With --events: only events of this type, for example task.attempt_failed."),
        _opt("--last", "last", type=int, help="With --events: only the newest N events."),
        _flag("--verification", "verification", help="With --unit: print the unit's verification.md."),
        _no_fetch(),
    ]),
    "probe": ("Run availability probes.", lambda: [
        click.Argument(["profiles"], nargs=-1), _opt("--role", "role"), _flag("--json", "as_json"),
        _flag("--no-cache", "no_cache"),
    ]),
    "verify": ("Run only the verifier on a unit.", lambda: [_unit(True), _flag("--dry-run", "dry_run", help=NYI)]),
    "archive": ("Run the done-gate and archive a unit.", lambda: [
        _unit(True), _flag("--retry", "retry", help="Try again an archive that failed on the same inputs."),
        _no_fetch(),
    ]),
    "questions": (QUESTIONS_HELP, lambda: [
        click.Argument(["words"], nargs=-1), _unit(),
        _opt("--text", "text", help="answer: the answer. - reads standard input."),
        _flag("--json", "as_json", help="list, show: print l4/questions@1 JSON."),
        _flag("--no-push", "no_push", help="accept, answer: print the diff and the commit message; write nothing."),
        _flag("--no-run", "no_run", help="accept, answer: do not start the harness's CI on the base branch."),
        _flag("--replace", "replace", help="answer: replace the answer of an answered verdict question; the old "
                                           "answer stays in the section."),
    ]),
    "feedback add": (feedback_help.ADD_HELP, lambda: [
        _opt("--kind", "kind", required=True,
             type=click.Choice(["refactor", "duplication", "tests", "config", "behaviour"], case_sensitive=False),
             help="What the change is: refactor, duplication, tests, config or behaviour."),
        _opt("--text", "text", required=True, help="The request. - reads standard input."),
        _opt("--title", "title", help="Heading of the item (default: the first line of the text, 72 characters)."),
        _opt("--at", "at", multiple=True, help="PATH[:L[-L]] the request is about (repeatable, up to 5)."),
        _opt("--env", "env", help="config: the environment variable NAME that replaces the hard-coded value."),
        _opt("--when", "when", help="behaviour: the condition (the WHEN of the criterion)."),
        _opt("--then", "then", help="behaviour: the expected result (the THEN of the criterion)."),
        _flag("--lesson", "lesson", help="Keep a lesson from this item once it is addressed."),
        _flag("--draft", "draft", help="Write Status draft: the harness ignores it until `submit`."),
        _unit(),
    ]),
    "feedback list": (feedback_help.LIST_HELP, lambda: [_unit(), _flag("--json", "as_json")]),
    "feedback show": (feedback_help.SHOW_HELP, lambda: [
        click.Argument(["item"]), _unit(), _flag("--json", "as_json"),
    ]),
    "feedback submit": (feedback_help.SUBMIT_HELP, lambda: [click.Argument(["item"]), _unit()]),
    "feedback withdraw": (feedback_help.WITHDRAW_HELP, lambda: [click.Argument(["item"]), _unit()]),
    "lessons": ("Inspect and curate lessons; `promote ID` moves an inbox proposal into lessons.md.", lambda: [
        click.Argument(["words"], nargs=-1),
        _opt("--from", "from_dir", type=click.Path(path_type=Path),
             help="promote: the inbox folder to read the proposal from (needed when two folders hold it)."),
        _flag("--yes", "yes", help="promote: do not ask (required when there is no terminal)."),
        _flag("--no-commit", "no_commit", help="promote: write lessons.md and keep the proposal; do not commit."),
    ]),
    "kg build": ("Build the experience index of this repository (manual; reads committed records only).", lambda: []),
    "kg report": ("Report what keeps failing, across units, from the experience index.", lambda: [
        _opt("--out", "out", type=click.Path(path_type=Path),
             help="Write the report to this file. Inside the repository it must be git-ignored."),
        _opt("--min-units", "min_units", type=int, default=2, show_default=True,
             help="A pattern needs at least this many units."),
    ]),
    "kg why": ("Explain one unit, finding, lesson, run or question from the experience index.", lambda: [
        click.Argument(["id"]),
    ]),
    "kg propose": ("Write draft lessons for a person into the inbox; it never writes a lesson.", lambda: [
        _opt("--min-units", "min_units", type=int, default=2, show_default=True,
             help="A pattern needs at least this many units."),
        _flag("--dry-run", "dry_run", help="Print the drafts instead of writing them."),
    ]),
    "skills install": (
        "Install the l4 skill (shipped in this package) for coding agents; no network.", lambda: [
            _opt("--agent", "agent", default="auto", show_default=True,
                 type=click.Choice(["auto", "all", "claude-code", "codex", "opencode", "kiro"]),
                 help="auto: the agents whose home folder or CLI is present."),
            _flag("--project", "project", help="Install into the repository (.claude/skills, .agents/skills, "
                                               ".opencode/skills, .kiro/skills) instead of the home folder."),
            _flag("--force", "force", help="Replace a copy whose files were edited."),
            _flag("--dry-run", "dry_run", help="Print what would be written; write nothing."),
        ],
    ),
    "skills status": ("Show each installed l4 skill: version, current or old, and edited files.", lambda: []),
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
        _unit(True), _opt("--reason", "reason", required=True, help=REASON_HELP),
        _opt("--extend-iterations", "extend_iterations", type=int, help=NYI),
        _opt("--extend-cost", "extend_cost", type=FINITE_FLOAT, help=NYI),
        _opt("--extend-fix-rounds", "extend_fix_rounds", type=int),
        _opt("--extend-feedback-rounds", "extend_feedback_rounds", type=int), _no_fetch(),
    ]),
    "retry": ("Continue a stopped unit from where it stopped, then start a run.", lambda: [
        _unit(True),
        _opt("--reason", "reason", required=True, help=REASON_HELP),
        _opt("--rounds", "rounds", type=int,
             help="Escalated at its fix-round (or feedback) limit: how many rounds to add (default 1)."),
        _flag("--no-run", "no_run", help="Do not start the harness's CI on the base branch after the push."),
    ]),
    "restart": ("Start a unit over on a new branch; the old branch head is kept as a ref.", lambda: [
        _unit(True),
        _opt("--reason", "reason", required=True, help="Why the unit starts over (kept in the ledger)."),
        _flag("--no-run", "no_run", help="Do not start the harness's CI on the base branch after the push."),
    ]),
    "yolo draft": ("Write or update a plan file from the specs here (fetches the unit refs first).", lambda: [
        click.Argument(["plan"]),
        _opt("--target", "target", help="The plan's target branch (default: forge.base_branch)."),
        _opt("--merge", "merge", type=click.Choice(["human", "auto"]), help="The merge mode (default: human)."),
        _flag("--update", "update", help="Add the specs no plan lists to the existing file; change nothing else."),
    ]),
    "yolo check": ("Admit a delivery plan at the target head and print the order; writes nothing.", lambda: [
        click.Argument(["plan"]),
        _flag("--worktree", "worktree", help="check the working tree's plan before the push"),
    ]),
    "yolo review": ("Ask CI to review a plan (--local: here; --worktree: the working tree, before the push).", lambda: [
        click.Argument(["plan"]),
        _flag("--local", "local", help="Run the readiness review on this machine and record it."),
        _flag("--worktree", "worktree", help="Review the working tree here, before the push (a dry run)."),
        _flag("--record", "record", help="With --worktree: record the review in the plan ledger (clean tree only)."),
        _opt("--fresh", "fresh", multiple=True, help="With --worktree: judge this subject again (repeatable)."),
        _flag("--json", "as_json", help="With --worktree: print the findings as JSON (as l4 yolo findings --json)."),
        _flag("--no-run", "no_run", help="Do not start the harness's CI on the base branch."),
    ]),
    "yolo findings": ("Show the findings of the latest review of a plan, with how to resolve each.", lambda: [
        click.Argument(["plan"]), click.Argument(["subject"], required=False),
        _flag("--all", "show_all", help="Also the READY subjects, minor findings, assumptions and missing."),
        _flag("--json", "as_json"),
        _flag("--worktree", "worktree", help="The latest dry run of review --worktree (local), not the ledger."),
    ]),
    "yolo accept": ("Accept a subject's review as it is, with a reason for the implementer (audited).", lambda: [
        click.Argument(["plan"]), click.Argument(["subject"], required=False),
        _flag("--all", "all_subjects", help="With --force: every unit and batch of the plan."),
        _flag("--force", "force", help="A person accepts every subject without a readiness review (with --all)."),
        _opt("--reason", "reason", required=True, help="What the implementer should do (kept in the plan ledger)."),
        _flag("--withdraw", "withdraw", help="Withdraw an acceptance."),
        _flag("--yes", "yes", help="Do not ask for the plan id (a person, or an agent the target lets accept)."),
    ]),
    "yolo waive": ("Waive an accepted finding of an active plan: the unit merges without it (audited).", lambda: [
        click.Argument(["plan"]), click.Argument(["finding"]),
        _opt("--reason", "reason", required=True, help="Why the finding needs no handling (kept in the plan ledger)."),
        _flag("--withdraw", "withdraw", help="Withdraw a waiver."),
        _flag("--yes", "yes", help="Do not ask for the plan id (a person, or an agent the target lets accept)."),
        _flag("--no-run", "no_run", help="Do not start the harness's CI on the base branch after the push."),
    ]),
    "yolo activate": ("Activate a reviewed delivery plan, then start a run.", lambda: [
        click.Argument(["plan"]),
        _opt("--reason", "reason", required=True, help="Why the plan is activated (kept in the plan ledger)."),
        _flag("--no-run", "no_run", help="Do not start the harness's CI on the base branch after the push."),
    ]),
    "yolo status": ("Show a plan (or all): units, review, acceptances, usage, the stop or wait, Next.", lambda: [
        click.Argument(["plan"], required=False), _flag("--json", "as_json"),
    ]),
    "yolo cancel": ("Cancel a delivery plan: nothing more is dispatched or merged.", lambda: [
        click.Argument(["plan"]),
        _opt("--reason", "reason", required=True, help="Why the plan is cancelled (kept in the plan ledger)."),
    ]),
    "yolo resume": (
        "Resume a stopped or waiting delivery plan once the cause is gone, or raise a limit of an active one "
        "(--extend-…).",
        lambda: [
            click.Argument(["plan"]),
            _opt("--reason", "reason", required=True, help="Why the plan resumes (kept in the plan ledger)."),
            _opt("--extend-cost", "extend_cost", type=FINITE_FLOAT, help="Raise the cost limit by this many dollars."),
            _opt("--extend-runs", "extend_runs", type=int, help="Raise the run limit by N."),
            _opt("--extend-attempts", "extend_attempts", type=int, help="Raise the attempts limit of every unit by N."),
            _opt("--extend-deadline", "extend_deadline", help="A later deadline, ISO 8601."),
            _flag("--no-run", "no_run", help="Do not start the harness's CI on the base branch after the push."),
        ],
    ),
    "yolo report": ("Print the report of a delivery plan.", lambda: [click.Argument(["plan"])]),
    "yolo go": (
        "Take a plan from its committed file to an active plan: preflight, push, check, review, findings, accept, "
        "activate, over the existing commands; it stops at the first step that cannot pass and prints one Next: "
        "command. It ACTIVATES the plan (l4 yolo status only looks).",
        lambda: [
            click.Argument(["plan"]),
            _opt("--reason", "reason", required=True,
                 help="Why the plan goes: the reason of every acceptance (write it for the implementer) and of the "
                      "activation (kept in the plan ledger)."),
            _flag("--accept-findings", "accept_findings",
                  help="Accept the subjects that are not READY by the rules of l4 yolo accept (all or nothing)."),
            _flag("--force", "force",
                  help="A person's force acceptance of every subject without a readiness review (l4 yolo accept "
                       "--all --force)."),
            _flag("--yes", "yes", help="Do not ask for the plan id where l4 yolo accept asks for it (l4 yolo go: and "
                                       "before it activates)."),
            _flag("--json", "as_json", help="Print one JSON document (l4/yolo-go@1) and nothing else on stdout."),
            _flag("--no-push", "no_push", help="Do not push the base branch: stop with the push command instead."),
            _flag("--local", "local", help="Review here (as l4 yolo review --local) instead of asking CI."),
            _opt("--wait", "wait", default="30m", show_default=True,
                 help="How long to wait for the CI review to be recorded: 0, or a duration such as 30s, 30m, 1h."),
        ],
    ),
    "mcp serve": (MCP_SERVE_HELP, lambda: [
        _opt("--repo", "repos", multiple=True, type=click.Path(path_type=Path),
             help="A repository to serve (repeatable): a git repository with .l4/config.yaml. Several: every tool "
                  "takes a `repo` argument naming one. Default: the working directory, when it is such a repository."),
    ]),
    "mcp install": (MCP_INSTALL_HELP, lambda: [
        _opt("--client", "client", required=True, type=click.Choice(MCP_CLIENTS),
             help="The MCP client whose configuration to write."),
        _flag("--project", "project", help="Write the repository's own configuration file (entry named l4), not the "
                                           "user's."),
        _opt("--repo", "target_repo", type=click.Path(path_type=Path),
             help="The repository the server serves (default: the repository of the working directory)."),
        _opt("--name", "entry", help="The entry name (default: l4 with --project, else l4-<repository folder>)."),
        _flag("--dry-run", "dry_run", help="Print what would be written; write nothing."),
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
    "ci start": ("Start the harness's CI run on the base branch only when it is idle.", lambda: [
        _opt("--if-idle", "if_idle", metavar="DURATION",
             help="Also require the last run to have ended at least DURATION ago (such as 12m)."),
    ]),
    "ci render-child": ("Print the GitLab child pipeline.", lambda: [
        _opt("--plan", "plan", required=True, type=click.Path(dir_okay=False, path_type=Path)),
    ]),
    "ci cache-key": ("Print the key of a CI cache (clis: a suffix; laya: the whole key, or nothing).", lambda: [
        click.Argument(["cache"], type=str),
    ]),
    "ci render-setup": ("Print the runner setup script (l4-setup.sh) for bash.", lambda: []),
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
_CANCELLABLE = frozenset(
    {"run", "verify", "archive", "resume", "retry", "restart", "yolo review", "yolo activate", "yolo cancel",
     "yolo resume", "yolo go"}
)  # fmt: skip


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
    short = QUESTIONS_SHORT if name == "questions" else None
    if name in STUBS:
        help_text = f"(not yet implemented) {help_text}"
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
    return click.Command(
        name.split()[-1], params=[*common, *params], callback=callback, help=help_text, short_help=short
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="l4")
def cli() -> None:
    """L4 harness: level-4 agentic development."""


_GROUPS = {
    "ci": click.Group("ci", help="CI helpers."),
    "setup": click.Group("setup", help="Forge setup."),
    "feedback": click.Group("feedback", help=feedback_help.GROUP_HELP),
    "yolo": click.Group("yolo", help="Delivery plans: ordered units, a readiness review, one activation."),
    "mcp": click.Group("mcp", help="L4 as an MCP server for IDEs and agents."),
    "skills": click.Group("skills", help="The l4 skill for coding agents."),
    "kg": click.Group("kg", help="Read the recorded history across units (manual; nothing reaches an agent)."),
}
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
