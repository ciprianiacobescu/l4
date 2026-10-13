"""Which task is next, and parent ticking (SPEC L4-IMP-001, OpenSpec grammar).

A pending task that an unanswered question lists under *Blocking tasks* is skipped for an independent one
(implementer-tdd-loop 1.11). A Kiro optional task (`[ ]*`) is neutral: `required()` leaves it out of every count
of pending work, and it is never selected. M1: `task_grouping: parent`.
"""

from collections.abc import Collection, Sequence

from l4.specs.base import Marker, SpecProvider, Task, UnitRef
from l4.specs.kiro import order_by_wave
from l4.specs.questions import QuestionsFile, blocked_tasks, holds, is_answered


def required(tasks: Sequence[Task]) -> list[Task]:
    """The tasks that count: every counter of pending work (plan, snapshot, orchestrator, step 0) goes through this."""
    return [t for t in tasks if not t.optional]


def _subtree(tasks: Sequence[Task], index: int) -> list[Task]:
    """Every descendant of the task, optional or not."""
    out = []
    for task in tasks[index + 1 :]:
        if task.depth <= tasks[index].depth:
            break
        out.append(task)
    return out


def _descendants(tasks: Sequence[Task], index: int) -> list[Task]:
    """The required descendants: the ones a parent waits for."""
    return [t for t in _subtree(tasks, index) if not t.optional]


def _closable(tasks: Sequence[Task], index: int) -> bool:
    """A parent (at least one descendant of any kind) with no open required descendant. Vacuously true when every
    descendant is optional (L4-KSP-001): such a parent is closed, never executed."""
    return bool(_subtree(tasks, index)) and all(k.done for k in _descendants(tasks, index))


def _tickable(task: Task) -> bool:
    """A box the harness can write: an empty `[ ]` (or a Kiro `[-]` / `[~]`, one byte as well) with a title. An
    OpenSpec `[-]`, a padded box or a text-less one cannot be ticked by one byte (L4-TMW-001) and is never selected."""
    pending = task.marker_char == " " or task.started
    return not task.done and pending and task.marker_offset is not None and bool(task.title)


def unselectable(tasks: Sequence[Task]) -> list[Task]:
    return [t for t in required(tasks) if not t.done and not _tickable(t)]


def _ancestors(tasks: Sequence[Task], index: int) -> list[Task]:
    out, depth = [], tasks[index].depth
    for task in reversed(tasks[:index]):
        if task.depth < depth:
            out.append(task)
            depth = task.depth
    return out


def task_scope(tasks: Sequence[Task], key: str) -> frozenset[str]:
    """The task and its ancestors: a question on a parent also holds, and so informs, its children."""
    index = next((i for i, t in enumerate(tasks) if t.key == key), None)
    if index is None:
        return frozenset({key})
    return frozenset({key, *(t.key for t in _ancestors(tasks, index))})


def _held(tasks: Sequence[Task], index: int, blocked: Collection[str]) -> bool:
    """A question on a task also holds the tasks under it."""
    return tasks[index].key in blocked or any(t.key in blocked for t in _ancestors(tasks, index))


def _leaves(tasks: Sequence[Task]) -> list[int]:
    """Indexes of the tasks that can run now: wave by wave, document order inside a wave (a unit without a wave
    graph is in document order). Only a leaf runs: a task with a descendant of any kind is a parent, and a parent is
    closed by `tick_completed_parents` once no required descendant is open."""
    ready = [t for i, t in enumerate(tasks) if not t.optional and _tickable(t) and not _subtree(tasks, i)]
    at = {t.line: i for i, t in enumerate(tasks)}
    return [at[t.line] for t in order_by_wave(ready)]


def select_next_step(tasks: Sequence[Task], blocked: Collection[str] = ()) -> Task | None:
    """The first pending required checkbox that has no pending required checkbox under it and that no question
    holds, by wave then document order (`blocked`: task keys, see `l4.specs.questions.blocked_tasks`)."""
    return next((tasks[i] for i in _leaves(tasks) if not _held(tasks, i, blocked)), None)


def questions_hold(tasks: Sequence[Task], blocked: Collection[str]) -> bool:
    """The signal "no task is eligible, questions are open": a pending leaf exists and every one is held."""
    leaves = _leaves(tasks)
    return bool(leaves) and all(_held(tasks, i, blocked) for i in leaves)


def _pending_keys(tasks: Sequence[Task]) -> list[str]:
    return [t.key for t in required(tasks) if not t.done]


def open_blocking_questions(file: QuestionsFile | None, tasks: Sequence[Task]) -> list[str]:
    """Ids of the unanswered questions that hold at least one pending task."""
    if file is None:
        return []
    held = holds(file.questions, _pending_keys(tasks), file.unreadable_ids)
    ids = [q.id for q in file.questions if q.id in held]
    return ids + [qid for qid in file.unreadable_ids if qid not in ids]


def answers_unblock(file: QuestionsFile | None, tasks: Sequence[Task]) -> list[str]:
    """Ids of the answered questions whose pending tasks are free to run, when at least one task is eligible now;
    empty otherwise. This is the "answers submitted" condition of the `awaiting_human -> implementing` row."""
    if file is None:
        return []
    pending = set(_pending_keys(tasks))
    held = blocked_tasks(file.questions, pending, file.unreadable_ids)
    ids = [q.id for q in file.questions if is_answered(q) and (pending - held) & set(q.blocking_tasks)]
    return ids if ids and select_next_step(tasks, held) is not None else []


def tick_completed_parents(provider: SpecProvider, ref: UnitRef) -> list[str]:
    """When the last child of a parent is ticked the parent is ticked too, or `remaining` never reaches 0
    (L4-IMP-001). Returns the keys ticked, innermost first."""
    ticked: list[str] = []
    while True:
        tasks = provider.tasks(ref)
        parent = next(
            (t for i, t in enumerate(tasks) if not t.optional and _tickable(t) and _closable(tasks, i)),
            None,
        )
        if parent is None:
            return ticked
        provider.set_marker(ref, parent.key, Marker.DONE)
        ticked.append(parent.key)
