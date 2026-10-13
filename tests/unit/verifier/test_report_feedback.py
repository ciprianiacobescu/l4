"""human-feedback 2.7 (L4-FBK-011; D12): `## Feedback` in `verification.md` lists the items taken or judged in the
round, from the round's `feedback.*` events."""

import json
from datetime import UTC, datetime, timedelta

from l4.redact import Redactor
from l4.state.ledger import TS_FORMAT, LedgerEvent
from l4.verifier.report import feedback_lines, render_verification_md, write_round_evidence
from l4.verifier.types import Verdict, VerifyResult

T0 = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
D = "\N{EM DASH}"


def events(*rows: tuple[str, dict]) -> list[LedgerEvent]:
    return [
        LedgerEvent(T0 + timedelta(seconds=n), "r-20261012T1200Z-aaaa", "openspec:p", n + 1, kind, data)
        for n, (kind, data) in enumerate(rows)
    ]


def verdict(round_: int) -> tuple[str, dict]:
    return "verify.verdict", {"round": round_, "verdict": "fail", "findings": 1}


ROUND_ONE = (
    ("feedback.taken", {"id": "FB-001", "kind": "refactor", "sha256": "a" * 64, "round": 1, "fix_unit": "p-fix-1"}),
    ("feedback.taken", {"id": "FB-002", "kind": "config", "sha256": "b" * 64, "round": 1, "fix_unit": "p-fix-1"}),
    ("feedback.waiting", {"ids": ["FB-003"], "reason": "fix_unit_full"}),
    verdict(1),
)
ROUND_TWO = (
    ("feedback.addressed", {"id": "FB-001", "round": 2, "sha": "0123456789abcdef", "evidence": "helper extracted"}),
    ("feedback.not_addressed", {"id": "FB-002", "round": 2, "evidence": "PACK_ROUNDING is\nnever read"}),
)


def test_a_round_lists_what_it_took_waited_on_and_judged():
    assert feedback_lines(events(*ROUND_ONE), 1) == [
        "FB-001 (refactor): taken into p-fix-1",
        "FB-002 (config): taken into p-fix-1",
        "FB-003: waiting for the next round (fix unit full)",
    ]
    assert feedback_lines(events(*ROUND_ONE, *ROUND_TWO), 2) == [
        "FB-001: addressed at 0123456789: helper extracted",
        "FB-002: not addressed: PACK_ROUNDING is never read",
    ]


def test_other_rounds_and_other_events_are_not_in_it():
    assert feedback_lines(events(verdict(1)), 2) == []
    assert feedback_lines(events(*ROUND_ONE, ("feedback.changed", {"id": "FB-001", "sha256": "c" * 64})), 2) == []


def result(**over) -> VerifyResult:
    base = VerifyResult("openspec:p", 2, Verdict.FAIL, "a" * 40, "b" * 40)
    for key, value in over.items():
        setattr(base, key, value)
    return base


def test_the_section_is_there_only_when_the_round_has_lines():
    assert "## Feedback" not in render_verification_md(result())
    text = render_verification_md(result(feedback=["FB-001: addressed at 0123456789: ok"]))
    assert "\n## Feedback\n\n- FB-001: addressed at 0123456789: ok\n" in text
    assert text.index("## Findings") < text.index("## Feedback")


def test_write_round_evidence_reads_the_round_from_the_ledger(tmp_path):
    ledger = tmp_path / ".l4" / "ledger"
    ledger.mkdir(parents=True)
    rows = events(*ROUND_ONE, *ROUND_TWO)
    (ledger / "r-20261012T1200Z-aaaa.jsonl").write_text("".join(json.dumps(_row(e)) + "\n" for e in rows))
    write_round_evidence(tmp_path, 2, result(), Redactor({}))
    text = (tmp_path / "verification.md").read_text()
    assert "- FB-001: addressed at 0123456789: helper extracted" in text
    assert "- FB-002: not addressed: PACK_ROUNDING is never read" in text
    assert "taken into" not in text


def _row(e: LedgerEvent) -> dict:
    envelope = {"ts": e.ts.strftime(TS_FORMAT), "run_id": e.run_id, "unit": e.unit, "seq": e.seq}
    return {**envelope, "type": e.type, **e.data}
