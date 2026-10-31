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


# --- L4-VER-017: a valid reply that leaves out an asked id is asked once more ----------------------------------------

A1, A2 = "F-0a1b2c", "F-3d4e5f"


def asking(accepted=(A1, A2), feedback=()) -> JudgePrompt:
    return JudgePrompt("SYSTEM", "USER", "0" * 64, "judge@1", accepted_ids=accepted, feedback_ids=feedback)


def ans(fid: str, addressed: bool = True, evidence: str = "src/pytdd/pricing.py:2") -> dict:
    return {"id": fid, "addressed": addressed, "evidence": evidence}


def test_scn_ver_69_a_reply_that_leaves_out_an_accepted_id_is_asked_once_more():
    first = judge_reply([ID], accepted=[ans(A1)])
    second = judge_reply([ID], accepted=[ans(A1), ans(A2, False, "not in the diff")])
    backend = Scripted(ok(first), ok(second))
    run = run_judge(backend, asking(), timeout_s=60, redact=str)
    assert run.status == "ok" and run.calls == 2 and run.reply == "retried"
    assert run.verdict is not None and [(a.id, a.addressed) for a in run.verdict.accepted or []] == [
        (A1, True),
        (A2, False),
    ]
    sent = backend.calls[1]
    assert sent[0].content == "USER" and sent[1].role == "assistant" and A1 in sent[1].content  # its own reply
    assert A2 in sent[-1].content and A1 not in sent[-1].content and "complete JSON object" in sent[-1].content
    assert run.cost_usd == pytest.approx(0.10)


def test_scn_ver_70_a_broken_second_reply_keeps_the_first_verdict():
    first = judge_reply([ID], accepted=[ans(A1)])
    run = run_judge(Scripted(ok(first), invalid()), asking(), timeout_s=60, redact=str)
    assert run.status == "ok" and run.calls == 2 and run.reply == "valid"
    assert run.verdict is not None and [a.id for a in run.verdict.accepted or []] == [A1]
    assert run.cost_usd == pytest.approx(0.09)


def test_a_second_call_that_times_out_keeps_the_first_verdict():
    first = judge_reply([ID], accepted=[ans(A1)])
    run = run_judge(Scripted(ok(first), StructuredResult("timeout", detail="no answer")), asking(), timeout_s=60,
                    redact=str)  # fmt: skip
    assert run.status == "ok" and run.calls == 2 and run.verdict is not None and run.reply == "valid"


def test_a_usage_limit_on_the_second_call_is_a_limit():
    first = judge_reply([ID], accepted=[ans(A1)])
    run_result = RunResult("quota", detail="usage limit", raw_events_path=None)  # type: ignore[arg-type]
    limit = StructuredResult("limit", detail="usage limit", run=run_result)
    with pytest.raises(RoleLimit):
        run_judge(Scripted(ok(first), limit), asking(), timeout_s=60, redact=str)


def test_scn_ver_71_a_feedback_id_left_out_is_asked_for_and_a_complete_reply_is_one_call():
    prompt = asking(accepted=(), feedback=("FB-001",))
    backend = Scripted(ok(judge_reply([ID])), ok(judge_reply([ID], feedback=[ans("FB-001")])))
    run = run_judge(backend, prompt, timeout_s=60, redact=str)
    assert run.calls == 2 and "feedback FB-001" in backend.calls[1][-1].content and run.reply == "retried"
    complete = Scripted(ok(judge_reply([ID], feedback=[ans("FB-001")])))
    assert run_judge(complete, prompt, timeout_s=60, redact=str).calls == 1


def test_a_reply_after_a_schema_repair_that_leaves_out_an_id_is_not_asked_a_third_time():
    backend = Scripted(invalid(), ok(judge_reply([ID], accepted=[ans(A1)])))
    run = run_judge(backend, asking(), timeout_s=60, redact=str)
    assert run.status == "ok" and run.calls == 2 and len(backend.calls) == 2


def test_a_prompt_that_asks_nothing_is_one_call():
    backend = Scripted(ok(judge_reply([ID])))
    assert run_judge(backend, PROMPT, timeout_s=60, redact=str).calls == 1


def test_a_second_call_served_by_another_model_keeps_the_first_verdict():
    first = ok(judge_reply([ID], accepted=[ans(A1)]))
    other = ok(judge_reply([ID], accepted=[ans(A1), ans(A2)]), model="gpt-5")
    run = run_judge(Scripted(first, other), asking(), timeout_s=60, redact=str, expect_model="claude-sonnet-5-5")
    assert run.status == "ok" and run.calls == 2 and run.model_resolved == "claude-sonnet-5-5"
    assert run.verdict is not None and [a.id for a in run.verdict.accepted or []] == [A1]


# --- L4-VER-071: the judge run carries the mark of a reply that stopped at the output limit --------------------------


def test_scn_ver_268_a_judge_run_carries_the_length_stop_of_its_last_call():
    stopped = StructuredResult("error", detail="the stream ended without a final stop (last reason: length)",
                               length_stop=True)  # fmt: skip
    run = run_judge(Scripted(stopped), PROMPT, timeout_s=5, redact=str)
    assert run.status == "error" and run.length_stop is True and run.calls == 1


def test_scn_ver_268_another_error_and_an_ok_reply_are_not_marked():
    other = run_judge(Scripted(StructuredResult("error", detail="x")), PROMPT, timeout_s=5, redact=str)
    assert other.status == "error" and other.length_stop is False
    assert run_judge(Scripted(ok()), PROMPT, timeout_s=5, redact=str).length_stop is False
