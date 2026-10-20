"""A replay stopped at the soft deadline is replayed again (L4-IMP-069, SCN-IMP-364): a `held.replayed` that a stop of
the same task and phase follows, with no commit of the task between them, does not count as a replay."""

from datetime import UTC, datetime

import pytest

from l4.deadline import DeadlineReached
from l4.implementer.held_patch import USED_UP_NOTICE, accepted_tests_block, replay_voided
from l4.implementer.loop import run_task
from l4.state.ledger import LedgerEvent

from .test_earlier_red import TASK
from .test_held_accept import held_new
from .test_held_answers import answer

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def event(seq: int, type_: str, **data) -> LedgerEvent:
    return LedgerEvent(NOW, "r-20260101T0000Z-aaaa", "openspec:u", seq, type_, data)


REPLAYED = event(1, "held.replayed", question="Q-001", task="1.1", phase="red")
STOP = event(2, "deadline.reached", when="during", during="gate", task="1.1", phase="red")


def test_a_replay_stopped_in_its_gate_is_replayed_again(make_bench, monkeypatch, raw, armed_deadline):
    """SCN-IMP-364: the accept holds; the next run replays the same patch, with no agent request."""
    bench = held_new(make_bench, monkeypatch)
    answer(bench, raw, "accept: the version pin cannot be shown to discriminate")
    dl = armed_deadline()
    real_emit = bench.wb.emit

    def emit(event_type, /, **data):
        real_emit(event_type, **data)
        if event_type == "held.replayed":
            dl.fire()  # the deadline reaches the replay's test gate

    monkeypatch.setattr(bench.wb, "emit", emit)
    with pytest.raises(DeadlineReached) as caught:
        run_task(bench.wb, TASK)
    assert caught.value.during == "gate" and len(bench.events("held.replayed")) == 1
    # the hand-back records the stop, commits the ledger only, and the next run builds its worktree again
    bench.wb.emit("deadline.reached", when="during", during="gate", task="1.1", phase="red", first=True)
    bench.wb.discard_changes()
    bench.wb.held_removals.clear()
    monkeypatch.undo()
    from l4 import deadline

    deadline.disarm()
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert len(bench.adapter.requests) == 1  # no agent ran, in either run
    assert len(bench.events("held.replayed")) == 2
    assert bench.events("task.red_ok") and bench.events("task.red_committed")


def test_a_replay_followed_by_a_commit_is_spent():
    events = [REPLAYED, event(2, "task.green_committed", task="1.1"), event(3, "task.done", task="1.1")]
    stop = event(4, "deadline.reached", when="during", during="agent", task="1.1", phase="red")
    assert not replay_voided([*events, stop], REPLAYED)


def test_replay_voided_reads_the_task_and_phase():
    assert replay_voided([REPLAYED, STOP], REPLAYED)
    other_task = event(2, "deadline.reached", when="during", during="gate", task="1.2", phase="red")
    other_phase = event(2, "deadline.reached", when="during", during="gate", task="1.1", phase="green")
    not_a_stop = event(2, "deadline.reached", when="before", task="1.1", phase="red")
    assert not replay_voided([REPLAYED, other_task], REPLAYED)
    assert not replay_voided([REPLAYED, other_phase], REPLAYED)
    assert not replay_voided([REPLAYED, not_a_stop], REPLAYED)  # a step that was not started ran nothing
    before = event(0, "deadline.reached", when="during", during="gate", task="1.1", phase="red")
    assert not replay_voided([before, REPLAYED], REPLAYED)  # a stop before the replay says nothing about it
    other_commit = event(2, "task.done", task="1.2")  # another task's commit does not spend this replay
    assert replay_voided([REPLAYED, other_commit, event(3, "deadline.reached", **STOP.data)], REPLAYED)


def test_the_used_up_notice_ignores_a_void_replay(make_bench, monkeypatch, raw):
    bench = held_new(make_bench, monkeypatch)
    answer(bench, raw, "accept: fine")
    bench.wb.emit("held.replayed", question="Q-001", task="1.1", check="pre_satisfied", phase="red", tests=[])

    def text() -> str:
        return "".join(body for _, body in accepted_tests_block(bench.wb, "red", TASK))

    assert USED_UP_NOTICE in text()  # a spent replay: the accept covers nothing now
    bench.wb.emit("deadline.reached", when="during", during="gate", task="1.1", phase="red", first=True)
    assert USED_UP_NOTICE not in text()  # the replay was stopped before it committed: it is still to be replayed
