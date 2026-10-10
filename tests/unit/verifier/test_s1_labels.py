"""Join line 29, trust: a `human:verdict` label comes only from a verdict that `consume_verdicts` recorded in this very
call. That call takes an answer only for a question the harness raised (`question.raised{kind: verdict}` in the
ledger), from a `questions.md` that no agent step or gate can change (a protected path, put back after each:
`test_gate_forgery.py`). A `human.verdict` that is merely in the ledger (planted, or left by an earlier run) is no
label."""

from types import SimpleNamespace

from l4.verifier import s1_labels

ITEM = "a" * 32
HOLD = "H-0123abcd"
FINDING = "F-89abcdef"
EVIDENCE = {
    "holds": [{"id": HOLD, "kind": "scope", "subjects": ["src/x.py"]}],
    "items": {"l4/file-relevant@1|src/x.py": ITEM},
}


def event(event_type: str, /, **data) -> SimpleNamespace:
    return SimpleNamespace(type=event_type, data=data)


def test_a_verdict_in_the_ledger_that_this_call_did_not_record_is_no_label(tmp_path, monkeypatch):
    events = [
        event("question.raised", id="Q-001", kind="verdict", target=HOLD, round=1),
        event("human.verdict", question="Q-001", target=HOLD, decision="reject", by="human"),  # not recorded now
        event("question.raised", id="Q-002", kind="verdict", target=FINDING, round=1),
        event("human.verdict", question="Q-002", target=FINDING, decision="accept", by="human"),
    ]
    monkeypatch.setattr(s1_labels, "read_ledger", lambda unit_dir: SimpleNamespace(events=events))
    monkeypatch.setattr(s1_labels, "read_verdict", lambda unit_dir, round_no: {"evidence": EVIDENCE})
    out = tmp_path / "labels.jsonl"
    assert s1_labels.record_human_labels(tmp_path, ["Q-002"], [out]) == 0
    assert not out.exists()
    assert s1_labels.record_human_labels(tmp_path, ["Q-001"], [out]) == 1  # the same event, recorded in this call
    assert '"out_of_scope"' in out.read_text() and ITEM in out.read_text()


def test_a_verdict_for_a_question_the_harness_never_raised_is_no_label(tmp_path, monkeypatch):
    events = [event("human.verdict", question="Q-009", target=HOLD, decision="reject", by="human")]
    monkeypatch.setattr(s1_labels, "read_ledger", lambda unit_dir: SimpleNamespace(events=events))
    monkeypatch.setattr(s1_labels, "read_verdict", lambda unit_dir, round_no: {"evidence": EVIDENCE})
    out = tmp_path / "labels.jsonl"
    assert s1_labels.record_human_labels(tmp_path, ["Q-009"], [out]) == 0  # no round to take the hold map from
    assert not out.exists()
