import pytest

from l4.agents.base import RunResult, Usage
from l4.implementer.tdd import RoleLimit
from l4.llm.agent_judge import Msg, StructuredResult
from l4.verifier.judge import JudgePrompt, run_judge

from .conftest import judge_reply

ID = "C-0a1b2c3d"
PROMPT = JudgePrompt("SYSTEM", "USER", "0" * 64, "judge@1")


class Scripted:
    def __init__(self, *results: StructuredResult) -> None:
        self._results = list(results)
        self.calls: list[list[Msg]] = []

    def complete_structured(self, system, messages, json_schema, *, effort, max_tokens, timeout_s):
        self.calls.append(list(messages))
        return self._results.pop(0)


def ok(reply=None, cost=0.05, model="claude-sonnet-5-5") -> StructuredResult:
    return StructuredResult("ok", parsed=reply or judge_reply([ID]), model_resolved=model, usage=Usage(cost_usd=cost))


def invalid(detail="$.riskiest_assumptions: fewer than 3 items") -> StructuredResult:
    return StructuredResult("schema_invalid", detail=detail, usage=Usage(cost_usd=0.04))


def test_an_ok_reply_is_one_call():
    backend = Scripted(ok())
    run = run_judge(backend, PROMPT, timeout_s=60, redact=str)
    assert run.status == "ok" and run.verdict is not None and run.calls == 1 and run.model_resolved
    assert run.cost_usd == pytest.approx(0.05)


def test_schema_invalid_once_is_repaired_with_the_paths_and_the_costs_add_up():
    backend = Scripted(invalid(), ok())
    run = run_judge(backend, PROMPT, timeout_s=60, redact=str)
    assert run.status == "ok" and run.calls == 2 and run.cost_usd == pytest.approx(0.09)
    assert [m.content for m in backend.calls[1]][0] == "USER"
    assert "riskiest_assumptions" in backend.calls[1][1].content and "JSON object only" in backend.calls[1][1].content


def test_the_repair_prompt_shows_the_model_its_rejected_reply_redacted_and_cut():
    rejected = StructuredResult(
        "schema_invalid", detail="$.criteria: required", raw={"note": "sk-live-SECRET " + "x" * 9_000}
    )
    backend = Scripted(rejected, ok())
    run_judge(backend, PROMPT, timeout_s=60, redact=lambda text: text.replace("sk-live-SECRET", "[REDACTED]"))
    user, assistant, repair = backend.calls[1]
    assert (user.role, assistant.role, repair.role) == ("user", "assistant", "user")
    assert "[REDACTED]" in assistant.content and "SECRET" not in assistant.content and len(assistant.content) <= 8_000


def test_schema_invalid_twice_discards_judge_verdicts():
    run = run_judge(Scripted(invalid(), invalid("$.criteria: required")), PROMPT, timeout_s=60, redact=str)
    assert run.status == "schema_invalid" and run.verdict is None and run.calls == 2
    assert "criteria" in run.detail


def test_a_reply_the_backend_accepted_but_the_verdict_model_rejects_is_also_repaired():
    bad = judge_reply([ID])
    bad["criteria"][0]["evidence"][0]["kind"] = "file"
    bad["findings"] = [{"severity": "major", "title": "t", "detail": "d", "evidence": [], "spec_gap": "yes"}]
    run = run_judge(Scripted(StructuredResult("ok", parsed=bad), ok()), PROMPT, timeout_s=60, redact=str)
    assert run.status == "ok" and run.calls == 2


def test_a_timeout_is_retried_once_then_discards_the_judge():
    first = Scripted(StructuredResult("timeout", detail="no answer"), ok())
    assert run_judge(first, PROMPT, timeout_s=5, redact=str).status == "ok"
    assert first.calls[0] == first.calls[1]  # same question, no repair text
    twice = run_judge(
        Scripted(StructuredResult("timeout"), StructuredResult("timeout")), PROMPT, timeout_s=5, redact=str
    )
    assert twice.status == "timeout" and twice.calls == 2 and twice.verdict is None


def test_an_error_is_not_retried():
    backend = Scripted(StructuredResult("error", detail="api_error_status 404"))
    run = run_judge(backend, PROMPT, timeout_s=5, redact=str)
    assert run.status == "error" and run.calls == 1 and "404" in run.detail


def test_a_limit_raises_role_limit_for_the_orchestrator_to_park_the_unit():
    run_result = RunResult("quota", detail="usage limit", raw_events_path=None)  # type: ignore[arg-type]
    with pytest.raises(RoleLimit) as exc:
        run_judge(
            Scripted(StructuredResult("limit", detail="usage limit", run=run_result)), PROMPT, timeout_s=5, redact=str
        )
    assert exc.value.result is run_result
