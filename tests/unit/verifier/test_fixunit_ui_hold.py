"""ui-hold-evidence, L4-VER-085: a rejected UI hold is fixed under its criterion, and a criterion and its UI hold that a
reviewer rejected in one round are one task (SCN-VER-338..342)."""

from l4.specs.base import Criterion, Framework
from l4.verifier.fixunit import plan_fix_unit
from l4.verifier.types import CriterionOutcome, Finding, HumanVerdict, Severity, Verdict, VerifyResult
from l4.verifier.ui_step import ui_hold_text
from l4.verifier.verdicts import hold_id, is_ui_hold_finding, settle_holds

CID = "C-1a2b3c4d"
OTHER = "C-2b3c4d5e"
HOLD = ui_hold_text(CID)
WHEN_A = "WHEN the cart page opens THEN it shows 4 items"
WHEN_B = "WHEN the cart page opens THEN it shows 5 items"


def criterion(cid: str, requirement: str, scenario: str, capability: str = "web") -> Criterion:
    return Criterion(cid, f"{capability} > {requirement} > {scenario}", Framework.OPENSPEC, capability, requirement,
                     scenario, "WHEN x THEN y", "specs/web/spec.md", 1)  # fmt: skip


ONE = [criterion(CID, "Cart", "Count")]
TWO = [criterion(CID, "Cart", "Count"), criterion(OTHER, "Checkout", "Pay")]


def reject(target: str, reason: str, question: str) -> HumanVerdict:
    return HumanVerdict(question, target, "reject", "human", reason, "x")


def plan(family, rejects, hold=HOLD, *, criterion_fails=True):
    """The fix unit of a FAIL round whose rejects are `rejects` (a list of HumanVerdict) for `hold`."""
    effective = {v.target: v for v in rejects}
    findings = settle_holds([], [hold], effective)
    outcomes = [CriterionOutcome(CID, "alias", "fail", None, "disputed, rejected")] if criterion_fails else []
    r = VerifyResult("openspec:add-cart", 2, Verdict.FAIL, "b", "h", findings=findings, criteria=outcomes)
    return findings, plan_fix_unit(family, r, rejects, ordinal=1, fix_minor=False)


def hold_reject(reason: str, question: str = "Q-005") -> HumanVerdict:
    return reject(hold_id(HOLD), reason, question)


def test_a_rejected_ui_hold_finding_cites_its_criterion_and_keeps_the_rest_of_0_4_59():
    for reason, source in ((f"the heading is wrong. {WHEN_A}", "deterministic"), ("the heading is wrong", "human")):
        [f] = settle_holds([], [HOLD], {hold_id(HOLD): hold_reject(reason)})
        assert f.criterion == CID and f.source == source and f.severity is Severity.MAJOR
        assert f.id == hold_id(HOLD) and f.title.startswith("Rejected hold: UI criterion C-1a2b3c4d has no end-to-end")
        assert is_ui_hold_finding(f)


def test_only_a_ui_hold_finding_is_one():
    scope = "scope: `src/inventory/stock.py` changes module `inventory`, which the spec does not name"
    coverage = "diff coverage: changed code not run by any test: `src/a.py::f`"
    for hold in (scope, coverage, "diff coverage: not measured: the coverage plugin wrote no status"):
        [f] = settle_holds([], [hold], {hold_id(hold): reject(hold_id(hold), f"no. {WHEN_A}", "Q-001")})
        assert f.criterion is None and not is_ui_hold_finding(f)
    assert not is_ui_hold_finding(Finding(Severity.MAJOR, "Judge says", "d", "judge", CID))
    assert not is_ui_hold_finding(Finding(Severity.MAJOR, "t", "d", "human", CID))  # a human's finding with an F- id


def test_scn_ver_338_a_criterion_and_its_ui_hold_rejected_in_one_round_are_one_task():
    v_criterion = reject(CID, f"the badge is wrong. {WHEN_A}", "Q-004")
    v_hold = hold_reject(f"same: {WHEN_A}", "Q-005")
    findings, fix = plan(ONE, [v_criterion, v_hold])
    [group] = fix.groups
    assert group.criteria == (CID,) and not group.chore and len(group.ids) == 2
    assert hold_id(HOLD) in group.ids and any(i != hold_id(HOLD) for i in group.ids)
    assert "Q-004" in group.detail and "Q-005" in group.detail
    assert group.detail.index("Q-004") < group.detail.index("Q-005")  # the criterion's decision first
    assert fix.consumed == ["Q-004", "Q-005"] and fix.not_converted == []
    [requirement] = fix.delta.requirements
    assert requirement.title == "Cart — regression 1"
    [scenario] = requirement.scenarios  # the same text once
    assert scenario.text == "- **WHEN** the cart page opens\n- **THEN** it shows 4 items"
    assert [f.id for f in findings] == [hold_id(HOLD)] and findings[0].criterion == CID


def test_scn_ver_339_two_different_scenarios_stay_in_the_one_task():
    v_criterion = reject(CID, f"the badge is wrong. {WHEN_A}", "Q-004")
    v_hold = hold_reject(f"same: {WHEN_B}", "Q-005")
    _, fix = plan(ONE, [v_criterion, v_hold])
    assert len(fix.groups) == 1 and fix.consumed == ["Q-004", "Q-005"]
    [requirement] = fix.delta.requirements
    assert requirement.title == "Cart — regression 1"
    assert [s.text.splitlines()[-1] for s in requirement.scenarios] == [
        "- **THEN** it shows 4 items",
        "- **THEN** it shows 5 items",
    ]


def test_scn_ver_340_a_ui_hold_rejected_alone_is_fixed_under_its_criterion_s_requirement():
    _, fix = plan(TWO, [hold_reject(f"the heading is wrong. {WHEN_A}")], criterion_fails=False)
    [group] = fix.groups
    assert group.criteria == (CID,) and not group.chore and fix.consumed == ["Q-005"]
    [requirement] = fix.delta.requirements
    assert requirement.title == "Cart — regression 1" and requirement.capability == "web"
    [scenario] = requirement.scenarios
    assert scenario.name == "Count" and scenario.text.endswith("it shows 4 items")  # named after C's scenario
    assert not any("finding H-" in r.title or r.title.startswith("Rejected hold") for r in fix.delta.requirements)


def test_a_second_scenario_under_a_taken_name_gets_a_number():
    v_criterion = reject(CID, "wrong", "Q-004")  # no scenario: the criterion's task is chore-less and has no name taken
    judged = Finding(Severity.MAJOR, "Count", "d [rejected]", "human", CID)
    v_judged = reject(judged.id, f"wrong. {WHEN_B}", "Q-006")
    effective = {v.target: v for v in (v_criterion, v_judged, hold_reject(f"wrong. {WHEN_A}"))}
    findings = [judged, *settle_holds([], [HOLD], effective)]
    r = VerifyResult("openspec:add-cart", 2, Verdict.FAIL, "b", "h", findings=findings,
                     criteria=[CriterionOutcome(CID, "alias", "fail", None, "r")])  # fmt: skip
    fix = plan_fix_unit(TWO, r, list(effective.values()), ordinal=1, fix_minor=False)
    [requirement] = fix.delta.requirements
    assert [s.name for s in requirement.scenarios] == ["Count", "Count (2)"]


def test_scn_ver_341_a_ui_hold_rejected_alone_without_a_scenario_is_not_converted_and_not_consumed():
    findings, fix = plan(ONE, [hold_reject("the heading is wrong")], criterion_fails=False)
    assert findings[0].criterion == CID and findings[0].source == "human"
    assert fix.groups == [] and fix.delta is None and fix.consumed == []
    assert len(fix.not_converted) == 1 and fix.not_converted[0].startswith(hold_id(HOLD))


def test_a_ui_hold_without_a_scenario_joins_the_task_of_its_rejected_criterion():
    v_criterion = reject(CID, f"the badge is wrong. {WHEN_A}", "Q-004")
    _, fix = plan(ONE, [v_criterion, hold_reject("the heading is wrong")])
    [group] = fix.groups
    assert len(group.ids) == 2 and fix.consumed == ["Q-004", "Q-005"] and len(fix.delta.requirements[0].scenarios) == 1


def test_a_ui_hold_whose_criterion_is_not_in_the_family_plans_as_in_0_4_59():
    foreign = criterion("C-99999999", "Other", "Thing")
    with_scenario, fix = plan([foreign], [hold_reject(f"wrong. {WHEN_A}")], criterion_fails=False)
    [group] = fix.groups
    assert group.criteria == () and group.chore is False and fix.consumed == ["Q-005"]
    [requirement] = fix.delta.requirements
    assert requirement.title == "Other — regression 1"  # one requirement in the family: as in 0.4.59
    assert requirement.scenarios[0].name.startswith("Rejected hold: UI criterion C-1a2b3c4d")
    _, bare = plan([foreign], [hold_reject("wrong")], criterion_fails=False)
    assert bare.groups == [] and bare.consumed == [] and len(bare.not_converted) == 1
