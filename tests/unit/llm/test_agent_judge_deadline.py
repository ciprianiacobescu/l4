"""A CLI judge stopped by the soft deadline raises instead of returning an error result (L4-IMP-068, D4)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from l4.agents.base import RunResult
from l4.deadline import DeadlineReached
from l4.llm.agent_judge import AgentJudge

SCHEMA = {"type": "object"}


class Stopped:
    """An adapter whose run ends with status `cancelled`, as `ProcRunner` reports an interrupted process."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.runs = 0

    def capabilities(self):
        return SimpleNamespace(schema_mode="native")

    def run(self, req) -> RunResult:
        self.runs += 1
        return RunResult(status="cancelled", raw_events_path=self.path, detail="interrupted")


def judge(tmp_path: Path) -> tuple[AgentJudge, Stopped]:
    adapter = Stopped(tmp_path / "raw.jsonl")
    return AgentJudge(adapter, lambda prompt, schema, timeout: object()), adapter  # type: ignore[arg-type]


def test_a_stopped_cli_judge_raises(tmp_path, armed_deadline):
    dl = armed_deadline()
    dl.fire()
    agent_judge, adapter = judge(tmp_path)
    with pytest.raises(DeadlineReached) as caught:
        agent_judge.complete_structured("system", [], SCHEMA)
    assert caught.value.when == "during" and caught.value.during == "judge"
    assert caught.value.mark is None
    assert adapter.runs == 1  # not tried again


def test_a_cancelled_judge_without_the_deadline_is_an_error_result(tmp_path, armed_deadline):
    armed_deadline()  # armed and not fired
    agent_judge, _ = judge(tmp_path)
    result = agent_judge.complete_structured("system", [], SCHEMA)
    assert result.status == "error" and result.detail == "interrupted"
    # and with no deadline at all
    from l4 import deadline

    deadline.disarm()
    assert judge(tmp_path)[0].complete_structured("system", [], SCHEMA).status == "error"
