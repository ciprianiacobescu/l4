from l4.specs.base import Criterion, Framework
from l4.verifier.fixunit import MAX_FIX_TASKS, plan_fix_unit, when_then
from l4.verifier.preconditions import ci_detail
from l4.verifier.types import CriterionOutcome, Finding, HumanVerdict, Severity, Verdict, VerifyResult


def criterion(cid: str, requirement: str = "Greet", scenario: str = "Named", capability: str = "greeting") -> Criterion:
    return Criterion(
        cid, f"{capability} > {requirement} > {scenario}", Framework.OPENSPEC, capability, requirement, scenario,
        "WHEN x THEN y", "specs/greeting/spec.md", 1,
    )  # fmt: skip


FAMILY = [criterion("C-00000001"), criterion("C-00000002", scenario="Empty")]


def result(verdict: Verdict, findings: list[Finding], outcomes: list[CriterionOutcome] | None = None) -> VerifyResult:
    r = VerifyResult("openspec:add-greeting", 1, verdict, "b", "h")
    r.findings, r.criteria = findings, outcomes or []
    return r


def reject(target: str, reason: str, question: str = "Q-001") -> HumanVerdict:
    return HumanVerdict(question, target, "reject", "human", reason, "x")


def det(title: str, criterion: str | None = None, severity: Severity = Severity.MAJOR) -> Finding:
    return Finding(severity, title, f"detail of {title}", "deterministic", criterion)


def test_when_then_needs_both_words_in_capitals_and_text_between_them():
    assert when_then("WHEN a code is blank THEN refuse it") == "- **WHEN** a code is blank\n- **THEN** refuse it"
    assert when_then("when a then b") is None and when_then("WHEN only") is None and when_then("WHEN THEN") is None


def test_a_plain_defect_is_one_task_per_criterion_and_adds_no_delta():
    a, b = det("Trim fails", "C-00000001"), det("Trim fails again", "C-00000001")
    found = [a, b, det("Other", "C-00000002")]
    plan = plan_fix_unit(FAMILY, result(Verdict.FAIL, found), [], ordinal=1, fix_minor=False)
    assert plan.delta is None and plan.consumed == []
    assert [(g.ids, g.criteria, g.chore) for g in plan.groups] == [
        ((a.id, b.id), ("C-00000001",), False),
        ((plan.groups[1].ids[0],), ("C-00000002",), False),
    ]
    assert plan.groups[0].title == "Trim fails (+1 more)"


def test_a_finding_without_a_criterion_is_a_chore_task():
    found = [det("An undeclared suppression")]
    plan = plan_fix_unit(FAMILY, result(Verdict.FAIL, found), [], ordinal=1, fix_minor=False)
    [group] = plan.groups
    assert group.chore and group.criteria == () and plan.delta is None


def test_a_failing_criterion_that_no_finding_names_still_gets_a_task():
    outcome = CriterionOutcome("C-00000001", "alias", "fail", None, "a tracing test fails at head: t1")
    plan = plan_fix_unit(FAMILY, result(Verdict.FAIL, [], [outcome]), [], ordinal=1, fix_minor=False)
    [group] = plan.groups
    assert group.criteria == ("C-00000001",) and "fails" in group.title and not group.chore


def test_judge_only_findings_are_not_converted_on_a_fail():
    judge = Finding(Severity.MAJOR, "Judge says", "d", "judge", "C-00000001")
    plan = plan_fix_unit(FAMILY, result(Verdict.FAIL, [judge, det("Real")]), [], ordinal=1, fix_minor=False)
    assert [g.title for g in plan.groups] == ["Real"]


def test_a_rejected_judge_finding_becomes_a_task_and_its_question_is_consumed():
    rejected = Finding(Severity.MAJOR, "Judge says", "d [rejected]", "human", "C-00000001")
    plan = plan_fix_unit(
        FAMILY, result(Verdict.FAIL, [rejected]), [reject(rejected.id, "just wrong", "Q-004")], ordinal=1,
        fix_minor=False,
    )  # fmt: skip
    assert plan.consumed == ["Q-004"] and plan.groups[0].ids == (rejected.id,) and plan.delta is None


def test_a_reject_with_when_then_adds_a_regression_scenario_under_the_requirement_of_the_criterion():
    outcome = CriterionOutcome("C-00000002", "alias", "fail", "pass", "rejected by human: x")
    human = [reject("C-00000002", "WHEN a code is blank THEN refuse it", "Q-002")]
    plan = plan_fix_unit(FAMILY, result(Verdict.FAIL, [], [outcome]), human, ordinal=2, fix_minor=False)
    assert plan.consumed == ["Q-002"]
    assert plan.delta is not None
    [req] = plan.delta.requirements
    assert (req.capability, req.title) == ("greeting", "Greet — regression 2")
    [scenario] = req.scenarios
    assert scenario.text == "- **WHEN** a code is blank\n- **THEN** refuse it"
    assert scenario.name == "a code is blank" and scenario.finding == plan.groups[0].ids[0]


def test_a_regression_requirement_of_an_earlier_fix_keeps_the_name_of_the_original():
    fam = [*FAMILY, criterion("C-00000003", requirement="Greet — regression 1", scenario="Gap")]
    judge = Finding(Severity.MINOR, "Gap", "d", "judge", "C-00000003", spec_gap=True, suggested_fix="WHEN a THEN b")
    plan = plan_fix_unit(fam, result(Verdict.PASS, [judge]), [], ordinal=2, fix_minor=True)
    assert plan.delta is not None and plan.delta.requirements[0].title == "Greet — regression 2"


def test_minors_on_a_pass_are_converted_only_when_fix_minor_findings_is_on():
    minor = Finding(Severity.MINOR, "Gap", "d", "judge", "C-00000001", spec_gap=True, suggested_fix="WHEN a THEN b")
    assert plan_fix_unit(FAMILY, result(Verdict.PASS, [minor]), [], ordinal=1, fix_minor=False).groups == []
    plan = plan_fix_unit(FAMILY, result(Verdict.PASS, [minor]), [], ordinal=1, fix_minor=True)
    assert [g.criteria for g in plan.groups] == [("C-00000001",)] and plan.delta is not None


def test_a_ui_gap_closed_by_an_accepted_generated_test_spawns_no_fix_unit():
    from l4.memory.curate import UI_GAP_TITLE
    from l4.verifier.types import GeneratedOutcome

    gap = Finding(Severity.MINOR, UI_GAP_TITLE, "d", "deterministic", "C-00000001")
    other = Finding(Severity.MINOR, UI_GAP_TITLE, "d", "deterministic", "C-00000002")
    r = result(Verdict.PASS, [gap, other])
    r.generated = [GeneratedOutcome("C-00000001", "accepted"), GeneratedOutcome("C-00000002", "fails_at_head")]
    plan = plan_fix_unit(FAMILY, r, [], ordinal=1, fix_minor=True)
    assert [g.criteria for g in plan.groups] == [("C-00000002",)]  # only the gap no test closed


def test_a_minor_spec_gap_without_a_source_for_its_scenario_is_listed_not_converted():
    gap = Finding(Severity.MINOR, "Gap", "d", "judge", "C-00000001", spec_gap=True, suggested_fix="add a check")
    plan = plan_fix_unit(FAMILY, result(Verdict.PASS, [gap]), [], ordinal=1, fix_minor=True)
    assert plan.groups == [] and "no WHEN ... THEN ..." in plan.not_converted[0] and gap.id in plan.not_converted[0]


def test_a_minor_without_a_criterion_or_scenario_is_not_converted():
    bare = Finding(Severity.MINOR, "m", "d", "judge")
    plan = plan_fix_unit(FAMILY, result(Verdict.PASS, [bare]), [], ordinal=1, fix_minor=True)
    assert plan.groups == [] and len(plan.not_converted) == 1


def test_a_scenario_without_a_criterion_uses_the_parents_only_requirement():
    gap = Finding(Severity.MINOR, "Gap", "d", "judge", None, spec_gap=True, suggested_fix="WHEN a THEN b")
    [fam_a] = [criterion("C-00000001")]
    plan = plan_fix_unit([fam_a], result(Verdict.PASS, [gap]), [], ordinal=1, fix_minor=True)
    assert plan.delta is not None and plan.delta.requirements[0].title == "Greet — regression 1"
    assert plan.groups[0].criteria == () and not plan.groups[0].chore  # the new scenario is its criterion
    other = [criterion("C-00000001"), criterion("C-00000009", requirement="Other")]
    plan = plan_fix_unit(other, result(Verdict.PASS, [gap]), [], ordinal=1, fix_minor=True)
    assert plan.groups == [] and "several" in plan.not_converted[0]


def test_at_most_five_tasks_go_into_one_fix_unit_the_most_severe_first():
    findings = [det(f"major {i}") for i in range(5)] + [det("blocker", severity=Severity.BLOCKER)]
    findings += [det("minor", severity=Severity.MINOR)]  # a minor is never converted on a FAIL
    plan = plan_fix_unit(FAMILY, result(Verdict.FAIL, findings), [], ordinal=1, fix_minor=True)
    assert len(plan.groups) == MAX_FIX_TASKS
    assert [g.severity for g in plan.groups] == ["blocker", "major", "major", "major", "major"]
    assert len(plan.not_converted) == 1 and "more than 5 tasks" in plan.not_converted[0]


def test_two_scenarios_with_the_same_title_get_distinct_names():
    f1 = Finding(Severity.MINOR, "Gap", "d", "judge", "C-00000001", spec_gap=True, suggested_fix="WHEN a THEN b")
    f2 = Finding(Severity.MINOR, "Gap", "d", "judge", "C-00000002", spec_gap=True, suggested_fix="WHEN c THEN d")
    plan = plan_fix_unit(FAMILY, result(Verdict.PASS, [f1, f2]), [], ordinal=1, fix_minor=True)
    assert plan.delta is not None
    [req] = plan.delta.requirements
    assert [s.name for s in req.scenarios] == ["Gap", "Gap (2)"]


def test_every_finding_of_a_criterion_keeps_its_own_scenario_in_the_one_task_of_that_criterion():
    # live M1.3 job 5478: three minors on C-e25f06d8, each with its own WHEN/THEN, became one task citing all three
    # findings, but the delta kept only the first scenario, so two "converted" findings were pinned by nothing
    f1 = Finding(Severity.MINOR, "Below", "d1", "judge", "C-00000001", spec_gap=True, suggested_fix="WHEN a THEN b")
    f2 = Finding(Severity.MINOR, "NaN", "d2", "judge", "C-00000001", spec_gap=True, suggested_fix="WHEN c THEN d")
    f3 = Finding(Severity.MINOR, "Zero", "d3", "judge", "C-00000001", spec_gap=True, suggested_fix="WHEN e THEN f")
    plan = plan_fix_unit(FAMILY, result(Verdict.PASS, [f1, f2, f3]), [], ordinal=1, fix_minor=True)
    [group] = plan.groups
    assert group.ids == (f1.id, f2.id, f3.id) and group.criteria == ("C-00000001",)
    assert plan.delta is not None
    [req] = plan.delta.requirements
    assert [(s.name, s.text, s.finding) for s in req.scenarios] == [
        ("Below", "- **WHEN** a\n- **THEN** b", f1.id),
        ("NaN", "- **WHEN** c\n- **THEN** d", f2.id),
        ("Zero", "- **WHEN** e\n- **THEN** f", f3.id),
    ]


def test_a_reject_of_the_criterion_adds_its_scenario_once_for_all_findings_of_that_criterion():
    f1, f2 = det("Trim fails", "C-00000001"), det("Trim fails again", "C-00000001")
    verdict = reject("C-00000001", "WHEN a blank name THEN refuse it")
    plan = plan_fix_unit(FAMILY, result(Verdict.FAIL, [f1, f2]), [verdict], ordinal=1, fix_minor=False)
    assert plan.delta is not None
    [req] = plan.delta.requirements
    assert [s.text for s in req.scenarios] == ["- **WHEN** a blank name\n- **THEN** refuse it"]


def test_a_rejected_finding_with_no_criterion_and_no_scenario_is_never_a_tdd_exempt_chore():
    rejected = Finding(Severity.MAJOR, "Judge says", "d [rejected]", "human")
    plan = plan_fix_unit(
        FAMILY, result(Verdict.FAIL, [rejected]), [reject(rejected.id, "just wrong", "Q-004")], ordinal=1,
        fix_minor=False,
    )  # fmt: skip
    assert plan.groups == [] and plan.consumed == [] and "answer again with a scenario" in plan.not_converted[0]


def test_text_in_a_plan_is_redacted_before_it_is_written_to_the_fix_unit():
    from l4.redact import Redactor
    from l4.verifier.fixunit import redact_plan

    secret = "ghp_" + "a1B2c3D4e5" * 4
    judge = Finding(Severity.MAJOR, f"leaks {secret}", f"detail {secret}", "deterministic", "C-00000001")
    reason = f"WHEN a token {secret} is given THEN it is refused"
    human = [reject("C-00000001", reason)]
    plan = plan_fix_unit(FAMILY, result(Verdict.FAIL, [judge]), human, ordinal=1, fix_minor=False)
    clean = redact_plan(plan, Redactor({}).redact_text)
    text = repr(clean.groups) + repr(clean.delta)
    assert secret not in text and "[REDACTED:" in text and clean.consumed == plan.consumed


LONG = (
    "total_with_vat starts from self.subtotal() and never uses the discounted total that Cart.total() computes. "
    "If a discount code has been applied, the VAT total is worked out on the pre-discount amount, so a customer "
    "would pay VAT on money they were not charged. The proposal says 'the cart total shown to the customer includes "
    "VAT', but the requirement says 'cart subtotal plus VAT', and no scenario covers a discounted cart. Two reasonable "
    "implementations give different answers. Example: with 10% off and RO, the committed code gives 121.00, while VAT "
    "on the discounted total gives 108.90."
)  # the judge's detail of live add-vat F-366420f0 (MR !5), 589 characters


def test_the_human_s_decision_survives_a_long_finding_detail_in_the_fix_task():
    # live add-vat, job 5487: the detail was cut at 600 characters, which dropped the "[rejected by human (WHEN ...)]"
    # note at its end; the fix unit's proposal then read "Two reasonable implementations give different answers"
    # with no decision, and Codex's red step blocked on that "ambiguity"
    from l4.verifier.verdicts import apply_finding_verdicts

    judged = Finding(Severity.MAJOR, "VAT ignores any applied discount code", LONG, "judge", spec_gap=True)
    why = "WHEN a 10 % discount code is applied to a RO cart with subtotal 100.00 THEN total_with_vat is 108.90"
    verdict = reject(judged.id, why, "Q-002")
    [rejected] = apply_finding_verdicts([judged], {judged.id: verdict})
    plan = plan_fix_unit(FAMILY, result(Verdict.FAIL, [rejected]), [verdict], ordinal=1, fix_minor=False)
    [group] = plan.groups
    assert len(group.detail) <= 600 and group.detail.startswith(f"Decided by human in Q-002: {why}.")
    assert group.detail.count(why) == 1  # the note the verdict appended is not repeated at the end
    assert "Two reasonable implementations" in group.detail


def test_each_rejected_finding_of_a_task_keeps_its_decision():
    # live M1.3 job 5482: the second finding's "[rejected by human (...)]" was cut to "an..." in the proposal
    from l4.verifier.verdicts import apply_finding_verdicts

    a = Finding(Severity.MAJOR, "Free shipping", LONG, "judge", "C-00000001")
    b = Finding(Severity.MAJOR, "Negative subtotal", LONG, "judge", "C-00000001")
    va = reject(a.id, "WHEN the subtotal is 50.00 THEN the fee is 0.00", "Q-001")
    vb = reject(b.id, "WHEN the subtotal is -1.00 THEN a ValueError is raised", "Q-002")
    found = apply_finding_verdicts([a, b], {a.id: va, b.id: vb})
    plan = plan_fix_unit(FAMILY, result(Verdict.FAIL, found), [va, vb], ordinal=1, fix_minor=False)
    [group] = plan.groups
    assert "Q-001: WHEN the subtotal is 50.00 THEN the fee is 0.00" in group.detail
    assert "Q-002: WHEN the subtotal is -1.00 THEN a ValueError is raised" in group.detail


def test_a_repository_ci_blocker_becomes_a_chore_task_with_the_tail():
    """SCN-ARC-14: the red job is named in the task, with the end of its log (what the fix needs to read)."""
    tail = "\n".join(f"line {i}" for i in range(80)) + "\nE   assert 1 == 2\nFAILED tests/test_x.py::test_y"
    finding = Finding(
        Severity.BLOCKER, "repository CI failed: test", ci_detail("test", "test", "a" * 40, "https://f/j/1", tail),
        "deterministic",
    )  # fmt: skip
    plan = plan_fix_unit(FAMILY, result(Verdict.FAIL, [finding]), [], ordinal=1, fix_minor=False)
    [group] = plan.groups
    assert group.chore and group.criteria == () and group.title == "repository CI failed: test"
    assert "stage test" in group.detail and "aaaaaaaaaa" in group.detail and "https://f/j/1" in group.detail
    assert "FAILED tests/test_x.py::test_y" in group.detail and "E assert 1 == 2" in group.detail


def settled(hold: str, reason: str = "add tests, do not remove the code"):
    """The findings of a round whose only hold the human rejected (`settle_holds`), and the round's result."""
    from l4.verifier.verdicts import hold_id, settle_holds

    verdict = reject(hold_id(hold), reason)
    findings = settle_holds([], [hold], {hold_id(hold): verdict})
    outcome = result(Verdict.FAIL, findings)
    outcome.holds = [hold]
    return outcome, [verdict], findings


COVERAGE_HOLD = "diff coverage: changed code not run by any test: `src/greet.py::shout`, `src/greet.py::<module>`"
SCOPE_HOLD = "scope: `src/billing.py` changes module `billing`, which the spec does not name"


def test_a_rejected_coverage_hold_becomes_a_test_chore():
    outcome, human, findings = settled(COVERAGE_HOLD)
    plan = plan_fix_unit(FAMILY, outcome, human, ordinal=1, fix_minor=False)
    [group] = plan.groups
    assert group.chore and group.tests and group.ids == (findings[0].id,)
    assert "Add tests that run the changed code" in group.detail


def test_a_scope_hold_stays_a_fix_chore():
    outcome, human, _ = settled(SCOPE_HOLD, "move it to its own change")
    [group] = plan_fix_unit(FAMILY, outcome, human, ordinal=1, fix_minor=False).groups
    assert group.chore and not group.tests
    plain = plan_fix_unit(
        FAMILY, result(Verdict.FAIL, [det("An undeclared suppression")]), [], ordinal=1, fix_minor=False
    )
    assert plain.groups[0].chore and not plain.groups[0].tests
