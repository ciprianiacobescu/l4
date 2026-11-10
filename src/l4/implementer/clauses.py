"""The clauses a step leaves unasserted (SPEC L4-IMP-095): which entries of its `unasserted` list are new, which an
answered question of the task already settled, and the `ambiguous` question that a new one becomes."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from l4.implementer.result import ResultQuestion, Unasserted
from l4.implementer.workbench import Workbench
from l4.specs.base import Criterion, Task
from l4.specs.questions import QUESTIONS_FILENAME, QuestionsFile, effective_answer, is_answered

MAX_IDS_SHOWN = 12  # criterion ids that the excerpt of a failed `unasserted` lists


def text_sha(criterion: Criterion) -> str:
    """The hash of a criterion's text, with every run of whitespace one space. An OpenSpec criterion id hashes the
    scenario's name, not its body, so the id stays when the body is edited: the answer to a clause is kept for the text
    it was given for (`question.raised.clause.text_sha`) and settles nothing once the text changed."""
    return hashlib.sha256(" ".join(criterion.text.split()).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Split:
    new: tuple[Unasserted, ...]  # no answered question of this task and criterion: each one is asked
    settled: tuple[tuple[Unasserted, str], ...]  # (entry, the id of the question that settles it)
    dismissed: frozenset[str] = frozenset()  # the settling questions that were dismissed: no answer to name


@dataclass(frozen=True)
class ClauseAsk:
    question: ResultQuestion  # the harness's question; `loop._questions` binds it to the task
    criterion: str  # recorded as `question.raised.clause.criterion`
    known: Criterion | None  # the unit's criterion of that id (`foreign_problems` fails a step with any other)
    text_sha: str = ""  # recorded as `question.raised.clause.text_sha`: the criterion's text this question is about


def split_clauses(wb: Workbench, task: Task, entries: Sequence[Unasserted]) -> Split:
    """New and settled entries (D2). The key is the task, the fix unit and the criterion, never the clause's words:
    the newest `question.raised` of that key settles the entry when its question in this unit's `questions.md` is
    answered and the criterion's text is the one it was asked about (`clause.text_sha`; a question with none, or about
    other text, settles nothing: the clause is asked again). An open question settles nothing, so a step never passes
    with its question open. A dismissed question settles, and is listed in `dismissed`: it has no answer to name."""
    if not entries:  # nothing to settle: no ledger, no questions.md
        return Split((), ())
    from l4.implementer.tdd import _answer_events  # tdd imports this module

    fix = wb.event_context.get("fix_unit") or None
    newest: dict[str, tuple[str, Any]] = {}
    for event in _answer_events(wb):
        data = event.data
        clause = data.get("clause")
        if event.type != "question.raised" or data.get("task") != task.key or (data.get("fix_unit") or None) != fix:
            continue
        if isinstance(clause, dict) and isinstance(clause.get("criterion"), str) and isinstance(data.get("id"), str):
            newest[clause["criterion"]] = (data["id"], clause.get("text_sha"))
    file = QuestionsFile.load(wb.ref.path / QUESTIONS_FILENAME) if newest else None
    current = {c.id: text_sha(c) for c in wb.provider.criteria(wb.ref)} if newest else {}
    new: list[Unasserted] = []
    settled: list[tuple[Unasserted, str]] = []
    dismissed: set[str] = set()
    for item in entries:
        qid, asked_about = newest.get(item.criterion, (None, None))
        question = file.get(qid) if file is not None and qid is not None else None
        if (
            qid is not None
            and question is not None
            and is_answered(question)
            and asked_about == current.get(item.criterion)
        ):
            settled.append((item, qid))
            if effective_answer(question) is None:
                dismissed.add(qid)
        else:
            new.append(item)
    return Split(tuple(new), tuple(settled), frozenset(dismissed))


def recorded_entries(wb: Workbench, task: Task, entries: Sequence[Unasserted]) -> dict[str, Any]:
    """The `unasserted` field of the event that carries a committed step's notes (D5): each entry as `{criterion,
    clause, why, question}` in the result's order, the texts redacted. The settling is decided again here, so a replayed
    step (which does not pass through `agent_step`) records the same. `question` is the id of the settling question
    only when it has an answer the judge is shown (answered, accepted or answered by the clarifier): an entry that a
    dismissed question settled, or that no answered question settles any more, is written without it. Nothing when
    there is no entry."""
    if not entries:
        return {}
    split = split_clauses(wb, task, entries)
    questions = {
        (item.criterion, item.clause, item.why): qid for item, qid in split.settled if qid not in split.dismissed
    }
    rows: list[dict[str, str]] = []
    for item in entries:
        row = {key: wb.redactor.redact_text(getattr(item, key)) for key in ("criterion", "clause", "why")}
        if (qid := questions.get((item.criterion, item.clause, item.why))) is not None:
            row["question"] = qid
        rows.append(row)
    return {"unasserted": rows}


def foreign_problems(entries: Sequence[Unasserted], criteria: Sequence[Criterion]) -> list[str]:
    """One problem text for each criterion id of `entries` that is not one of the unit's `criteria` (a well-formed id
    that names nothing here): the step is a failed attempt, never a question that nothing bounds."""
    known = {c.id for c in criteria}
    return [
        f"unasserted: {cid} is not one of this unit's criteria"
        for cid in dict.fromkeys(e.criterion for e in entries)
        if cid not in known
    ]


def unasserted_excerpt(problems: Sequence[str], criteria: Sequence[Criterion]) -> str:
    """The text of the next prompt after a failed `unasserted` list (L4-IMP-095): each problem, what the step lost, and
    what an item is. Harness words and the unit's own criterion ids; the agent's text is quoted at most 40
    characters."""
    ids = [c.id for c in criteria][:MAX_IDS_SHOWN]
    more = f" (and {len(criteria) - MAX_IDS_SHOWN} more)" if len(criteria) > MAX_IDS_SHOWN else ""
    lines = ["Nothing of that step was kept: its `unasserted` list is not valid.", *(f"- {p}" for p in problems)]
    lines.append(
        "Each item of `unasserted` has a `criterion` (the id of one of this unit's criteria"
        + (f": {', '.join(ids)}{more}" if ids else "")
        + "), a `clause` (quoted from that criterion) and a `why`, none of them empty. Fix the items, or leave "
        "`unasserted` out when no clause of a cited scenario is left unasserted."
    )
    return "\n".join(lines)


def clause_question(task: Task, phase: str, entry: Unasserted, criteria: Sequence[Criterion]) -> ClauseAsk:
    """The question of one new entry (D3): kind `ambiguous`, no options, the clause and the reason quoted."""
    known = next((c for c in criteria if c.id == entry.criterion), None)
    one_line = " ".join(entry.clause.split())
    quote = "\n".join(f"> {line}" for line in entry.clause.splitlines() or [""])
    context = (
        f"The {phase} step of task {task.key} did not assert this clause of {entry.criterion}, and listed it in "
        f"`unasserted`:\n\n{quote}\n\nIts reason: {entry.why}\n\n"
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
    return ClauseAsk(question, entry.criterion, known, text_sha(known) if known is not None else "")
