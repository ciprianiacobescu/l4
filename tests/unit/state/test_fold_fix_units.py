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
