import json
from pathlib import Path

import pytest

from l4.agents.base import AdapterError, PermissionPolicy, RunRequest
from l4.config.schema import Profile
from l4.sim.fakes import ScriptedAgent, asked_for
from l4.sim.scenarios import Step, When

PROMPT = "# Contract\nrules\n\n# Task {task}\n<l4:data>x</l4:data>\n\n# Phase: {phase} (tests first)\nwrite tests\n"


def request(tmp_path: Path, *, phase: str = "RED", task: str = "1.1", mode: str = "implement") -> RunRequest:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return RunRequest(
        profile=Profile(adapter="fake"), role="implementer", cwd=work, prompt=PROMPT.format(task=task, phase=phase),
        result_path=tmp_path / "tmp" / "result.json", raw_events_path=tmp_path / "raw" / "events.jsonl",
        env={}, permission_policy=PermissionPolicy(mode),  # type: ignore[arg-type]
    )  # fmt: skip


def test_asked_for_reads_phase_and_task_from_the_prompt():
    assert asked_for(PROMPT.format(task="2.1", phase="GREEN")) == When(phase="green", task="2.1")
    assert asked_for("# Task L12\n") == When(phase=None, task="L12")
    assert asked_for("a judge prompt") == When()
    assert asked_for("not at line start # Phase: RED") == When()


def test_matching_step_writes_files_and_returns_result(tmp_path):
    agent = ScriptedAgent(
        [Step(when=When(phase="red", task="1.1"), write={"tests/test_a.py": "x = 1\n"}, result={"tests_added": ["t"]})]
    )
    run = agent.run(request(tmp_path))
    assert run.status == "ok"
    assert (tmp_path / "work" / "tests" / "test_a.py").read_text() == "x = 1\n"
    assert run.structured == {
        "status": "done", "phase": "red", "task_ids": ["1.1"], "criteria_ids": [], "summary": "red done",
        "tests_added": ["t"],
    }  # fmt: skip
    assert json.loads((tmp_path / "tmp" / "result.json").read_text()) == run.structured
    assert agent.matched == [When(phase="red", task="1.1")]


def test_steps_answer_once_and_in_any_order(tmp_path):
    agent = ScriptedAgent(
        [
            Step(when=When(phase="green"), write={"b.txt": "green"}),
            Step(when=When(phase="red"), write={"a.txt": "red"}),
        ]
    )
    agent.run(request(tmp_path, phase="RED"))
    agent.run(request(tmp_path, phase="GREEN"))
    assert [(tmp_path / "work" / n).read_text() for n in ("a.txt", "b.txt")] == ["red", "green"]
    with pytest.raises(AdapterError, match="steps left: none"):
        agent.run(request(tmp_path, phase="RED"))


def test_unmatched_request_fails_naming_when_and_steps(tmp_path):
    agent = ScriptedAgent([Step(when=When(phase="green", task="1.2"))])
    with pytest.raises(AdapterError) as err:
        agent.run(request(tmp_path, phase="RED", task="1.1"))
    message = str(err.value)
    assert "phase='red'" in message and "task='1.1'" in message and "'task': '1.2'" in message


def test_a_step_without_when_matches_anything_and_status_is_passed_through(tmp_path):
    agent = ScriptedAgent([Step(status="quota")])
    assert agent.run(request(tmp_path)).status == "quota"


def test_a_scripted_write_cannot_leave_the_worktree(tmp_path):
    agent = ScriptedAgent([Step(write={"../escape.txt": "x"})])
    with pytest.raises(AdapterError, match="outside the worktree"):
        agent.run(request(tmp_path))
    assert not (tmp_path / "escape.txt").exists()


def test_judge_mode_returns_the_scripted_verdict(tmp_path):
    verdict = {"criteria": [], "test_adequacy": [], "findings": [], "riskiest_assumptions": ["a", "b", "c"]}
    for scripted in (verdict, json.dumps(verdict)):
        run = ScriptedAgent(verdict=scripted).run(request(tmp_path, mode="judge"))
        assert run.structured == verdict and run.status == "ok"
    with pytest.raises(AdapterError, match="no verdict"):
        ScriptedAgent().run(request(tmp_path, mode="judge"))


def test_probes_default_to_ok_and_can_be_scripted():
    from l4.agents.base import ProbeResult

    agent = ScriptedAgent(probes={"quota": ProbeResult("quota", False, reason="exhausted")})
    assert agent.probe(Profile(adapter="fake"), "binary", None).ok  # type: ignore[arg-type]
    assert not agent.probe(Profile(adapter="fake"), "quota", None).ok  # type: ignore[arg-type]
    assert agent.capabilities().schema_mode == "native"
