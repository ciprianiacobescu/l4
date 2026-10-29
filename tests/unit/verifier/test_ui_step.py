"""Step 5's glue (plan line 34): which criteria need a generated test, which generated tests of earlier rounds still
stand, and how an accepted one enters the evidence."""

import dataclasses
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
    ui_hold_binding,
    ui_hold_text,
    ui_waivers,
    unclosed_holds,
    with_generated,
)
from l4.verifier.verdicts import finding_sha256, hold_id, text_sha256

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


def test_a_gap_that_is_not_closed_is_a_hold_with_a_text_that_does_not_name_the_status():
    refused = GeneratedOutcome(CID, "fails_at_head", PATH, 2, "the test fails at the head: t::x")
    again = GeneratedOutcome(CID, "uncollectable", PATH, 2, "a different sentence")
    accepted = GeneratedOutcome(OTHER, "accepted", PATH, 1)
    gaps = [crit(CID), crit(OTHER)]
    (hold,) = unclosed_holds(gaps, [refused, accepted])
    assert hold == ui_hold_text(CID) and CID in hold
    assert not any(
        status in hold for status in ("fails_at_head", "uncollectable", "not attempted", "fails at the head")
    )
    assert unclosed_holds(gaps, [again, accepted]) == [hold]
    assert unclosed_holds([crit(CID)], []) == [hold]


def test_the_hold_of_a_criterion_keeps_its_id_whatever_the_generator_said(  # SCN-VER-252
):
    ids = {
        hold_id(h)
        for status in ("fails_at_head", "not_testable", "uncollectable", "writer_failed")
        for h in unclosed_holds([crit(CID)], [GeneratedOutcome(CID, status, PATH, 1)])  # type: ignore[arg-type]
    }
    assert ids == {hold_id(ui_hold_text(CID))}


def test_a_waived_criterion_is_closed_and_raises_no_hold():
    waived = GeneratedOutcome(CID, "waived", None, 0, by="Q-004")
    assert unclosed_holds([crit(CID), crit(OTHER)], [waived]) == [ui_hold_text(OTHER)]


def test_the_gap_finding_of_a_waived_criterion_says_who_waived_it():
    (gap,) = gap_findings([crit(CID)], waived={CID: "Q-004"})
    assert gap.title == UI_GAP_TITLE and gap.criterion == CID and "waived by Q-004" in gap.detail
    assert "step 5 generates one" not in gap.detail
    assert "waived" not in gap_findings([crit(CID)])[0].detail


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


# -- ui-hold-waiver: an accepted UI criterion is not held again (L4-VER-067)

HOLD = ui_hold_text(CID)
TRACING = "tests.test_page::test_badge"
UNPROVED = "e2e.test_page::test_unproved"
STAMP = datetime(2026, 10, 30, tzinfo=UTC)


def changed() -> Criterion:
    return dataclasses.replace(crit(CID), text="WHEN z THEN y")


def tracing(*tests: str, ignored: tuple[tuple[str, str], ...] = ()) -> list[CriterionEvidence]:
    return [
        CriterionEvidence(CID, "a", "covered", tuple(TracingTest(t, "passed", "red_assertion") for t in tests), ignored)
    ]


def blobs(table: dict[str, str] | None = None):
    """A test id -> the file and blob that hold it, as the ladder gives it; every blob is `b1` unless the table says."""
    table = table or {}
    return lambda test: f"{test.split('::')[0]}\t{table.get(test, 'b1')}"


def led(seq: int, event_type: str, **data) -> LedgerEvent:
    return LedgerEvent(STAMP, "r-1", "openspec:add-thing", seq, event_type, data)


def raised(seq: int, question: str, target: str, **data) -> LedgerEvent:
    return led(seq, "question.raised", id=question, kind="verdict", source="verifier", target=target, round=1, **data)


def decided(seq: int, question: str, target: str, decision: str, sha: str) -> LedgerEvent:
    return led(
        seq, "human.verdict", question=question, target=target, decision=decision, by="ana", reason="r", text_sha256=sha
    )


def binding(files=None) -> str:
    return ui_hold_binding(crit(CID), tracing(TRACING)[0], blobs(files))


def waivers(events, trace=None, files=None, criteria=None):
    return ui_waivers(events, criteria or [crit(CID)], tracing(TRACING) if trace is None else trace, blobs(files))


def held_and_accepted(decision: str = "accept", sha: str | None = None) -> list[LedgerEvent]:
    """Round 1 raised the hold (bound to the criterion's text and its tracing files); a person answered it."""
    return [
        raised(
            1, "Q-001", hold_id(HOLD), criterion=CID, criterion_sha256=text_sha256(crit(CID)), text_sha256=binding()
        ),
        decided(2, "Q-001", hold_id(HOLD), decision, sha or binding()),
    ]


def test_the_binding_follows_the_criterion_text_and_the_head_blobs_of_its_tracing_files():
    assert binding() == binding()
    assert binding() != binding({TRACING: "b2"})
    assert binding() != ui_hold_binding(changed(), tracing(TRACING)[0], blobs())
    unproved = tracing(TRACING, ignored=((UNPROVED, "never proved"),))[0]
    assert binding() != ui_hold_binding(crit(CID), unproved, blobs())
    assert binding() != finding_sha256(hold_id(HOLD))


def test_a_test_the_harness_wrote_is_not_part_of_the_binding():
    plain = tracing(TRACING)[0]
    more = CriterionEvidence(CID, "a", "covered", (*plain.tests, TracingTest("tests.test_l4::t", "passed", "audit")))
    gen = CriterionEvidence(CID, "a", "covered", (*plain.tests, TracingTest("e2e.test_l4::t", "passed", "generated")))
    assert ui_hold_binding(crit(CID), more, blobs()) == ui_hold_binding(crit(CID), plain, blobs())
    assert ui_hold_binding(crit(CID), gen, blobs()) == ui_hold_binding(crit(CID), plain, blobs())


def test_an_accepted_criterion_verdict_waives_it():  # SCN-VER-247
    events = [raised(1, "Q-002", CID), decided(2, "Q-002", CID, "accept", text_sha256(crit(CID)))]
    assert waivers(events) == {CID: "Q-002"}
    assert waivers(events, criteria=[crit(CID), crit(OTHER)]) == {CID: "Q-002"}


def test_an_accepted_ui_hold_waives_the_criterion_in_a_later_round_whatever_the_status():  # SCN-VER-248
    assert waivers(held_and_accepted()) == {CID: "Q-001"}


def test_an_accept_written_before_this_change_is_found_by_the_title_of_its_question():  # SCN-VER-249
    old = f"UI criterion {CID} has no end-to-end test (fails_at_head); see the generated UI tests table"
    title = (
        f"Hold {hold_id(old)}: UI criterion {CID} has no end-to-end test (fails_at_head); see the generated UI table"
    )
    events = [
        raised(1, "Q-001", hold_id(old), title=title, text_sha256=finding_sha256(hold_id(old))),
        decided(2, "Q-001", hold_id(old), "accept", finding_sha256(hold_id(old))),
    ]
    assert waivers(events) == {CID: "Q-001"}
    assert waivers(events, criteria=[crit(OTHER)], trace=[]) == {}  # another criterion's hold is not this one's


def test_a_hold_that_is_not_about_a_ui_criterion_waives_nothing():
    other = "diff coverage: not measured: the coverage plugin wrote no status"
    events = [
        raised(
            1,
            "Q-001",
            hold_id(other),
            title=f"Hold {hold_id(other)}: {other}",
            text_sha256=finding_sha256(hold_id(other)),
        ),
        decided(2, "Q-001", hold_id(other), "accept", finding_sha256(hold_id(other))),
    ]
    assert waivers(events) == {}


def test_a_changed_criterion_or_tracing_file_ends_the_waiver():  # SCN-VER-250
    events = held_and_accepted()
    assert waivers(events, files={TRACING: "b2"}) == {}  # a file of its tracing tests changed
    assert waivers(events, trace=tracing(TRACING, "tests.test_other::test_more")) == {}  # another test traces it now
    assert waivers(events, criteria=[changed()]) == {}
    accepted = [raised(1, "Q-002", CID), decided(2, "Q-002", CID, "accept", text_sha256(crit(CID)))]
    assert waivers(accepted, criteria=[changed()]) == {}


def test_a_reject_a_void_or_a_failing_tracing_test_is_not_waived():  # SCN-VER-251
    assert waivers(held_and_accepted("reject")) == {}
    assert waivers([*held_and_accepted(), led(3, "human.void", question="Q-001", target=hold_id(HOLD))]) == {}
    failing = [CriterionEvidence(CID, "a", "fail", (TracingTest(TRACING, "failed", "red_assertion"),))]
    assert waivers(held_and_accepted(), trace=failing) == {}
    errored = [CriterionEvidence(CID, "a", "covered", (TracingTest(TRACING, "error", "red_assertion"),))]
    assert waivers(held_and_accepted(), trace=errored) == {}


def test_a_later_reject_ends_the_waiver_and_a_later_accept_brings_it_back():
    criterion = [raised(3, "Q-002", CID), decided(4, "Q-002", CID, "reject", text_sha256(crit(CID)))]
    assert waivers([*held_and_accepted(), *criterion]) == {}
    rejected_hold = [
        *held_and_accepted(),
        raised(3, "Q-002", hold_id(HOLD), criterion=CID),
        decided(4, "Q-002", hold_id(HOLD), "reject", binding()),
    ]
    assert waivers(rejected_hold) == {}
    again = [
        *rejected_hold,
        raised(5, "Q-003", hold_id(HOLD), criterion=CID),
        decided(6, "Q-003", hold_id(HOLD), "accept", binding()),
    ]
    assert waivers(again) == {CID: "Q-003"}
    older_reject = [*criterion, raised(5, "Q-003", CID), decided(6, "Q-003", CID, "accept", text_sha256(crit(CID)))]
    assert waivers(older_reject) == {CID: "Q-003"}


def test_the_latest_accept_of_the_criterion_or_of_its_hold_is_the_one_named():
    events = [*held_and_accepted(), raised(3, "Q-002", CID), decided(4, "Q-002", CID, "accept", text_sha256(crit(CID)))]
    assert waivers(events) == {CID: "Q-002"}
