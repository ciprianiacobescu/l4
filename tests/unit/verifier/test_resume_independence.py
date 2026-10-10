"""At the M1.3 merge: a round resumed at aggregation (D4) keeps M1.2's independence record of the judge whose step 9
it reuses, so its verification.md and verdict.json still say how the vendors are known (L4-VER-001)."""

import json

from l4.verifier.evidence import restore_round
from l4.verifier.report import render_verification_md, verdict_json
from l4.verifier.selection import assess_independence

from .test_report import result
from .test_report_independence import CFG


def test_a_resumed_round_keeps_the_independence_line_of_the_round_it_reuses():
    record = assess_independence(CFG, ["codex"], "claude", served_model="claude-haiku-4-5-20251001")
    first = result(independence=record)
    back = restore_round(json.loads(json.dumps(verdict_json(first))), first.unit, first.round + 1)
    assert back.independence == record
    assert record.line() in render_verification_md(back)
    assert verdict_json(back)["independence"] == verdict_json(first)["independence"]


def test_a_round_with_no_record_restores_none():
    first = result()
    back = restore_round(json.loads(json.dumps(verdict_json(first))), first.unit, first.round + 1)
    assert back.independence is None
