"""Step 3 runs a failed gate again when its only failures are a few pre-existing tests (L4-VER-076, design
gate-flake-rerun).

`settle` takes the first outcome of the test gate or the e2e gate and a callable that runs the same gate again under a
name (`<gate>-repeat-<n>`). A gate is repeated only when its report was read, holds no collection error and every id
it has to hold, is not the altered-report blocker, and one to `MAX_REPEAT_FAILURES` tests failed or errored, every one
of them pre-existing (`pre_existing`: not a red test of the unit, in a file that `git diff <base> <head>` does not
name). It runs at most `verifier.flaky_repeats` times in all, and stops once every failing test has passed in a run,
when a repeat fails exactly as run 1 did, or when the soft deadline leaves too little time for another run. Before a
repeat the worktree is put back to what run 1 started from (`tree_reset`).
Over the usable runs, a test that failed in one and passed in another is flaky: the minor finding `FLAKY_TITLE`, and not
a failure; a pre-existing test that never passed, and a test that is not pre-existing and failed in any run, keep the
gate's blocker. The report it hands on is the first run's with each flaky test's passing case, so that step 4 does not
fail a criterion on a flake that step 3 excused. Step 1's repeat (L4-VER-038) is `base_tests`'s own.
"""

import logging
import os
import re
import shutil
from collections.abc import Callable, Collection, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TypeVar

from l4 import deadline
from l4.exitcodes import L4Exit
from l4.fsutil import UnsafeFile, reject_symlinks
from l4.gates.junit import TestCase, TestReport, fold_subtest_id
from l4.implementer.test_locate import file_of_id
from l4.implementer.workbench import Workbench
from l4.vcs.git import Git, GitError
from l4.verifier.gates import ALTERED, MAX_NAMED, TestGateOutcome
from l4.verifier.integrity import _changed, _listed
from l4.verifier.types import Finding, GateLine, Severity

log = logging.getLogger(__name__)

FLAKY_TITLE = "a pre-existing test is flaky in the {gate} gate"
MAX_REPEAT_FAILURES = 5  # a flake is one or a few tests; a change that breaks the app fails many, and is not repeated
_REPEAT = re.compile(r"(?:test|e2e)-repeat-\d+")
JS_EXTENSIONS = frozenset({"ts", "tsx", "js", "jsx", "mjs", "cjs", "mts", "cts"})
MIN_MARGIN_S = 60.0  # a repeat starts only when the soft deadline leaves run 1's duration plus this (or 10%)
HARNESS_DIRS = (".git", ".l4", ".l4-out")  # never removed between two runs: the ledger, the logs, the evidence
FAILED = ("failed", "error")

Outcome = TypeVar("Outcome", bound=TestGateOutcome)


def repeat_name(gate: str, n: int) -> str:
    """The name of the `n`-th repeat (1, 2, ...) of `gate`, after step 1's `base-tests-repeat`."""
    return f"{gate}-repeat-{n}"


def is_repeat(name: str) -> bool:
    return _REPEAT.fullmatch(name) is not None


def pre_existing(git: Git, base_sha: str, head: str, red_tests: Collection[str]) -> Callable[[str], bool]:
    """Is a failing test id pre-existing (design D1)? It is when it is not a red test of the unit (`red_tests`), its
    file is found among the files of the head tree (a path that `base..head` changed is preferred when several
    match, the cautious side) and `git diff <base> <head>` does not name that file. A test whose file is not found, a
    Go id and any test at all when git fails are not. The tree and the diff are read once, on the first call."""
    loaded: list[tuple[list[str], set[str]] | None] = []

    def read() -> tuple[list[str], set[str]] | None:
        if not loaded:
            try:
                listing = git.run_bytes("ls-tree", "-r", "--name-only", "-z", head).decode("utf-8", "replace")
                loaded.append(([p for p in listing.split("\0") if p], set(_changed(git, base_sha, head))))
            except GitError:
                loaded.append(None)
        return loaded[0]

    def check(test_id: str) -> bool:
        state = read()
        if state is None or test_id in red_tests or fold_subtest_id(test_id) in red_tests:
            return False
        tree, changed = state
        head_part = test_id.split("::", 1)[0]
        extension = head_part.rsplit(".", 1)[-1] if "." in head_part else ""
        if extension in JS_EXTENSIONS:  # a spec id never names a Python or Go file (`app.spec.ts` is not `app.py`)
            tree = [p for p in tree if p.endswith("." + extension)]
            changed = {p for p in changed if p.endswith("." + extension)}
            # Playwright writes the file relative to its test directory (`auth/signin.spec.ts`): dots, as the others
            test_id = head_part.replace("/", ".") + test_id[len(head_part) :]
        path = file_of_id(test_id, tree, changed)
        return path is not None and path not in changed and file_of_id(test_id, sorted(changed)) is None

    return check


def _untracked(git: Git) -> set[str] | None:
    """Every path git does not track, the ignored ones included, collapsed to the directory when it is untracked as a
    whole (`git ls-files --others --directory`); None when git fails."""
    try:
        listing = git.run_bytes("ls-files", "--others", "--directory", "-z")
    except GitError:
        return None
    return {os.fsdecode(p) for p in listing.split(b"\0") if p}


def tree_reset(git: Git, root: Path, keep: Collection[str] = ()) -> Callable[[], bool] | None:
    """Record what is untracked in `root` now, before run 1 of a gate (D10), and give the function that puts the tree
    back to it before a repeat: every entry that is new since, a file or a whole directory that run 1 created, is
    removed, so the repeat starts from the tree run 1 started from and a test that needs state an earlier run left
    cannot pass on it. The build of step 2 exists before run 1 and stays. The harness's own directories and the paths
    in `keep` (the gate's reports) are never removed. A file that run 1 added inside a directory that was already
    untracked as a whole stays (the tool caches are reset at every gate anyway). The function returns False when
    something could not be removed or listed: the repeat is not run. None when git cannot list the tree."""
    before = _untracked(git)
    if before is None:
        return None

    def kept(entry: str) -> bool:
        path = entry.rstrip("/")
        return path.split("/", 1)[0] in HARNESS_DIRS or any(k == path or k.startswith(path + "/") for k in keep)

    def reset() -> bool:
        now = _untracked(git)
        if now is None:
            return False
        clean = True
        for entry in sorted(now - before):
            if kept(entry):
                continue
            parts = entry.rstrip("/").split("/")
            target = root.joinpath(*parts)
            try:
                reject_symlinks(root, *parts[:-1])  # never remove through a link the gate planted
                if target.is_symlink() or target.is_file():
                    target.unlink()
                elif target.is_dir():
                    shutil.rmtree(target)
            except (UnsafeFile, OSError) as exc:
                log.warning("gate repeat: could not remove %s: %s", entry, exc)
                clean = False
        return clean

    return reset


def _failing(report: TestReport) -> set[str]:
    return {i for i, case in report.tests.items() if case.status in FAILED}


def _altered(outcome: TestGateOutcome) -> bool:
    return any(f.title == ALTERED for f in outcome.findings)


def _readable(outcome: TestGateOutcome, must_contain: Collection[str]) -> bool:
    """A report was read, holds no collection error and every id the gate has to hold."""
    report = outcome.report
    return report is not None and not report.collection_errors and all(i in report.tests for i in must_contain)


def _usable(outcome: TestGateOutcome, must_contain: Collection[str]) -> bool:
    """A repeat counts when its report is readable and either the gate passed or a test failed in it: a run that failed
    on its exit code with every test passing, or that executed no test, says nothing about the failing tests."""
    return _readable(outcome, must_contain) and (
        outcome.gate.status == "pass" or bool(outcome.report and _failing(outcome.report))
    )


def _short_of_time(first_seconds: float) -> bool:
    """Does the soft deadline leave less than another run needs: run 1's duration plus a margin?"""
    armed = deadline.current()
    return armed is not None and armed.remaining_s() < first_seconds + max(MIN_MARGIN_S, 0.1 * first_seconds)


def _runs(numbers: Sequence[int]) -> str:
    if len(numbers) == 1:
        return f"run {numbers[0]}"
    return "runs " + ", ".join(map(str, numbers[:-1])) + f" and {numbers[-1]}"


def settle(
    wb: Workbench,
    first: Outcome,
    *,
    gate: str,
    command: str,
    must_contain: Collection[str],
    again: Callable[[str], Outcome],
    is_pre_existing: Callable[[str], bool],
    runs: int,
    round_no: int,
    reset: Callable[[], bool] | None = None,
    first_seconds: float = 0.0,
) -> Outcome:
    """`first` after the repeats of its gate (D2 to D7); `first` itself when none is made. `gate`: `test` or `e2e`;
    `again(name)` runs the gate once more as `name`; the soft deadline (`DeadlineReached`) passes through, an `L4Exit`
    (a server that never gets ready) ends the repeats as an unusable repeat; `runs`: `verifier.flaky_repeats`;
    `reset()` puts the worktree back to what run 1 started from (`tree_reset`) and is called before each repeat;
    `first_seconds`: how long run 1 took, for the deadline. Emits `verify.gate_repeat` after the last repeat."""
    report = first.report
    if (
        runs < 2
        or report is None
        or first.gate.status != "fail"
        or _altered(first)
        or not _readable(first, must_contain)
    ):
        return first
    failing = _failing(report)
    if not failing or len(failing) > MAX_REPEAT_FAILURES or not all(map(is_pre_existing, failing)):
        return first
    seen: list[tuple[int, TestReport]] = [(1, report)]  # the runs that gave a usable report, by their number
    repeats: list[GateLine] = []
    extra: list[Finding] = []  # the blocker of a repeat whose report was altered
    pending, made, stopped = set(failing), 1, ""
    run_1 = {i: report.tests[i].message for i in failing}
    while pending and made < runs:
        if _short_of_time(first_seconds):
            stopped = "budget"
            break
        if reset is not None and not reset():
            stopped = "unusable"
            break
        made += 1
        try:
            repeat = again(repeat_name(gate, made - 1))
        except L4Exit as exc:  # the server of this repeat never got ready: the runner's trouble, not a finding
            log.warning("gate repeat %s: %s", repeat_name(gate, made - 1), exc)
            stopped = "unusable"
            break
        repeats.append(repeat.gate)
        if _altered(repeat):
            extra += [f for f in repeat.findings if f.title == ALTERED]
            stopped = "unusable"
            break
        if not _usable(repeat, must_contain):
            stopped = "unusable"
            break
        assert repeat.report is not None  # `_usable`
        seen.append((made, repeat.report))
        if not all(map(is_pre_existing, _failing(repeat.report))):
            stopped = "not_pre_existing"
            break
        pending -= repeat.report.ids_with("passed")
        if pending and {i: repeat.report.tests[i].message for i in _failing(repeat.report)} == run_1:
            stopped = "same_failures"  # it failed exactly as run 1 did: another run would say the same
            break
    stopped = stopped or ("limit" if pending else "passed")
    if made == 1:  # no repeat ran (no time left, or the tree could not be put back): run 1 stands, the ledger says why
        wb.emit(
            "verify.gate_repeat", round=round_no, gate=gate, runs=1, flaky=[], failing=sorted(failing), stopped=stopped
        )
        return first
    failed_in = {
        i: [n for n, rep in seen if i in _failing(rep)] for i in set().union(*(_failing(rep) for _, rep in seen))
    }
    passed_in = {i: [n for n, rep in seen if i in rep.ids_with("passed")] for i in failed_in}
    flaky = sorted(i for i in failed_in if passed_in[i] and is_pre_existing(i))
    still = sorted(set(failed_in) - set(flaky))
    findings: list[Finding] = []
    if still:
        detail = f"`{command}` failed ({made} runs); failing: {', '.join(still[:MAX_NAMED])}"
        findings.append(Finding(Severity.BLOCKER, f"{gate} gate failed", detail, "deterministic", log=first.gate.log))
    if flaky:
        listed = _listed([f"{i} (failed in {_runs(failed_in[i])}, passed in {_runs(passed_in[i])})" for i in flaky])
        findings.append(
            Finding(Severity.MINOR, FLAKY_TITLE.format(gate=gate), listed, "deterministic", log=first.gate.log)
        )
    findings += extra
    wb.emit("verify.gate_repeat", round=round_no, gate=gate, runs=made, flaky=flaky, failing=still, stopped=stopped)
    note = [f"{gate}: {made} runs (L4-VER-076)"]
    note += [
        f"{label}: {', '.join(ids[:MAX_NAMED])}" for label, ids in (("flaky", flaky), ("still failing", still)) if ids
    ]
    return replace(
        first,
        gate=replace(first.gate, status="flaky") if not still and not extra else first.gate,
        report=replace(report, tests=_handed_on(report, seen, flaky, still)),
        findings=findings, repeats=repeats, repeat_note="; ".join(note),
    )  # fmt: skip


def _handed_on(
    report: TestReport, seen: Sequence[tuple[int, TestReport]], flaky: Sequence[str], still: Sequence[str]
) -> dict[str, TestCase]:
    """The first run's cases, each flaky test's from the first run in which it passed (D6), and each test that still
    fails but passed in the first run (a repeat failed it) as its first failing case: every case is one a run
    produced, and `failures` holds the tests that still fail."""
    tests = dict(report.tests)
    for test_id in flaky:
        tests[test_id] = next(rep.tests[test_id] for _, rep in seen if test_id in rep.ids_with("passed"))
    for test_id in still:
        if test_id not in tests or tests[test_id].status not in FAILED:
            tests[test_id] = next(rep.tests[test_id] for _, rep in seen if test_id in _failing(rep))
    return tests
