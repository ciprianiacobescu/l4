"""Step 3 runs a failed gate again when its only failures are a few pre-existing tests (L4-VER-076, design
gate-flake-rerun).

`settle` takes the first outcome of the test gate or the e2e gate and a callable that runs the same gate again under a
name (`<gate>-repeat-<n>`). A gate is repeated only when its report was read, holds no collection error and every id
it has to hold, is not the altered-report blocker, and one to `MAX_REPEAT_FAILURES` tests failed or errored, every one
of them pre-existing (`pre_existing`: not a red test of the unit, in a file that `git diff <base> <head>` does not
name). It runs at most `verifier.flaky_repeats` times in all, and stops once every failing test has passed in a run.
Over the usable runs, a test that failed in one and passed in another is flaky: the minor finding `FLAKY_TITLE`, and not
a failure; a pre-existing test that never passed, and a test that is not pre-existing and failed in any run, keep the
gate's blocker. The report it hands on is the first run's with each flaky test's passing case, so that step 4 does not
fail a criterion on a flake that step 3 excused. Step 1's repeat (L4-VER-038) is `base_tests`'s own.
"""

import re
from collections.abc import Callable, Collection, Sequence
from dataclasses import replace
from typing import TypeVar

from l4.gates.junit import TestCase, TestReport, fold_subtest_id
from l4.implementer.test_locate import file_of_id
from l4.implementer.workbench import Workbench
from l4.vcs.git import Git, GitError
from l4.verifier.gates import ALTERED, MAX_NAMED, TestGateOutcome
from l4.verifier.integrity import _changed, _listed
from l4.verifier.types import Finding, GateLine, Severity

FLAKY_TITLE = "a pre-existing test is flaky in the {gate} gate"
MAX_REPEAT_FAILURES = 5  # a flake is one or a few tests; a change that breaks the app fails many, and is not repeated
_REPEAT = re.compile(r"(?:test|e2e)-repeat-\d+")
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
        path = file_of_id(test_id, tree, changed)
        return path is not None and path not in changed

    return check


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
) -> Outcome:
    """`first` after the repeats of its gate (D2 to D7); `first` itself when none is made. `gate`: `test` or `e2e`;
    `again(name)` runs the gate once more as `name` and raises what a first run would (a server that never gets ready,
    the soft deadline); `runs`: `verifier.flaky_repeats`. Emits `verify.gate_repeat` after the last repeat."""
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
    while pending and made < runs:
        made += 1
        repeat = again(repeat_name(gate, made - 1))
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
    stopped = stopped or ("limit" if pending else "passed")
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
