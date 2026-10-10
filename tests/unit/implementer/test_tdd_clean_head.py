"""A baseline measures the step base, never the work a killed run left in the worktree (L4-IMP-002, L4-STA-003)."""

from l4.implementer.tdd import baseline, resume_red, run_red, static_baseline
from l4.specs.base import Task

from .conftest import IMPL, red_step

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
PRICING = "src/pytdd/pricing.py"
BROKEN = IMPL.replace("round(sum(prices), 2)", "0")


def test_resume_red_takes_its_baseline_from_the_red_commit_not_from_the_restored_work(make_bench):
    bench = make_bench([red_step()])
    wb = bench.wb
    red = run_red(wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    # what reconcile puts back after a kill: a green attempt that broke an existing test, plus a new file
    (wb.worktree / PRICING).write_text(BROKEN)
    (wb.worktree / "wip_note.txt").write_text("half done\n")

    resumed = resume_red(wb, TASK)

    assert resumed is not None and resumed.base_report is not None
    failing = resumed.base_report.ids_with("failed")
    assert not failing, f"the WIP's breakage leaked into the baseline: {sorted(failing)}"
    # the work is back afterwards, the ledger kept every event written meanwhile
    assert (wb.worktree / PRICING).read_text() == BROKEN
    assert (wb.worktree / "wip_note.txt").read_text() == "half done\n"
    assert [e["name"] for e in bench.events("gate.finished")].count("baseline") >= 1


def test_baselines_are_measured_at_a_clean_head_and_cached_per_commit(make_bench):
    bench = make_bench([])
    wb = bench.wb
    (wb.worktree / PRICING).write_text(BROKEN)
    report = baseline(wb, wb.head())
    assert not report.ids_with("failed")
    assert static_baseline(wb, wb.head()) == {}
    assert (wb.worktree / PRICING).read_text() == BROKEN
    assert baseline(wb, wb.head()) is report


def test_the_tracked_ledger_keeps_every_line_written_while_the_work_is_set_aside(make_bench):
    bench = make_bench([red_step()])
    wb = bench.wb
    assert run_red(wb, TASK, attempt=1).status == "ok"  # the red commit carries the ledger as it was then
    (wb.worktree / PRICING).write_text(BROKEN)
    before = (wb.worktree / wb.ledger_rel).read_bytes()
    with wb.at_clean_head():
        wb.emit("task.note", note="written while the baseline runs")
        during = (wb.worktree / wb.ledger_rel).read_bytes()
        assert during.startswith(before) and during != before
    after = (wb.worktree / wb.ledger_rel).read_bytes()
    assert after == during  # the snapshot's (HEAD's) copy did not replace the live file
    assert (wb.worktree / PRICING).read_text() == BROKEN
