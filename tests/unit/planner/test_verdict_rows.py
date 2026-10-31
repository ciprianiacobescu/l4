"""The `awaiting_human` rows for verdict questions (simulation-harness 1.13 delta)."""

import pytest

from l4.planner import UnitFacts, next_action


def facts(**over) -> UnitFacts:
    base = {"unit": "openspec:x", "framework": "openspec", "phase": "awaiting_human", "tasks_done": 2, "tasks_total": 2}
    return UnitFacts(**{**base, **over})


@pytest.mark.parametrize(
    ("over", "action", "reason"),
    [
        ({"verdicts_ready": ("Q-001", "Q-002")}, "verify", "verdicts answered: Q-001, Q-002"),
        ({"verdicts_ready": ("Q-001",), "verdicts_open": ("Q-002",)}, "none", "verdicts open: Q-002"),
        ({"verdicts_open": ("Q-001",)}, "none", "verdicts open: Q-001"),
        ({"verdicts_invalid": ("Q-001",)}, "none", "must start with accept or reject: Q-001"),
        (
            {"verdicts_open": ("Q-001",), "verdicts_dismissed": ("Q-001",)},
            "none",
            "Q-001: a verdict question cannot be dismissed: start the answer with accept or reject",
        ),
        ({"verdicts_ready": ("Q-001",), "verdicts_invalid": ("Q-002",)}, "none", "Q-002"),
        ({}, "none", "awaiting_human: no new answers"),  # no verdict facts: the M1.1 reason, unchanged
    ],
)
def test_verdict_answers_decide_the_next_action(over, action, reason):
    got_action, got_reason = next_action(facts(**over))
    assert got_action == action and reason in got_reason


def test_verdict_answers_win_over_an_answer_that_frees_a_task():
    got = next_action(facts(verdicts_ready=("Q-003",), answers_unblock=("Q-001",)))
    assert got[0] == "verify"


def test_verdict_facts_play_no_part_outside_awaiting_human():
    assert next_action(facts(phase="verified", verdicts_ready=("Q-001",)))[0] == "hand_off"


def test_a_legacy_round_of_stale_verdict_questions_says_so():  # L4-VER-070
    action, reason = next_action(facts(legacy_round=2, verdicts_stale=("Q-001", "Q-003")))
    assert action == "verify"
    assert reason.startswith("legacy round 2: NEEDS_HUMAN, and its verdict questions were raised by an earlier attempt")
    assert "Q-001, Q-003" in reason and "without verdict questions" not in reason
    action, reason = next_action(facts(legacy_round=2))  # none was ever raised: the wording of L4-VER-013, unchanged
    assert action == "verify" and "NEEDS_HUMAN without verdict questions, the run raises them" in reason
