"""`next_step` (L4-OPS-006, design D6): the one command or action that moves a unit, for each phase."""

import pytest

from l4.planner import UnitFacts
from l4.state.next_step import feedback_way_out, judge_view_way_out, label_for, next_step, way_out

QPATH = "openspec/changes/x/questions.md"
BRANCH = "l4/openspec/x"


def facts(phase: str | None, **over) -> UnitFacts:
    base = {"unit": "openspec:x", "framework": "openspec", "phase": phase, "tasks_done": 1, "tasks_total": 2}
    return UnitFacts(**{**base, **over})


def step(phase: str | None, **over) -> str:
    return next_step(facts(phase, **over), branch=BRANCH, questions_path=QPATH)


@pytest.mark.parametrize("phase", ["halted", "escalated"])
def test_a_stopped_unit_is_retried(phase):
    assert step(phase) == "l4 retry --unit openspec:x --reason TEXT"


def test_the_escalation_with_no_convertible_finding_names_feedback_before_the_retry():
    """SCN-OPS-38 (L4-OPS-022): a retry alone repeats the verdict."""
    got = step("escalated", halt_reason="no_convertible_finding")
    assert got.index("l4 feedback add --unit openspec:x --kind behaviour --when") < got.index(
        "l4 retry --unit openspec:x --reason TEXT"
    )
    assert "--then" in got and "--text" in got and "a retry alone repeats the same verdict" in got


def test_scn_ver_138_the_escalation_with_judge_view_rejected_names_its_own_way_out():
    """L4-VER-044: a fix unit cannot shrink the diff; split the change, or replace the answer and retry."""
    got = step("escalated", halt_reason="judge_view_rejected")
    assert got == judge_view_way_out("openspec:x")
    assert "l4 restart --unit openspec:x" in got and "--replace" in got and "l4 retry --unit openspec:x" in got
    assert "l4 feedback add" not in got and "a retry alone repeats" not in got
    assert got.index("l4 restart --unit") < got.index("l4 retry --unit")


def test_way_out_is_the_units_own_step_for_two_reasons_and_nothing_for_the_others():
    assert way_out("openspec:x", "no_convertible_finding") == feedback_way_out("openspec:x")
    assert way_out("openspec:x", "judge_view_rejected") == judge_view_way_out("openspec:x")
    assert way_out("openspec:x", "fix_rounds_exhausted") is None and way_out("openspec:x", None) is None


@pytest.mark.parametrize(
    ("phase", "code"),
    [
        ("escalated", "fix_rounds_exhausted"),
        ("escalated", "same_failure"),
        ("escalated", None),
        ("halted", "no_convertible_finding"),
    ],
)
def test_other_causes_keep_the_plain_retry(phase, code):
    """SCN-OPS-39 (L4-OPS-022)."""
    assert step(phase, halt_reason=code) == "l4 retry --unit openspec:x --reason TEXT"


def test_an_abandoned_unit_is_restarted():
    assert step("abandoned") == "l4 restart --unit openspec:x --reason TEXT"


def test_awaiting_human_names_the_questions_the_file_and_the_branch():
    got = step("awaiting_human", open_blocking_questions=("Q-001", "Q-002"), verdicts_open=("V-1",))
    assert got == f"answer Q-001, Q-002, V-1 in {QPATH} on {BRANCH} (Status answered), then push"


def test_a_dismissed_verdict_question_is_named():
    got = step("awaiting_human", verdicts_open=("Q-001",), verdicts_dismissed=("Q-001",))
    assert "Q-001" in got and "dismissed" in got and "accept or reject" in got and QPATH in got


def test_an_invalid_verdict_answer_is_named():
    got = step("awaiting_human", verdicts_invalid=("Q-004",))
    assert "Q-004" in got and "accept or reject" in got and BRANCH in got


def test_a_draft_answer_is_named():
    got = step("awaiting_human", open_blocking_questions=("Q-001",), drafts=("Q-001",))
    assert "Q-001" in got and "Status" in got


def test_answers_already_submitted_need_only_a_run():
    assert step("awaiting_human", answers_unblock=("Q-001",)) == "nothing: the harness continues at the next run"


def test_waiting_capacity_names_the_time_and_the_override():
    got = step("waiting_capacity", retry_after="2026-10-14T10:00:00+00:00")
    assert got == "wait until 2026-10-14T10:00:00+00:00, or l4 retry --unit openspec:x --reason TEXT"


def test_in_review_names_the_pr_and_the_feedback_command():
    assert step("in_review") == "review and merge the PR, or ask for changes with l4 feedback add"


def test_a_corrupt_ledger_points_to_the_runbook():
    assert step("corrupt", corrupt="r.jsonl:2 bad") == "see docs/runbook.md section 7.9"


def test_the_label_that_does_the_same_is_named_for_stopped_and_abandoned_units():
    assert label_for(facts("halted"), "l4:") == "l4:retry"
    assert label_for(facts("escalated"), "x-") == "x-retry"
    assert label_for(facts("abandoned"), "l4:") == "l4:restart"
    assert label_for(facts("in_review"), "l4:") is None


def test_a_merged_unit_needs_nothing():
    assert step("merged") == "nothing"


def test_a_merged_unit_with_waiting_feedback_names_the_follow_up():
    got = step("merged", follow_up_items=("F-1",))
    assert "F-1" in got and "follow-up unit" in got
    assert "open follow-up" in step("merged", follow_up_items=("F-1",), follow_up_open="x-2")


@pytest.mark.parametrize("phase", [None, "intake", "implementing", "verifying", "fixing", "verified", "rejected"])
def test_every_other_phase_continues_by_itself(phase):
    assert step(phase) == "nothing: the harness continues at the next run"
