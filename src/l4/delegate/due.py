"""Which questions the delegate has still to decide, and for which units the planner names the action `delegate`
(delegate-answers 9.3; L4-DLG-003, design D6).

A question is *due* when it is open, of a kind `delegate.kinds` names, holds a pending task (a verdict question: is
still to be consumed), and has no final delegate record (`answered`, `escalated`, `discarded`) for its current raise.
A deferral with a `retry_after` keeps it due, with that time, so that the planner names the action only once the time
has passed. The pass (`l4.delegate.run`) and the planner read the very same rule here."""

import dataclasses
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime

from l4.config.schema import DelegateCfg
from l4.delegate.scope import PlansView, in_scope
from l4.implementer.tasks import open_blocking_questions
from l4.specs.base import Task
from l4.specs.questions import Question, QuestionsFile, QuestionStatus
from l4.state.fold import question_key
from l4.state.ledger import LedgerEvent
from l4.state.status import UnitSnapshot
from l4.verifier.verdicts import verdict_status

FINAL = ("answered", "escalated", "discarded")  # a `delegate.result` that ends a question's current raise
WAITING_PHASES = ("awaiting_human", "fixing")
Due = tuple[str, str | None]  # (question key, the time it may be asked again, or None)


def since_raise(events: Sequence[LedgerEvent], key: str) -> list[LedgerEvent]:
    """The events after the latest `question.raised` of `key` (`Q-003`, or `<fix unit>/Q-003`)."""
    last = max((i for i, e in enumerate(events) if e.type == "question.raised" and question_key(e) == key), default=-1)
    return list(events[last + 1 :])


def results_of(events: Sequence[LedgerEvent], key: str) -> list[LedgerEvent]:
    return [e for e in since_raise(events, key) if e.type == "delegate.result" and e.data.get("question") == key]


def is_final(events: Sequence[LedgerEvent], key: str) -> bool:
    return any(e.data.get("status") in FINAL for e in results_of(events, key))


def retry_after(events: Sequence[LedgerEvent], key: str) -> str | None:
    """The `retry_after` of the question's latest deferral, when that deferral is its latest record."""
    results = results_of(events, key)
    if results and results[-1].data.get("status") == "deferred":
        value = results[-1].data.get("retry_after")
        return value if isinstance(value, str) and value else None
    return None


def parse_time(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def deferred_now(events: Sequence[LedgerEvent], key: str, now: datetime) -> bool:
    due = parse_time(retry_after(events, key))
    return due is not None and due > now


def held_ids(
    file: QuestionsFile | None, tasks: Sequence[Task], consumed: Collection[str], *, verdicts: bool
) -> set[str]:
    """The questions that hold a pending task, and (for the unit itself) the verdict questions still to be consumed."""
    if file is None:
        return set()
    held = set(open_blocking_questions(file, tasks))
    return held | set(verdict_status(file, consumed).open) if verdicts else held


def open_questions(file: QuestionsFile | None, held: Collection[str], cfg: DelegateCfg) -> list[Question]:
    """The open questions of `file` in `held` of the kinds the delegate answers, oldest first."""
    if file is None:
        return []
    kinds = set(cfg.kinds)
    found = [
        q for q in file.questions if q.status is QuestionStatus.OPEN and q.kind is not None
        and q.kind.value in kinds and q.id in held
    ]  # fmt: skip
    return sorted(found, key=lambda q: int(q.id.rpartition("-")[2] or 0))


def due_questions(snapshot: UnitSnapshot, cfg: DelegateCfg) -> tuple[Due, ...]:
    """The questions of the unit (and, while it is `fixing`, of its open fix unit) that the delegate has still to
    decide, with the time each may be asked again. Pure over the snapshot; the scope is the caller's."""
    state = snapshot.state
    if (state.phase or "") not in WAITING_PHASES:
        return ()
    events = snapshot.events
    out: list[Due] = []
    held = held_ids(snapshot.questions, snapshot.tasks, state.verdicts_consumed, verdicts=True)
    for q in open_questions(snapshot.questions, held, cfg):
        if not is_final(events, q.id):
            out.append((q.id, retry_after(events, q.id)))
    if state.phase == "fixing" and state.open_fix_unit:
        child = next((c for c in snapshot.children if c.name == state.open_fix_unit), None)
        if child is not None:
            held = held_ids(child.questions, child.tasks, (), verdicts=False)
            for q in open_questions(child.questions, held, cfg):
                key = f"{child.name}/{q.id}"
                if not is_final(events, key):
                    out.append((key, retry_after(events, key)))
    return tuple(out)


def stamp_due(rows: Sequence[UnitSnapshot], cfg: DelegateCfg, plans: Callable[[], PlansView]) -> list[UnitSnapshot]:
    """Each snapshot of a unit in scope, with `delegate_due` set. `plans` is read only when the delegate is on and some
    unit waits; a delegate that is off changes nothing."""
    if not cfg.enabled:
        return list(rows)
    view: PlansView | None = None
    stamped = []
    for snap in rows:
        if (snap.state.phase or "") in WAITING_PHASES and (due := due_questions(snap, cfg)):
            view = view or plans()
            if in_scope(snap.ref.id, view, cfg, phase=snap.state.phase, fix_of=snap.fix_of):
                snap = dataclasses.replace(snap, delegate_due=due)
        stamped.append(snap)
    return stamped


def due_by_unit(rows: Sequence[UnitSnapshot]) -> Mapping[str, tuple[Due, ...]]:
    return {s.ref.id: s.delegate_due for s in rows if s.delegate_due}
