"""A run on a stale copy of the workflow relays to the base (run-continuation D8, L4-IMP-072).

A scheduled run on a default branch that is not the base runs the default branch's copy of `.github/workflows/l4.yml`,
and so that copy's harness. When that harness is not the base's pin, `l4 doctor --ci`, `l4 plan --sweep`, `l4 run` and
`l4 status` stop (L4-ADO-005) and the first of the first three starts the base's own workflow once, so that the
schedule keeps moving a plan whose base is not the default branch.

All of this runs before the configuration is loaded: the running harness may be older than the base's configuration,
and a key it does not know must not stop the relay. It reads only the job environment, the checked-out workflow, and a
few keys of `.l4/config.yaml` without the schema (`lenient_settings`)."""

import json
import logging
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast, get_args

import yaml
from pydantic import ValidationError

from l4.ci import pin_guard
from l4.ci.github import ACTION_PATH, WORKFLOW_RELPATH
from l4.config.defaults import DEFAULT_REDACT_ENV, RUNNER_SECRET_ENV
from l4.config.loader import CONFIG_RELPATH, _Yaml12Loader
from l4.config.schema import L4Config, effective_delivery
from l4.exitcodes import ExitCode
from l4.forge.base import ForgeUnavailable, fetch_auth_config, make_forge
from l4.fsutil import seal_out_dir
from l4.init.action import read_pin
from l4.redact import Redactor
from l4.vcs.git import Git
from l4.vcs.refresh import PLAN_REFSPEC
from l4.yolo.model import PLAN_ID, PLAN_REF_PREFIX
from l4.yolo.state import fold_plan
from l4.yolo.store import LEDGER_FILE, parse_ledger

log = logging.getLogger("l4.ci.relay")

LENIENT_KEYS = (
    "harness.delivery", "harness.repository", "forge.type", "forge.base_branch", "forge.branch_prefix",
    "forge.token_env", "spec.openspec.root", "spec.kiro.root",
)  # fmt: skip
MAX_CONFIG_BYTES = 1024 * 1024  # the bound of `l4.init.upgrade.MAX_CONFIG_BYTES`
MARKER_NAME = "l4-relay.json"
_FORGE_KEYS = ("type", "base_branch", "branch_prefix", "token_env")
_WORK_PLANS = ("active", "waiting")

Relay = Literal["dispatched", "already_running", "no_work", "on_base", "refused", "unsupported", "failed"]
_RELAYS = frozenset(get_args(Relay))


@dataclass(frozen=True)
class EarlyStop:
    """The command does no work and exits `exit_code` before it loads the configuration; `relay` is the job's answer
    (None for `l4 status`, which never relays)."""

    exit_code: ExitCode
    relay: Relay | None


def _plain(value: object) -> str | None:
    """A scalar as a string; a mapping, a list or nothing is ignored."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str | int | float):
        return str(value)
    return None


def lenient_settings(repo: Path, config_path: Path | None = None) -> dict[str, str]:
    """The `LENIENT_KEYS` of `.l4/config.yaml` that are present, read with the strict loader's YAML 1.2 rules and no
    schema, plus `harness.delivery` as `effective_delivery` would say (the file's key, else `fetched` for a
    `harness.repository`, else `action` when the checked-out workflow pins the setup action, else `vendored`). `{}`
    for a file that is a symbolic link, over 1 MB, not YAML, or not a mapping.
    `config_path` is the file `--config` named (the command's own); without it, `.l4/config.yaml` of the repository."""
    path = config_path if config_path is not None else repo / CONFIG_RELPATH
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
            return {}
        loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=_Yaml12Loader)  # noqa: S506 (SafeLoader subclass)
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    found: dict[str, str] = {}
    for key in LENIENT_KEYS:
        node: object = loaded
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        value = _plain(node)
        if value is not None:
            found[key] = value
    if "harness.delivery" not in found:
        found["harness.delivery"] = "fetched" if "harness.repository" in found else _delivery_of_workflow(repo)
    return found


def _delivery_of_workflow(repo: Path) -> str:
    try:
        text = (repo / WORKFLOW_RELPATH).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "vendored"
    return "action" if read_pin(text) is not None else "vendored"


def base_branch(environ: Mapping[str, str], configured: str | None) -> str:
    """`L4_BASE_BRANCH` (the template's), else `forge.base_branch`, else its default."""
    return environ.get("L4_BASE_BRANCH") or configured or "main"


def on_base(environ: Mapping[str, str], base: str) -> bool:
    return environ.get("GITHUB_REF_TYPE", "branch") == "branch" and environ.get("GITHUB_REF_NAME") == base


def late_label(environ: Mapping[str, str], configured_base: str) -> Relay | None:
    """`relay` for the `outcome.json` of a run that the pin guard stopped after the configuration loaded: `on_base`
    on the base itself (a mismatch there is a different fault: nothing is relayed), else None."""
    if environ.get("GITHUB_ACTIONS") != "true":
        return None
    return "on_base" if on_base(environ, base_branch(environ, configured_base)) else None


def _redactor(environ: Mapping[str, str], token_env: str | None = None) -> Redactor:
    """The redactor of `l4.cli`, plus the configured `forge.token_env` (a custom name is no default secret name)."""
    return Redactor.from_env((*DEFAULT_REDACT_ENV, *RUNNER_SECRET_ENV, *((token_env,) if token_env else ())), environ)


def early_pin_stop(
    repo: Path, environ: Mapping[str, str], *, command: str, config_path: Path | None = None
) -> EarlyStop | None:
    """`command`: `doctor`, `plan`, `run` or `status`; `config_path`: the command's `--config`, if any. None unless
    this is GitHub Actions, off the base, with the `action` delivery and a harness that is not the checked-out
    workflow's pin. Then: the pin guard's warning, the relay (not for `status`), and the stop."""
    if environ.get("GITHUB_ACTIONS") != "true":
        return None
    settings = lenient_settings(repo, config_path)
    if settings.get("harness.delivery") != "action":
        return None
    base = base_branch(environ, settings.get("forge.base_branch"))
    if on_base(environ, base):
        return None
    check = pin_guard.early_check("action", repo, environ)
    if check.status != "mismatch":
        return None
    redact = _redactor(environ, settings.get("forge.token_env")).redact_text
    print(redact(pin_guard.stale_pin_text(check, settings.get("forge.branch_prefix", "l4/"), environ)), file=sys.stderr)
    if command == "status":
        return EarlyStop(ExitCode.OK, None)
    return EarlyStop(ExitCode.OK, _relay_once(repo, environ, settings, base, redact))


def _relay_once(repo: Path, environ: Mapping[str, str], settings: dict[str, str], base: str, redact) -> Relay:
    earlier = _read_marker(repo, environ)
    if earlier is not None:
        print(redact(f"l4: relayed earlier in this job ({earlier})"), file=sys.stderr)
        return earlier
    answer, detail = _relay(repo, environ, settings, base)
    _write_marker(repo, environ, answer)
    print(redact(_line(answer, base, detail)), file=sys.stderr)
    return answer


def _line(answer: Relay, base: str, detail: str) -> str:
    if answer == "dispatched":
        return f"::notice::l4 relayed this run to {base}: started l4.yml on {base}, which runs the base's pin"
    if answer == "already_running":
        return f"l4: not relayed: a run of l4.yml is already queued or running on {base}"
    if answer == "no_work":
        return f"l4: not relayed: {base} has no active or waiting plan, no unit branch and no unit folder"
    if answer in ("refused", "unsupported") and detail:  # no token at all: the cause is the detail
        return f"l4: not relayed: {detail}"
    if answer in ("refused", "unsupported"):
        return (
            f"l4: not relayed: the token may not start a run on {base}; start one with: "
            f"gh workflow run l4.yml --ref {base}"
        )
    if answer == "on_base":
        return f"l4: not relayed: this run is on {base}, whose copy of the workflow ran"
    return f"l4: not relayed: {detail}; start one with: gh workflow run l4.yml --ref {base}"


def relay_to_base(repo: Path, environ: Mapping[str, str], settings: dict[str, str]) -> Relay:
    """Start `l4.yml` on the base, when it may have work and no other run of it is queued or running there."""
    return _relay(repo, environ, settings, base_branch(environ, settings.get("forge.base_branch")))[0]


def _relay(repo: Path, environ: Mapping[str, str], settings: dict[str, str], base: str) -> tuple[Relay, str]:
    """The answer and, for `failed`, the first line of what went wrong."""
    if on_base(environ, base):  # the loop guard: the relayed run is on the base, with the base's pin
        return "on_base", ""
    try:
        cfg = L4Config.model_validate(
            {
                "forge": {
                    **{k: settings[f"forge.{k}"] for k in _FORGE_KEYS if f"forge.{k}" in settings},
                    "base_branch": base,
                }
            }
        )
    except ValidationError as exc:
        log.info("relay: the forge keys of the configuration are not valid")
        loc = exc.errors()[0].get("loc", ()) if exc.errors() else ()
        key = ".".join(str(part) for part in loc[:2]) or "forge"
        return "failed", f"the forge key {key} of .l4/config.yaml is not valid"
    if not _base_may_have_work(repo, environ, cfg, settings):
        return "no_work", ""
    try:
        forge = make_forge(cfg, environ, repo=repo)
        answer = forge.relay_run(base, exclude_run_id=environ.get("GITHUB_RUN_ID"))
    except ForgeUnavailable:
        name = cfg.forge.token_env
        return "refused", (
            f"{name} (forge.token_env) is not set in this job, so no run can be started on {base}; give the job that "
            f"variable (the job's environment must allow the default branch), or start one with: "
            f"gh workflow run l4.yml --ref {base}"
        )
    except Exception as exc:  # noqa: BLE001 - any failure is a line: the stopped job exits 0 (L4-ADO-005)
        redact = _redactor(environ, settings.get("forge.token_env") or cfg.forge.token_env).redact_text
        message = redact((str(exc).strip().splitlines() or [type(exc).__name__])[0])  # the log line too (B-m7)
        log.info("relay: %s", message)
        return "failed", message
    return answer, ""


def _base_may_have_work(repo: Path, environ: Mapping[str, str], cfg: L4Config, settings: dict[str, str]) -> bool:
    """Read with git only: an active or waiting plan, a plan ref that cannot be read, a unit branch on origin, or a unit
    folder on the checked-out base. Anything that fails to be read counts as work."""
    try:
        git = Git(repo, environ=environ)
        git.fetch("origin", refspecs=(PLAN_REFSPEC,), config=fetch_auth_config(cfg, environ))
        refs = git.run("for-each-ref", "--format=%(refname)", PLAN_REF_PREFIX, check=False).stdout.split()
        for ref in refs:
            plan_id = ref.removeprefix(PLAN_REF_PREFIX)
            shown = git.run("show", f"{ref}:{LEDGER_FILE}", check=False)
            if shown.returncode != 0 or not PLAN_ID.match(plan_id):
                return True
            try:
                state = fold_plan(plan_id, parse_ledger(shown.stdout))
            except (ValueError, KeyError, TypeError):
                return True
            if state.status in _WORK_PLANS:
                return True
        unit_prefix = f"refs/remotes/origin/{cfg.forge.branch_prefix}"
        remote_refs = git.run("for-each-ref", "--format=%(refname)", "refs/remotes/origin/", check=False).stdout.split()
        if any(ref.startswith(unit_prefix) for ref in remote_refs):
            return True
        return _has_unit_folder(repo, settings)
    except Exception as exc:  # noqa: BLE001 - fail open: a base that cannot be read is relayed to
        log.info("relay: cannot tell whether the base has work (%s)", (str(exc).strip().splitlines() or [""])[0])
        return True


def _under(repo: Path, root: str) -> Path | None:
    """`root` below the repository, or None for an absolute path or one that climbs out of it."""
    parts = Path(root).parts
    if Path(root).is_absolute() or ".." in parts:
        return None
    return repo.joinpath(*parts)


def _has_unit_folder(repo: Path, settings: dict[str, str]) -> bool:
    openspec = _under(repo, settings.get("spec.openspec.root", "openspec"))
    kiro = _under(repo, settings.get("spec.kiro.root", ".kiro/specs"))
    for folder, skip in ((openspec / "changes" if openspec else None, "archive"), (kiro, None)):
        if folder is None or not folder.is_dir():
            continue
        for entry in folder.iterdir():
            if entry.name != skip and entry.is_dir() and (entry / "tasks.md").is_file():
                return True
    return False


# --- the job's marker: one relay per job ---------------------------------------------------------------------------


def _marker_path(repo: Path, environ: Mapping[str, str]) -> Path:
    temp = environ.get("RUNNER_TEMP")
    return Path(temp) / MARKER_NAME if temp else repo / ".l4-out" / "relay.json"


def _identity(environ: Mapping[str, str]) -> dict[str, str]:
    return {
        "run_id": environ.get("GITHUB_RUN_ID", ""),
        "run_attempt": environ.get("GITHUB_RUN_ATTEMPT", ""),
        "job": environ.get("GITHUB_JOB", ""),
    }


def _read_marker(repo: Path, environ: Mapping[str, str]) -> Relay | None:
    """The answer of an earlier relay of this job: only when the marker's run id, run attempt and job are this job's
    (an uncleaned self-hosted checkout can keep the marker of an earlier run)."""
    try:
        marker = json.loads(_marker_path(repo, environ).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(marker, dict) or any(marker.get(k) != v for k, v in _identity(environ).items()):
        return None
    answer = marker.get("answer")
    return cast(Relay, answer) if isinstance(answer, str) and answer in _RELAYS else None


def _write_marker(repo: Path, environ: Mapping[str, str], answer: Relay) -> None:
    path = _marker_path(repo, environ)
    try:
        if not environ.get("RUNNER_TEMP"):
            seal_out_dir(path.parent)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**_identity(environ), "answer": answer}), encoding="utf-8")
    except OSError as exc:
        log.info("relay: the job's marker was not written (%s)", type(exc).__name__)


# --- the base's own run: a default-branch copy that is behind (L4-IMP-074) --------------------------------------

RELAY_FROM = (0, 4, 19)  # the first release whose stopped runs relay
_RELEASE = re.compile(r"^#\s*v(\d+)\.(\d+)\.(\d+)$")
_USES_COMMENT = re.compile(
    r"^\s*-?\s*(?:id:\s*\S+\s+)?uses:\s*\S*" + re.escape(ACTION_PATH) + r"@\S+\s+(#.*)$", re.MULTILINE
)


def parse_release(comment: str) -> tuple[int, int, int] | None:
    """`# v0.4.19` as (0, 4, 19), to compare as numbers; any other comment (a branch name, nothing) is None."""
    found = _RELEASE.match(comment.strip())
    return (int(found[1]), int(found[2]), int(found[3])) if found else None


def _default_branch_of(environ: Mapping[str, str]) -> str | None:
    """`repository.default_branch` of the event payload (`GITHUB_EVENT_PATH`)."""
    try:
        payload = json.loads(Path(environ.get("GITHUB_EVENT_PATH", "")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    repository = payload.get("repository") if isinstance(payload, dict) else None
    name = repository.get("default_branch") if isinstance(repository, dict) else None
    return name if isinstance(name, str) and name else None


def default_copy_warning(cfg: L4Config, repo: Path, environ: Mapping[str, str]) -> str | None:
    """On the base's own run in GitHub Actions with the `action` delivery: the `::warning::` that names the default
    branch's copy of the workflow when it is missing or pins another harness than the base's. Nothing for the same pin,
    an unknown default branch, the base as default branch, or another delivery."""
    if environ.get("GITHUB_ACTIONS") != "true" or effective_delivery(cfg) != "action":
        return None
    base = base_branch(environ, cfg.forge.base_branch)
    default = _default_branch_of(environ)
    if default is None or default == base or not on_base(environ, base):
        return None
    try:
        git = Git(repo, environ=environ)
        ref = f"refs/remotes/origin/{default}"
        if git.rev_parse(ref) is None:
            return None
        own = read_pin((repo / WORKFLOW_RELPATH).read_text(encoding="utf-8"))
        if own is None or own.effective is None:
            return None
        shown = git.run("show", f"{ref}:{WORKFLOW_RELPATH}", check=False)
    except Exception as exc:  # noqa: BLE001 - a hint: it never stops the run
        log.info("default-branch copy: not read (%s)", (str(exc).strip().splitlines() or [""])[0])
        return None
    copy_step = f"copy {WORKFLOW_RELPATH} to {default} once (or promote {base})"
    if shown.returncode != 0:
        return (
            f"::warning::the default branch {default} has no {WORKFLOW_RELPATH}: no scheduled run starts there; "
            f"{copy_step}"
        )
    theirs = read_pin(shown.stdout)
    if theirs is None or theirs.effective is None or theirs.effective == own.effective:
        return None
    comment = _USES_COMMENT.search(shown.stdout)
    release = parse_release(comment[1]) if comment else None
    label = f" (v{'.'.join(map(str, release))})" if release else ""
    if release is None:
        clause = f"if that copy is older than 0.4.19, its scheduled runs cannot relay to {base}"
    elif release < RELAY_FROM:
        clause = f"being older than 0.4.19, its scheduled runs cannot relay to {base}"
    else:
        clause = f"its scheduled runs relay to {base}"
    return (
        f"::warning::the default branch {default}'s copy of {WORKFLOW_RELPATH} pins {theirs.effective[:7]}{label}, "
        f"not {own.effective[:7]} as {base} does: its scheduled runs stop on the pin check; {clause}; {copy_step}"
    )
