"""No phase commits a symbolic link that points outside the worktree, unless the base held the same link
(L4-SEC-020 part e, owner decision 3): a guard.violation and a failed attempt, before the commit."""

import os

from l4.agents.fake import Step
from l4.implementer.guardnotes import guard_note_text
from l4.implementer.stubs import escaping_links
from l4.implementer.tdd import run_green, run_red, run_single
from l4.specs.base import Task

from .conftest import IMPL, green_step, red_step, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)


CHORE_TASK = Task("1.1", "1.1", "1.1 an inline suppression was not declared (F-6eb0cc43)", False, " ", 0, 3, 3)
CHORE_FINDINGS = ["F-6eb0cc43"]


def outside_dir(tmp_path):
    """An empty directory outside the worktree (the pytest temporary directory holds the repositories themselves)."""
    path = tmp_path / "outside"
    path.mkdir(exist_ok=True)
    return path


def refusals(bench) -> list[dict]:
    events = [e.get("data", e) for e in bench.events("guard.violation")]
    return [e for e in events if e.get("rule") == "link outside worktree"]


def test_red_refuses_an_absolute_link_under_a_test_path(make_bench, tmp_path):
    bench = make_bench([red_step(links={"tests/data": str(outside_dir(tmp_path))})])
    head = bench.wb.head()
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed"
    assert out.reason.startswith("the step left a symbolic link that points outside the worktree: tests/data ->")
    assert bench.wb.head() == head and bench.events("task.red_committed") == []
    assert not (bench.wb.worktree / "tests/data").is_symlink()  # the attempt was discarded
    (event,) = refusals(bench)
    assert event["phase"] == "red" and event["path"] == "tests/data" and event["target"] == str(outside_dir(tmp_path))
    assert "link outside worktree" in guard_note_text(bench.wb.guard_notes)


def test_red_refuses_a_relative_link_that_climbs_above_the_root(make_bench):
    bench = make_bench([red_step(links={"tests/up": "../../elsewhere"})])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and "tests/up -> ../../elsewhere" in out.reason


def test_green_refuses_a_link_that_leaves_the_worktree_and_makes_no_commit(make_bench, tmp_path):
    bench = make_bench([red_step(), green_step(links={"notes": str(outside_dir(tmp_path))})])
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "failed" and "symbolic link that points outside the worktree: notes ->" in out.reason
    assert bench.wb.head() == red.sha and bench.events("task.done") == []
    (event,) = refusals(bench)
    assert event["phase"] == "green" and event["path"] == "notes"


def test_a_fix_chore_refuses_a_link_that_leaves_the_worktree(make_bench, tmp_path):
    chore = Step(writes={"src/pytdd/pricing.py": IMPL}, links={"vendor": str(outside_dir(tmp_path))},
                 structured=result("single"))  # fmt: skip
    bench = make_bench([chore])
    head = bench.wb.head()
    out = run_single(bench.wb, CHORE_TASK, CHORE_FINDINGS, attempt=1)
    assert out.status == "failed" and "vendor ->" in out.reason and bench.wb.head() == head
    (event,) = refusals(bench)
    assert event["phase"] == "single" and event["path"] == "vendor"
    assert not (bench.wb.worktree / "vendor").is_symlink()


def test_a_link_inside_the_worktree_is_accepted(make_bench):
    bench = make_bench([red_step(links={"tests/alias.py": "test_discount.py"})])
    assert run_red(bench.wb, TASK, attempt=1).status == "ok"  # a relative link that stays inside
    assert refusals(bench) == []


def test_a_link_the_base_already_holds_is_not_the_steps_but_another_target_is(make_bench, tmp_path):
    bench = make_bench([])
    os.symlink(str(outside_dir(tmp_path)), bench.wb.worktree / "vendor")
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("commit", "-q", "-m", "a vendor link")
    assert escaping_links(bench.wb, bench.wb.head()) == []
    (bench.wb.worktree / "vendor").unlink()
    os.symlink(str(tmp_path / "other"), bench.wb.worktree / "vendor")  # the same name, another target: the step's
    assert escaping_links(bench.wb, bench.wb.head()) == [("vendor", str(tmp_path / "other"))]
