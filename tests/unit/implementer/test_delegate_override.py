"""The delegate's accept of a harness question (delegate-answers 13.1; L4-DLG-010, SCN-DLG-30): the proofs say
`delegate_override` with the question, the digest, the model and the CLI, `check.accepted` says `by: delegate`, and
the judge's list says who accepted."""

from l4.implementer.loop import run_task
from l4.specs.questions import QuestionsFile

from .conftest import KNOWN
from .test_earlier_red import OLD_ID, TASK
from .test_held_answers import answer, held

MODEL, CLI = "claude-opus-5-5", "claude-code"
NOTE = f"accepted by the delegate ({MODEL} via {CLI}) through Q-001: the check was inconclusive"


def delegate_answer(bench, raw, text: str, *, record: bool = True) -> str:
    """The delegate answered Q-001 and its pass recorded it (`question.answered{by: delegate}`)."""
    digest = answer(bench, raw, text, record=False)
    if record:
        bench.wb.emit(
            "question.answered", id="Q-001", by="delegate", profile="dlg", model=MODEL, cli=CLI, answer_sha256=digest
        )
    return digest


def test_a_delegate_accept_is_delegate_override(make_bench, monkeypatch, raw):  # SCN-DLG-30
    bench = held(make_bench, monkeypatch)
    digest = delegate_answer(bench, raw, "accept: the check is broken")
    assert run_task(bench.wb, TASK).status == "done"
    proof = bench.events("task.red_ok")[-1]["criteria"][KNOWN]
    assert proof == {
        "tests": [], "proof": "pre_satisfied", "discriminating": [OLD_ID], "via": "delegate_override",
        "question": "Q-001", "answer_sha256": digest, "model": MODEL, "cli": CLI,
    }  # fmt: skip
    pre = bench.events("criterion.pre_satisfied")[-1]
    assert (pre["via"], pre["question"], pre["model"], pre["cli"]) == ("delegate_override", "Q-001", MODEL, CLI)
    [accepted] = bench.events("check.accepted")
    assert (accepted["by"], accepted["model"], accepted["cli"]) == ("delegate", MODEL, CLI)
    assert accepted["answer_sha256"] == digest and accepted["criteria"] == [KNOWN]
    from datetime import UTC, datetime

    from l4.state.ledger import LedgerEvent
    from l4.verifier.traceability import red_notes

    red_ok = LedgerEvent(
        datetime(2026, 10, 18, tzinfo=UTC), "r", "u", 1, "task.red_ok", {"task": "1.1", "criteria": {KNOWN: proof}}
    )
    assert next(iter(red_notes([red_ok]).values())) == NOTE


def test_a_delegate_accept_without_a_record_does_not_count(make_bench, monkeypatch, raw):
    bench = held(make_bench, monkeypatch)
    delegate_answer(bench, raw, "accept: the check is broken", record=False)
    assert run_task(bench.wb, TASK).status == "blocked"  # the ledger never recorded the answer: asked again


def test_an_earlier_red_never_counts_a_delegate_override_as_evidence():
    from l4.implementer.earlier_red import _NO_EVIDENCE_VIA

    assert "delegate_override" in _NO_EVIDENCE_VIA


def test_a_delegate_answer_edited_afterwards_does_not_count(make_bench, monkeypatch, raw):
    bench = held(make_bench, monkeypatch)
    delegate_answer(bench, raw, "accept: the check is broken")
    unit = bench.wb.ref.path
    file = QuestionsFile.load(unit / "questions.md")
    assert file is not None
    file.set_answer("Q-001", "accept: something else, edited later").save(unit / "questions.md")
    raw(bench.wb.worktree, "add", "-A")
    raw(bench.wb.worktree, "-c", "user.name=Pat", "-c", "user.email=pat@example.invalid", "commit", "-q", "-m", "edit")
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "blocked" and bench.events("check.accepted") == []
