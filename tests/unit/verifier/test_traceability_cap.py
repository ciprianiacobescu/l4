"""Step 4 keeps the proved, passing tests over the per-test cap as candidates (L4-VER-054, SCN-VER-182, SCN-VER-184)."""

import dataclasses

from tests.unit.verifier.test_traceability import CFG, A, B, C, case, crit, proof, red_ok, report

from l4.verifier.evidence import _evidence
from l4.verifier.traceability import trace_criteria
from l4.verifier.types import TracingTest

D = "C-dddddddd"
IDS = (A, B, C, D)
FLOW_REASON = "it traces 4 criteria (verifier.max_criteria_per_test=3)"


def wide(status: str = "passed") -> object:
    return report(case("t::flow", status, *IDS))


def test_a_proved_passing_test_over_the_cap_is_a_candidate():
    ledger = [red_ok({i: proof(["t::flow"]) for i in IDS})]
    out = trace_criteria([crit(i) for i in IDS], wide(), ledger, CFG)  # type: ignore[arg-type]
    assert {e.state for e in out} == {"uncovered"}
    for e in out:
        assert e.ignored == (("t::flow", FLOW_REASON),)
        assert e.capped == (TracingTest("t::flow", "passed", "zero_value", over_cap=4),)
        assert not e.tests


def test_a_red_record_without_a_run_keeps_its_note_on_the_candidate():
    record = {i: {**proof(["t::flow"]), "via": "not_applicable"} for i in IDS}
    out = trace_criteria([crit(i) for i in IDS], wide(), [red_ok(record)], CFG)  # type: ignore[arg-type]
    assert out[0].capped[0].note == "not applicable: no project code"


def test_no_proof_or_skipped_is_no_candidate():
    bare = trace_criteria([crit(i) for i in IDS], wide(), [], CFG)  # type: ignore[arg-type]
    assert all(e.capped == () and e.ignored == (("t::flow", FLOW_REASON),) for e in bare)
    ledger = [red_ok({i: proof(["t::flow"]) for i in IDS})]
    skipped = trace_criteria([crit(i) for i in IDS], wide("skipped"), ledger, CFG)  # type: ignore[arg-type]
    assert all(e.capped == () and e.ignored == (("t::flow", FLOW_REASON),) for e in skipped)


def test_a_failing_test_over_the_cap_is_no_candidate():
    ledger = [red_ok({i: proof(["t::flow"]) for i in IDS})]
    out = trace_criteria([crit(i) for i in IDS], wide("failed"), ledger, CFG)  # type: ignore[arg-type]
    assert all(e.capped == () and e.state == "uncovered" for e in out)


def test_a_pass_to_pass_test_over_the_cap_is_a_candidate():
    base = [crit(i) for i in IDS]
    out = trace_criteria(base, wide(), [], CFG, base=base)  # type: ignore[arg-type]
    assert out[0].capped == (TracingTest("t::flow", "passed", "pass_to_pass", over_cap=4),)


def test_the_record_keeps_the_candidates_and_the_notes():
    record = {i: {**proof(["t::flow"]), "via": "not_applicable"} for i in IDS}
    out = trace_criteria([crit(i) for i in IDS], wide(), [red_ok(record)], CFG)  # type: ignore[arg-type]
    stored = dataclasses.asdict(out[0])
    again = _evidence(stored)
    assert again.capped == out[0].capped and again.capped[0].over_cap == 4
    assert again.capped[0].note == "not applicable: no project code"
    bare = {k: v for k, v in stored.items() if k != "capped"}
    bare["tests"] = [{"id": "t::a", "status": "passed", "proof": "zero_value"}]
    old = _evidence(bare)
    assert old.capped == () and old.tests[0].over_cap == 0 and old.tests[0].note == ""
