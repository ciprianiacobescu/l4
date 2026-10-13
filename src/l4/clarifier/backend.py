"""One clarifier call over a tool-less structured-output backend (design D4, backend path; L4-CLR-001, L4-CLR-005).

At most two calls: a reply that breaks `l4/clarifier-answer@1` is asked for once more, with the violated paths (never
the values) and the rejected reply, redacted and cut; a second break is `invalid`. Unlike the judge, a usage limit or a
lost login does not end the run with exit 12: the clarifier is optional and humans can always answer, so the reply is
`unavailable` and the agent run that reported the limit is kept for the ledger.
# M1: clarification-loop 1.6 `AgentClarifier` (read-only agent with tools), 3.2 chain fallback
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from l4.agents.base import RunResult
from l4.clarifier.answer import CLARIFIER_ANSWER_SCHEMA, AnswerInvalid, ClarifierAnswer, validate_answer
from l4.clarifier.context import ClarifierPrompt
from l4.clarifier.ports import QuestionView
from l4.llm.agent_judge import LLMBackend, Msg, StructuredResult

MAX_CALLS = 2  # the first answer and one repair or retry
MAX_ANSWER_TOKENS = 2000  # [I] the API backends cap the reply; `claude -p` has no flag for it
MAX_REPAIR_ECHO_CHARS = 8_000


@dataclass
class ClarifierReply:
    """`invalid`: two replies broke the schema. `unavailable`: the backend could not answer (limit, lost login, error,
    two timeouts); `limit` is the agent run that reported a usage limit or a lost login."""

    status: Literal["ok", "invalid", "unavailable"]
    answer: ClarifierAnswer | None = None
    model_resolved: str | None = None
    cost_usd: float | None = None
    calls: int = 0
    detail: str = ""
    limit: RunResult | None = None


def _repair(problems: str) -> Msg:
    return Msg(
        "user",
        f"Your reply did not satisfy the schema ({problems}). Reply again with the complete JSON object only.",
    )


class BackendClarifier:
    def __init__(self, backend: LLMBackend, *, redact: Callable[[str], str], timeout_s: int = 600) -> None:
        self._backend = backend
        self._redact = redact
        self._timeout_s = timeout_s

    def answer(self, question: QuestionView, prompt: ClarifierPrompt) -> ClarifierReply:
        first = [Msg("user", prompt.user)]
        messages = first
        out = ClarifierReply("unavailable")
        for call in range(1, MAX_CALLS + 1):
            result = self._backend.complete_structured(
                prompt.system, messages, CLARIFIER_ANSWER_SCHEMA,
                effort=None, max_tokens=MAX_ANSWER_TOKENS, timeout_s=self._timeout_s,
            )  # fmt: skip
            out.calls = call
            out.model_resolved = result.model_resolved or out.model_resolved
            if result.usage.cost_usd is not None:  # None is "not reported" (codex), which is not "free"
                out.cost_usd = (out.cost_usd or 0.0) + result.usage.cost_usd
            if result.status in ("limit", "error"):
                return _unavailable(out, result)
            if result.status == "timeout":
                out.status, out.detail = "unavailable", result.detail
                messages = first
                continue
            parsed = _classify(result, question.id)
            if isinstance(parsed, ClarifierAnswer):
                out.status, out.answer, out.detail = "ok", parsed, ""
                return out
            out.status, out.detail = "invalid", "; ".join(parsed.problems)
            rejected = result.raw or result.parsed
            echo = [Msg("assistant", self._redact(json.dumps(rejected))[:MAX_REPAIR_ECHO_CHARS])] if rejected else []
            messages = [*first, *echo, _repair(out.detail)]
        return out


def _unavailable(out: ClarifierReply, result: StructuredResult) -> ClarifierReply:
    out.status, out.detail, out.limit = "unavailable", result.detail, result.run if result.status == "limit" else None
    return out


def _classify(result: StructuredResult, question_id: str) -> ClarifierAnswer | AnswerInvalid:
    """The backend's own validation is not trusted: the clarifier's schema has the last word, and the answer must be
    to the question that was asked (the schema cannot pin the id)."""
    if result.status != "ok" or result.parsed is None:
        return AnswerInvalid((result.detail or "no structured reply",))
    parsed = validate_answer(result.parsed)
    if isinstance(parsed, ClarifierAnswer) and parsed.question_id != question_id:
        return AnswerInvalid((f"question_id: must be {question_id}",))
    return parsed
