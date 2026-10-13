import pytest

from l4.planner import UnitFacts, compute_plan, next_action
from l4.state.lifecycle import Phase


def facts(
    phase: str | None, done: int = 0, total: int = 2, unit: str = "openspec:x", *, answers: tuple[str, ...] = (),
    open_questions: tuple[str, ...] = (),
) -> UnitFacts:  # fmt: skip
    return UnitFacts(
        unit=unit, framework="openspec", phase=phase, tasks_done=done, tasks_total=total, answers_unblock=answers,
        open_blocking_questions=open_questions,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("phase", "done", "total", "action", "reason_part"),
    [
        (None, 0, 2, "implement", "pending tasks"),
        (None, 1, 2, "implement", "pending tasks"),
        (None, 2, 2, "verify", "no verification"),
        (None, 0, 0, "none", "no tasks"),
        ("intake", 0, 2, "implement", "intake"),
        ("ready", 0, 2, "implement", "ready"),
        ("implementing", 1, 2, "implement", "implementing"),
        ("implemented", 2, 2, "verify", "implemented"),
        ("verifying", 2, 2, "verify", "verifying"),
        ("verified", 2, 2, "hand_off", "verified"),
        ("awaiting_human", 1, 2, "none", "awaiting_human: no new answers"),
        ("clarifying", 1, 2, "clarify", "clarifying"),
        ("fixing", 2, 2, "none", "fixing"),
        ("waiting_capacity", 1, 2, "none", "waiting_capacity"),
        ("halted", 1, 2, "none", "halted: a member adds the label l4:resume"),
        ("escalated", 2, 2, "none", "escalated: needs l4 resume"),
        ("rejected", 0, 2, "none", "rejected: inputs unchanged"),
        ("in_review", 2, 2, "none", "in_review: waiting for merge"),
        ("archived", 2, 2, "none", "archived"),
        ("merged", 2, 2, "none", "merged"),
        ("abandoned", 1, 2, "none", "abandoned"),
        ("from_the_future", 1, 2, "none", "unknown phase from_the_future"),
    ],
)
def test_every_lifecycle_phase_maps_to_expected_action_and_reason(phase, done, total, action, reason_part):
    got_action, reason = next_action(facts(phase, done, total))
    assert got_action == action and reason_part in reason


def test_the_halted_reason_names_the_label():
    action, reason = next_action(facts("halted", 1, 2))
    assert action == "none"
    assert reason == "halted: a member adds the label l4:resume (or runs l4 resume)"


def test_awaiting_human_with_submitted_answers_implements_and_names_them():
    assert next_action(facts("awaiting_human", answers=("Q-001", "Q-003"))) == (
        "implement", "answers submitted: Q-001, Q-003"
    )  # fmt: skip


def test_awaiting_human_without_answers_stays_none_and_names_the_open_questions():
    action, reason = next_action(facts("awaiting_human", open_questions=("Q-001",)))
    assert action == "none" and reason == "awaiting_human: no new answers (open: Q-001)"
    assert next_action(facts("awaiting_human")) == ("none", "awaiting_human: no new answers")


@pytest.mark.parametrize("phase", ["in_review", "halted", "verified", "implementing", "clarifying"])
def test_answers_only_matter_in_awaiting_human(phase):
    assert next_action(facts(phase, answers=("Q-001",))) == next_action(facts(phase))


def test_every_phase_of_the_lifecycle_is_covered():
    covered = {"intake", "ready", "implementing", "implemented", "verifying", "verified", "awaiting_human",
               "clarifying", "fixing", "waiting_capacity", "halted", "escalated", "rejected", "in_review",
               "archived", "merged", "abandoned"}  # fmt: skip
    assert covered == {p.value for p in Phase}


def test_plan_is_sorted_by_unit_and_actionable_follows_the_action():
    entries = compute_plan(
        [facts("verified", unit="openspec:b"), facts("halted", unit="openspec:a"), facts(None, unit="openspec:c")]
    )
    assert [(e.unit, e.next_action, e.actionable) for e in entries] == [
        ("openspec:a", "none", False), ("openspec:b", "hand_off", True), ("openspec:c", "implement", True)
    ]  # fmt: skip


def test_an_awaiting_unit_names_the_drafts_and_the_unreadable_questions():
    base = facts("awaiting_human", open_questions=("Q-002",))
    action, reason = next_action(
        UnitFacts(**{**base.__dict__, "drafts": ("Q-001",), "unreadable": ("Q-003",)})  # type: ignore[arg-type]
    )
    assert action == "none"
    assert "(open: Q-002)" in reason and "Status is still open: Q-001" in reason and "all tasks held: Q-003" in reason


def test_a_legacy_needs_human_round_is_offered_as_verify_so_the_run_can_raise_its_questions():
    legacy = UnitFacts(
        unit="openspec:x", framework="openspec", phase="awaiting_human", tasks_done=2, tasks_total=2, legacy_round=1
    )
    action, reason = next_action(legacy)
    assert action == "verify" and reason.startswith("legacy round 1: NEEDS_HUMAN without verdict questions")
    waiting = UnitFacts(
        unit="openspec:x", framework="openspec", phase="awaiting_human", tasks_done=2, tasks_total=2,
        verdicts_open=("Q-002",),
    )  # fmt: skip
    assert next_action(waiting)[0] == "none"


@pytest.mark.parametrize("phase", ["halted", "escalated"])
def test_a_stopped_unit_shows_the_recorded_cause(phase):
    """L4-OPS-006: the recorded detail replaces the fixed text; without one the fixed text stays."""
    detail = "task 1.1: max_task_attempts (3) reached in red"
    base = facts(phase, 1, 2)
    got = next_action(UnitFacts(**{**base.__dict__, "halt_detail": detail}))
    assert got == ("none", f"{phase}: {detail}")
    assert next_action(base)[1] != f"{phase}: {detail}" and next_action(base)[1].startswith(f"{phase}: ")
