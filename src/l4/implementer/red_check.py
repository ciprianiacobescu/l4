"""The targeted red check (SPEC L4-CFG-007, L4-GAT-007..009, L4-IMP-117..122): a red step that only adds test modules
runs only those, and every other step runs the whole suite as before. Pure: this module runs no gate and no git. It
may only send a step to the whole suite, never judge it more leniently than a whole run would."""

import shlex
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from l4.config.schema import L4Config
from l4.fsutil import UnsafeFile, read_inside
from l4.gates.junit import TestReport
from l4.implementer.stubs import MAX_SOURCE_BYTES, is_tool_noise
from l4.implementer.test_locate import file_of_id
from l4.security.protected import glob_match
from l4.verifier.support_base import is_support_source

if TYPE_CHECKING:
    from l4.implementer.stubs import RedScope

MAX_FILES = 50
MAX_PATH_BYTES = 8000
MAX_DETAIL = 300
MAX_NAMED = 5
FILES = "{files}"


@dataclass(frozen=True)
class Targeted:
    """The step runs its new test files only."""

    files: tuple[str, ...]


@dataclass(frozen=True)
class Full:
    """The step runs the whole suite: `why` is a word of L4-IMP-117 or L4-GAT-009, `detail` at most 300 characters."""

    why: str
    detail: str = ""


def detail_of(items: Iterable[str]) -> str:
    """At most five of `items`, sorted, and at most 300 characters (L4-IMP-120)."""
    ordered = sorted(items)
    text = ", ".join(ordered[:MAX_NAMED]) + (f" (+{len(ordered) - MAX_NAMED} more)" if len(ordered) > MAX_NAMED else "")
    return text if len(text) <= MAX_DETAIL else text[: MAX_DETAIL - 3] + "..."


def targeted_command(template: str, files: Iterable[str]) -> str:
    """`template` split with `shlex`, its one `{files}` word replaced by `files` (sorted by their text) as separate
    words, joined again (L4-GAT-007): the gate runner splits the result the same way and runs no shell, so a path is one
    argument whatever it holds."""
    words: list[str] = []
    for word in shlex.split(template):
        words += sorted(files) if word == FILES else [word]
    return shlex.join(words)


def with_targeted(base: TestReport, targeted: TestReport) -> TestReport:
    """The report the red checks judge (L4-GAT-008): the tests of the base report and those of the targeted report
    (disjoint: `unusable` refuses a run that holds an id of the base), no collection error. A new object."""
    return TestReport({**base.tests, **targeted.tests}, [], {})


def _file_of(cfg: L4Config, worktree: Path, path: str) -> bool:
    """True when `path` is a test module: a test glob, no support or runner-configuration glob, and no support file by
    the verifier's rule applied to the work-tree file (L4-IMP-117)."""
    tdd = cfg.tdd
    if not any(glob_match(g, path) for g in tdd.test_globs):
        return False
    if any(glob_match(g, path) for g in (*tdd.test_support_globs, *tdd.runner_config_files)):
        return False
    source: str | None = None
    if path.endswith(".py"):
        try:
            got = read_inside(worktree, path, limit=MAX_SOURCE_BYTES)
            source = None if got is None else got[0].decode("utf-8")
        except (UnsafeFile, OSError, ValueError):  # a link, a missing file or not UTF-8 text: no test module
            source = None
    return not is_support_source(cfg, path, source)


def _odd(path: str) -> bool:
    return path.startswith("-") or any(ord(c) < 32 or ord(c) == 127 for c in path)


def choose(
    cfg: L4Config,
    worktree: Path,
    *,
    switched: bool,
    named: bool,
    stale: bool,
    base_report: TestReport,
    scope: "RedScope",
    changed: Mapping[str, bool],
    ledger_rel: str,
) -> Targeted | Full:
    """The check of one red step of a `targeted` configuration (L4-IMP-117). `switched`: the unit's ledger holds
    `task.red_check_disabled`; `named`: the task names an existing test red may change; `stale`: a reopened task's stale
    tests; `changed`: path -> "existed at the base". The first rule that fails gives `why`. No model output and no
    clock: the same step gives the same answer."""
    if switched:
        return Full("unit_switched")
    if named:
        return Full("named_tests")
    if stale:
        return Full("stale_tests")
    if base_report.collection_errors:
        return Full("base_collection_errors", detail_of(base_report.collection_errors))
    if scope.stub_files or scope.stubs:
        return Full("stubs", detail_of(scope.stub_files))
    if scope.restored:
        return Full("restored", detail_of(scope.restored))
    mine = {p: existed for p, existed in changed.items() if p != ledger_rel and not is_tool_noise(p)}
    if old := [p for p, existed in mine.items() if existed]:
        return Full("existing_file_changed", detail_of(old))
    if not_tests := [p for p in mine if not _file_of(cfg, worktree, p)]:
        return Full("not_a_test_module", detail_of(not_tests))
    if not mine:
        return Full("no_test_file")
    if len(mine) > MAX_FILES or sum(len(p.encode("utf-8", "replace")) for p in mine) > MAX_PATH_BYTES:
        return Full("too_many_files", f"{len(mine)} files")
    if odd := [p for p in mine if _odd(p)]:
        return Full("odd_path", detail_of(ascii(p) for p in odd))
    return Targeted(tuple(sorted(mine)))


def unusable(
    base: TestReport,
    targeted: TestReport | None,
    files: Sequence[str],
    paths: Collection[str],
    *,
    reason: str = "",
) -> tuple[str, str] | None:
    """`(why, detail)` when the targeted run cannot stand for the whole suite, None when it is usable (L4-GAT-009).
    Tested in this order: a report was read; no collection error; no id of the base report ran; every file owns an id
    and every id belongs to a file; every id fails or errors. `paths`: the tracked paths, listed files among them."""
    if targeted is None:
        return "no_report", detail_of([reason]) if reason else ""
    if targeted.collection_errors:
        return "collection_errors", detail_of(targeted.collection_errors)
    if ran := [i for i in targeted.tests if i in base.tests]:
        return "existing_tests_ran", detail_of(ran)
    owners = {i: file_of_id(i, paths, preferred=files) for i in targeted.tests}
    if empty := [f for f in files if f not in owners.values()]:
        return "file_without_tests", detail_of(empty)
    if stray := [i for i, owner in owners.items() if owner not in files]:
        return "id_without_file", detail_of(stray)
    if passing := [i for i, case in targeted.tests.items() if case.status not in ("failed", "error")]:
        return "new_test_not_failing", detail_of(passing)
    return None


def unit_switched(events: Iterable[Any]) -> bool:
    """The unit's ledger holds `task.red_check_disabled` (L4-IMP-121): its red steps run the whole suite."""
    return any(e.type == "task.red_check_disabled" for e in events)


def unit_targeted(events: Iterable[Any]) -> bool:
    """A red step of the unit (or of a fix unit) ran targeted: its `task.red_ok` says `check: targeted`."""
    return any(e.type == "task.red_ok" and e.data.get("check") == "targeted" for e in events)
