"""The answers to a harness question (L4-IMP-063, design D8; SCN-IMP-314, 315): `accept` counts the criteria when the
check is inconclusive again, `retry` runs the check again."""

from l4.implementer import tdd
from l4.implementer.discrimination import PreSatisfied
from l4.implementer.loop import run_task
from l4.specs.questions import QuestionsFile, QuestionStatus, answer_sha256

from .conftest import KNOWN, Bench
from .test_earlier_red import OLD_ID, TASK
from .test_held_check import held_bench, no_test, zero_says


def held(make_bench, monkeypatch, *, script=None) -> Bench:
    zero_says(monkeypatch)
    bench = held_bench(make_bench, script or [no_test(), no_test()])
    first = run_task(bench.wb, TASK)
    assert (first.status, first.question_ids) == ("blocked", ["Q-001"])
    return bench


def answer(bench: Bench, raw, text: str, *, status: str = "answered", by: str = "human", record: bool = True) -> str:
    """A person answered Q-001 on the branch, and the re-entry recorded it (as `l4 run` does)."""
    unit = bench.wb.ref.path
    file = QuestionsFile.load(unit / "questions.md")
    assert file is not None
    file = file.set_answer("Q-001", text).set_status("Q-001", QuestionStatus(status))
    file.save(unit / "questions.md")
    raw(bench.wb.worktree, "add", "-A")
    raw(
        bench.wb.worktree, "-c", "user.name=Pat", "-c", "user.email=pat@example.invalid", "commit", "-q", "-m", "answer"
    )
    written = QuestionsFile.load(unit / "questions.md")
    assert written is not None
    digest = answer_sha256(written.get("Q-001"))
    assert digest is not None
    if record:
        bench.wb.emit("question.answered", id="Q-001", by=by, answer_sha256=digest)
    return digest


def test_scn_imp_314_a_person_accepts_the_claim_on_the_evidence_of_the_real_run(make_bench, monkeypatch, raw):
    bench = held(make_bench, monkeypatch)
    digest = answer(bench, raw, "accept: the decorator factory is zeroed by an L4 bug")
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    proof = bench.events("task.red_ok")[-1]["criteria"][KNOWN]
    assert proof == {
        "tests": [], "proof": "pre_satisfied", "discriminating": [OLD_ID], "via": "human_override",
        "question": "Q-001", "answer_sha256": digest,
    }  # fmt: skip
    [accepted] = bench.events("check.accepted")
    assert (accepted["task"], accepted["check"], accepted["question"]) == ("1.1", "pre_satisfied", "Q-001")
    assert accepted["answer_sha256"] == digest and accepted["criteria"] == [KNOWN]
    pre = bench.events("criterion.pre_satisfied")[-1]
    assert (pre["via"], pre["question"]) == ("human_override", "Q-001")


def test_an_accept_does_not_excuse_a_refuted_criterion(make_bench, monkeypatch, raw):
    bench = held(make_bench, monkeypatch)
    answer(bench, raw, "accept: the decorator factory is zeroed by an L4 bug")
    zero_says(monkeypatch, refuted=(KNOWN,))  # the check now decides: the test does not discriminate
    outcome = tdd.run_red(bench.wb, TASK, attempt=2)
    assert outcome.status == "failed" and outcome.reason.startswith(f"not discriminating: {KNOWN}")
    assert bench.events("check.accepted") == []


def test_an_accept_whose_text_changed_after_it_was_recorded_does_not_count(make_bench, monkeypatch, raw):
    bench = held(make_bench, monkeypatch)
    answer(bench, raw, "accept: the decorator factory is zeroed by an L4 bug")
    unit = bench.wb.ref.path
    file = QuestionsFile.load(unit / "questions.md")
    file.set_answer("Q-001", "accept: something else, edited later").save(unit / "questions.md")
    raw(bench.wb.worktree, "add", "-A")
    raw(bench.wb.worktree, "-c", "user.name=Pat", "-c", "user.email=pat@example.invalid", "commit", "-q", "-m", "edit")
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "blocked" and bench.events("check.accepted") == []
    assert len(bench.events("check.inconclusive")) == 2  # held again, with a new question


def test_an_accept_by_the_clarifier_or_without_a_record_does_not_count(make_bench, monkeypatch, raw):
    bench = held(make_bench, monkeypatch)
    answer(bench, raw, "accept: fine", record=False)  # no question.answered event: the harness never saw it
    assert run_task(bench.wb, TASK).status == "blocked" and bench.events("check.accepted") == []


def test_scn_imp_315_a_retry_runs_the_check_again(make_bench, monkeypatch, raw):
    bench = held(make_bench, monkeypatch)
    answer(bench, raw, "retry: upgraded L4 to the release that keeps decorator factories")
    monkeypatch.setattr(
        tdd,
        "confirm_pre_satisfied",
        lambda wb, cands, *, real=None: PreSatisfied({c: tuple(t) for c, t in cands.items()}),
    )
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    proof = bench.events("task.red_ok")[-1]["criteria"][KNOWN]
    assert proof["proof"] == "pre_satisfied" and "via" not in proof
    assert "upgraded L4 to the release that keeps decorator factories" in bench.adapter.requests[-1].prompt
