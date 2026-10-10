"""Which units get browser checks (verifier 6.1, reduced): a unit is UI-facing when a file it changed matches
`verifier.playwright.ui_paths`. The S1 choice question of L4-VER-014 ("does this criterion describe observable UI
behaviour?") is deferred, so every criterion of a UI-facing unit is a UI criterion.

Also the merge-base checkout that step 5 serves next to the head app (verifier 6.2, plan D3) and the trace and
screenshot files of a failing e2e run (6.3). The e2e command has to ask pytest-playwright to write them
(`--tracing retain-on-failure --screenshot only-on-failure`); the output directory is the command's `--output`, or
`test-results/` (pytest-playwright's default).
M1: verifier 6.1 (the S1 choice question)
"""

import shlex
import shutil
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from l4.config.schema import L4Config, duration_seconds
from l4.exitcodes import ExitCode, L4Exit
from l4.gates.e2e import run_gate_at
from l4.gates.junit import TestReport
from l4.gates.runner import GateSpec
from l4.implementer.workbench import Workbench
from l4.security.protected import glob_match
from l4.specs.base import Criterion
from l4.vcs.git import Git

BASE_DIR = "e2e-base"
ARTIFACT_DIR = "test-results"
ARTIFACT_NAMES = ("trace.zip",)
ARTIFACT_SUFFIXES = (".png", ".webm")
MAX_ARTIFACTS = 50


def playwright_enabled(cfg: L4Config) -> bool:
    """`auto` follows the e2e gate: on when `gates.e2e.command` is configured."""
    setting = cfg.verifier.playwright.enabled
    return bool(cfg.gates.e2e.command.strip()) if setting == "auto" else setting


def unit_changed_files(git: Git, base_sha: str, head: str = "HEAD") -> list[str]:
    """Paths the unit branch changed since its merge base (`Preconditions.base_sha`), renames as delete plus add."""
    raw = git.run_bytes("diff", "--name-only", "-z", "--no-renames", base_sha, head)
    return sorted({name.decode("utf-8", "surrogateescape") for name in raw.split(b"\0") if name})


def ui_files(changed: Iterable[str], ui_paths: Sequence[str]) -> list[str]:
    """The changed files under `ui_paths`: the UI diff the test writer is shown."""
    return [path for path in changed if any(glob_match(pattern, path) for pattern in ui_paths)]


def ui_facing_criteria(
    criteria: Sequence[Criterion], changed: Iterable[str], ui_paths: Sequence[str]
) -> list[Criterion]:
    return list(criteria) if ui_files(changed, ui_paths) else []


def _remove_checkout(wb: Workbench, path: Path) -> None:
    wb.git.run("worktree", "remove", "--force", str(path), check=False)
    shutil.rmtree(path, ignore_errors=True)
    wb.git.run("worktree", "prune", check=False)


@contextmanager
def base_checkout(wb: Workbench, base_sha: str) -> Iterator[Path]:
    """A detached worktree of the merge base with `gates.setup` run in it (with the network: that is where the
    dependencies are downloaded), removed on the way out whatever happens. A setup that fails here is an internal
    error (exit 1): it passed at the head, so the harness or the runner is at fault, not the unit (L4-VER-010)."""
    path = wb.unit_cache / BASE_DIR
    _remove_checkout(wb, path)  # a checkout left by a killed run
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.git.run("worktree", "add", "--detach", str(path), base_sha)
    try:
        for command in wb.cfg.gates.setup:
            spec = GateSpec("setup-base", command, (), "junit", duration_seconds(wb.cfg.gates.timeout))
            result = run_gate_at(wb, path, spec, network=True)
            if result.status != "pass":
                raise L4Exit(ExitCode.INTERNAL_ERROR, f"gates.setup failed at the merge base: {result.reason}")
        yield path
    finally:
        _remove_checkout(wb, path)


def artifact_dir(command: str) -> str:
    """Where the e2e command makes pytest-playwright write traces: its `--output` argument when that is a plain
    relative path (the command is config, but the path ends up joined to a worktree), else the default."""
    try:
        words = shlex.split(command)
    except ValueError:
        return ARTIFACT_DIR
    for i, word in enumerate(words):
        if word == "--output" and i + 1 < len(words):
            value = words[i + 1]
        elif word.startswith("--output="):
            value = word.removeprefix("--output=")
        else:
            continue
        path = PurePosixPath(value)
        if value and not path.is_absolute() and ".." not in path.parts:
            return path.as_posix()
    return ARTIFACT_DIR


def failure_artifacts(tree: Path, report: TestReport | None, *, directory: str = ARTIFACT_DIR) -> list[str]:
    """Traces and screenshots that a run with failing tests left under `directory`, as paths relative to `tree`
    (sorted, at most MAX_ARTIFACTS, regular files only). Nothing when no test failed."""
    if report is None or not (report.ids_with("failed") | report.ids_with("error")):
        return []
    root = tree / directory
    if root.is_symlink() or not root.is_dir():
        return []
    found = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if path.name in ARTIFACT_NAMES or path.suffix in ARTIFACT_SUFFIXES:
            found.append(path.relative_to(tree).as_posix())
    return found[:MAX_ARTIFACTS]
