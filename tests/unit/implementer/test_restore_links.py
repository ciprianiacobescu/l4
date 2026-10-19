"""`restore_to_base` and the production guard survive a directory a link replaced (L4-SEC-020 part d, L4-SEC-021).

A planted link halts the unit (owner decision 1, like a secret in a push): the step raises `PlantedLink`, after the
worktree was put back, and the orchestrator halts the unit with the evidence (tests/unit/orchestrator)."""

import os
import shutil
from pathlib import Path

import pytest

from l4.agents.fake import Step
from l4.implementer.stubs import ProductionGuard, restore_to_base
from l4.implementer.tdd import PlantedLink, run_green, run_red, run_single
from l4.specs.base import Task

from ..conftest import TEST_COMMAND
from .conftest import IMPL, STUB, green_step, red_step, result
from .test_planted_links import nothing_in, planted, swap_cmd
from .test_tdd_green import CORRECTED, answer_naming, two_test_red

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)


def link_dir(wb, rel: str, outside: Path) -> None:
    shutil.rmtree(wb.worktree / rel)
    (wb.worktree / rel).symlink_to(outside)


def test_a_linked_directory_that_was_a_tree_at_the_base_comes_back_whole(make_bench, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    wb = make_bench([]).wb
    base = wb.head()
    files = sorted(p.name for p in (wb.worktree / "src/pytdd").iterdir() if p.is_file())
    link_dir(wb, "src/pytdd", outside)
    restore_to_base(wb, base, "src/pytdd")
    package = wb.worktree / "src/pytdd"
    assert package.is_dir() and not package.is_symlink()
    assert sorted(p.name for p in package.iterdir() if p.is_file()) == files
    assert list(outside.iterdir()) == []


def test_a_new_linked_path_is_removed_and_leaves_no_index_entries(make_bench, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    wb = make_bench([]).wb
    base = wb.head()
    (wb.worktree / "newlink").symlink_to(outside)
    wb.git.run("add", "newlink")
    restore_to_base(wb, base, "newlink")
    assert not (wb.worktree / "newlink").is_symlink() and not (wb.worktree / "newlink").exists()
    assert wb.git.run("ls-files", "--", "newlink").stdout == ""
    assert outside.exists()


def test_a_link_where_the_base_had_a_link_comes_back_as_the_base_link(make_bench, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    bench = make_bench([])
    wb = bench.wb
    (wb.worktree / "lib/app").mkdir(parents=True)
    (wb.worktree / "lib/app/core.py").write_text("x = 1\n")
    os.symlink("../lib/app", wb.worktree / "src/app")
    wb.git.run("add", "-A")
    wb.git.run("commit", "-q", "-m", "a committed link")
    base = wb.head()
    (wb.worktree / "src/app").unlink()
    (wb.worktree / "src/app").symlink_to(outside)
    restore_to_base(wb, base, "src/app")
    assert (wb.worktree / "src/app").is_symlink() and os.readlink(wb.worktree / "src/app") == "../lib/app"


def test_a_new_directory_with_staged_files_is_removed(make_bench):
    wb = make_bench([]).wb
    base = wb.head()
    (wb.worktree / "fresh/deeper").mkdir(parents=True)
    (wb.worktree / "fresh/deeper/a.py").write_text("a = 1\n")
    wb.git.run("add", "fresh")
    restore_to_base(wb, base, "fresh")
    assert not (wb.worktree / "fresh").exists() and wb.git.run("ls-files", "--", "fresh").stdout == ""


def test_scn_sec_45_a_package_directory_an_agent_step_replaced_with_a_link_is_put_back_without_an_error(
    make_bench, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    bench = make_bench([red_step(links={"src/pytdd": str(outside)})])
    base_files = sorted(p.name for p in (bench.wb.worktree / "src/pytdd").iterdir() if p.is_file())
    outcome = run_red(bench.wb, TASK, attempt=1)  # no GitError: an outcome, not an exception
    assert outcome.status in ("failed", "ok")
    package = bench.wb.worktree / "src/pytdd"
    assert package.is_dir() and not package.is_symlink()
    assert sorted(p.name for p in package.iterdir() if p.is_file()) == base_files or outcome.status == "ok"
    assert list(outside.iterdir()) == []
    assert not bench.events("task.red_committed") or not (outside / "pricing.py").exists()


def _guarded(bench, outside: Path):
    """A ProductionGuard after a fake red step: `pricing.py` holds the stub (a gate then swaps the package)."""
    wb = bench.wb
    base = wb.head()
    (wb.worktree / "src/pytdd/pricing.py").write_text(STUB)
    return wb, base, ProductionGuard(wb, base)


def test_scn_sec_46_the_production_guard_removes_a_link_a_gate_put_in_place_of_a_production_directory(
    make_bench, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "pricing.py").write_text("OUTSIDE\n")
    bench = make_bench([], test={"command": swap_cmd(outside)})
    wb, base, guard = _guarded(bench, outside)
    base_files = sorted(p.name for p in (wb.worktree / "src/pytdd").iterdir() if p.is_file())
    wb.run_gate("test", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports)
    assert (wb.worktree / "src/pytdd").is_symlink()  # the gate planted it
    notes = guard.check("test run")
    assert (outside / "pricing.py").read_text() == "OUTSIDE\n"
    package = wb.worktree / "src/pytdd"
    assert package.is_dir() and not package.is_symlink()
    assert sorted(p.name for p in package.iterdir() if p.is_file()) == base_files
    assert (package / "pricing.py").read_text() == STUB  # red's guarded version
    assert planted(bench, "src/pytdd") and notes  # the link, and the gate-mutated-production notes
    rules = {(e.get("data", e)["rule"]) for e in bench.events("guard.violation")}
    assert {"planted link", "gate-mutated-production"} <= rules


def test_scn_sec_41_a_link_planted_during_the_vacuity_run_halts_the_unit_and_writes_nothing_outside(
    make_bench, tmp_path
):
    outside = tmp_path / "host-dir"
    outside.mkdir()
    # only during run (b): the stub module holds apply_discount but no NotImplementedError (the zero-value variant)
    cond = "grep -q apply_discount src/pytdd/pricing.py && ! grep -q NotImplementedError src/pytdd/pricing.py"
    bench = make_bench([red_step()], test={"command": swap_cmd(outside, cond)})
    with pytest.raises(PlantedLink) as halted:
        run_red(bench.wb, TASK, attempt=1)
    assert str(halted.value).startswith("a gate run put a symbolic link at src/pytdd")
    assert [u.link for u in halted.value.links] == ["src/pytdd"]
    assert nothing_in(outside) and not (outside / "pricing.py").exists()
    package = bench.wb.worktree / "src/pytdd"
    assert package.is_dir() and not package.is_symlink()
    assert planted(bench, "src/pytdd")
    assert bench.wb.is_clean()  # the attempt was discarded
    assert bench.events("task.red_committed") == []


def test_green_a_link_planted_while_the_code_runs_at_the_red_commit_halts_the_unit_with_no_commit(
    make_bench, raw, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    armed = tmp_path / "armed"
    cond = f"[ -f {armed} ] && grep -q NotImplementedError src/pytdd/pricing.py"
    corrected = Step(
        writes={"tests/test_discount.py": CORRECTED, "src/pytdd/pricing.py": IMPL}, structured=result("green")
    )
    bench = make_bench([two_test_red(), corrected], test={"command": swap_cmd(outside, cond)})
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    answer_naming(bench, raw, "Change `tests/test_discount.py:9` to use a 100.0 amount.")  # so that fails_at_red runs
    armed.write_text("")
    before = bench.wb.head()  # the person's answer is committed on the branch
    with pytest.raises(PlantedLink) as halted:
        run_green(bench.wb, TASK, red, attempt=1)
    assert [u.link for u in halted.value.links] == ["src/pytdd"]
    assert bench.wb.head() == before  # no commit
    assert nothing_in(outside) and bench.events("task.done") == []
    assert not (bench.wb.worktree / "src/pytdd").is_symlink()


def test_single_a_link_planted_while_a_tests_chore_is_discriminated_halts_the_unit_with_no_commit(make_bench, tmp_path):
    from .test_criterion_tests_chore import BOUND, FINDINGS
    from .test_single_phase import NEW_TESTS, UNIT_TASK

    outside = tmp_path / "outside"
    outside.mkdir()
    armed = tmp_path / "armed"
    cond = f"[ -f {armed} ] && ! grep -q round src/pytdd/pricing.py"  # only the zero-value variant has no `round`
    chore = Step(writes={"tests/test_more.py": NEW_TESTS}, structured=result("single"))
    bench = make_bench([red_step(), green_step(), chore], test={"command": swap_cmd(outside, cond)})
    tasks = bench.wb.ref.path / "tasks.md"
    tasks.write_text(tasks.read_text().rstrip("\n") + f"\n- [ ] {BOUND.title}\n")
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("commit", "-q", "-m", "a second task")
    red = run_red(bench.wb, UNIT_TASK, attempt=1)
    assert run_green(bench.wb, UNIT_TASK, red, attempt=1).status == "ok"
    head = bench.wb.head()
    armed.write_text("")  # the zero-value run of the chore's discrimination swaps IMPL for its zero values
    with pytest.raises(PlantedLink):
        run_single(bench.wb, BOUND, FINDINGS, attempt=1, kind="tests")
    assert bench.wb.head() == head and nothing_in(outside)


def test_scn_sec_49_a_failed_restore_fails_the_attempt_and_the_next_attempt_is_told(make_bench):
    """A restore the harness cannot make is `restore failed`: the run goes on to the next attempt (no halt)"""
    from l4.implementer.loop import run_task

    cond = "grep -q apply_discount src/pytdd/pricing.py && ! grep -q NotImplementedError src/pytdd/pricing.py"
    mkdir = f"sh -c 'if {cond}; then rm -f src/pytdd/pricing.py && mkdir src/pytdd/pricing.py; fi; exec {TEST_COMMAND}'"
    bench = make_bench([red_step(), red_step()], test={"command": mkdir}, implementer={"max_task_attempts": 2})
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt" and "max_task_attempts" in outcome.reason  # two failed attempts, not a planted link
    failed = [e.get("data", e) for e in bench.events("task.attempt_failed")]
    assert failed[0]["reason"].startswith("the harness could not put src/pytdd/pricing.py back after a gate run")
    assert "(restore failed)" not in failed[0]["reason"]  # the plain reason, without the note
    second = bench.adapter.requests[1].prompt
    assert "- `src/pytdd/pricing.py` (restore failed) refused" in second
    assert "Tests must not replace, delete or lock source files" in second
