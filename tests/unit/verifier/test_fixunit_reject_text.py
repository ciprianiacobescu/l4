"""M1.12 line 23 (F1, L4-VER-006): the human's reject text is the first thing of a fix task for a coverage hold, in
every shape the MF-7 resume could have had (reproduction before any change)."""

import dataclasses

from l4.verifier.fixunit import plan_fix_unit
from l4.verifier.types import Verdict

from .test_fixunit import COVERAGE_HOLD, FAMILY, reject, result, settled

WRONG = "the code is wrong: sub_areas must be removed from the rename payload, the key is subareas"


def test_the_reject_reason_opens_the_task_of_a_rejected_coverage_hold():
    outcome, human, findings = settled(COVERAGE_HOLD, WRONG)
    [group] = plan_fix_unit(FAMILY, outcome, human, ordinal=1, fix_minor=False).groups
    assert group.tests and group.detail.startswith(f"Decided by human in Q-001: {WRONG}. ")
    assert "Add tests that run the changed code" in group.detail  # the harness's own words follow the decision


def test_a_reject_that_targets_the_criterion_and_not_the_finding_still_opens_the_task():
    outcome, human, findings = settled(COVERAGE_HOLD, WRONG)
    cited = dataclasses.replace(findings[0], criterion="C-00000001")
    outcome.findings = [cited]
    by_criterion = [reject("C-00000001", WRONG)]  # the question was about the criterion, not the hold's finding id
    [group] = plan_fix_unit(FAMILY, outcome, by_criterion, ordinal=1, fix_minor=False).groups
    assert group.detail.startswith(f"Decided by human in Q-001: {WRONG}. ")


def test_a_reason_longer_than_the_cut_is_kept_whole_and_the_finding_detail_is_what_is_cut():
    long = "the code is wrong: " + "sub_areas must go; " * 60 + "END-OF-DECISION"
    assert len(long) > 600
    outcome, human, _ = settled(COVERAGE_HOLD, long)
    [group] = plan_fix_unit(FAMILY, outcome, human, ordinal=1, fix_minor=False).groups
    assert group.detail.startswith(f"Decided by human in Q-001: {' '.join(long.split())}. ")
    assert "END-OF-DECISION" in group.detail


def test_the_task_of_a_verdict_reject_keeps_the_same_form():
    """The decision first is the existing rule for a judge finding (live-fix a1a0ca3); a hold now follows it."""
    from l4.verifier.types import Finding, Severity

    rejected = Finding(Severity.MAJOR, "Judge says", "d [rejected]", "human", "C-00000001")
    plan = plan_fix_unit(
        FAMILY, result(Verdict.FAIL, [rejected]), [reject(rejected.id, WRONG, "Q-004")], ordinal=1, fix_minor=False
    )
    assert plan.groups[0].detail.startswith(f"Decided by human in Q-004: {WRONG}. ")


def test_two_long_rejects_on_one_criterion_both_reach_the_proposal_whole(tmp_path):
    """Review fix: the proposal cuts a finding's detail at one length; two decisions of the same task together must
    fit under it, or the second owner text is cut away on its way to the implementer."""
    from l4.specs.base import Framework, UnitRef
    from l4.specs.openspec import _proposal
    from l4.verifier.types import Finding, Severity

    first = Finding(Severity.MAJOR, "Judge says one", "d [rejected]", "human", "C-00000001")
    second = Finding(Severity.MAJOR, "Judge says two", "d [rejected]", "human", "C-00000001")
    reasons = ["the code is wrong: " + "x" * 1000 + " END-ONE", "also wrong: " + "y" * 1000 + " END-TWO"]
    human = [reject(first.id, reasons[0], "Q-001"), reject(second.id, reasons[1], "Q-002")]
    plan = plan_fix_unit(FAMILY, result(Verdict.FAIL, [first, second]), human, ordinal=1, fix_minor=False)
    [group] = plan.groups
    text = _proposal(UnitRef(Framework.OPENSPEC, "add-greeting", tmp_path), 1, plan.groups)
    assert "END-ONE" in text and "END-TWO" in text, group.detail[-300:]
