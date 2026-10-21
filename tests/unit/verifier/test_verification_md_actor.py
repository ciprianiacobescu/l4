"""A verdict by an agent or the delegate is named (delegate-answers 13.1; L4-DLG-010, L4-VER-051): `verification.md`,
the outcome reasons and the notes of the round that follows say `agent (CLAUDECODE)` or `the delegate (<model> via
<cli>)`; a person's verdict reads as before."""

from datetime import UTC, datetime

from l4.state.ledger import LedgerEvent
from l4.verifier.report import render_verification_md
from l4.verifier.types import Verdict, VerifyResult
from l4.verifier.verdicts import effective_verdicts

STAMP = datetime(2026, 10, 18, tzinfo=UTC)
TEXT = "a" * 64


def verdict_event(seq: int, target: str, by: str, **more) -> LedgerEvent:
    data = {"question": f"Q-00{seq}", "target": target, "decision": "accept", "by": by, "reason": "fine",
            "text_sha256": TEXT, **more}  # fmt: skip
    return LedgerEvent(STAMP, "r-1", "u", seq, "human.verdict", data)


def effective(*events: LedgerEvent):
    targets = {e.data["target"]: TEXT for e in events}
    return effective_verdicts(list(events), targets)


def test_a_verdict_by_an_agent_or_the_delegate_is_named():
    got = effective(
        verdict_event(1, "C-1", "human"),
        verdict_event(2, "C-2", "agent", marker="CLAUDECODE"),
        verdict_event(3, "C-3", "delegate", profile="dlg", model="claude-opus-5-5", cli="claude-code"),
    )  # fmt: skip
    assert got["C-1"].by == "human" and got["C-1"].label == "human"
    assert got["C-2"].by == "agent" and got["C-2"].label == "agent (CLAUDECODE)"
    assert got["C-3"].by == "delegate" and got["C-3"].label == "the delegate (claude-opus-5-5 via claude-code)"
    result = VerifyResult("openspec:u", 1, Verdict.PASS, "", "abc")
    result.human = list(got.values())
    text = render_verification_md(result)
    assert "## Answers to verdict questions" in text
    assert "Q-001 accept C-1 by human: fine" in text
    assert "Q-002 accept C-2 by agent (CLAUDECODE): fine" in text
    assert "Q-003 accept C-3 by the delegate (claude-opus-5-5 via claude-code): fine" in text


def test_the_reasons_and_notes_of_the_round_name_the_actor():
    from l4.verifier.aggregate import aggregate_criterion
    from l4.verifier.verdicts import rejection_note

    delegate = verdict_event(3, "C-3", "delegate", model="gpt-6.1-sol", cli="codex")
    (verdict,) = effective(delegate).values()
    outcome = aggregate_criterion("C-3", "a", None, None, human=verdict, require_traceability=False)
    assert outcome.reason == "accepted by the delegate (gpt-6.1-sol via codex): fine"
    rejected = effective(
        LedgerEvent(STAMP, "r-1", "u", 4, "human.verdict", {**delegate.data, "decision": "reject", "target": "F-1"})
    )["F-1"]
    assert rejection_note(rejected) == " [rejected by the delegate (gpt-6.1-sol via codex) (fine)]"
    (person,) = effective(verdict_event(5, "C-5", "human")).values()
    assert aggregate_criterion("C-5", "a", None, None, human=person).reason == "accepted by human: fine"
