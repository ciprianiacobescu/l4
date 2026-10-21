"""Step 5's glue (plan line 34): which criteria need a generated test, which generated tests of earlier rounds still
stand, and how an accepted one enters the evidence."""

import hashlib
from datetime import UTC, datetime

from l4.gates.junit import TestCase, TestReport
from l4.memory.curate import UI_GAP_TITLE
from l4.specs.base import Criterion, Framework
from l4.state.ledger import LedgerEvent
from l4.verifier.types import CriterionEvidence, GeneratedOutcome, TracingTest
from l4.verifier.ui_step import (
    gap_findings,
    plan_generation,
    previously_generated,
    unclosed_holds,
    with_generated,
)

CID, OTHER = "C-de7f2d3f", "C-68f2e098"
PATH = "e2e/test_l4_c_de7f2d3f.py"
TEST = "e2e.test_l4_c_de7f2d3f::test_badge"
UI = ["src/web/page.py"]


def crit(cid: str) -> Criterion:
    return Criterion(cid, f"web › {cid}", Framework.OPENSPEC, "web", "R", cid, "WHEN x THEN y", "spec.md", 1)


def report(*ids: str, status: str = "passed") -> TestReport:
    return TestReport({i: TestCase(i, status) for i in ids})  # type: ignore[arg-type]


def test_gaps_are_the_ui_criteria_that_no_test_of_the_e2e_report_traces():
    criteria = [crit(CID), crit(OTHER)]
    plan = plan_generation(criteria, report(f"e2e.test_{OTHER.replace('-', '_').lower()}::t"), ["src/web/page.py"], UI)
    assert [c.id for c in plan.gaps] == [CID] and plan.skipped == ""


def test_a_unit_that_changes_no_ui_path_has_nothing_to_generate():
    plan = plan_generation([crit(CID)], report("e2e.test_smoke::t"), ["src/core.py"], UI)
    assert plan.gaps == [] and "ui_paths" in plan.skipped


def test_every_ui_criterion_covered_in_the_e2e_report_is_not_a_gap():
    plan = plan_generation([crit(CID)], report(TEST), ["src/web/page.py"], UI)
    assert plan.gaps == [] and plan.skipped == ""


def test_a_unit_test_never_closes_a_gap():
    # the e2e report is the only one asked: a main-report test naming the criterion is not passed in at all
    plan = plan_generation([crit(CID)], report("tests.test_page::test_x"), ["src/web/page.py"], UI)
    assert [c.id for c in plan.gaps] == [CID]


def event(**data) -> LedgerEvent:
    base = {"criterion": CID, "test": PATH, "status": "accepted", "tests": [TEST], "sha256": ""}
    return LedgerEvent(datetime.now(UTC), "r", "u", 1, "verify.generated", {**base, **data})


def test_an_earlier_accepted_test_that_is_unchanged_stays_generated(tmp_path):
    (tmp_path / "e2e").mkdir()
    body = b"# l4:generated\ndef test_badge(): ...\n"
    (tmp_path / PATH).write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    found, edited = previously_generated([event(sha256=digest)], tmp_path, report(TEST))
    assert found == {CID: [TEST]} and edited == []


def test_an_edited_generated_file_is_not_trusted_and_is_reported(tmp_path):
    (tmp_path / "e2e").mkdir()
    (tmp_path / PATH).write_bytes(b"def test_badge(): pass\n")
    found, edited = previously_generated([event(sha256="0" * 64)], tmp_path, report(TEST))
    assert found == {} and edited == [CID]


def test_a_removed_file_or_a_refused_attempt_or_an_event_without_a_digest_counts_for_nothing(tmp_path):
    assert previously_generated([event(sha256="0" * 64)], tmp_path, report(TEST)) == ({}, [])
    assert previously_generated([event(status="fails_at_head", sha256="0" * 64)], tmp_path, report(TEST)) == ({}, [])
    assert previously_generated([event(sha256="")], tmp_path, report(TEST)) == ({}, [])


def test_an_accepted_outcome_adds_a_generated_passing_test_and_covers_the_criterion():
    uncovered = CriterionEvidence(CID, "a", "uncovered")
    done = GeneratedOutcome(CID, "accepted", PATH, 1, tests=(TEST,), base="fail", head="pass")
    (back,) = with_generated([uncovered], [done])
    assert back.state == "covered" and back.tests == (TracingTest(TEST, "passed", "generated"),)


def test_a_refused_outcome_changes_nothing_and_a_failing_test_elsewhere_still_fails_the_criterion():
    failing = CriterionEvidence(CID, "a", "fail", (TracingTest("t::x", "failed", "red_assertion"),))
    refused = GeneratedOutcome(CID, "fails_at_head", PATH, 2)
    assert with_generated([failing], [refused]) == [failing]
    done = GeneratedOutcome(CID, "accepted", PATH, 1, tests=(TEST,))
    (back,) = with_generated([failing], [done])
    assert back.state == "fail" and len(back.tests) == 2


def test_the_gap_finding_is_the_one_the_lesson_rule_matches():
    (gap,) = gap_findings([crit(CID)])
    assert gap.title == UI_GAP_TITLE and gap.criterion == CID and gap.source == "deterministic"


def test_a_gap_that_is_not_closed_is_a_hold_with_a_text_that_does_not_depend_on_the_writers_reason():
    refused = GeneratedOutcome(CID, "fails_at_head", PATH, 2, "the test fails at the head: t::x")
    again = GeneratedOutcome(CID, "fails_at_head", PATH, 2, "a different sentence")
    accepted = GeneratedOutcome(OTHER, "accepted", PATH, 1)
    gaps = [crit(CID), crit(OTHER)]
    (hold,) = unclosed_holds(gaps, [refused, accepted])
    assert CID in hold and "fails_at_head" in hold and "fails at the head" not in hold
    assert unclosed_holds(gaps, [again, accepted]) == [hold]
    (never,) = unclosed_holds([crit(CID)], [])
    assert "(not attempted)" in never


# -- m1.x F6: an e2e test that was never proved discriminating is not coverage for step 5


def proven(criterion: str, *ids: str) -> dict[str, set[str]]:
    return {criterion: set(ids)}


def test_an_unproved_e2e_test_does_not_close_the_gap_and_is_named_in_the_plan():
    plan = plan_generation([crit(CID)], report(TEST), UI, UI, proven={})  # the trace has no proof for it
    assert [c.id for c in plan.gaps] == [CID] and plan.unproved == {CID: (TEST,)}
    [finding] = gap_findings(plan.gaps, plan.unproved)
    assert finding.title == UI_GAP_TITLE and TEST in finding.detail and "never proved" in finding.detail
    assert "step 5 generates one" in finding.detail


def test_a_proved_e2e_test_still_closes_the_gap():
    plan = plan_generation([crit(CID)], report(TEST), UI, UI, proven=proven(CID, TEST))
    assert plan.gaps == [] and plan.unproved == {}


def test_only_the_proved_tests_of_a_criterion_count_when_it_has_several():
    other = "e2e.test_more_c_de7f2d3f::test_badge_too"
    both = report(TEST, other)
    plan = plan_generation([crit(CID)], both, UI, UI, proven=proven(CID, other))
    assert plan.gaps == []
    plan = plan_generation([crit(CID)], both, UI, UI, proven=proven(CID))
    assert [c.id for c in plan.gaps] == [CID] and plan.unproved == {CID: tuple(sorted((other, TEST)))}


def test_without_the_trace_the_old_rule_stands():
    assert plan_generation([crit(CID)], report(TEST), UI, UI).gaps == []


def test_a_criterion_with_no_e2e_test_at_all_has_nothing_unproved():
    plan = plan_generation([crit(CID)], report("e2e.test_smoke::t"), UI, UI, proven={})
    assert [c.id for c in plan.gaps] == [CID] and plan.unproved == {}
    assert "never proved" not in gap_findings(plan.gaps, plan.unproved)[0].detail
