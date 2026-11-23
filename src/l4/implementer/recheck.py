"""A task step runs its test gate once more before it fails an attempt on a few pre-existing tests (L4-IMP-105).

A red step or a green step (or a fix, tests or refactor chore) that would fail its attempt only because one to five
pre-existing tests regressed runs its whole test gate again, as `test-recheck`, on the tree run 1 started from. A
regressed test that passes there is flaky: the attempt goes on with run 1's report, each flaky test's case taken from
the re-run (the merged report), and is judged again by the step's own checks. A test that fails again, or a test that
passed in run 1 and does not in the re-run, still fails the attempt, with a text that says so. The re-run is recorded as
`task.tests_rechecked`, and `verification.md` lists what passed only on it (L4-VER-082).

The step, not this module, decides which failure is a candidate: `classify_red` and `green_failures` say that the
last reason of the attempt is the regression (`RedVerdict.regressed`, `GreenWhy.regressed`). The text of a reason is
never read here.
"""

import logging
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from typing import Any

from l4.gates.hang import TIMEOUT_MARKER
from l4.gates.junit import TestReport
from l4.gates.runner import GateResult
from l4.implementer.workbench import Workbench
from l4.vcs.git import GitError
from l4.verifier.gate_repeat import MAX_REPEAT_FAILURES, short_of_time, tree_reset, untouched

log = logging.getLogger(__name__)

FAILED = ("failed", "error")
MAX_RECORDED = 20  # ids per list of `task.tests_rechecked`
MAX_NAMED = 5  # ids a reason's suffix names
ROOM_FACTOR = 2.0  # the re-run starts only when the soft deadline leaves this many run-1 durations (and the margin)


def recheck_candidates(
    report: TestReport | None, regressed: Sequence[str], untouched_by: Callable[[str], bool]
) -> list[str] | None:
    """The ids to run again, or None when the step gets no re-run: one to `MAX_REPEAT_FAILURES` regressed ids, each
    failed or errored in `report` (an id the report lacks is gone, not flaky), none with the time-out marker in its
    message (a hang costs its whole timeout again), and each one `untouched_by` the unit and the step."""
    if report is None or not 1 <= len(regressed) <= MAX_REPEAT_FAILURES:
        return None
    for test_id in regressed:
        case = report.tests.get(test_id)
        if case is None or case.status not in FAILED or TIMEOUT_MARKER in case.message:
            return None
    return sorted(regressed) if all(untouched_by(i) for i in regressed) else None


def _untouched_rule(wb: Workbench, red_tests: Collection[str]) -> Callable[[str], bool]:
    """`gate_repeat.untouched` on what the step sees: the files of HEAD and of the work tree, and the files that the
    unit's branch or this step changed. A git failure is no rule at all: nothing is re-run."""
    try:
        listing = wb.git.run_bytes("ls-tree", "-r", "--name-only", "-z", "HEAD").decode("utf-8", "replace")
        step_changed = wb.changed_files()
        tree = [*(p for p in listing.split("\0") if p), *step_changed]
        changed = {*wb.branch_changed_files(), *step_changed}
    except GitError:
        return lambda _id: False
    return untouched(tree, changed, red_tests)


@dataclass
class Rerun:
    """What a step's re-run decided. `report` is the merged report when every regressed test passed and nothing that
    passed in run 1 failed (the step goes on with it and judges it again); None otherwise, and then `suffix` is the text
    that follows run 1's reason. `guard` is what the step's guard after a gate run returned."""

    report: TestReport | None = None
    suffix: str = ""
    guard: Any = None
    stopped: str = ""


def _ids(found: Sequence[str]) -> list[str]:
    return list(found)[:MAX_RECORDED]


def recheck_step(
    wb: Workbench,
    *,
    task: str,
    phase: str,
    attempt: int,
    run_1: GateResult,
    regressed: Sequence[str],
    red_tests: Collection[str],
    reset: Callable[[], bool] | None,
    extra_env: dict[str, str] | None,
    guard: Callable[[], Any],
) -> Rerun | None:
    """The re-run of L4-IMP-105, or None when the step gets none (no candidates: nothing is recorded). `reset` is
    `tree_reset`, taken right before run 1 (a None means that git could not list the tree). `guard` is the step's own
    check after a gate run (red's tamper check, green's replay restore) and runs after the re-run."""
    report = run_1.report
    if report is None or not regressed:
        return None
    candidates = recheck_candidates(report, regressed, _untouched_rule(wb, red_tests))
    if candidates is None:
        return None

    def record(stopped: str, flaky: Sequence[str] = (), failing: Sequence[str] = (), new: Sequence[str] = ()) -> None:
        wb.emit(
            "task.tests_rechecked", task=task, phase=phase, attempt=attempt, tests=_ids(candidates),
            flaky=_ids(flaky), failing=_ids(failing), new_failures=_ids(new), stopped=stopped,
        )  # fmt: skip

    if reset is None or not reset():  # the tree could not be put back: a re-run on a dirty tree proves nothing
        record("tree")
        return Rerun(stopped="tree")
    if short_of_time(run_1.seconds, runs=ROOM_FACTOR):
        record("budget")
        return Rerun(stopped="budget")
    again = wb.run_gate(
        "test-recheck", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports, extra_env=extra_env
    )
    guarded = guard()
    second = again.report
    if (
        second is None
        or second.collection_errors
        or second.executed == 0
        or any(i not in second.tests for i in candidates)
    ):
        record("unusable")
        return Rerun(suffix="; its re-run was not usable", guard=guarded, stopped="unusable")
    flaky = [i for i in candidates if second.tests[i].status == "passed"]
    failing = [i for i in candidates if i not in flaky]
    new = sorted(i for i in report.ids_with("passed") if i not in second.tests or second.tests[i].status in FAILED)
    if failing or new:
        record("failed", flaky, failing, new)
        named = [*failing, *new]
        more = f" (+{len(named) - MAX_NAMED} more)" if len(named) > MAX_NAMED else ""
        text = f"; failed again on a re-run (L4-IMP-105): {', '.join(named[:MAX_NAMED])}{more}"
        return Rerun(suffix=text, guard=guarded, stopped="failed")
    record("passed", flaky)
    log.warning("%s: task %s %s attempt %d: pre-existing tests failed once and passed on a re-run: %s",
                wb.ref.id, task, phase, attempt, ", ".join(flaky))  # fmt: skip
    merged = replace(report, tests={**report.tests, **{i: second.tests[i] for i in flaky}})
    return Rerun(report=merged, guard=guarded, stopped="passed")


def tree_before(wb: Workbench) -> Callable[[], bool] | None:
    """`tree_reset` of the step's worktree: what is untracked now, taken right before run 1 and after the agent's edits.
    The reports of the test gate are never removed."""
    return tree_reset(wb.git, wb.worktree, keep=wb.cfg.gates.test.reports)
