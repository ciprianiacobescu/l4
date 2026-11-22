"""An older `l4` does not write for a newer pin (L4-OPS-026, readiness-entry-and-actor D5).

The repository's pin is the contract CI runs. A person's command that records an event or pushes a commit applies the
same rules locally, so an `l4` older than the pin would apply rules the pin has since fixed. Outside a CI job such a
command compares the running version with the pin before it reads or writes anything else, with no fetch and no
network: the pin is read at `refs/remotes/origin/<base>` as last fetched, else in the working tree. An unknown pin (a
copy of the action, a comment that is not a version, a file that is absent, unreadable or too large) means no check.

An older `l4` makes the writing commands exit 2 unless `--allow-older-cli` is given (then a warning); a stop, a
withdrawal and a command that writes only a local file warn and run. A newer `l4` only warns."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from l4 import __version__
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.versions import parse_version

MAX_BYTES = 1024 * 1024  # the bound of `relay.MAX_CONFIG_BYTES`
CONFIG_PATH = ".l4/config.yaml"
WORKFLOW_PATH = ".github/workflows/l4.yml"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_USES = re.compile(
    r"uses:\s*(?P<repo>[\w.-]+/[\w.-]+)/\.github/actions/l4@[0-9a-f]{40}\s+#\s*v?(?P<version>\d+\.\d+\.\d+)\b",
    re.ASCII,
)


@dataclass(frozen=True)
class Pin:
    """The version a repository pins, where it was read (`source`), and for an action pin its `owner/repo`."""

    version: str
    source: str
    repository: str | None = None


def _where(ref: str | None) -> str:
    return f"at {ref.removeprefix('refs/remotes/')}" if ref else "in the working tree"


def _read_ref(app: AppContext, ref: str, path: str) -> str | None:
    """The text of `path` at `ref` when it is a regular file of at most 1 MB, else None (`git show`, no fetch)."""
    from l4.vcs.git import Git

    git = Git(app.repo, environ=app.environ)
    listed = git.run("ls-tree", ref, "--", path, check=False)
    if listed.returncode != 0 or not listed.stdout.strip():
        return None
    mode = listed.stdout.split()[0]
    if mode not in ("100644", "100755"):  # a symbolic link or a submodule is no configuration
        return None
    data = git.run_bytes("show", f"{ref}:{path}", check=False)
    if not data or len(data) > MAX_BYTES:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _read_tree(root: Path, path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def pinned_version(app: AppContext) -> Pin | None:
    """The version the repository pins, or None when it cannot be told (nothing is then said)."""
    from l4.ci.relay import lenient_settings, lenient_settings_text
    from l4.vcs.git import Git

    base = lenient_settings(app.repo, app.config_path).get("forge.base_branch") or "main"
    ref = f"refs/remotes/origin/{base}"
    git = Git(app.repo, environ=app.environ)
    if git.rev_parse(ref) is not None:
        config_text = _read_ref(app, ref, CONFIG_PATH)
        workflow_text = _read_ref(app, ref, WORKFLOW_PATH)
        where: str | None = ref
    else:
        config_path = app.config_path if app.config_path is not None else app.repo / CONFIG_PATH
        config_text = _read_tree(app.repo, config_path)
        workflow_text = _read_tree(app.repo, app.repo / WORKFLOW_PATH)
        where = None
    if config_text is None:
        return None
    settings = lenient_settings_text(config_text, workflow_text)
    if settings.get("harness.delivery") == "action":
        found = _USES.search(workflow_text or "")
        if found is None:  # a copy of the action, or a comment that is no version: a sha says "differs", never "older"
            return None
        source = f"the uses: line of {WORKFLOW_PATH} {_where(where)}"
        return Pin(found.group("version"), source, found.group("repo"))
    match = _VERSION.match(settings.get("harness.version", ""))
    if match is None:
        return None
    return Pin(".".join(match.groups()), f"harness.version {_where(where)}")


# --- which command writes ----------------------------------------------------------------------------------------

REFUSE, WARN = "refuse", "warn"


def _words(options: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(options.get("words") or ())


def _questions(options: Mapping[str, Any]) -> str | None:
    if (_words(options) or ("list",))[0] not in ("accept", "answer"):
        return None
    return WARN if options.get("no_push") else REFUSE


def _review(options: Mapping[str, Any]) -> str | None:
    return REFUSE if options.get("local") or (options.get("worktree") and options.get("record")) else None


def _unless(flag: str) -> Callable[[Mapping[str, Any]], str | None]:
    return lambda options: None if options.get(flag) else REFUSE


def _withdrawable(options: Mapping[str, Any]) -> str | None:
    return WARN if options.get("withdraw") else REFUSE


def _only(kind: str) -> Callable[[Mapping[str, Any]], str | None]:
    return lambda options: kind


def _lessons(options: Mapping[str, Any]) -> str | None:
    return WARN if (_words(options) or ("",))[0] == "promote" else None


WRITES: dict[str, Callable[[Mapping[str, Any]], str | None]] = {
    "run": _unless("dry_run"),
    "verify": _only(REFUSE),
    "archive": _only(REFUSE),
    "resume": _only(REFUSE),
    "retry": _only(REFUSE),
    "restart": _only(REFUSE),
    "plan": lambda options: REFUSE if options.get("sweep") else None,
    "questions": _questions,
    "yolo review": _review,
    "yolo accept": _withdrawable,
    "yolo waive": _withdrawable,
    "yolo activate": _only(REFUSE),
    "yolo resume": _only(REFUSE),
    "yolo go": _only(REFUSE),
    "yolo cancel": _only(WARN),
    "yolo draft": _only(WARN),
    "feedback add": _only(WARN),
    "feedback submit": _only(WARN),
    "feedback withdraw": _only(WARN),
    "lessons": _lessons,
}


def _install(app: AppContext, pin: Pin) -> str:
    if (app.repo / ".l4" / "bin" / "l4").exists():
        return "use .l4/bin/l4 (it runs the pinned harness)"
    if pin.repository is not None:
        return f"install it: uv tool install --force git+https://github.com/{pin.repository}@v{pin.version}"
    return f"install l4 v{pin.version}"


def check(name: str, options: Mapping[str, Any], app: AppContext, *, allow_older: bool = False) -> None:
    """Called by the command line before the command runs. Exit 2 (`L4Exit`) for a writing command of an older `l4`;
    a warning on stderr for the commands that only stop or write locally, with `--allow-older-cli`, and for a newer
    `l4`. Nothing for a CI job, an unknown pin, an equal version, or a command that does not write."""
    from l4.ci.detect import in_ci_job

    rule = WRITES.get(name)
    if rule is None or in_ci_job(app.environ):
        return
    kind = rule(options)
    if kind is None:
        return
    try:
        pin = pinned_version(app)
    except Exception:  # a pin that cannot be read is no pin: the check never blocks a command it cannot judge
        return
    have, wanted = parse_version(__version__), parse_version(pin.version) if pin else None
    if pin is None or have is None or wanted is None or have == wanted:
        return
    install = _install(app, pin)
    where = f"{pin.version}, {pin.source}"
    if have > wanted:
        click.echo(
            f"warning: this l4 is {__version__}, newer than the harness this repository pins ({where}): CI runs "
            f"{pin.version}, so a rule of {__version__} may differ there; {install}",
            err=True,
        )
        return
    warning = f"warning: this l4 is {__version__}, older than the harness this repository pins ({where}); {install}"
    if kind == REFUSE and not allow_older:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"{name}: this l4 is {__version__}, older than the harness this repository pins ({where}): it would "
            f"apply the rules of {__version__} to the repository's units and plans\n"
            f"Fix: {install}, or pass --allow-older-cli to run this l4 anyway",
        )
    click.echo(warning, err=True)
