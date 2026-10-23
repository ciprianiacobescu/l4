"""copilot-cli 5.1, D18, L4-FAC-014: the simulation replays a Copilot judge's stream through the real adapter."""

import json
import re

import pytest

from l4.sim.builtin.manifest import BUILTIN, scenario_text
from l4.sim.replay import ReplayProc
from l4.sim.runner import run_scenario
from l4.sim.scenarios import ScenarioError, fixture_root, load_scenario

CRITERIA = {"C-9618b9f5", "C-6057a7e3", "C-49a0a655"}


@pytest.fixture
def calls(monkeypatch):
    """Every replayed process call (argv, env, stdin), recorded around the real replay."""
    seen: list[dict] = []
    original = ReplayProc.run

    def record(self, argv, env, cwd, **kw):
        seen.append({"argv": list(argv), "env": dict(env), "cwd": cwd, "stdin": kw.get("stdin")})
        return original(self, argv, env, cwd, **kw)

    monkeypatch.setattr(ReplayProc, "run", record)
    return seen


def test_happy_copilot_judge_is_ready_and_passes(tmp_path, calls):
    assert BUILTIN["happy-copilot-judge"].ready
    result = run_scenario(load_scenario(scenario_text("happy-copilot-judge")), root=tmp_path / "world")
    assert result.status == "pass", result.report
    assert (result.exit_code, result.final_phase) == (0, "in_review")
    (verdict,) = [e for e in result.events if e["type"] == "verify.verdict"]
    assert verdict["verdict"] == "PASS"
    (judged,) = [e for e in result.events if e["type"] == "verify.judge"]
    assert judged["profile"] == "judge" and judged["status"] == "ok"


def test_the_replayed_call_has_the_judge_argv_and_stdin(tmp_path, calls):
    run_scenario(load_scenario(scenario_text("happy-copilot-judge")), root=tmp_path / "world")
    (call,) = calls
    argv = call["argv"]
    assert argv[argv.index("--model") + 1] == "auto"
    assert "--available-tools=l4_no_tools" in argv
    assert not any(a.startswith("--allow-tool") for a in argv)
    assert call["stdin"] and set(re.findall(r"C-[0-9a-f]{8}", call["stdin"])) >= CRITERIA
    assert call["env"]["COPILOT_HOME"]


def test_the_verdict_names_the_served_model(tmp_path):
    root = tmp_path / "world"
    run_scenario(load_scenario(scenario_text("happy-copilot-judge")), root=root, keep=True)
    texts = [p.read_text(encoding="utf-8") for p in root.rglob("verification.md")]
    assert texts, "the run wrote no verification.md"
    assert all("judge openai (served gpt-6.1-sol)" in text for text in texts)


def test_the_packaged_stream_is_a_valid_verdict_for_the_fixtures_criteria():
    text = fixture_root("openspec-basic").joinpath("payloads", "judge_pass.copilot.jsonl").read_text(encoding="utf-8")
    lines = [json.loads(line) for line in text.splitlines()]
    assert all(isinstance(line["type"], str) for line in lines)
    (message,) = [line for line in lines if line["type"] == "assistant.message"]
    assert message["data"]["model"] == "gpt-6.1-sol" and message["data"]["toolRequests"] == []
    (result,) = [line for line in lines if line["type"] == "result"]
    assert lines[-1] is result and result["exitCode"] == 0
    content = message["data"]["content"]
    verdict = json.loads(content[content.index("{") : content.rindex("}") + 1])
    assert {c["id"] for c in verdict["criteria"]} == CRITERIA


BASE = """
name: x
fixture: openspec-basic
judges:
  j: {%s}
expect: {exit_code: 0}
"""


def test_a_copilot_replay_loads_and_an_unknown_adapter_is_still_an_error():
    ok = 'replay: {adapter: copilot-cli, stream: "@fixture:judge_pass.copilot.jsonl"}'
    assert load_scenario(BASE % ok).judges["j"].replay.adapter == "copilot-cli"
    with pytest.raises(ScenarioError):
        load_scenario(BASE % 'replay: {adapter: codex, stream: "@fixture:judge_pass.copilot.jsonl"}')
    with pytest.raises(ScenarioError, match="names no file"):
        load_scenario(BASE % 'replay: {adapter: copilot-cli, stream: "@fixture:nope.jsonl"}')
