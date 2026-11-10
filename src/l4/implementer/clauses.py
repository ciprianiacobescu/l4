"""The clauses a step leaves unasserted (SPEC L4-IMP-095): which entries of its `unasserted` list are new, which an
answered question of the task already settled, and the `ambiguous` question that a new one becomes."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from l4.implementer.result import ResultQuestion, Unasserted
from l4.implementer.workbench import Workbench
from l4.specs.base import Criterion, Task
from l4.specs.questions import QUESTIONS_FILENAME, QuestionsFile, is_answered


@dataclass(frozen=True)
class Split:
    new: tuple[Unasserted, ...]  # no answered question of this task and criterion: each one is asked
    settled: tuple[tuple[Unasserted, str], ...]  # (entry, the id of the answered question that settles it)


@dataclass(frozen=True)
class ClauseAsk:
    question: ResultQuestion  # the harness's question; `loop._questions` binds it to the task
    criterion: str  # recorded as `question.raised.clause.criterion`
    known: Criterion | None  # the unit's criterion of that id, None when the id is not the unit's


def split_clauses(wb: Workbench, task: Task, entries: Sequence[Unasserted]) -> Split:
    """New and settled entries (D2). The key is the task, the fix unit and the criterion, never the clause's words:
    the newest `question.raised` of that key settles the entry when its question in this unit's `questions.md` is
    answered. An open question settles nothing, so a step never passes with its question open."""
    from l4.implementer.tdd import _answer_events  # tdd imports this module

    fix = wb.event_context.get("fix_unit") or None
    newest: dict[str, str] = {}
    for event in _answer_events(wb):
        data = event.data
        clause = data.get("clause")
        if event.type != "question.raised" or data.get("task") != task.key or (data.get("fix_unit") or None) != fix:
            continue
        if isinstance(clause, dict) and isinstance(clause.get("criterion"), str) and isinstance(data.get("id"), str):
            newest[clause["criterion"]] = data["id"]
    file = QuestionsFile.load(wb.ref.path / QUESTIONS_FILENAME) if newest else None
    new: list[Unasserted] = []
    settled: list[tuple[Unasserted, str]] = []
    for item in entries:
        qid = newest.get(item.criterion)
        question = file.get(qid) if file is not None and qid is not None else None
        if qid is not None and question is not None and is_answered(question):
            settled.append((item, qid))
        else:
            new.append(item)
    return Split(tuple(new), tuple(settled))


def recorded_entries(wb: Workbench, task: Task, entries: Sequence[Unasserted]) -> dict[str, Any]:
    """The `unasserted` field of the event that carries a committed step's notes (D5): each entry as `{criterion,
    clause, why, question}` in the result's order, the texts redacted. The settling is decided again here, so a replayed
    step (which does not pass through `agent_step`) records the same; an entry that no answered question settles any
    more is written without `question`. Nothing when there is no entry."""
    questions = {(item.criterion, item.clause, item.why): qid for item, qid in split_clauses(wb, task, entries).settled}
    rows: list[dict[str, str]] = []
    for item in entries:
        row = {key: wb.redactor.redact_text(getattr(item, key)) for key in ("criterion", "clause", "why")}
        if (qid := questions.get((item.criterion, item.clause, item.why))) is not None:
            row["question"] = qid
        rows.append(row)
    return {"unasserted": rows} if rows else {}


def clause_question(task: Task, phase: str, entry: Unasserted, criteria: Sequence[Criterion]) -> ClauseAsk:
    """The question of one new entry (D3): kind `ambiguous`, no options, the clause and the reason quoted."""
    known = next((c for c in criteria if c.id == entry.criterion), None)
    one_line = " ".join(entry.clause.split())
    quote = "\n".join(f"> {line}" for line in entry.clause.splitlines() or [""])
    foreign = f"\n\n{entry.criterion} is not one of this unit's criteria." if known is None else ""
    context = (
        f"The {phase} step of task {task.key} did not assert this clause of {entry.criterion}, and listed it in "
        f"`unasserted`:\n\n{quote}{foreign}\n\nIts reason: {entry.why}\n\n"
        "The step was not kept. Answer with what the clause means for this task: the value or behaviour the code must "
        "have, or that it stays unasserted. The next step of the task reads the answer, and the judge checks the code "
        "against it."
    )
    question = ResultQuestion(
        title=f"Task {task.key} ({phase}) left a clause of {entry.criterion} unasserted: {one_line}",
        context=context,
        kind="ambiguous",
        blocking_tasks=[task.key],
    )
    return ClauseAsk(question, entry.criterion, known)
