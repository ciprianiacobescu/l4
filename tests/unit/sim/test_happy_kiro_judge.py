"""kiro-judge 9.1, SCN-KJD-27: the simulation replays a Kiro judge's stream through the real kiro-cli adapter."""

import json
import re

import pytest

from l4.sim.builtin.manifest import BUILTIN, scenario_text
from l4.sim.replay import ReplayProc
from l4.sim.runner import run_scenario
from l4.sim.scenarios import ScenarioError, fixture_root, load_scenario

CRITERIA = {"C-8fd7d830", "C-4e4feccc", "C-590ae9d1"}


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


def test_happy_kiro_judge_is_ready_and_passes(tmp_path, calls):
    assert BUILTIN["happy-kiro-judge"].ready
    result = run_scenario(load_scenario(scenario_text("happy-kiro-judge")), root=tmp_path / "world")
    assert result.status == "pass", result.report
    assert (result.exit_code, result.final_phase) == (0, "in_review")
    events = result.events
    (verdict,) = [e for e in events if e["type"] == "verify.verdict"]
    assert verdict["verdict"] == "PASS"
    (judged,) = [e for e in events if e["type"] == "verify.judge"]
    assert judged["profile"] == "judge" and judged["status"] == "ok" and judged["credits"] == pytest.approx(0.0512)
    (cost,) = [e for e in events if e["type"] == "budget.cost" and e.get("role") == "judge"]
    assert cost["credits"] == pytest.approx(0.0512) and cost["credits_source"] == "kiro.stream" and "usd" not in cost
    unverified = [e for e in events if e["type"] == "availability.model_unverified" and e["profile"] == "judge"]
    assert unverified


def test_the_replayed_call_has_the_judge_argv_and_stdin(tmp_path, calls):
    run_scenario(load_scenario(scenario_text("happy-kiro-judge")), root=tmp_path / "world")
    (call,) = calls
    argv = call["argv"]
    assert argv[1:4] == ["chat", "--no-interactive", "--v2"]
    assert argv[argv.index("--model") + 1] == "auto"
    assert "--trust-all-tools" not in argv and not any(a.startswith("--trust-tools") for a in argv)
    assert argv[argv.index("--agent") + 1].startswith("l4-judge-")
    assert argv[-2:] == ["--output-format", "stream-json"]  # the prompt is on stdin, not in the argv
    assert call["stdin"] and set(re.findall(r"C-[0-9a-f]{8}", call["stdin"])) >= CRITERIA
    assert "KIRO_HOME" in call["env"]


def test_the_packaged_stream_is_a_valid_verdict_for_the_fixtures_criteria():
    text = fixture_root("kiro-basic").joinpath("payloads", "judge_pass.stream.jsonl").read_text(encoding="utf-8")
    lines = [json.loads(line) for line in text.splitlines()]
    assert all(isinstance(line["type"], str) and isinstance(line["data"], dict) for line in lines)
    final = next(line for line in lines if line["type"] == "runFinished")["data"]["finalText"]
    verdict = json.loads(final[final.index("{") : final.rindex("}") + 1])
    assert {c["id"] for c in verdict["criteria"]} == CRITERIA


BASE = """
name: x
fixture: kiro-basic
judges:
  j: {%s}
expect: {exit_code: 0}
"""


def test_replay_and_verdict_together_are_a_scenario_error():
    both = 'verdict: "@fixture:pass_all.json", replay: {adapter: kiro-cli, stream: "@fixture:judge_pass.stream.jsonl"}'
    with pytest.raises(ScenarioError):
        load_scenario(BASE % both)
    with pytest.raises(ScenarioError):
        load_scenario(BASE % "")  # neither


def test_an_unknown_replay_adapter_or_missing_stream_is_an_error():
    with pytest.raises(ScenarioError):
        load_scenario(BASE % 'replay: {adapter: codex, stream: "@fixture:judge_pass.stream.jsonl"}')
    with pytest.raises(ScenarioError, match="names no file"):
        load_scenario(BASE % 'replay: {adapter: kiro-cli, stream: "@fixture:nope.jsonl"}')
