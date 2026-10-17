"""An already-satisfied red step that adds no test (L4-IMP-003, SCN-IMP-207..210): the tests that an earlier task
wrote are its candidates, the harness confirms them as it confirms new ones, and the commit holds no test."""

from l4.agents.fake import Step
from l4.implementer import tdd
from l4.implementer.base_run import BaseRunResult
from l4.implementer.loop import run_task
from l4.implementer.tdd import NO_NEW_TEST, run_red

from .conftest import KNOWN, UNKNOWN, Bench, result
from .test_earlier_red import OLD, OLD_FILE, OLD_ID, TASK, commit_old, record, refuse

REASON = {"reason": "already_satisfied by 0.9"}


def no_test(*, criteria=(KNOWN,), exemption: dict | None = REASON, writes: dict | None = None) -> Step:
    over: dict = {"criteria_ids": list(criteria)}
    if exemption is not None:
        over["tdd_exemption"] = exemption
    return Step(writes=writes or {}, structured=result("red", **over))


def seeded(make_bench, step: Step) -> tuple[Bench, str]:
    bench: Bench = make_bench([step])
    base, sha = commit_old(bench)
    record(bench, base, sha)
    return bench, sha


def test_a_task_that_adds_no_test_reuses_the_earlier_ones(make_bench):
    """SCN-IMP-207."""
    bench, sha = seeded(make_bench, no_test())
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    pre = bench.events("criterion.pre_satisfied")[-1]
    assert (pre["task"], pre["criterion"], pre["tests"], pre["via"]) == ("1.1", KNOWN, [OLD_ID], "earlier_red")
    assert bench.events("task.red_ok")[-1]["criteria"][KNOWN] == {
        "tests": [], "proof": "pre_satisfied", "discriminating": [OLD_ID], "via": "earlier_red",
        "red_sha": sha, "red_task": "0.9",
    }  # fmt: skip
    changed = bench.wb.git.run("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.split()
    assert not any(p.startswith("tests/") for p in changed), changed
    message = bench.wb.git.run("log", "-1", "--format=%B").stdout
    assert message.splitlines()[0] == "test(add-discount-codes): 1.1 already satisfied [skip ci]"
    assert "L4-TDD: already-satisfied" in message


def test_the_task_finishes_with_no_green_step(make_bench):
    """SCN-IMP-207."""
    bench, _ = seeded(make_bench, no_test())
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert len(bench.adapter.requests) == 1  # no green step
    done = bench.events("task.done")[-1]
    assert (done["task"], done["tdd"]) == ("1.1", "already-satisfied")
    red_ok = bench.events("task.red_ok")[-1]
    assert (red_ok["tests"], red_ok["frozen"]) == ([], [])
    assert "[x] 1.1" in (bench.wb.ref.path / "tasks.md").read_text()


def test_a_cited_criterion_that_no_test_traces_needs_a_new_test(make_bench):
    """SCN-IMP-208."""
    bench, _ = seeded(make_bench, no_test(criteria=(KNOWN, UNKNOWN)))
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed"
    assert outcome.reason == f"no test traces {UNKNOWN} yet: write a new test for each"
    assert [e for e in bench.events("criterion.pre_satisfied") if e["task"] == TASK.key] == []
    assert bench.events("task.done") == []


TOUCHED = {OLD_FILE: OLD + "\n# touched\n"}  # a test file changes, no test is added


def test_no_test_and_no_reason_is_still_no_new_test(make_bench):
    """SCN-IMP-209."""
    bench, _ = seeded(make_bench, no_test(exemption=None, writes=TOUCHED))
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and outcome.reason == NO_NEW_TEST


def test_no_test_and_no_criteria_is_still_no_new_test(make_bench):
    """SCN-IMP-209."""
    bench, _ = seeded(make_bench, no_test(criteria=(), writes=TOUCHED))
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and outcome.reason == NO_NEW_TEST


def test_another_reason_is_still_no_new_test(make_bench):
    """SCN-IMP-209."""
    bench, _ = seeded(make_bench, no_test(exemption={"reason": "nothing to test"}, writes=TOUCHED))
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and outcome.reason == NO_NEW_TEST


def test_a_step_that_changes_a_test_file_takes_the_new_test_path_whatever_its_reason(make_bench):
    """SCN-IMP-209: the reason does not excuse a changed test file."""
    bench, _ = seeded(make_bench, no_test(writes=TOUCHED))
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and outcome.reason == NO_NEW_TEST


def test_a_step_that_changes_nothing_and_has_no_reason_fails_as_before(make_bench):
    """SCN-IMP-209: with nothing changed at all, `classify_red` says `no tests added`, as it did."""
    bench, _ = seeded(make_bench, no_test(exemption=None))
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and outcome.reason == "no tests added"


def test_a_cited_id_that_is_not_the_units_fails(make_bench):
    bench, _ = seeded(make_bench, no_test(criteria=("C-ffffffff",)))
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed"
    assert outcome.reason == "criteria that are not one of this unit's: C-ffffffff"


def test_existing_tests_that_nothing_confirms_are_no_proof(make_bench, monkeypatch):
    """SCN-IMP-210: no earlier red saw them fail, no zero-value run fails them, no base run fails them."""
    bench: Bench = make_bench([no_test()])
    commit_old(bench)  # the test exists and passes, but the ledger holds no red for it
    refuse(monkeypatch)
    monkeypatch.setattr(tdd, "confirmed_by_base_run", lambda wb, cands, ids: BaseRunResult(reason="no failure"))
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and outcome.reason.startswith(f"not discriminating: {KNOWN}"), outcome.reason
    assert [e for e in bench.events("criterion.pre_satisfied") if e["task"] == TASK.key] == []
    assert bench.events("task.done") == []
