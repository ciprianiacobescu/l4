"""L4-VER-006: a rejected finding that cites no criterion keeps its WHEN ... THEN ... when the parent has several
requirements; the scenario goes under an ADDED requirement of its own (SCN-VER-76, SCN-VER-77)."""

from l4.verifier.fixunit import plan_fix_unit
from l4.verifier.types import Finding, Severity, Verdict

from .test_fixunit import FAMILY, criterion, reject, result

SEVERAL = [
    criterion("C-00000003", requirement="Skip", scenario="Online-only", capability="ingestion"),
    criterion("C-00000001"),
    criterion("C-00000002", requirement="Count", scenario="Per run", capability="ingestion"),
]
NOT_DONE = "task 2.3 is ticked as already satisfied, but its text is not done"
WHY = (
    "the help text is not updated. WHEN mintmory index-tree --help is shown THEN the --text-content help says that "
    "online-only files are skipped"
)


def _rejected() -> Finding:
    return Finding(Severity.MAJOR, NOT_DONE, "help text unchanged [rejected]", "human")


def test_a_scenario_with_no_criterion_gets_a_requirement_of_its_own_when_the_parent_has_several():
    finding = _rejected()
    outcome = result(Verdict.FAIL, [finding])
    plan = plan_fix_unit(SEVERAL, outcome, [reject(finding.id, WHY, "Q-007")], ordinal=1, fix_minor=False)
    assert not plan.not_converted
    [group] = plan.groups
    assert group.ids == (finding.id,) and not group.chore
    assert plan.delta is not None
    [requirement] = plan.delta.requirements
    assert requirement.capability == "greeting"  # the first capability by name, as a feedback item's (L4-FBK-004)
    assert requirement.title == f"{NOT_DONE} \N{EM DASH} finding {finding.id}"
    [scenario] = requirement.scenarios
    assert "mintmory index-tree --help is shown" in scenario.text and scenario.finding == finding.id
    assert plan.consumed == ["Q-007"]


def test_a_parent_with_one_requirement_keeps_the_regression_name():
    finding = _rejected()
    plan = plan_fix_unit(FAMILY, result(Verdict.FAIL, [finding]), [reject(finding.id, WHY)], ordinal=2, fix_minor=False)
    assert plan.delta is not None
    [requirement] = plan.delta.requirements
    assert requirement.title == "Greet \N{EM DASH} regression 2"
