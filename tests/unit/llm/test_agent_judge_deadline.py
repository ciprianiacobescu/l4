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


class Metered(Stopped):
    def run(self, req) -> RunResult:
        from l4.agents.base import Usage

        self.runs += 1
        usage = Usage(cost_usd=0.07, credits=0.42, credits_source="kiro.stream")
        return RunResult(status="cancelled", raw_events_path=self.path, detail="interrupted", usage=usage)


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def append(self, type_: str, **fields) -> None:
        self.events.append((type_, fields))


def test_a_stopped_judge_records_the_cost_it_metered(tmp_path, armed_deadline):
    """C-m1: the call was paid for even though it gives no verdict; the cost is recorded before the stop is raised."""
    armed_deadline().fire()
    sink = Sink()
    agent_judge = AgentJudge(
        Metered(tmp_path / "raw.jsonl"), lambda prompt, schema, timeout: object(),  # type: ignore[arg-type]
        events=sink, role="clarifier", profile="kiro",
    )  # fmt: skip
    with pytest.raises(DeadlineReached):
        agent_judge.complete_structured("system", [], SCHEMA)
    assert sink.events == [
        ("budget.cost", {"usd": 0.07, "profile": "kiro", "role": "clarifier"}),
        ("budget.cost", {"credits": 0.42, "credits_source": "kiro.stream", "profile": "kiro", "role": "clarifier"}),
    ]


def test_a_stopped_judge_with_no_metered_cost_records_nothing(tmp_path, armed_deadline):
    armed_deadline().fire()
    sink = Sink()
    agent_judge = AgentJudge(
        Stopped(tmp_path / "raw.jsonl"), lambda prompt, schema, timeout: object(),  # type: ignore[arg-type]
        events=sink, role="judge", profile="p",
    )  # fmt: skip
    with pytest.raises(DeadlineReached):
        agent_judge.complete_structured("system", [], SCHEMA)
    assert sink.events == []
