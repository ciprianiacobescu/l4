import json

import pytest

from l4.clarifier.answer import CLARIFIER_ANSWER_SCHEMA
from l4.clarifier.backend import MAX_ANSWER_TOKENS, BackendClarifier
from l4.clarifier.context import ClarifierPrompt
from l4.clarifier.ports import QuestionView
from l4.llm.agent_judge import StructuredResult
from l4.specs.questions import QuestionKind, QuestionStatus

from .conftest import ScriptedBackend, limit_run, ok

PROMPT = ClarifierPrompt("SYSTEM", "USER", "0" * 64, "clarifier@1")
VIEW = QuestionView(
    "Q-002", "t", QuestionStatus.OPEN, QuestionKind.TECHNICAL, ("1.1",), "c", (), "", "", None
)  # fmt: skip


def reply(**over) -> dict:
    base = {
        "question_id": "Q-002", "answer": "Use bcrypt.", "confidence": "high", "kind": "technical",
        "citations": [{"ref": "design.md#L3", "quote": "hash with bcrypt", "claim": "c"}], "rationale": "r",
    }  # fmt: skip
    return {**base, **over}


def test_a_valid_reply_is_returned_after_one_call():
    backend = ScriptedBackend(ok(reply(), cost=0.05))
    out = BackendClarifier(backend, redact=lambda t: t).answer(VIEW, PROMPT)
    assert out.status == "ok" and out.answer is not None and out.answer.answer == "Use bcrypt."
    assert out.calls == 1 and out.cost_usd == pytest.approx(0.05) and out.model_resolved == "claude-x"
    call = backend.calls[0]
    assert call["system"] == "SYSTEM" and [m.content for m in call["messages"]] == ["USER"]
    assert call["schema"] == CLARIFIER_ANSWER_SCHEMA and call["max_tokens"] == MAX_ANSWER_TOKENS == 2000


def test_a_schema_break_gets_one_repair_with_the_paths_and_the_rejected_reply():
    secret = "glpat-AAAAAAAAAAAAAAAAAAAA"
    bad = reply(confidence="certain", rationale=secret)
    backend = ScriptedBackend(ok(bad), ok(reply()))
    out = BackendClarifier(backend, redact=lambda t: t.replace(secret, "[REDACTED]")).answer(VIEW, PROMPT)
    assert out.status == "ok" and out.calls == 2
    second = backend.calls[1]["messages"]
    assert [m.role for m in second] == ["user", "assistant", "user"]
    assert "[REDACTED]" in second[1].content and secret not in second[1].content
    assert json.loads(second[1].content)["confidence"] == "certain"
    assert "confidence" in second[2].content and "certain" not in second[2].content  # paths, never values


def test_invalid_twice_returns_invalid_status():
    backend = ScriptedBackend(ok(reply(kind="verdict")), StructuredResult("schema_invalid", detail="answer: too long"))
    out = BackendClarifier(backend, redact=lambda t: t).answer(VIEW, PROMPT)
    assert out.status == "invalid" and out.answer is None and out.calls == 2 and len(backend.calls) == 2
    assert "answer: too long" in out.detail


def test_an_answer_to_another_question_is_a_schema_problem():
    backend = ScriptedBackend(ok(reply(question_id="Q-009")), ok(reply(question_id="Q-009")))
    out = BackendClarifier(backend, redact=lambda t: t).answer(VIEW, PROMPT)
    assert (
        out.status == "invalid" and "question_id" in out.detail and "Q-002" in backend.calls[1]["messages"][-1].content
    )


def test_a_usage_limit_is_unavailable_not_exit_12():
    run = limit_run()
    out = BackendClarifier(
        ScriptedBackend(StructuredResult("limit", detail="usage limit", run=run)), redact=str
    ).answer(VIEW, PROMPT)
    assert out.status == "unavailable" and out.limit is run and out.calls == 1 and "usage limit" in out.detail


def test_an_error_is_unavailable_and_a_timeout_is_retried_once():
    boom = ScriptedBackend(StructuredResult("error", detail="no login"))
    assert BackendClarifier(boom, redact=str).answer(VIEW, PROMPT).status == "unavailable" and len(boom.calls) == 1
    slow = ScriptedBackend(StructuredResult("timeout", detail="late"), ok(reply()))
    out = BackendClarifier(slow, redact=str).answer(VIEW, PROMPT)
    assert out.status == "ok" and out.calls == 2 and [m.content for m in slow.calls[1]["messages"]] == ["USER"]
    dead = ScriptedBackend(StructuredResult("timeout", detail="late"), StructuredResult("timeout", detail="late"))
    assert BackendClarifier(dead, redact=str).answer(VIEW, PROMPT).status == "unavailable"
