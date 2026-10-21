"""A killed run's snapshot decides what the next run does with the step it interrupted (L4-STA-003)."""

import json

from l4.agents.base import RunResult
from l4.agents.fake import FakeAdapter, Step
from l4.implementer.tdd import agent_step
from l4.redact import Redactor
from l4.specs.base import Task
from l4.state.ledger import LedgerWriter
from l4.state.reconcile import MarkFinished, Rerun, RestoreWip, plan_reconcile, reconcile
from l4.vcs.wip import wip_ref

from ..implementer import conftest as bench_conftest
from ..implementer.conftest import UNIT, Bench

make_bench = bench_conftest.make_bench  # the fixture of the implementer tests, available here too

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 1, 3)
PARTIAL = "src/pytdd/partial.py"


class Partial:
    name = "fake"

    def capabilities(self):  # the prompt asks for the schema mode (M1.2 prompt-contract adapters)
        return FakeAdapter([]).capabilities()

    def run(self, req) -> RunResult:
        (req.cwd / PARTIAL).write_text("PARTIAL = True\n")
        return FakeAdapter([Step(structured={"status": "done", "phase": "green", "task_ids": ["1.1"]})]).run(req)


def interrupted(make_bench) -> tuple[Bench, LedgerWriter]:
    """A bench whose green step 1.1/green/1 left a snapshot, then 'crashed': the worktree is back at HEAD and the next
    run has a ledger file of its own."""
    bench = make_bench([])
    bench.wb.selected.impl = Partial()  # type: ignore[misc]
    agent_step(bench.wb, "green", TASK, 1, None)
    snapshot = bench.wb.git.rev_parse(wip_ref(UNIT))
    bench.wb.discard_changes()  # a fresh clone has a clean tree; discarding also drops the ref, which a crash does not
    bench.wb.git.run("update-ref", wip_ref(UNIT), snapshot)
    writer = LedgerWriter.open(bench.wb.ref.path, UNIT, "r-20261003T1400Z-0002", redactor=Redactor({}))
    return bench, writer


def reconciled(bench: Bench) -> list[dict]:
    path = bench.wb.ref.path / ".l4" / "ledger"
    lines = [line for f in sorted(path.glob("*.jsonl")) for line in f.read_text().splitlines()]
    return [e for e in map(json.loads, lines) if e["type"] == "step.reconciled"]


def test_crash_mid_step_reconciles_without_duplicates(make_bench):
    bench, writer = interrupted(make_bench)
    wb = bench.wb
    head = wb.head()
    assert not (wb.worktree / PARTIAL).exists()
    action = reconcile(wb.git, wb.ref, writer)
    assert action == RestoreWip("1.1/green/1", wb.git.rev_parse(wip_ref(UNIT)))
    assert (wb.worktree / PARTIAL).read_text() == "PARTIAL = True\n"  # put back as uncommitted work
    assert wb.head() == head and wb.git.run("diff", "--cached", "--name-only").stdout == ""  # no commit, index clean
    [event] = reconciled(bench)
    assert (event["action"], event["step"], event["sha"]) == ("restore_wip", "1.1/green/1", action.sha)
    # the step re-runs on the restored tree and commits once
    commit = wb.commit("feat(add-discount-codes): green [skip ci]", task="1.1", attempt=1, phase="green", tdd="green")
    greens = wb.git.run("log", "--format=%H", "--grep=L4-Step: 1.1/green/1", "origin/main..HEAD").stdout.split()
    assert greens == [commit]


def test_a_commit_with_that_step_means_it_finished_and_the_snapshot_is_dropped(make_bench):
    bench, writer = interrupted(make_bench)
    wb = bench.wb
    (wb.worktree / PARTIAL).write_text("PARTIAL = True\n")
    snapshot = wb.git.rev_parse(wip_ref(UNIT))
    commit = wb.commit("feat(add-discount-codes): green [skip ci]", task="1.1", attempt=1, phase="green", tdd="green")
    wb.git.run("update-ref", wip_ref(UNIT), snapshot)  # a kill between the commit and the ref's removal
    assert plan_reconcile(wb.git, UNIT) == MarkFinished("1.1/green/1", commit)
    action = reconcile(wb.git, wb.ref, writer)
    assert action == MarkFinished("1.1/green/1", commit)
    assert wb.git.rev_parse(wip_ref(UNIT)) is None  # stale: gone
    [event] = reconciled(bench)
    assert (event["action"], event["commit"]) == ("mark_finished", commit)


def test_a_snapshot_of_a_head_that_is_gone_is_dropped_and_the_step_reruns(make_bench):
    bench, writer = interrupted(make_bench)
    wb = bench.wb
    (wb.worktree / "src" / "pytdd" / "other.py").write_text("OTHER = 1\n")
    snapshot = wb.git.rev_parse(wip_ref(UNIT))
    wb.commit("test(add-discount-codes): red for 1.9 [skip ci]", task="1.9", attempt=1, phase="red", tdd="red")
    wb.git.run("update-ref", wip_ref(UNIT), snapshot)  # the head moved on while the snapshot stayed
    action = reconcile(wb.git, wb.ref, writer)
    assert action == Rerun("1.1/green/1")
    assert wb.git.rev_parse(wip_ref(UNIT)) is None
    assert reconciled(bench)[0]["action"] == "rerun"


def test_nothing_to_reconcile_without_a_snapshot(make_bench):
    bench = make_bench([])
    assert reconcile(bench.wb.git, bench.wb.ref, bench.wb.ledger) is None
    assert reconciled(bench) == []


def test_a_snapshot_without_a_step_trailer_is_restored(make_bench):
    from l4.vcs.wip import snapshot_wip

    bench = make_bench([])
    wb = bench.wb
    (wb.worktree / PARTIAL).write_text("PARTIAL = True\n")
    sha = snapshot_wip(wb.git, UNIT, config=wb.exclude_config)
    wb.discard_changes()
    wb.git.run("update-ref", wip_ref(UNIT), sha)  # discarding drops the ref; a crashed run never got to
    assert reconcile(wb.git, wb.ref, wb.ledger) == RestoreWip(None, sha)
    assert (wb.worktree / PARTIAL).exists()
