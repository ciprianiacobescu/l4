from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from l4.agents.base import AdapterError, PermissionPolicy, RunRequest
from l4.agents.kiro_cli import KiroCliAdapter
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "kiro-cli" / "2.27.1"
PROFILE = Profile(adapter="kiro-cli", model="claude-sonnet-4", vendor="anthropic", options={"agent": "l4"})
SCHEMA = {"type": "object", "required": ["status"], "properties": {"status": {"type": "string"}}}


def request(tmp_path: Path, **kw) -> RunRequest:
    kw.setdefault("profile", PROFILE)
    kw.setdefault("prompt", "do the task")
    (tmp_path / "bin").mkdir(exist_ok=True)
    exe = tmp_path / "bin" / "kiro-cli"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return RunRequest(
        role="implementer", cwd=tmp_path / "wt", result_path=tmp_path / "res" / "result.json",
        raw_events_path=tmp_path / "raw" / "events.jsonl", env={"PATH": str(tmp_path / "bin")}, **kw,
    )  # fmt: skip


class FakeProc:
    def __init__(self) -> None:
        self.calls = []

    def run(self, argv, env, cwd, *, stdout_path, timeout_s, stdin=None, stderr_path=None, **kw):
        self.calls.append({"argv": list(argv), "env": dict(env), "stdin": stdin, "kw": kw})
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text("")
        return ProcOutcome(0)


def test_the_argv_is_the_spec_one_with_the_prompt_last(tmp_path):
    proc = FakeProc()
    KiroCliAdapter(proc).run(request(tmp_path))
    argv = proc.calls[0]["argv"]
    assert argv[1:] == [
        "chat", "--no-interactive", "--trust-tools=fs_read,fs_write,execute_bash", "--agent", "l4",
        "--model", "claude-sonnet-4", "--output-format", "stream-json", "--require-mcp-startup", "do the task",
    ]  # fmt: skip
    assert proc.calls[0]["stdin"] is None  # the prompt is an argument; stdin is /dev/null


def test_trust_tools_follow_the_permission_policy(tmp_path):
    for mode, expected in (("read_only", "--trust-tools=fs_read"), ("judge", "--trust-tools=read")):
        proc = FakeProc()
        KiroCliAdapter(proc).run(request(tmp_path, permission_policy=PermissionPolicy(mode)))
        assert expected in proc.calls[0]["argv"]


def test_the_judge_never_gets_an_empty_trust_list(tmp_path):
    """`--trust-tools=` (empty) trusts every tool on kiro-cli 2.28.0 [V: a shell `date > d.txt` ran under it] (K4)."""
    proc = FakeProc()
    KiroCliAdapter(proc).run(request(tmp_path, permission_policy=PermissionPolicy("judge")))
    assert "--trust-tools=" not in proc.calls[0]["argv"]
    from l4.agents.kiro_cli import TRUST_TOOLS

    assert all(value for value in TRUST_TOOLS.values())


def test_a_prompt_too_large_for_one_argument_is_refused_not_truncated(tmp_path):
    with pytest.raises(AdapterError, match="argument"):
        KiroCliAdapter(FakeProc()).run(request(tmp_path, prompt="x" * 200_000))


def test_exit3_is_mcp_startup_error(tmp_path):
    out = KiroCliAdapter().parse([], exit_code=3, raw_events_path=tmp_path / "e")
    assert out.status == "error" and "MCP" in (out.detail or "") and out.limit is None


def test_exit0_with_a_valid_result_file_is_ok_and_nulls_are_dropped(tmp_path):
    out = KiroCliAdapter().parse(
        [], exit_code=0, raw_events_path=tmp_path / "e", result_text='{"status": "done", "x": null}', schema=SCHEMA
    )
    assert out.status == "ok" and out.structured == {"status": "done"}


@pytest.mark.parametrize("text", [None, "not json", '{"status": 3}'])
def test_exit0_without_a_usable_result_file_is_an_error(tmp_path, text):
    out = KiroCliAdapter().parse([], exit_code=0, raw_events_path=tmp_path / "e", result_text=text, schema=SCHEMA)
    assert out.status == "error" and out.structured is None


def test_other_exit_codes_timeouts_and_interrupts(tmp_path):
    adapter = KiroCliAdapter()
    assert adapter.parse([], exit_code=1, raw_events_path=tmp_path / "e").status == "error"
    assert adapter.parse([], exit_code=0, raw_events_path=tmp_path / "e", timed_out=True).status == "timeout"
    assert adapter.parse([], exit_code=0, raw_events_path=tmp_path / "e", interrupted=True).status == "cancelled"


def test_the_run_is_experimental_and_does_not_report_the_served_model():
    assert KiroCliAdapter.experimental is True and KiroCliAdapter.model_unverified is True
    caps = KiroCliAdapter().capabilities()
    assert caps.schema_mode == "prompt_contract" and not caps.resume and not caps.served_model


R28 = Path(__file__).parents[2] / "fixtures" / "recorded" / "kiro-cli" / "2.28.0"


def test_the_stream_gives_the_session_and_the_final_text(tmp_path):
    lines = (R28 / "hello.stream.jsonl").read_text().splitlines()
    out = KiroCliAdapter().parse(
        lines, exit_code=0, raw_events_path=tmp_path / "e", result_text='{"status": "done"}', schema=SCHEMA
    )
    assert out.status == "ok" and out.session_id == "20373329-a874-487e-8a01-8ddee2cdc356"
    assert out.final_text == "L4-OK"


def test_a_run_error_names_its_stage_and_is_a_failed_attempt(tmp_path):
    lines = (R28 / "missing-agent.stream.jsonl").read_text().splitlines()
    out = KiroCliAdapter().parse(lines, exit_code=4, raw_events_path=tmp_path / "e")
    assert out.status == "error" and out.limit is None
    assert out.detail is not None and "runError" in out.detail and "init" in out.detail and "exited" in out.detail


def test_out_of_credits_is_a_credits_limit_not_a_failed_attempt(tmp_path):
    """The wording is [U] (never recorded): a runError that names credits and being used up. Raw events keep it."""
    err = '{"type":"runError","data":{"stage":"turn","message":"You have used all your credits for this month"}}'
    out = KiroCliAdapter().parse([err], exit_code=1, raw_events_path=tmp_path / "e")
    assert out.status == "quota" and out.limit is not None and out.limit.kind == "credits"
    other = '{"type":"runError","data":{"stage":"turn","message":"credit card on file"}}'
    assert KiroCliAdapter().parse([other], exit_code=1, raw_events_path=tmp_path / "e").limit is None


def test_run_hands_the_recorded_stream_to_parse(tmp_path):
    class Streaming(FakeProc):
        def run(self, argv, env, cwd, *, stdout_path, **kw):
            super().run(argv, env, cwd, stdout_path=stdout_path, **kw)
            stdout_path.write_text((R28 / "hello.stream.jsonl").read_text())
            return ProcOutcome(0)

    out = KiroCliAdapter(Streaming()).run(request(tmp_path))
    assert out.session_id == "20373329-a874-487e-8a01-8ddee2cdc356"


# --- K3: the harness agent (kiro-e2e H1 live-fix) ------------------------------------------------------------------
# On the default agent the user's MCP servers, skills, steering and `~/.kiro/settings/permissions.yaml` reach the run,
# and on the Mac kiro-cli 2.28.0 denied every write and shell call in 3 of 4 harness-spawned implementer steps although
# `--trust-tools=fs_read,fs_write,execute_bash` named them (docs/live/kiro-e2e/h1). Under a harness-written agent with
# five native tools and `--trust-all-tools`, a private `KIRO_HOME` holding only that agent, the same red prompt ran with
# 0 denials and no MCP server [V, 2.28.0].

BARE = Profile(adapter="kiro-cli", model="qwen3-coder-next", vendor="alibaba")


def test_an_implementer_step_runs_a_harness_agent_with_trust_all_in_a_private_kiro_home(tmp_path):
    proc = FakeProc()
    KiroCliAdapter(proc).run(request(tmp_path, profile=BARE))
    call = proc.calls[0]
    argv = call["argv"]
    agent = argv[argv.index("--agent") + 1]
    assert agent.startswith("l4-implement-") and len(agent) > len("l4-implement-")
    assert argv[1:] == [
        "chat", "--no-interactive", "--agent", agent, "--trust-all-tools",
        "--model", "qwen3-coder-next", "--output-format", "stream-json", "--require-mcp-startup", "do the task",
    ]  # fmt: skip
    assert not any(a.startswith("--trust-tools") for a in argv)
    home = Path(call["env"]["KIRO_HOME"])
    assert home.parent == tmp_path / "res"  # the step's private directory, never the worktree or the user's ~/.kiro
    import json

    config = json.loads((home / "agents" / f"{agent}.json").read_text(encoding="utf-8"))
    assert config["name"] == agent
    assert config["tools"] == ["read", "write", "shell", "glob", "grep"]
    assert config["includeMcpJson"] is False and config["mcpServers"] == {} and config["resources"] == []
    assert config["allowedTools"] == [] and config["toolsSettings"] == {}
    assert sorted(home.iterdir()) == [home / "agents"]  # no user settings, MCP config, skills or steering
    assert call["env"]["PATH"] == str(tmp_path / "bin")  # the rest of the built environment is passed unchanged


def test_each_step_gets_an_agent_name_a_repository_cannot_predict(tmp_path):
    proc = FakeProc()
    KiroCliAdapter(proc).run(request(tmp_path, profile=BARE))
    KiroCliAdapter(proc).run(request(tmp_path, profile=BARE))
    names = [c["argv"][c["argv"].index("--agent") + 1] for c in proc.calls]
    assert names[0] != names[1]  # a workspace `.kiro/agents/<name>.json` would shadow a fixed name


def test_a_configured_agent_keeps_the_trust_list_and_the_users_kiro_home(tmp_path):
    """`options.agent` names the operator's own agent (G2 uses a missing one for its exit-4 halt): unchanged."""
    proc = FakeProc()
    KiroCliAdapter(proc).run(request(tmp_path))
    assert "KIRO_HOME" not in proc.calls[0]["env"] and "--trust-all-tools" not in proc.calls[0]["argv"]


def test_read_only_and_judge_steps_keep_their_trust_lists(tmp_path):
    for mode in ("read_only", "judge"):
        proc = FakeProc()
        KiroCliAdapter(proc).run(request(tmp_path, profile=BARE, permission_policy=PermissionPolicy(mode)))
        assert "--trust-all-tools" not in proc.calls[0]["argv"] and "KIRO_HOME" not in proc.calls[0]["env"]


NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def adapter(**kw) -> KiroCliAdapter:
    return KiroCliAdapter(clock=lambda: NOW, **kw)


def test_free_tier_throttling_is_a_rate_limit_not_a_failed_attempt(tmp_path):
    """Kiro e2e H2 (job 6146, 1.1 green attempt 1): `runError at prompt`, "The request was throttled by the service".
    It counted as a failed attempt; a third one in a row would have halted the unit."""
    lines = (R28 / "throttled.stream.jsonl").read_text().splitlines()
    out = adapter().parse(lines, exit_code=1, raw_events_path=tmp_path / "e")
    assert out.status == "rate_limited" and out.limit is not None
    assert (out.limit.kind, out.limit.source, out.limit.tool) == ("rate_limit", "kiro.run_error", "kiro-cli")
    assert out.limit.resets_at == NOW + timedelta(minutes=2)  # the short default
    assert out.session_id == "dc8effe3-f3c1-4ae2-9775-7a6bbb162922"
    assert out.detail is not None and "throttled" in out.detail and "prompt" in out.detail


def test_a_retry_hint_in_the_throttle_message_sets_the_cooldown(tmp_path):
    err = '{"type":"runError","data":{"stage":"turn","message":"Too many requests, retry in 45s"}}'
    out = adapter().parse([err], exit_code=1, raw_events_path=tmp_path / "e")
    assert out.status == "rate_limited" and out.limit is not None
    assert out.limit.resets_at == NOW + timedelta(seconds=45)


def test_throttling_wording_is_not_mistaken_for_other_errors(tmp_path):
    other = '{"type":"runError","data":{"stage":"turn","message":"Internal error (code -32603): model not found"}}'
    out = adapter().parse([other], exit_code=1, raw_events_path=tmp_path / "e")
    assert out.status == "error" and out.limit is None
    credits = '{"type":"runError","data":{"stage":"turn","message":"throttled: you have used all your credits"}}'
    assert adapter().parse([credits], exit_code=1, raw_events_path=tmp_path / "e").limit.kind == "credits"


def test_the_stream_metering_is_credits_with_its_source_never_dollars(tmp_path):
    """Kiro e2e H2: the CI streams metered 10.72 credits while `/usage` rose by 5.42 (FREE). The stream's number is kept
    as credits, labelled with where it came from; `cost_usd` stays None, so no budget counts it as dollars."""
    lines = (R28 / "throttled.stream.jsonl").read_text().splitlines()
    out = adapter().parse(lines, exit_code=1, raw_events_path=tmp_path / "e")
    assert out.usage.credits == pytest.approx(0.1095762305140962 + 0.19826163018242124 + 0.21373383416252073)
    assert out.usage.credits_source == "kiro.stream" and out.usage.cost_usd is None
    hello = adapter().parse(
        (R28 / "hello.stream.jsonl").read_text().splitlines(), exit_code=0, raw_events_path=tmp_path / "e"
    )
    assert hello.usage.credits == pytest.approx(0.027819477611940292)
    silent = '{"type":"runFinished","data":{"status":"success","finalText":"x"}}'
    unmetered = adapter().parse([silent], exit_code=0, raw_events_path=tmp_path / "e")
    assert unmetered.usage.credits is None and unmetered.usage.credits_source is None  # v3 spec runs meter nothing


def _parsed(name: str, tmp_path):
    return adapter().parse((R28 / name).read_text().splitlines(), exit_code=0, raw_events_path=tmp_path / "e")


def test_last_message_is_the_text_after_the_last_tool_call_and_final_text_is_unchanged(tmp_path):
    """SCN-FAC-17 (kiro part): `finalText` holds all the text; `last_message` only what follows the last tool call."""
    out = _parsed("red-tools.stream.jsonl", tmp_path)
    assert out.final_text and out.last_message
    assert len(out.last_message) < len(out.final_text) and out.final_text.endswith(out.last_message)
    assert out.last_message.startswith("The RED") and not out.last_message.startswith("I'll start")
    assert "Let me l" not in out.last_message
    hello = _parsed("hello.stream.jsonl", tmp_path)  # no tool call: the whole text
    assert hello.last_message == "L4-OK" == hello.final_text


def test_no_agent_text_gives_no_last_message(tmp_path):
    silent = '{"type":"runFinished","data":{"status":"success","finalText":"x"}}'
    assert adapter().parse([silent], exit_code=0, raw_events_path=tmp_path / "e").last_message is None


def test_the_context_peak_is_the_largest_context_usage_percentage(tmp_path):
    """SCN-FAC-18 (kiro part): the largest `metadata.contextUsagePercentage`, with the credits kept."""
    tools = _parsed("red-tools.stream.jsonl", tmp_path)
    assert tools.usage.context_peak_percent == pytest.approx(14.687499046325684)
    assert tools.usage.context_peak_tokens is None and tools.usage.credits is not None
    assert _parsed("hello.stream.jsonl", tmp_path).usage.context_peak_percent == pytest.approx(8.037500381469727)
    lines = [
        '{"type":"metadata","data":{"contextUsagePercentage":1.1}}',
        '{"type":"metadata","data":{"contextUsagePercentage":3.6}}',
        '{"type":"metadata","data":{"contextUsagePercentage":2.0}}',
    ]
    out = adapter().parse(lines, exit_code=0, raw_events_path=tmp_path / "e")
    assert out.usage.context_peak_percent == 3.6 and out.usage.credits is None
    none = adapter().parse(['{"type":"runStarted","data":{}}'], exit_code=0, raw_events_path=tmp_path / "e")
    assert none.usage.context_peak_percent is None
