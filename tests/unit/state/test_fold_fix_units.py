from datetime import UTC, datetime, timedelta

from l4.clarifier.clarifier import _consumed, _drafted, _recorded
from l4.state.fold import fold
from l4.state.ledger import LedgerEvent

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
RUN = "r-20261004T1200Z-aaaa"
FIX = "p-fix-1"


def events(*rows: tuple[str, dict]) -> list[LedgerEvent]:
    return [
        LedgerEvent(T0 + timedelta(seconds=n), RUN, "openspec:p", n, kind, data) for n, (kind, data) in enumerate(rows)
    ]


def test_fix_unit_tasks_and_questions_are_not_the_parents():
    state = fold(
        events(
            ("question.raised", {"id": "Q-001"}),
            ("task.done", {"task": "1.1"}),
            ("fix.spawned", {"fix_unit": FIX, "round": 1}),
            ("question.raised", {"id": "Q-001", "fix_unit": FIX}),
            ("task.started", {"task": "1.2", "fix_unit": FIX}),
            ("task.done", {"task": "1.2", "fix_unit": FIX}),
            ("question.answered", {"id": "Q-001", "fix_unit": FIX}),
        ),
        "openspec:p",
    )
    assert state.tasks.done == ["1.1"] and state.tasks.in_progress is None
    assert state.questions.open == ["Q-001"] and state.questions.answered == [f"{FIX}/Q-001"]
    assert state.open_fix_unit == FIX and state.fix_round == 1 and state.children == [FIX]


def test_the_clarifier_ignores_the_question_events_of_a_fix_unit():
    rows = events(
        ("question.answered", {"id": "Q-001", "answer_sha256": "parent"}),
        ("question.answered", {"id": "Q-001", "answer_sha256": "fix", "fix_unit": FIX}),
        ("prompt.rendered", {"answers": [{"id": "Q-001", "answer_sha256": "fix"}], "fix_unit": FIX}),
        ("question.unsubmitted_answer", {"id": "Q-001", "answer_sha256": "fix", "fix_unit": FIX}),
    )
    assert _recorded(rows)["Q-001"]["answer_sha256"] == "parent"
    assert _consumed(rows) == {} and _drafted(rows) == {}


# --- `l4 retry` of a unit in `fixing` (L4-VER-095) ------------------------------------------------------------------


def _fixing(*more: tuple[str, dict]):
    return fold(
        events(
            ("fix.spawned", {"fix_unit": FIX, "round": 2}),
            ("question.raised", {"id": "Q-001", "fix_unit": FIX}),
            ("question.raised", {"id": "Q-001"}),
            *more,
        ),
        "openspec:p",
    )


def test_a_retry_that_names_a_fix_unit_to_close_is_pending_until_the_fix_unit_is_done():
    asked = _fixing(("unit.retried", {"reason": "env-gated", "close_fix_unit": FIX}))
    assert asked.close_fix_unit == FIX and asked.open_fix_unit == FIX
    done = _fixing(("unit.retried", {"reason": "x", "close_fix_unit": FIX}), ("fix.done", {"fix_unit": FIX}))
    assert done.close_fix_unit is None and done.open_fix_unit is None


def test_a_retry_with_no_fix_unit_to_close_records_none():
    assert _fixing(("unit.retried", {"reason": "x"})).close_fix_unit is None
    assert _fixing(("unit.resumed", {"reason": "x", "close_fix_unit": FIX})).close_fix_unit is None  # retry only


def test_a_close_that_found_a_task_to_run_is_dropped_by_the_event_that_says_so():
    state = _fixing(
        ("unit.retried", {"reason": "x", "close_fix_unit": FIX}),
        ("fix.close_skipped", {"fix_unit": FIX, "reason": "a task can run"}),
    )
    assert state.close_fix_unit is None and state.open_fix_unit == FIX


def test_a_close_that_names_another_fix_unit_is_not_taken_by_the_open_one_finishing():
    state = _fixing(("unit.retried", {"reason": "x", "close_fix_unit": "p-fix-9"}), ("fix.done", {"fix_unit": FIX}))
    assert state.close_fix_unit == "p-fix-9"


def test_question_superseded_of_a_fix_unit_takes_only_that_fix_units_question_out_of_open():
    """5.1: with `fix_unit` on the event, `question.superseded` removes `<fix unit>/Q-001`, not the parent's `Q-001`."""
    state = _fixing(("question.superseded", {"ids": ["Q-001"], "fix_unit": FIX}))
    assert state.questions.open == ["Q-001"]  # the parent's own, untouched
    without = _fixing(("question.superseded", {"ids": ["Q-001"]}))
    assert without.questions.open == [f"{FIX}/Q-001"]  # no `fix_unit` on the event: it names the parent's
