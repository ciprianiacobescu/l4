"""The record of a refused harness write (L4-SEC-021, design D4): a planted link is removed, never followed."""

import shutil

import pytest

from l4.fsutil import LinkedPath, UnsafeFile
from l4.implementer.guardnotes import guard_note_text
from l4.implementer.loop import run_task
from l4.implementer.workbench import UnsafeWrite
from l4.specs.base import Task

from .conftest import blocked_step

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)


@pytest.fixture
def bench_with_link(make_bench, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "pricing.py").write_text("outside\n")
    bench = make_bench([])
    wb = bench.wb
    shutil.rmtree(wb.worktree / "src/pytdd")
    (wb.worktree / "src/pytdd").symlink_to(outside)
    return bench, outside


def test_refused_write_removes_the_link_and_not_its_target_and_emits_one_violation(bench_with_link):
    bench, outside = bench_with_link
    wb = bench.wb
    wb.refused_write(LinkedPath("src/pytdd"), path="src/pytdd/pricing.py", where="test-zero")
    assert not (wb.worktree / "src/pytdd").exists() and not (wb.worktree / "src/pytdd").is_symlink()
    assert (outside / "pricing.py").read_text() == "outside\n"
    (event,) = bench.events("guard.violation")
    flat = event.get("data", event)
    assert flat["phase"] == "gate" and flat["rule"] == "planted link" and flat["path"] == "src/pytdd"
    assert flat["action"] == "removed" and flat["where"] == "test-zero" and flat["target"] == "src/pytdd/pricing.py"
    assert flat["points_to"] == str(outside)


def test_the_same_link_is_recorded_once_per_attempt(bench_with_link):
    bench, _ = bench_with_link
    wb = bench.wb
    wb.refused_write(LinkedPath("src/pytdd"), path="src/pytdd/pricing.py", where="test-zero")
    wb.refused_write(LinkedPath("src/pytdd"), path="src/pytdd/other.py", where="test-zero")
    assert len(bench.events("guard.violation")) == 1 and len(wb.unsafe) == 1


def test_a_refusal_that_is_no_link_is_restore_failed(make_bench):
    bench = make_bench([])
    bench.wb.refused_write(UnsafeFile("src/pytdd/pricing.py is a directory"), path="src/pytdd/pricing.py", where="x")
    (event,) = bench.events("guard.violation")
    flat = event.get("data", event)
    assert flat["rule"] == "restore failed" and flat["action"] == "refused" and "is a directory" in flat["why"]


def test_unsafe_reason_is_empty_then_names_the_paths_and_caps_the_list(make_bench):
    bench = make_bench([])
    wb = bench.wb
    assert wb.unsafe_reason() == ""
    for i in range(7):
        wb.unsafe.append(UnsafeWrite(f"p{i}/f.py", "planted link", "gate", link=f"p{i}"))
    reason = wb.unsafe_reason()
    assert reason.startswith("a gate run put a symbolic link at p0, p1, p2, p3, p4 (+2 more)")
    assert "wrote nothing through it" in reason
    wb.unsafe.clear()
    wb.unsafe.append(UnsafeWrite("src/a.py", "restore failed", "gate"))
    assert wb.unsafe_reason().startswith("the harness could not put src/a.py back after a gate run")


def test_both_events_make_guard_notes_with_the_new_advice(bench_with_link):
    bench, _ = bench_with_link
    wb = bench.wb
    wb.refused_write(LinkedPath("src/pytdd"), path="src/pytdd/pricing.py", where="test-zero")
    wb.refused_write(UnsafeFile("x is a directory"), path="src/a.py", where="test")
    text = guard_note_text(wb.guard_notes)
    assert "- `src/pytdd` (planted link) removed" in text and "- `src/a.py` (restore failed) refused" in text
    assert "Create links only under the test's own temporary directory (`tmp_path`)" in text
    assert "Tests must not replace, delete or lock source files" in text


def test_run_task_clears_the_record_at_the_start_of_each_attempt(make_bench):
    bench = make_bench([blocked_step()])
    bench.wb.unsafe.append(UnsafeWrite("a", "planted link", "gate", link="a"))
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "blocked" and bench.wb.unsafe == []
