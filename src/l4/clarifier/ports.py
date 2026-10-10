"""The clarifier's narrow interfaces (design D2): what it reads of a question, what it may write, and what it
returns to the orchestrator. `SpecQuestionsPort` is the real `QuestionsPort`, over `l4.specs.questions`; the
clarifier writes only the Status line and the *Clarifier suggestion* block (L4-QMD-003).
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from l4.agents.base import RunResult
from l4.clarifier.answer import Citation, ClarifierAnswer
from l4.redact import Redactor
from l4.specs.questions import (
    Question,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    answer_sha256,
    answered_by,
    effective_answer,
    is_answered,
    unescape_text,
)

_OPTION_NUMBER = re.compile(r"^\s*\d+\.\s*")


@dataclass(frozen=True)
class QuestionView:
    """One question as the clarifier sees it. `kind` is the implementer's label (None: the file's Kind line is not
    one). `answer_text` is the effective answer, empty while the question is not answered."""

    id: str
    title: str
    status: QuestionStatus
    kind: QuestionKind | None
    blocking: tuple[str, ...]
    context: str
    options: tuple[str, ...]
    answer_text: str
    suggestion_text: str
    by: Literal["human", "clarifier"] | None  # who answered; None while the question is open

    @classmethod
    def of(cls, question: Question) -> "QuestionView":
        options = tuple(
            _OPTION_NUMBER.sub("", line) for line in unescape_text(question.options_text).splitlines() if line.strip()
        )
        return cls(
            id=question.id, title=question.title, status=question.status, kind=question.kind,
            blocking=question.blocking_tasks, context=unescape_text(question.context_text), options=options,
            answer_text=effective_answer(question) or "", suggestion_text=unescape_text(question.suggestion_text),
            by=answered_by(question) if is_answered(question) else None,
        )  # fmt: skip


class QuestionsPort(Protocol):
    def load(self) -> list[QuestionView]: ...

    def set_clarifier_answer(self, qid: str, answer_md: str, citations: Sequence[Citation]) -> None:
        """Status becomes `answered-by-clarifier`; the answer and its citations are the suggestion block."""

    def set_clarifier_suggestion(self, qid: str, suggestion_md: str, meta: str) -> None:
        """Status stays `open`; `meta` is one line (confidence, kind, S1) above the suggestion."""

    def answer_sha256(self, qid: str) -> str | None:
        """Hash of the effective answer as the file now holds it: what `question.answered` must record."""

    def unreadable_ids(self) -> tuple[str, ...]:
        """Questions the file has a heading for and no readable section of: no view, no clarifier call, still open."""


def render_answer_with_citations(answer_md: str, citations: Sequence[Citation]) -> str:
    if not citations:
        return answer_md
    def one_line(text: str) -> str:
        return " ".join(text.split())

    cited = "\n".join(
        f'- `{one_line(c.ref).replace(chr(96), chr(39))}`: "{one_line(c.quote)}" (shows: {one_line(c.claim)})'
        for c in citations
    )
    return f"{answer_md}\n\nCitations:\n{cited}"


class SpecQuestionsPort:
    """Every write is saved at once (atomic), so a run that dies after the first of three questions keeps it."""

    def __init__(self, path: Path, file: QuestionsFile, *, redactor: Redactor) -> None:
        self._path, self._file, self._redactor = path, file, redactor

    @property
    def file(self) -> QuestionsFile:
        return self._file

    def load(self) -> list[QuestionView]:
        return [QuestionView.of(q) for q in self._file.questions]

    def set_clarifier_answer(self, qid: str, answer_md: str, citations: Sequence[Citation]) -> None:
        text = render_answer_with_citations(answer_md, citations)
        edited = self._file.set_suggestion(qid, text, redactor=self._redactor)
        self._write(edited.set_status(qid, QuestionStatus.ANSWERED_BY_CLARIFIER))

    def set_clarifier_suggestion(self, qid: str, suggestion_md: str, meta: str) -> None:
        text = f"{' '.join(meta.split())}\n\n{suggestion_md}"
        self._write(self._file.set_suggestion(qid, text, redactor=self._redactor))

    def unreadable_ids(self) -> tuple[str, ...]:
        return self._file.unreadable_ids

    def answer_sha256(self, qid: str) -> str | None:
        question = self._file.get(qid)
        return answer_sha256(question) if question is not None else None

    def _write(self, edited: QuestionsFile) -> None:
        edited.save(self._path)
        self._file = edited


@dataclass(frozen=True)
class RoutingDecision:
    """`reasons` holds every failed condition of L4-CLR-002 that was evaluated (empty when auto-accepted); `s1` says
    what served S1, or `not_asked` when a cheaper condition already blocked and no S1 call was spent."""

    auto_accept: bool
    reasons: tuple[str, ...] = ()
    p_product: float | None = None  # 1 - P(technical): all that is not technical (System One: product + ambiguous)
    citation_support: tuple[float, ...] = ()
    citation_opposite: tuple[float, ...] = ()  # System One only: P(cited text shows the opposite of the claim)
    p_internal: float | None = None  # System One only: P(derivable from the project's own material)
    s1_model: str | None = None  # the model that served S1, as its reply says (Jev answers `jev-1.13.0` to `latest`)
    s1_questions: str | None = None  # the question-set id the thresholds belong to
    s1_detail: Mapping[str, float] = field(default_factory=dict)  # every raw p, for calibration (L4-VER-008)
    citation_failures: tuple[str, ...] = ()
    s1: Literal["system_one", "llm_boolean", "unavailable", "not_asked"] = "not_asked"
    s1_limit: RunResult | None = None  # the S1 run that reported a usage limit, for `availability.limit`
    p_technical: float | None = None  # the router's own measure (mean over both option orders for System One)


@dataclass(frozen=True)
class QuestionResult:
    """`reply_status` is the clarifier call's own outcome (`clarifier.result.status`); `status` is the question's."""

    status: Literal["answered-by-clarifier", "open"]
    reply_status: Literal["ok", "invalid", "unavailable"]
    answer: ClarifierAnswer | None = None
    decision: RoutingDecision | None = None
    suggestion: str | None = None
    reasons: tuple[str, ...] = ()
    profile: str | None = None


@dataclass(frozen=True)
class ClarifyOutcome:
    """What `Clarifier.run` hands the orchestrator: the phase that follows and the exit code that goes with it
    (`awaiting_human` is exit 11, never 12: a human can always answer, L4-CLR-005)."""

    next_phase: Literal["implementing", "awaiting_human"]
    exit_code: Literal[0, 11]
    results: dict[str, QuestionResult] = field(default_factory=dict)
    clarifier_available: bool = True
    sticky_section: str | None = None

    def __post_init__(self) -> None:
        if (self.next_phase, self.exit_code) not in (("implementing", 0), ("awaiting_human", 11)):
            raise ValueError(f"phase {self.next_phase} does not go with exit code {self.exit_code}")
