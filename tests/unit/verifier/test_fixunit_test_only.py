"""M1.13 lines 8-9 (W-C1, SPEC L4-VER-006): a finding about the tests of a criterion the round found satisfied is a task
that adds tests, not a red/green task (the code is right, so no honest red test can fail).

Damage line: a code defect on a passing criterion must never be turned into "add tests"."""

import dataclasses

from l4.verifier.fixunit import plan_fix_unit
from l4.verifier.types import CriterionOutcome, Finding, Severity, Verdict

from .test_fixunit import FAMILY, reject, result

TITLE = "New tests bypass the HTTP server and do not check the observable outcomes"
REASON = (
    "design D3 asks for tests that drive the real server; "
    "calling a private helper on a hand-built handler shows nothing"
)


def accepted(cid: str = "C-00000001", value: str = "pass") -> CriterionOutcome:
    return CriterionOutcome(cid, "alias", value, "insufficient_evidence", "accepted by human: the behaviour matches")  # type: ignore[arg-type]


def rejected(title: str = TITLE, cid: str | None = "C-00000001", source: str = "human") -> Finding:
    return Finding(Severity.MAJOR, title, "the tests call a private function [rejected]", source, cid)  # type: ignore[arg-type]


def plan(finding: Finding, outcomes: list[CriterionOutcome], reason: str = REASON):
    return plan_fix_unit(
        FAMILY, result(Verdict.FAIL, [finding], outcomes), [reject(finding.id, reason, "Q-004")], ordinal=1,
        fix_minor=False,
    )  # fmt: skip


def test_the_cbsg_shape_is_a_tests_task_that_keeps_its_criterion_and_the_decision_first():
    [group] = plan(rejected(), [accepted()]).groups
    assert group.chore and group.tests and group.criteria == ("C-00000001",)
    assert group.detail.startswith(f"Decided by human in Q-004: {REASON}. ")


def test_the_reject_is_still_consumed_by_the_tests_task():
    assert plan(rejected(), [accepted()]).consumed == ["Q-004"]


def test_a_failing_criterion_keeps_the_red_green_task():
    [group] = plan(rejected(), [accepted(value="fail")]).groups
    assert not group.chore and not group.tests


def test_a_criterion_without_an_outcome_keeps_the_red_green_task():
    [group] = plan(rejected(), []).groups
    assert not group.chore and not group.tests


def test_a_finding_with_a_regression_scenario_keeps_the_red_green_task():
    [group] = plan(rejected(), [accepted()], "WHEN a request arrives THEN the real server answers 200").groups
    assert not group.chore and not group.tests


def test_a_finding_that_is_not_about_tests_keeps_the_red_green_task():
    for title in ("Edge case of an empty cart is not handled", "The total ignores a discount of zero"):
        [group] = plan(rejected(title), [accepted()]).groups
        assert not group.chore and not group.tests, title


def test_a_gates_finding_is_not_turned_into_tests():
    finding = Finding(Severity.MAJOR, "Tests fail at head", "d", "deterministic", "C-00000001")
    [group] = plan_fix_unit(
        FAMILY, result(Verdict.FAIL, [finding], [accepted()]), [], ordinal=1, fix_minor=False
    ).groups
    assert not group.chore and not group.tests


def test_a_human_finding_without_a_criterion_is_still_not_converted():
    converted = plan(rejected(cid=None), [accepted()])
    assert converted.groups == [] and "no criterion" in converted.not_converted[0]


def test_the_judges_own_finding_is_not_converted_on_a_fail_as_before():
    finding = rejected(source="judge")
    assert (
        plan_fix_unit(FAMILY, result(Verdict.FAIL, [finding], [accepted()]), [], ordinal=1, fix_minor=False).groups
        == []
    )


def test_the_group_is_the_one_a_fix_unit_is_written_from():
    [group] = plan(rejected(), [accepted()]).groups
    assert dataclasses.asdict(group)["tests"] is True


def test_the_spec_says_when_a_finding_is_a_tests_task():
    from pathlib import Path

    spec = (Path(__file__).resolve().parents[3] / "docs" / "SPEC.md").read_text(encoding="utf-8")
    spec = " ".join(spec.split())
    assert "A finding about the tests of a criterion the round found satisfied" in spec
    assert "`task.tests_added.discriminating`" in spec
