"""SCN-VER-268: `StructuredResult` carries the run's `length_stop` (L4-VER-071); the status stays `error`."""

from pathlib import Path

from l4.agents.base import AgentCaps, RunResult
from l4.llm.agent_judge import AgentJudge, Msg

SCHEMA = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}


class OneRun:
    name = "stub"

    def __init__(self, run: RunResult) -> None:
        self._run = run

    def capabilities(self) -> AgentCaps:
        return AgentCaps("native", False, False, False, False, False, False, False)

    def run(self, req):
        return self._run


def asked(run: RunResult):
    judge = AgentJudge(OneRun(run), lambda prompt, schema, timeout_s: None)  # type: ignore[arg-type,return-value]
    return judge.complete_structured("SYSTEM", [Msg("user", "USER")], SCHEMA)


def run_of(status="error", **kw) -> RunResult:
    return RunResult(status, raw_events_path=Path("raw.jsonl"), **kw)  # type: ignore[arg-type]


def test_an_error_run_that_stopped_at_the_output_limit_gives_an_error_result_with_the_mark():
    result = asked(run_of(detail="the stream ended without a final stop (last reason: length)", length_stop=True))
    assert result.status == "error" and result.length_stop is True
    assert result.detail == "the stream ended without a final stop (last reason: length)"


def test_an_error_run_without_the_mark_gives_a_result_without_it():
    result = asked(run_of(detail="opencode reported an error"))
    assert result.status == "error" and result.length_stop is False


def test_an_ok_run_is_not_marked():
    result = asked(run_of("ok", structured={"a": "x"}))
    assert result.status == "ok" and result.length_stop is False
