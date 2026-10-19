"""The label of a proof that the delegate accepted (delegate-answers 13.1; L4-DLG-010, L4-VER-051; SCN-DLG-47): the
judge's per-test list, the satisfied block and `verification.md` say who accepted, with the model and the CLI."""

from l4.verifier.traceability import UNPROVEN_VIA, red_notes, red_proofs, trace_criteria

from .test_traceability import CFG, A, case, crit, red_ok, report

DELEGATE = {
    "tests": [], "proof": "pre_satisfied", "discriminating": ["t"], "via": "delegate_override", "question": "Q-007",
    "answer_sha256": "a" * 64, "model": "gpt-6.1-sol", "cli": "codex",
}  # fmt: skip
NOTE = "accepted by the delegate (gpt-6.1-sol via codex) through Q-007: the check was inconclusive"


def test_the_delegate_label():  # SCN-DLG-47
    assert "delegate_override" in UNPROVEN_VIA
    ledger = [red_ok({A: DELEGATE})]
    assert red_proofs(ledger) == {A: {"t": "pre_satisfied"}}  # evidence, like a person's accept
    assert red_notes(ledger) == {(A, "t"): NOTE}
    [e] = trace_criteria([crit(A)], report(case("t", "passed", A)), ledger, CFG)
    assert e.state == "covered" and [(t.id, t.proof, t.note) for t in e.tests] == [("t", "pre_satisfied", NOTE)]


def test_the_satisfied_block_and_verification_md_carry_it():
    from l4.specs.base import Task
    from l4.state.ledger import LedgerEvent
    from l4.verifier.judge import satisfied_refs
    from l4.verifier.report import render_verification_md
    from l4.verifier.types import CriterionEvidence, TracingTest, Verdict, VerifyResult

    from .test_judge_satisfied import ev

    events = [
        ev(1, "task.red_ok", task="3.1", criteria={A: DELEGATE}, tdd="already-satisfied"),
        ev(2, "task.done", task="3.1", tdd="already-satisfied"),
    ]
    [ref] = satisfied_refs([Task("3.1", "3.1", "t", True, "x", 0, 1, None)], events)
    assert ref.labels == ((A, NOTE),)
    result = VerifyResult("openspec:u", 1, Verdict.PASS, "", "abc")
    result.trace = [CriterionEvidence(A, "a", "covered", (TracingTest("t", "passed", "pre_satisfied", note=NOTE),))]
    assert f"t (passed, pre_satisfied, {NOTE})" in render_verification_md(result)
    assert LedgerEvent  # the event type the judge reads


def test_a_record_without_the_model_still_names_the_delegate():
    bare = {k: v for k, v in DELEGATE.items() if k not in ("model", "cli")}
    assert red_notes([red_ok({A: bare})]) == {
        (A, "t"): "accepted by the delegate through Q-007: the check was inconclusive"
    }


def test_the_label_is_not_a_persons():
    person = {**DELEGATE, "via": "human_override"}
    assert red_notes([red_ok({A: person})]) == {(A, "t"): "accepted by Q-007: the check was inconclusive"}
