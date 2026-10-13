"""The folds of the operator commands (L4-OPS-001, L4-OPS-004, L4-OPS-005): the cause of a stop (`halt_detail`),
`unit.retried` (folds like `unit.resumed`) and `unit.restarted` (a new start of the unit)."""

from datetime import UTC, datetime, timedelta

from l4.state.fold import fold
from l4.state.ledger import LedgerEvent

T0 = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)
RUN = "r-20261013T0900Z-aaaa"


def events(*rows: tuple[str, dict]) -> list[LedgerEvent]:
    return [LedgerEvent(T0 + timedelta(seconds=n), RUN, "openspec:x", n + 1, t, d) for n, (t, d) in enumerate(rows)]


def changed(src: str | None, to: str, trigger: str, **data: object) -> tuple[str, dict]:
    return "phase.changed", {"from": src, "to": to, "trigger": trigger, **data}


TO_IMPLEMENTING = [
    ("run.started", {}),
    changed(None, "intake", "unit_discovered_pending"),
    changed("intake", "ready", "intake_all_pass"),
    changed("ready", "implementing", "lease_acquired"),
]


def test_a_stop_keeps_its_code_and_its_detail():
    state = fold(
        events(
            *TO_IMPLEMENTING,
            changed(
                "implementing", "halted", "breaker_or_budget", reason="max_task_attempts", detail="task 1.1 failed"
            ),
        ),
        "openspec:x",
    )
    assert (state.halt_reason, state.halt_detail) == ("max_task_attempts", "task 1.1 failed")


def test_an_old_ledger_without_detail_folds_the_reason_text_as_the_detail():
    state = fold(
        events(*TO_IMPLEMENTING, changed("implementing", "halted", "breaker_or_budget", reason="task 1.1 failed")),
        "openspec:x",
    )
    assert (state.halt_reason, state.halt_detail) == ("task 1.1 failed", "task 1.1 failed")


def test_a_stop_without_any_text_has_no_detail_and_a_resume_clears_both():
    stopped = [*TO_IMPLEMENTING, changed("implementing", "halted", "breaker_or_budget")]
    assert fold(events(*stopped), "openspec:x").halt_detail is None
    with_reason = [*TO_IMPLEMENTING, changed("implementing", "halted", "breaker_or_budget", reason="r", detail="d")]
    resumed = fold(
        events(*with_reason, ("unit.resumed", {"reason": "go"}), changed("halted", "implementing", "resumed")),
        "openspec:x",
    )
    assert (resumed.phase, resumed.halt_reason, resumed.halt_detail) == ("implementing", None, None)


def test_unit_retried_folds_like_unit_resumed():
    base = [
        *TO_IMPLEMENTING,
        ("breaker.tripped", {"reason": "x"}),
        changed("implementing", "halted", "breaker_or_budget", reason="r", detail="d"),
    ]
    tripped = fold(events(*base), "openspec:x")
    assert tripped.breaker_trips == 1
    retried = fold(
        events(
            *base,
            ("unit.retried", {"reason": "again", "by": "member", "signal": "label:7"}),
            changed("halted", "implementing", "resumed"),
        ),
        "openspec:x",
    )
    assert retried.breaker_trips == 0 and retried.resumed_signals == ["label:7"]
    assert retried.phase == "implementing" and retried.previous_phase is None


def test_unit_restarted_is_a_new_start_of_the_unit():
    old = [
        *TO_IMPLEMENTING,
        ("task.done", {"task": "1.1"}),
        ("fix.spawned", {"fix_unit": "x-fix-1", "round": 1}),
        ("budget.extended", {"fix_rounds": 2}),
        ("breaker.tripped", {"reason": "x"}),
        ("pr.updated", {"url": "https://forge.invalid/mr/1"}),
        ("question.raised", {"id": "Q-001"}),
        changed("implementing", "escalated", "verify_fail_exhausted", reason="same_failure", detail="d"),
    ]
    before = fold(events(*old), "openspec:x")
    assert before.fix_round == 1 and before.fix_rounds_extra == 2 and before.restarts == 0
    after = fold(
        events(*old, ("unit.restarted", {"attempt": 1, "previous_head": "abc", "reason": "redo", "signal": "label:9"})),
        "openspec:x",
    )
    assert after.phase is None and after.previous_phase is None and after.halt_reason is None
    assert after.halt_detail is None and after.pr is None
    assert after.tasks.done == [] and after.children == [] and after.questions.open == []
    assert (after.fix_round, after.fix_rounds_extra, after.fix_rounds_counted, after.breaker_trips) == (0, 0, 0, 0)
    assert after.restarts == 1 and after.resumed_signals == ["label:9"]  # a label event acts once, also a restart
    assert after.iteration == before.iteration  # the run count only grows


def test_events_after_a_restart_build_on_the_new_start_and_restarts_are_counted():
    rows = [
        *TO_IMPLEMENTING,
        ("unit.restarted", {"attempt": 1}),
        changed(None, "intake", "unit_discovered_pending"),
        ("unit.restarted", {"attempt": 2}),
        ("task.done", {"task": "1.1"}),
    ]
    state = fold(events(*rows), "openspec:x")
    assert (state.phase, state.restarts, state.tasks.done) == (None, 2, ["1.1"])


def test_reopened_tasks_are_no_longer_done():
    """L4-OPS-015: `tasks.reopened{tasks, requirements}` takes the tasks out of the folded done list."""
    state = fold(
        events(
            *TO_IMPLEMENTING,
            ("task.done", {"task": "1.1"}),
            ("task.done", {"task": "2.1"}),
            ("tasks.reopened", {"tasks": ["2.1", "2"], "requirements": ["2.3"]}),
            ("tasks.reopened", {"tasks": "bad"}),
        ),
        "openspec:x",
    )
    assert state.tasks.done == ["1.1"]


SEEN = ("spec.edit_seen", {"head": "b" * 40, "base": "a" * 40, "commits": ["c" * 40, "b" * 40]})


def test_a_spec_edit_seen_while_fixing_is_pending_until_its_head_is_retried():
    """L4-OPS-014: `spec.edit_seen{head, base, commits}` stays pending; only `unit.retried` with signal
    `spec_edit:<that head>` takes it, and another head's signal does not."""
    rows = [*TO_IMPLEMENTING, changed("implementing", "fixing", "verify_fail_fix"), SEEN]
    state = fold(events(*rows), "openspec:x")
    pending = state.pending_spec_edit
    assert pending is not None and (pending.head, pending.base) == ("b" * 40, "a" * 40)
    assert pending.commits == ["c" * 40, "b" * 40]
    other = fold(events(*rows, ("unit.retried", {"signal": f"spec_edit:{'d' * 40}", "by": "push"})), "openspec:x")
    assert other.pending_spec_edit is not None
    taken = fold(events(*rows, ("unit.retried", {"signal": f"spec_edit:{'b' * 40}", "by": "push"})), "openspec:x")
    assert taken.pending_spec_edit is None


def test_a_spec_edit_seen_twice_or_after_its_retry_is_ignored_and_a_bad_row_too():
    """Each head is recorded once: a head whose signal is consumed is not pending again."""
    retry = ("unit.retried", {"signal": f"spec_edit:{'b' * 40}", "by": "push"})
    state = fold(events(*TO_IMPLEMENTING, retry, SEEN), "openspec:x")
    assert state.pending_spec_edit is None
    state = fold(
        events(*TO_IMPLEMENTING, ("spec.edit_seen", {"head": "", "base": 1}), ("spec.edit_seen", {})), "openspec:x"
    )
    assert state.pending_spec_edit is None


def test_a_restart_forgets_a_pending_spec_edit():
    state = fold(events(*TO_IMPLEMENTING, SEEN, ("unit.restarted", {"attempt": 2})), "openspec:x")
    assert state.pending_spec_edit is None
