"""human-feedback 2.3 (L4-FBK-005; SCN-FBK-13, SCN-FBK-14): the fix planner turns feedback findings into one task per
item, by kind, and never drops one for lacking a criterion. Items past `MAX_FIX_TASKS` wait for the next round."""

from l4.specs.base import Criterion, Framework
from l4.verifier.fixunit import MAX_FIX_TASKS, plan_fix_unit, redact_plan
from l4.verifier.types import FeedbackRef, Finding, Severity, Verdict, VerifyResult

BY = "Ana, 2026-10-12T15:04:00Z"


def criterion(cid: str, capability: str = "stock") -> Criterion:
    return Criterion(
        cid, f"{capability} > Reorder > Rounds", Framework.OPENSPEC, capability, "Reorder", "Rounds", "WHEN x THEN y",
        f"specs/{capability}/spec.md", 1,
    )  # fmt: skip


FAMILY = [criterion("C-00000001"), criterion("C-00000002", "alpha")]


def feedback(fid: str, kind: str, **kw) -> Finding:
    ref = FeedbackRef(
        fid, kind, kw.pop("title", f"Title of {fid}"), kw.pop("text", f"Please do {fid}."), BY,
        kw.pop("places", ("src/inventory/reorder.py:7-9",)), kw.pop("env", None), kw.pop("when", None),
        kw.pop("then", None), kw.pop("code", "packs = ceil(x)"), "a" * 64,
    )  # fmt: skip
    return Finding(
        Severity.MAJOR, f"Feedback {fid} ({kind}): {ref.title}", ref.text[:1200], "feedback", feedback=ref
    )  # fmt: skip


def plan(*findings: Finding, ordinal: int = 1):
    r = VerifyResult("openspec:add-reorder", 1, Verdict.FAIL, "b", "h")
    r.findings = list(findings)
    return plan_fix_unit(FAMILY, r, [], ordinal=ordinal, fix_minor=False)


def test_a_refactor_is_a_chore_that_keeps_the_tests_and_the_request_comes_first():
    """SCN-FBK-11 (planner side): marker `refactors` is fed by `refactor`; no scenario, no delta."""
    f = feedback("FB-001", "refactor", text="Move the rounding\ninto a helper.")
    result = plan(f)
    [group] = result.groups
    assert (group.chore, group.refactor, group.tests, group.criteria) == (True, True, False, ())
    assert group.ids == (f.id,) and group.item == "FB-001" and result.delta is None
    assert group.request == (
        f"Requested by {BY} in FB-001 (refactor, src/inventory/reorder.py:7-9): Move the rounding into a helper."
    )  # fmt: skip
    assert group.code == "packs = ceil(x)"
    assert [r.id for r in result.taken] == ["FB-001"] and result.waiting == []


def test_a_duplication_is_a_refactor_chore_too():
    [group] = plan(feedback("FB-002", "duplication", places=("a.py:1", "b.py:3-5"))).groups
    assert (group.chore, group.refactor, group.tests) == (True, True, False)
    assert "in FB-002 (duplication, a.py:1, b.py:3-5): " in group.request


def test_a_tests_item_is_the_test_chore():
    [group] = plan(feedback("FB-003", "tests", places=())).groups
    assert (group.chore, group.tests, group.refactor) == (True, True, False)
    assert "in FB-003 (tests): " in group.request


def test_a_config_item_gets_the_two_built_scenarios_in_an_added_requirement():
    """SCN-FBK-13: D4, scenario 1 names the value written at the first place."""
    f = feedback("FB-004", "config", title="Pack rounding from the environment", env="PACK_ROUNDING")
    result = plan(f)
    [group] = result.groups
    assert (group.chore, group.refactor, group.tests) == (False, False, False)
    assert result.delta is not None
    [req] = result.delta.requirements
    assert (req.capability, req.title) == ("alpha", "Pack rounding from the environment \N{EM DASH} feedback FB-004")
    set_, unset = req.scenarios
    assert set_.text == (
        "- **WHEN** the environment variable PACK_ROUNDING is set\n"
        "- **THEN** the system SHALL use its value instead of the value written at src/inventory/reorder.py:7-9"
    )  # fmt: skip
    assert unset.text == (
        "- **WHEN** PACK_ROUNDING is not set\n- **THEN** the system SHALL CONTINUE TO behave as before this change"
    )  # fmt: skip
    assert {set_.finding, unset.finding} == {f.id} and set_.name != unset.name


def test_a_config_items_own_when_then_replace_the_first_scenario():
    f = feedback("FB-005", "config", env="PACK_ROUNDING", when="PACK_ROUNDING is `down`", then="packs round down")
    result = plan(f)
    assert result.delta is not None
    first, second = result.delta.requirements[0].scenarios
    assert first.text == "- **WHEN** PACK_ROUNDING is `down`\n- **THEN** packs round down"
    assert second.text.startswith("- **WHEN** PACK_ROUNDING is not set")


def test_a_behaviour_item_has_its_when_then_as_the_only_scenario_and_is_never_a_chore():
    """SCN-FBK-14: red/green against the person's criterion."""
    f = feedback("FB-006", "behaviour", places=(), when="the stock is 0", then="reorder_quantity returns 0")
    result = plan(f)
    [group] = result.groups
    assert not group.chore and group.item == "FB-006"
    assert result.delta is not None
    [scenario] = result.delta.requirements[0].scenarios
    assert scenario.text == "- **WHEN** the stock is 0\n- **THEN** reorder_quantity returns 0"
    assert scenario.finding == f.id


def test_feedback_is_never_dropped_for_lacking_a_criterion():
    result = plan(feedback("FB-001", "refactor"), feedback("FB-002", "tests"))
    assert len(result.groups) == 2 and result.not_converted == []


def test_each_item_has_its_own_task_even_on_the_same_place():
    result = plan(feedback("FB-001", "refactor"), feedback("FB-002", "refactor"))
    assert [g.item for g in result.groups] == ["FB-001", "FB-002"]


def test_the_request_is_kept_whole_up_to_1200_characters():
    text = "x" * 1190 + " end"
    [group] = plan(feedback("FB-001", "refactor", text=text)).groups
    assert group.request.endswith(": " + text) and len(text) == 1194
    [cut] = plan(feedback("FB-001", "refactor", text="y" * 1500)).groups
    assert cut.request.endswith("y" * 1197 + "...")


def test_items_past_the_cap_wait_and_are_not_taken_or_not_converted():
    """L4-FBK-005: they stay takeable; `feedback.waiting{reason: fix_unit_full}` is the caller's."""
    items = [feedback(f"FB-{n:03d}", "refactor") for n in range(1, 8)]
    result = plan(*items)
    assert len(result.groups) == MAX_FIX_TASKS
    assert [r.id for r in result.taken] == [f"FB-{n:03d}" for n in range(1, 6)]
    assert result.waiting == ["FB-006", "FB-007"] and result.not_converted == []


def test_the_cap_counts_every_task_not_only_feedback():
    det = [Finding(Severity.MAJOR, f"Other {n}", "d", "deterministic") for n in range(4)]
    result = plan(*det, feedback("FB-001", "refactor"), feedback("FB-002", "refactor"))
    assert [g.item for g in result.groups] == ["", "", "", "", "FB-001"]
    assert result.waiting == ["FB-002"]


def test_feedback_only_is_true_when_every_task_is_feedback():
    assert plan(feedback("FB-001", "refactor")).feedback_only
    mixed = plan(feedback("FB-001", "refactor"), Finding(Severity.MAJOR, "Other", "d", "deterministic"))
    assert not mixed.feedback_only and [r.id for r in mixed.taken] == ["FB-001"]


def test_redaction_reaches_the_request_and_the_code():
    result = redact_plan(
        plan(feedback("FB-001", "refactor", code="token = 'SECRET'")), lambda t: t.replace("SECRET", "X")
    )
    assert result.groups[0].code == "token = 'X'"
    leaked = redact_plan(plan(feedback("FB-001", "refactor", text="use SECRET")), lambda t: t.replace("SECRET", "X"))
    assert leaked.groups[0].request.endswith("use X")
