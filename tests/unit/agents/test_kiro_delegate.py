"""The kiro-cli delegate runs a read-only harness agent (L4-DLG-017; SCN-DLG-61, 63, 103): its own agent with the three
read tools in a private `KIRO_HOME`, the prompt on stdin, the served model from the session file, every tool name of
the run kept, credits recorded and never converted."""

import json
from pathlib import Path

import pytest

from l4.agents.base import PermissionPolicy, RunRequest
from l4.agents.kiro_cli import DELEGATE_PREFIX, DELEGATE_TOOLS, KiroCliAdapter, stream_events, stream_facts
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile

from .cli_streams import SESSION, kiro_call, kiro_chunk, kiro_event, kiro_stream

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "kiro-cli"
SONNET = Profile(adapter="kiro-cli", model="claude-sonnet-4.5", vendor="anthropic")
SCHEMA = {"type": "object", "required": ["decision"], "properties": {"decision": {"enum": ["answer", "escalate"]}}}
REPLY = '{"decision": "answer"}'
RAW = Path("events.jsonl")


class RecordingProc:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, argv, env, cwd, *, stdout_path, timeout_s, stdin=None, stderr_path=None, **kw):
        home = env.get("KIRO_HOME")
        files = None
        if home:
            files = {
                str(p.relative_to(home)): (p.read_text(encoding="utf-8") if p.is_file() else None)
                for p in sorted(Path(home).rglob("*"))
            }
        self.calls.append({"argv": list(argv), "env": dict(env), "stdin": stdin, "cwd": Path(cwd), "home_files": files})
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text("")
        return ProcOutcome(0)


def request(tmp_path: Path, profile: Profile = SONNET, prompt: str = "answer this", **kw) -> RunRequest:
    (tmp_path / "bin").mkdir(exist_ok=True)
    exe = tmp_path / "bin" / "kiro-cli"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    env = {"PATH": str(tmp_path / "bin"), **kw.pop("env", {})}
    return RunRequest(
        role="delegate", cwd=tmp_path / "wt", result_path=tmp_path / "res" / "result.json",
        raw_events_path=tmp_path / "raw" / "events.jsonl", env=env, profile=profile, prompt=prompt,
        permission_policy=PermissionPolicy("read_only"), **kw,
    )  # fmt: skip


def run(tmp_path: Path, **kw) -> dict:
    proc = RecordingProc()
    KiroCliAdapter(proc).run(request(tmp_path, **kw))
    return proc.calls[0]


def test_the_delegate_runs_its_own_read_only_agent(tmp_path):  # SCN-DLG-61
    leftover = tmp_path / "res" / "kiro-home" / "agents" / "old.json"
    leftover.parent.mkdir(parents=True)
    leftover.write_text("{}")
    call = run(tmp_path, env={"KIRO_LOG_LEVEL": "trace", "KIRO_HOME": "/users/own"})
    argv = call["argv"]
    name = argv[argv.index("--agent") + 1]
    assert name.startswith(DELEGATE_PREFIX) and len(name) == len(DELEGATE_PREFIX) + 12
    assert argv[1:] == [
        "chat", "--no-interactive", "--v2", "--agent", name, "--model", "claude-sonnet-4.5", "--trust-all-tools",
        "--output-format", "stream-json",
    ]  # fmt: skip
    assert not any(a.startswith("--trust-tools") or a == "--require-mcp-startup" for a in argv)
    assert "answer this" not in argv and call["stdin"] == "answer this"
    assert call["cwd"] == tmp_path / "wt"  # the detached worktree, not an empty directory
    assert call["env"]["KIRO_HOME"] == str(tmp_path / "res" / "kiro-home") and "KIRO_LOG_LEVEL" not in call["env"]
    assert sorted(call["home_files"]) == sorted(["agents", f"agents/{name}.json", "settings", "settings/cli.json"])
    assert json.loads(call["home_files"][f"agents/{name}.json"]) == {
        "name": name, "description": "L4 harness delegate: read-only file tools", "prompt": None, "mcpServers": {},
        "tools": ["read", "glob", "grep"], "toolAliases": {}, "allowedTools": ["read", "glob", "grep"],
        "resources": [], "hooks": {}, "toolsSettings": {}, "includeMcpJson": False, "model": "claude-sonnet-4.5",
    }  # fmt: skip
    assert json.loads(call["home_files"]["settings/cli.json"]) == {
        "chat.disableInheritingDefaultResources": True, "chat.agentEngine": "v2",
        "chat.enableAutoAgentUpgrade": False, "app.disableAutoupdates": True,
    }  # fmt: skip
    assert DELEGATE_TOOLS == ("read", "glob", "grep")


def test_a_prompt_over_the_argument_cap_goes_on_stdin(tmp_path):
    prompt = "x" * 200_000
    call = run(tmp_path, prompt=prompt)
    assert call["stdin"] == prompt and not any(prompt in a for a in call["argv"])


def test_a_profile_with_no_model_runs_auto(tmp_path):
    call = run(tmp_path, profile=Profile(adapter="kiro-cli"))
    argv = call["argv"]
    assert argv[argv.index("--model") + 1] == "auto"
    assert json.loads(call["home_files"][f"agents/{argv[argv.index('--agent') + 1]}.json"])["model"] == "auto"


def test_an_empty_prompt_is_refused_before_the_spawn(tmp_path):
    from l4.agents.base import AdapterError

    proc = RecordingProc()
    with pytest.raises(AdapterError, match="empty"):
        KiroCliAdapter(proc).run(request(tmp_path, prompt=" \n"))
    assert proc.calls == []


def parse(lines, **kw):
    return KiroCliAdapter().parse(lines, exit_code=0, raw_events_path=RAW, read_only=True, schema=SCHEMA, **kw)


def error_event() -> str:
    return kiro_event("runError", {"stage": "turn", "message": "boom"})


@pytest.mark.parametrize(
    ("lines", "why"),
    [
        (kiro_stream(kiro_chunk(REPLY), final=REPLY, engine="v3"), "engine v3"),
        (kiro_stream(error_event(), kiro_chunk(REPLY), final=REPLY), "runError"),
        (kiro_stream(kiro_call("write"), kiro_chunk(REPLY), final=REPLY), "write"),
        (kiro_stream(kiro_call("shell"), kiro_chunk(REPLY), final=REPLY), "shell"),
        (kiro_stream(kiro_call("web_search"), kiro_chunk(REPLY), final=REPLY), "web_search"),
    ],
)
def test_another_engine_a_run_error_or_a_write_tool_is_no_reply(lines, why):
    result = parse(lines)
    assert result.status == "error" and result.structured is None and why in (result.detail or "")


@pytest.mark.parametrize("tool", DELEGATE_TOOLS)
def test_a_read_tool_is_fine(tool):
    result = parse(kiro_stream(kiro_call(tool), kiro_chunk(REPLY), final=REPLY))
    assert result.status == "ok" and result.structured == {"decision": "answer"}


def test_the_served_model_comes_from_the_session_file(tmp_path):
    (tmp_path / "sessions" / "cli").mkdir(parents=True)
    state = {"session_state": {"rts_model_state": {"model_info": {"model_id": "claude-sonnet-4.5"}}}}
    (tmp_path / "sessions" / "cli" / f"{SESSION}.json").write_text(json.dumps(state))
    lines = kiro_stream(kiro_call("read"), kiro_chunk(REPLY), final=REPLY)
    result = parse(lines, kiro_home=tmp_path, model="claude-sonnet-4.5")
    assert result.status == "ok" and result.model_resolved == "claude-sonnet-4.5"  # also when pinned and equal
    other = {"session_state": {"rts_model_state": {"model_info": {"model_id": "claude-haiku-4.5"}}}}
    (tmp_path / "sessions" / "cli" / f"{SESSION}.json").write_text(json.dumps(other))
    wrong = parse(lines, kiro_home=tmp_path, model="claude-sonnet-4.5")
    assert wrong.status == "error" and wrong.structured is None and wrong.model_resolved == "claude-haiku-4.5"
    assert wrong.detail == "model_mismatch: kiro-cli selected claude-haiku-4.5, the profile names claude-sonnet-4.5"
    no_file = parse(lines, kiro_home=tmp_path / "none", model="claude-sonnet-4.5")
    assert no_file.status == "ok" and no_file.model_resolved is None


def test_credits_are_usage_credits():
    lines = (RECORDED / "2.32.0" / "judge-pass.stream.jsonl").read_text().splitlines()
    result = KiroCliAdapter().parse(lines, exit_code=0, raw_events_path=RAW, read_only=True, schema=None)
    assert result.status == "ok"
    assert result.usage.credits == pytest.approx(0.20670165854063016) and result.usage.cost_usd is None
    assert result.usage.credits_source == "kiro.stream"


def test_a_turn_keeps_every_tool_name():  # SCN-DLG-103
    lines = kiro_stream(
        kiro_call("read"),
        kiro_call("read", "tool_call_update"),
        kiro_call("grep"),
        kiro_call("web_search"),
        kiro_chunk(REPLY),
        final=REPLY,
    )
    facts = stream_facts(stream_events("\n".join(lines)))
    assert facts["tool_names"] == ["read", "grep", "web_search"] and facts["tool_name"] == "read"


def test_an_update_without_a_tool_name_names_no_tool():
    update = {"sessionUpdate": "tool_call_update", "toolCallId": "t", "title": "Reading x.py", "kind": "read"}
    event = kiro_event("sessionUpdate", {"sessionId": SESSION, "update": update})
    facts = stream_facts(stream_events("\n".join(kiro_stream(kiro_call("read"), event, final=REPLY))))
    assert facts["tool_names"] == ["read"]


def test_a_call_to_a_tool_the_agent_lacks_voids_the_run():  # SCN-DLG-103
    lines = kiro_stream(kiro_call("read"), kiro_call("nonexistent_tool"), kiro_chunk(REPLY), final=REPLY)
    result = parse(lines)
    assert result.status == "error" and result.structured is None
    assert "nonexistent_tool" in (result.detail or "") and not (result.detail or "").startswith("structured")


def test_a_recorded_run_that_wrote_and_ran_a_command_gives_no_reply():
    lines = (RECORDED / "2.28.0" / "red-tools.stream.jsonl").read_text().splitlines()
    result = KiroCliAdapter().parse(lines, exit_code=0, raw_events_path=RAW, read_only=True, schema=None)
    assert result.status == "error" and result.structured is None
    assert "shell" in (result.detail or "") and "write" in (result.detail or "")
