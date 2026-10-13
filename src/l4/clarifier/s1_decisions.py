"""The System-One question set of the clarifier (SPEC L4-CLR-002 rules 3 to 5, as redesigned in docs/eval-framework.md
6.3): what the router asks of Laya or Jev, and how the replies become verdicts.

Why not the SPEC's two yes/no questions: measured on Jev, "is this a product decision?" scored the technical cases
0.24 and 0.42 (the rule needs <= 0.1) and "does the cited text support the answer?" peaked at 0.89 on the spec line
itself (the rule needs >= 0.9), so auto-accept would never fire. The questions here are the ones that did separate the
cases, each with criteria that carry the project's policy:

* router: one `choice` over technical / product / ambiguous, asked in both option orders in one request (the order moves
  the split by 0.13 to 0.21) and averaged;
* citation: per citation, on the state {question, answer, claim, cited_text} (the window cut around the quoted lines):
  "does `cited_text` state or show `claim`?", "... the opposite of `claim`?", "does `claim`, as shown by `cited_text`,
  establish `answer`?" (a true claim does not vouch for a wrong answer) and "can `answer` be derived from the
  project's own material?". The last one needs the answer and the cited text: asked over the question alone, Jev
  rated every repo-answerable question 0.28 to 0.58 and nothing was ever auto-accepted.

Every raw value goes into the verdict's `detail`, with the served model and the question-set id, for calibration
(L4-VER-008). Thresholds are `verifier.s1.decisions.*`. Bump `QUESTION_SET` when a question or a criterion changes: the
thresholds belong to a version of the questions. S1 only ever makes auto-accept stricter.
M1: clarification-loop 2.2 (the model's own tokenizer), eval-framework 6.4 (project policy in the criteria, `margin`,
`repeats`).
"""

import json
import re
from collections.abc import Mapping

from l4.clarifier.answer import Citation, ClarifierAnswer
from l4.clarifier.ports import QuestionView
from l4.clarifier.router import (
    CHARS_PER_TOKEN,
    CitationVerdict,
    Gates,
    RouterVerdict,
    S1Unavailable,
    approx_tokens,
    router_question,
)
from l4.config.schema import S1Cfg
from l4.llm.system_one import (
    Question,
    Reply,
    SystemOneBackend,
    SystemOneBadAnswer,
    SystemOneUnavailable,
)

QUESTION_SET = "clarifier-s1@2"
OPTIONS = ("technical", "product", "ambiguous")
ROUTE_A, ROUTE_B = "route_a", "route_b"
INTERNAL, SHOWS, OPPOSITE, ESTABLISHES = "internal", "shows", "opposite", "establishes"

_ROUTE_CRITERIA = {
    "technical": (
        "The project's own specification, code or documentation settles it, or it is an implementation detail with no "
        "effect on what users see or what the business promises or charges: naming, structure, method or property, "
        "which existing helper to reuse."
    ),
    "product": (
        "The owner has to choose: it changes what users see or what the business promises or charges, such as "
        "rounding, prices, limits, wording, or who may do what."
    ),
    "ambiguous": "The question does not say enough to tell, or the specification contradicts itself.",
}
ROUTE_INSTRUCTION = (
    "Who has to settle the question below: the project's own material (technical), the product owner (product), or "
    "is it too unclear to tell (ambiguous)?"
)
INTERNAL_INSTRUCTION = (
    "Can the answer be derived from this project's own specification, code and documentation, without the owner's "
    "preferences and without facts about systems outside the project?"
)
_TRUE_FALSE = {
    INTERNAL: ("The material in the project is enough to answer it.", "Someone has to decide, or know something else."),
    SHOWS: ("The text says it in words or the code does it.", "The text is about something else or says less."),
    OPPOSITE: ("The text says or does the contrary.", "The text does not say or do the contrary."),
    ESTABLISHES: ("The claim, as the text shows it, settles the answer.", "The answer says more, or something else."),
}
SHOWS_INSTRUCTION = "Does `cited_text` state or show `claim`?"
OPPOSITE_INSTRUCTION = "Does `cited_text` state or show the opposite of `claim`?"
ESTABLISHES_INSTRUCTION = "Does `claim`, as shown by `cited_text`, establish `answer` as the answer to `question`?"


def _noul(instruction: str, key: str) -> Question:
    true, false = _TRUE_FALSE[key]
    return Question("noul", instruction, {"true": true, "false": false})


def route_questions() -> dict[str, Question]:
    a = Question("choice", ROUTE_INSTRUCTION, {name: _ROUTE_CRITERIA[name] for name in OPTIONS})
    b = Question("choice", ROUTE_INSTRUCTION, {name: _ROUTE_CRITERIA[name] for name in reversed(OPTIONS)})
    return {ROUTE_A: a, ROUTE_B: b}


def citation_questions() -> dict[str, Question]:
    return {
        SHOWS: _noul(SHOWS_INSTRUCTION, SHOWS),
        OPPOSITE: _noul(OPPOSITE_INSTRUCTION, OPPOSITE),
        ESTABLISHES: _noul(ESTABLISHES_INSTRUCTION, ESTABLISHES),
        INTERNAL: _noul(INTERNAL_INSTRUCTION, INTERNAL),
    }


def question_text(questions: Mapping[str, Question]) -> str:
    """The longest question as the server reads it: what the state budget has to leave room for."""
    return max((json.dumps(q.wire(), ensure_ascii=False) for q in questions.values()), key=len)


def cut_around(text: str, quote: str, max_chars: int) -> str:
    """At most `max_chars` of `text`, centred on `quote` (whitespace-insensitive), never a prefix: the lines that carry
    the claim are the ones S1 must keep."""
    if len(text) <= max_chars:
        return text
    if max_chars <= 0:
        return ""
    words = quote.split()[:6]
    found = re.search(r"\s+".join(re.escape(w) for w in words), text) if words else None
    centre = (found.start() + found.end()) // 2 if found else len(text) // 2
    start = max(0, min(centre - max_chars // 2, len(text) - max_chars))
    return text[start : start + max_chars]


def citation_state(
    question: str, answer: str, claim: str, cited_text: str, quote: str, *, max_tokens: int, reserve: str
) -> tuple[str, bool]:
    """(the state as JSON, whether the cited text was cut). The question, answer and claim are never cut."""

    def render(text: str) -> str:
        return json.dumps(
            {"question": question, "answer": answer, "claim": claim, "cited_text": text}, ensure_ascii=False
        )

    room = max_tokens - approx_tokens(render("") + reserve)
    kept = cut_around(cited_text, quote, max(room, 0) * CHARS_PER_TOKEN)
    return render(kept), kept != cited_text


def _unit(value: object, qid: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0.0 <= float(value) <= 1.0:
        raise SystemOneBadAnswer(f"no probability between 0 and 1 for question {qid}")
    return float(value)


def p_noul(reply: Reply, qid: str) -> float:
    answer = reply.answers.get(qid)
    return _unit(answer.get("noul") if isinstance(answer, dict) and answer.get("type") == "noul" else None, qid)


def p_technical(reply: Reply, qid: str) -> float:
    """P(technical) of a choice question: its `probabilities` map, not the `confidence` of the chosen option."""
    answer = reply.answers.get(qid)
    odds = answer.get("probabilities") if isinstance(answer, dict) and answer.get("type") == "choice" else None
    return _unit(odds.get("technical") if isinstance(odds, dict) else None, qid)


class SystemOneDecisions:
    """An `S1Judge` over a `SystemOneBackend`. The backend is started at the first question and stopped by `close()`,
    so a clarifier pass that never reaches S1 never starts `laya-serve`; after the first failure S1 stays down."""

    source = "system_one"
    question_set = QUESTION_SET

    def __init__(self, backend: SystemOneBackend) -> None:
        self._backend = backend
        self._down: SystemOneUnavailable | None = None

    def gates(self, limits: S1Cfg) -> Gates:
        d = limits.decisions
        return Gates(
            technical_min=d.router.technical_min, support_min=d.citation.support_min,
            internal_min=d.router.internal_min, opposite_max=d.citation.opposite_max,
            establishes_min=d.citation.establishes_min,
        )  # fmt: skip

    def route(self, question: QuestionView, limits: S1Cfg) -> RouterVerdict:
        questions = route_questions()
        state = router_question(
            question, max_tokens=limits.budget(self._backend.engine), instruction=question_text(questions)
        ).state
        reply = self._ask(state, questions)
        try:
            a, b = p_technical(reply, ROUTE_A), p_technical(reply, ROUTE_B)
        except SystemOneBadAnswer as exc:
            raise self._fail(exc) from None
        return RouterVerdict((a + b) / 2, None, {ROUTE_A: a, ROUTE_B: b}, reply.model)

    def support(
        self, answer: ClarifierAnswer, citation: Citation, cited_text: str, limits: S1Cfg, *, question: QuestionView
    ) -> CitationVerdict:
        questions = citation_questions()
        state, cut = citation_state(
            question.title, answer.answer, citation.claim, cited_text, citation.quote,
            max_tokens=limits.budget(self._backend.engine), reserve=question_text(questions),
        )  # fmt: skip
        reply = self._ask(state, questions)
        try:
            raw = {key: p_noul(reply, key) for key in (SHOWS, OPPOSITE, ESTABLISHES, INTERNAL)}
        except SystemOneBadAnswer as exc:
            raise self._fail(exc) from None
        return CitationVerdict(
            raw[SHOWS], raw[OPPOSITE], cut, raw, reply.model, internal=raw[INTERNAL], establishes=raw[ESTABLISHES]
        )

    def close(self) -> None:
        self._backend.stop()

    def _ask(self, state: str, questions: Mapping[str, Question]) -> Reply:
        if self._down is not None:
            raise S1Unavailable(str(self._down))
        try:
            if not self._backend.running:
                self._backend.start()
            return self._backend.query(state, questions)
        except SystemOneUnavailable as exc:
            raise self._fail(exc) from None

    def _fail(self, exc: SystemOneUnavailable) -> S1Unavailable:
        self._down = exc
        return S1Unavailable(str(exc))
