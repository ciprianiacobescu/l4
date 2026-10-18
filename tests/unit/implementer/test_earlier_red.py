"""Confirmation by an earlier red (L4-IMP-003, SCN-IMP-71..75): a criterion whose tests already failed at an earlier
red of the same unit on this branch, unchanged since, and which pass at head, needs no zero-value run."""

import pytest

from l4.agents.fake import Step
from l4.implementer import tdd
from l4.implementer.discrimination import PreSatisfied
from l4.implementer.tdd import run_red
from l4.specs.base import Task

from .conftest import KNOWN, UNKNOWN, Bench, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 1, 3)
OLD_FILE = "tests/test_old.py"
OLD_ID = "tests.test_old::test_old_total"
OLD = (
    'import pytest\n\nfrom pytdd import total\n\n\n@pytest.mark.l4("' + KNOWN + '")\n'
    "def test_old_total():\n    assert total([1.0, 2.0]) == 3.0\n"
)
NEW = OLD.replace("test_old_total", "test_new_total").replace("[1.0, 2.0]", "[2.0, 2.0]").replace("3.0", "4.0")
NEW_ID = "tests.test_new::test_new_total"
OTHER = (
    'import pytest\n\nfrom pytdd import total\n\n\n@pytest.mark.l4("' + UNKNOWN + '")\n'
    "def test_other_total():\n    assert total([5.0]) == 5.0\n"
)
OTHER_ID = "tests.test_new::test_other_total"


def commit_old(bench: Bench, *, text: str = OLD) -> tuple[str, str]:
    """The earlier red commit: (base, sha)."""
    wb = bench.wb
    base = wb.head()
    (wb.worktree / OLD_FILE).write_text(text)
    wb.git.run("add", OLD_FILE)
    sha = wb.commit("test: red for 1.1", task="0.9", attempt=1, phase="red", tdd="red")
    return base, sha


def record(
    bench: Bench, base: str, sha: str, *, proof: str = "red_assertion", test: str = OLD_ID, task: str = "0.9",
    ctx: dict | None = None, pre: bool = False, tdd_kind: str | None = None, sha_event: bool = True,
    discriminating: bool = True,
) -> None:  # fmt: skip
    ctx = ctx or {}
    bench.writer.append(
        "task.red_ok", task=task, base=base, tests=[test], frozen=[], tdd=tdd_kind,
        criteria={KNOWN: {"tests": [test], "proof": proof, "discriminating": [test] if discriminating else []}}, **ctx,
    )  # fmt: skip
    if pre:
        bench.writer.append("criterion.pre_satisfied", task=task, criterion=KNOWN, tests=[test], **ctx)
    if sha_event:
        bench.writer.append("task.red_committed", task=task, base=base, sha=sha, **ctx)


def new_step(*extra: tuple[str, str], criteria=(KNOWN,)) -> Step:
    writes = {"tests/test_new.py": NEW, **dict(extra)}
    return Step(writes=writes, structured=result("red", criteria_ids=list(criteria)))


@pytest.fixture
def spy(monkeypatch):
    """Records what confirm_pre_satisfied receives; confirms everything it is given."""
    seen: list[dict] = []

    def fake(wb, candidates, *, real=None):
        seen.append({c: list(t) for c, t in candidates.items()})
        return PreSatisfied({c: tuple(t) for c, t in candidates.items()})

    monkeypatch.setattr(tdd, "confirm_pre_satisfied", fake)
    return seen


def refuse(monkeypatch):
    monkeypatch.setattr(
        tdd,
        "confirm_pre_satisfied",
        lambda wb, cands, *, real=None: PreSatisfied({}, {c: tuple(t) for c, t in cands.items()}, "unconfirmed"),
    )


def test_a_criterion_that_failed_at_an_earlier_red_is_confirmed_without_a_zero_value_run(make_bench, spy):
    """SCN-IMP-71: the live case."""
    bench: Bench = make_bench([new_step()])
    base, sha = commit_old(bench)
    record(bench, base, sha)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    assert not any(spy)  # nothing was left for the zero-value run (called with no candidates, or not at all)
    pre = bench.events("criterion.pre_satisfied")[-1]  # the only one of this step
    assert (pre["criterion"], pre["tests"], pre["via"]) == (KNOWN, [NEW_ID], "earlier_red")
    proof = bench.events("task.red_ok")[-1]["criteria"][KNOWN]
    assert proof == {
        "tests": [NEW_ID], "proof": "pre_satisfied", "discriminating": [OLD_ID], "via": "earlier_red",
        "red_sha": sha, "red_task": "0.9",
    }  # fmt: skip


def test_a_test_in_a_class_is_evidence_of_the_earlier_red_that_saw_it_fail(make_bench, spy):
    """SCN-IMP-206: pytest names the class in the id (`tests.test_old.TestTotal::test_old_total`); the file is
    `tests/test_old.py` at the red commit."""
    in_class = (
        'import pytest\n\nfrom pytdd import total\n\n\nclass TestTotal:\n    @pytest.mark.l4("' + KNOWN + '")\n'
        "    def test_old_total(self):\n        assert total([1.0, 2.0]) == 3.0\n"
    )
    class_id = "tests.test_old.TestTotal::test_old_total"
    bench: Bench = make_bench([new_step()])
    base, sha = commit_old(bench, text=in_class)
    record(bench, base, sha, test=class_id)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    assert not any(spy)
    proof = bench.events("task.red_ok")[-1]["criteria"][KNOWN]
    assert (proof["via"], proof["discriminating"]) == ("earlier_red", [class_id])


def test_the_task_finishes_as_already_satisfied(make_bench, monkeypatch):
    from l4.implementer.loop import run_task

    refuse(monkeypatch)  # the zero-value confirmation would reject: only the earlier red can carry it
    bench: Bench = make_bench([new_step()])
    base, sha = commit_old(bench)
    record(bench, base, sha)
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert len(bench.adapter.requests) == 1  # no green step
    assert bench.events("task.done")[-1]["tdd"] == "already-satisfied"


def run_unconfirmed(bench, monkeypatch):
    refuse(monkeypatch)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and outcome.reason.startswith(f"not discriminating: {KNOWN}"), outcome.reason
    assert [e for e in bench.events("criterion.pre_satisfied") if e["task"] == TASK.key] == []


def test_a_test_the_earlier_red_allowed_to_pass_is_not_evidence(make_bench, monkeypatch):
    """SCN-IMP-72."""
    bench: Bench = make_bench([new_step()])
    base, sha = commit_old(bench)
    record(bench, base, sha, proof="pre_satisfied", pre=True)
    run_unconfirmed(bench, monkeypatch)


def test_a_test_listed_as_pre_satisfied_of_that_task_is_not_evidence_whatever_its_proof(make_bench, monkeypatch):
    bench: Bench = make_bench([new_step()])
    base, sha = commit_old(bench)
    record(bench, base, sha, proof="red_assertion", pre=True)
    run_unconfirmed(bench, monkeypatch)


def test_a_test_the_earlier_red_did_not_record_as_discriminating_is_not_evidence(make_bench, monkeypatch):
    """Listed under a red_assertion proof but not among its `discriminating` tests (it did not fail by assertion)."""
    bench: Bench = make_bench([new_step()])
    base, sha = commit_old(bench)
    record(bench, base, sha, discriminating=False)
    run_unconfirmed(bench, monkeypatch)


def test_an_already_satisfied_event_contributes_nothing(make_bench, monkeypatch):
    bench: Bench = make_bench([new_step()])
    base, sha = commit_old(bench)
    record(bench, base, sha, tdd_kind="already-satisfied")
    run_unconfirmed(bench, monkeypatch)


def test_a_test_file_changed_since_the_red_commit_is_not_evidence(make_bench, monkeypatch):
    """SCN-IMP-73: a commit since the red changed a line of the earlier test."""
    bench: Bench = make_bench([new_step()])
    base, sha = commit_old(bench)
    record(bench, base, sha)
    edited = OLD.replace("assert total([1.0, 2.0]) == 3.0", "assert total([1.0, 2.0]) == total([2.0, 1.0])")
    (bench.wb.worktree / OLD_FILE).write_text(edited)
    bench.wb.git.run("add", OLD_FILE)
    bench.wb.commit("test: edit", task="1.2", attempt=1, phase="green", tdd="green")
    run_unconfirmed(bench, monkeypatch)


def test_a_test_file_an_earlier_task_and_this_step_appended_to_is_still_evidence(make_bench, spy):
    """Live MR !2, task 3.1: task 2.1's already-satisfied commit appended its tests to 1.1's file, and 3.1 appends
    again. Every change since the red commit is an added line, so 1.1's red still speaks for its test."""
    later = OLD + "\n\ndef test_extra():\n    assert total([2.0]) == 2.0\n"
    appended = (
        later + '\n\n@pytest.mark.l4("' + KNOWN + '")\ndef test_appended_total():\n    assert total([3.0]) == 3.0\n'
    )
    bench: Bench = make_bench([new_step((OLD_FILE, appended))])
    base, sha = commit_old(bench)
    record(bench, base, sha)
    (bench.wb.worktree / OLD_FILE).write_text(later)
    bench.wb.git.run("add", OLD_FILE)
    bench.wb.commit("test: 2.1 already satisfied", task="2.1", attempt=1, phase="red", tdd="already-satisfied")
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    assert not any(spy)


def test_a_test_file_whose_lines_this_step_changed_is_not_evidence(make_bench, monkeypatch):
    """This step rewrote a line of the earlier test (here its assertion): the earlier red no longer speaks for it."""
    edited = OLD.replace("assert total([1.0, 2.0]) == 3.0", "assert total([1.0, 2.0]) == total([2.0, 1.0])")
    bench: Bench = make_bench([new_step((OLD_FILE, edited))])
    base, sha = commit_old(bench)
    record(bench, base, sha)
    run_unconfirmed(bench, monkeypatch)


def test_a_test_file_this_step_only_appended_to_is_still_evidence(make_bench, spy):
    """Live MR !2: task 2.1 is told to add its tests to task 1.1's test file. Appended lines leave the earlier test as
    the red saw it, so the earlier red still confirms the criterion."""
    appended = (
        OLD + '\n\n@pytest.mark.l4("' + KNOWN + '")\ndef test_appended_total():\n    assert total([2.0]) == 2.0\n'
    )
    bench: Bench = make_bench([new_step((OLD_FILE, appended))])
    base, sha = commit_old(bench)
    record(bench, base, sha)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    assert not any(spy)
    assert bench.events("task.red_ok")[-1]["criteria"][KNOWN]["discriminating"] == [OLD_ID]


def test_a_test_absent_at_head_is_not_evidence(make_bench, monkeypatch):
    """SCN-IMP-73."""
    bench: Bench = make_bench([new_step()])
    base, sha = commit_old(bench)
    record(bench, base, sha, test="tests.test_old::test_renamed")
    run_unconfirmed(bench, monkeypatch)


def test_a_test_failing_at_head_is_not_evidence(make_bench, monkeypatch):
    """SCN-IMP-73."""
    bench: Bench = make_bench([new_step()])
    base, sha = commit_old(bench, text=OLD.replace("3.0", "9.0"))
    record(bench, base, sha)
    run_unconfirmed(bench, monkeypatch)


@pytest.mark.parametrize("ctx", [{"fix_unit": "other-unit"}])
def test_a_red_of_another_fix_unit_context_is_not_evidence(make_bench, monkeypatch, ctx):
    """SCN-IMP-74."""
    bench: Bench = make_bench([new_step()])
    base, sha = commit_old(bench)
    record(bench, base, sha, ctx=ctx)
    run_unconfirmed(bench, monkeypatch)


def test_a_red_that_is_not_on_this_branch_is_not_evidence(make_bench, monkeypatch):
    """SCN-IMP-75: after a rebase the recorded base and sha are not ancestors of head."""
    bench: Bench = make_bench([new_step()])
    base, sha = commit_old(bench)
    record(bench, "1" * 40, sha)
    run_unconfirmed(bench, monkeypatch)


def test_a_red_sha_that_is_not_on_this_branch_is_not_evidence(make_bench, monkeypatch):
    bench: Bench = make_bench([new_step()])
    base, sha = commit_old(bench)
    record(bench, base, "2" * 40)
    run_unconfirmed(bench, monkeypatch)


def test_a_red_with_no_committed_sha_is_not_evidence(make_bench, monkeypatch):
    bench: Bench = make_bench([new_step()])
    base, sha = commit_old(bench)
    record(bench, base, sha, sha_event=False)
    run_unconfirmed(bench, monkeypatch)


def test_only_the_criteria_the_earlier_red_does_not_confirm_go_to_the_zero_value_run(make_bench, spy):
    """SCN-IMP-71, mixed."""
    bench: Bench = make_bench([new_step(("tests/test_other.py", OTHER), criteria=(KNOWN, UNKNOWN))])
    base, sha = commit_old(bench)
    record(bench, base, sha)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    assert spy == [{UNKNOWN: ["tests.test_other::test_other_total"]}], spy
    proofs = bench.events("task.red_ok")[-1]["criteria"]
    assert proofs[KNOWN]["via"] == "earlier_red" and "via" not in proofs[UNKNOWN]
    assert proofs[UNKNOWN]["proof"] == "pre_satisfied"
    vias = {e["criterion"]: e.get("via") for e in bench.events("criterion.pre_satisfied") if e["task"] == TASK.key}
    assert vias == {KNOWN: "earlier_red", UNKNOWN: None}
