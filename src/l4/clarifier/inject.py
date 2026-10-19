"""Answers as prompt data (SPEC L4-CLR-006): one `<l4:data kind="answer">` block per answered question, redacted
first, so what an agent reads is information and never an instruction."""

from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass

from l4.clarifier.actor import Actor
from l4.implementer.prompt import defuse
from l4.specs.questions import Question, QuestionStatus, answer_sha256, answered_by, effective_answer, is_answered

MAX_ANSWER_CHARS = 8000


@dataclass(frozen=True)
class RenderedAnswers:
    text: str  # the blocks, in question order; empty when nothing is answered
    consumed: tuple[tuple[str, str | None], ...]  # (question id, answer_sha256): what this prompt carries


def _body(question: Question, redact: Callable[[str], str]) -> str:
    if question.status is QuestionStatus.DISMISSED:
        return f"{question.id} dismissed by a human: proceed without it"
    # redact before bounding: a cut could otherwise split a secret into two pieces that no longer match its shape
    text = defuse(redact(effective_answer(question) or ""))
    if len(text) > MAX_ANSWER_CHARS:
        text = f"{text[:MAX_ANSWER_CHARS]}\n[truncated: {len(text) - MAX_ANSWER_CHARS} characters omitted]"
    return text


def render_answer_blocks(
    questions: Iterable[Question],
    redact: Callable[[str], str],
    *,
    tasks: Collection[str] | None = None,
    actor_of: Callable[[Question], Actor] | None = None,
) -> RenderedAnswers:
    """The answered questions that hold one of `tasks` (all of them when None). `consumed` is the hash of each
    effective answer as the file holds it, the value `question.answered` recorded (L4-QMD-006). `by` is the real actor
    of the answer (L4-QMD-009, `actor_of`); without it the status decides, as before."""
    wanted = None if tasks is None else set(tasks)
    blocks, consumed = [], []
    for q in questions:
        if not is_answered(q) or (wanted is not None and wanted.isdisjoint(q.blocking_tasks)):
            continue
        by = actor_of(q).by if actor_of else answered_by(q)
        blocks.append(f'<l4:data kind="answer" id="{q.id}" by="{by}">\n{_body(q, redact)}\n</l4:data>')
        consumed.append((q.id, answer_sha256(q)))
    return RenderedAnswers("\n".join(blocks), tuple(consumed))
