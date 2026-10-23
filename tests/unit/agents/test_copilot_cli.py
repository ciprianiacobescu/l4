"""The Copilot CLI adapter `l4.agents.copilot_cli` (copilot-cli 2.1): the parse, the stop watcher and the usage
document, against streams recorded on Copilot CLI 1.0.102 in BYOK mode (a local OpenAI-compatible model) and against
the first GitHub-routed calls (`1.0.102-firstcalls`)."""

import json
import os
from pathlib import Path

import pytest

from l4.agents import copilot_cli
from l4.agents.activity import copilot_signals
from l4.agents.base import AdapterError, AgentCaps, McpServer, PermissionPolicy, RunRequest
from l4.agents.copilot_cli import (
    CopilotCliAdapter,
    CopilotStop,
    build_command,
    effective_model,
    gate_rule,
    parse,
    read_usage,
    stream_facts,
    usage_of,
    write_home,
    write_run_cache,
)
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile
from l4.recordedversions import load
from l4.verifier.judge import MODEL_MISMATCH_DETAIL

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "copilot-cli" / "1.0.102-byok"
FIRSTCALLS = Path(__file__).parents[2] / "fixtures" / "recorded" / "copilot-cli" / "1.0.102-firstcalls"
ROUTED = Path(__file__).parents[2] / "fixtures" / "recorded" / "copilot-cli" / "1.0.102"
PROFILE = Profile(adapter="copilot-cli", model="claude-sonnet-5.5")
SCHEMA = {"type": "object", "required": ["status"], "properties": {"status": {"type": "string"}}}
VERDICT = {"status": "pass"}


def recorded(name: str) -> str:
    return (RECORDED / name).read_text(encoding="utf-8")


def firstcall(name: str) -> str:
    return (FIRSTCALLS / name).read_text(encoding="utf-8")


def routed(name: str) -> str:
    return (ROUTED / name).read_text(encoding="utf-8")


def with_last_content(text: str, content: str) -> str:
    """The stream with the content of its last `assistant.message` replaced."""
    lines = text.splitlines()
    index = max(i for i, line in enumerate(lines) if json.loads(line)["type"] == "assistant.message")
    event = json.loads(lines[index])
    event["data"]["content"] = content
    lines[index] = json.dumps(event)
    return "\n".join(lines) + "\n"


def event_line(kind: str, **data) -> str:
    return json.dumps({"type": kind, "data": data})


def denied(call: str = "c") -> str:
    return event_line("tool.execution_complete", toolCallId=call, success=False, error={"code": "denied"})


def succeeded(call: str = "c") -> str:
    return event_line("tool.execution_complete", toolCallId=call, success=True)


def feed(watcher: CopilotStop, lines: list[str]) -> list[int]:
    """The 1-based numbers of the lines for which the watcher returned True."""
    return [n for n, line in enumerate(lines, 1) if watcher(line)]


def request(tmp_path: Path, **kw) -> RunRequest:
    kw.setdefault("profile", PROFILE)
    kw.setdefault("prompt", "do the task")
    kw.setdefault("env", {"PATH": str(tmp_path / "bin")})
    (tmp_path / "bin").mkdir(parents=True, exist_ok=True)
    exe = tmp_path / "bin" / "copilot"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    (tmp_path / "wt").mkdir(parents=True, exist_ok=True)
    return RunRequest(
        role="implementer", cwd=tmp_path / "wt", result_path=tmp_path / "step" / "result.json",
        raw_events_path=tmp_path / "raw" / "events.jsonl", **kw,
    )  # fmt: skip


class FakeProc:
    def __init__(self, stdout: str = "") -> None:
        self.calls: list[dict] = []
        self.stdout = stdout

    def run(self, argv, env, cwd, *, stdout_path, timeout_s, stdin=None, stderr_path=None, on_line=None, **kw):
        call = {"argv": list(argv), "env": dict(env), "stdin": stdin, "cwd": cwd, "on_line": on_line, **kw}
        self.calls.append(call)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(self.stdout)
        # files the CLI would have written at the spawn, seen before the run ends
        call["seen"] = {
            n: (Path(env["COPILOT_HOME"]).parent / n).exists() for n in ("copilot-usage.json", "result.json")
        }
        for line in self.stdout.splitlines():
            if on_line is not None and on_line(line):
                call["stopped_at"] = line
                break
        return ProcOutcome(0)


def judge(text: str, tmp_path: Path, **kw):
    return parse(text, exit_code=0, raw_events_path=tmp_path / "e", mode="judge", schema=SCHEMA, **kw)


# the run, as the prototype has it until 3.1: only the names changed


def test_the_adapter_is_named_copilot_cli_and_a_judge_gets_an_unknown_tool_name(tmp_path):
    """An empty `--available-tools` leaves every tool on 1.0.102 [V]: the judge names a tool that does not exist."""
    assert copilot_cli.NAME == "copilot-cli" and CopilotCliAdapter().name == "copilot-cli"
    req = request(tmp_path, permission_policy=PermissionPolicy("judge"))
    argv = build_command(req, exe="copilot", session_id="s", usage_path=Path("u"))
    assert "--available-tools=l4_no_tools" in argv
    assert not any(a in ("--available-tools", "--available-tools=") for a in argv)
    assert not any(a.startswith("--allow") for a in argv)


def test_the_constants_of_the_contract():
    assert (copilot_cli.BINARY, copilot_cli.MCP_FILE, copilot_cli.USAGE_LIMIT) == (
        "copilot",
        "copilot-mcp.json",
        1_048_576,
    )
    assert (copilot_cli.AUTO_MODEL, copilot_cli.DENIAL_LIMIT, copilot_cli.RUN_CACHE_DIR) == ("auto", 20, "xdg-cache")
    assert copilot_cli.COMMON_FLAGS == (
        "--output-format", "json", "--no-ask-user", "--no-auto-update", "--no-custom-instructions",
        "--disable-builtin-mcps", "--disable-client-telemetry", "--disallow-temp-dir",
    )  # fmt: skip


def test_the_delegate_reads_only_and_the_implementer_runs_only_the_gate_binary(tmp_path):
    reader = build_command(
        request(tmp_path, permission_policy=PermissionPolicy("read_only")), exe="copilot", session_id="s",
        usage_path=Path("u"),
    )  # fmt: skip
    assert "--available-tools=view,grep,glob" in reader and not any(a.startswith("--allow") for a in reader)
    req = request(tmp_path, permission_policy=PermissionPolicy("implement", gate_prefix=".venv/bin/python -m pytest"))
    implementer = build_command(req, exe="copilot", session_id="s", usage_path=Path("u"))
    assert "--allow-tool=write" in implementer and "--allow-tool=shell(.venv/bin/python:*)" in implementer
    assert "--allow-all-tools" not in implementer and "--yolo" not in implementer
    assert implementer[implementer.index("--add-dir") + 1] == str(req.result_path.parent)


def test_every_run_is_isolated_and_reads_its_prompt_from_stdin(tmp_path):
    proc = FakeProc(recorded("implement-bash.jsonl"))
    req = request(tmp_path, env={"PATH": str(tmp_path / "bin"), "COPILOT_ALLOW_ALL": "true"})
    CopilotCliAdapter(proc).run(req)
    call = proc.calls[0]
    assert call["stdin"] == "do the task" and "do the task" not in call["argv"] and "-p" not in call["argv"]
    for flag in copilot_cli.COMMON_FLAGS[2:]:
        assert flag in call["argv"]
    assert "COPILOT_ALLOW_ALL" not in call["env"]
    home = Path(call["env"]["COPILOT_HOME"])
    assert home.parent == req.result_path.parent
    assert json.loads((home / "settings.json").read_text())["includeCoAuthoredBy"] is False


# 3.1: the run

TOKEN = "github_pat_" + "x" * 40


def copilot_argv(call: dict) -> list[str]:
    """The `copilot` argv of a spawn, behind the credential loader when there is one."""
    argv = call["argv"]
    return argv[
        argv.index("copilot") if "copilot" in argv else next(i for i, a in enumerate(argv) if a.endswith("/copilot")) :
    ]


def common_argv(session: str, step: Path, model: str) -> list[str]:
    return [
        *copilot_cli.COMMON_FLAGS, "--session-id", session, "--usage-output-file", str(step / "copilot-usage.json"),
        "--model", model,
    ]  # fmt: skip


def run_mode(tmp_path: Path, mode: str, stdout: str = "", **kw) -> tuple[FakeProc, RunRequest]:
    proc = FakeProc(stdout)
    policy = kw.pop("permission_policy", PermissionPolicy(mode))
    req = request(tmp_path, permission_policy=policy, **kw)
    CopilotCliAdapter(proc).run(req)
    return proc, req


def test_scn_fac_22_every_mode_starts_with_the_common_argv_and_the_prompt_goes_on_stdin(tmp_path):
    l4_home = tmp_path / "l4"
    for mode in ("judge", "read_only", "implement"):
        step = tmp_path / mode
        proc = FakeProc("")
        req = request(
            step, permission_policy=PermissionPolicy(mode), preset_session_id="sess-1",
            host_env={"L4_HOME": str(l4_home)},
        )  # fmt: skip
        CopilotCliAdapter(proc).run(req)
        call = proc.calls[0]
        argv = copilot_argv(call)
        assert argv[1:15] == common_argv("sess-1", req.result_path.parent, "claude-sonnet-5.5")
        assert call["stdin"] == "do the task" and "do the task" not in call["argv"]
        env = call["env"]
        home = Path(env["COPILOT_HOME"])
        assert home == req.result_path.parent / "copilot-home" and sorted(p.name for p in home.iterdir()) == [
            "settings.json"
        ]
        assert json.loads((home / "settings.json").read_text()) == copilot_cli.HOME_SETTINGS
        assert env["COPILOT_AUTO_UPDATE"] == "false"
        cache = req.result_path.parent / "xdg-cache"
        assert env["XDG_CACHE_HOME"] == str(cache)
        assert [p.name for p in cache.iterdir()] == ["copilot"] and [p.name for p in (cache / "copilot").iterdir()] == [
            "pkg"
        ]
        assert (cache / "copilot" / "pkg").is_symlink()
        assert os.readlink(cache / "copilot" / "pkg") == str(l4_home / "copilot-cache" / "copilot" / "pkg")


def test_a_file_left_in_the_run_cache_by_an_earlier_run_is_gone(tmp_path):
    req = request(tmp_path, host_env={"L4_HOME": str(tmp_path / "l4")})
    planted = req.result_path.parent / "xdg-cache" / "go-build"
    planted.mkdir(parents=True)
    (planted / "planted").write_text("x")
    CopilotCliAdapter(FakeProc("")).run(req)
    assert not planted.exists()


def test_scn_fac_23_a_profile_with_no_model_or_auto_in_any_case_runs_auto(tmp_path):
    for n, model in enumerate((None, "AUTO", " Auto ")):
        proc, _ = run_mode(
            tmp_path / str(n), "judge", profile=Profile(adapter="copilot-cli", model=model), preset_session_id="s"
        )
        argv = copilot_argv(proc.calls[0])
        assert argv[argv.index("--model") + 1] == "auto"
    assert [effective_model(Profile(adapter="copilot-cli", model=m)) for m in (None, "", "AUTO", "gpt-6-luna")] == [
        "auto", "auto", "auto", "gpt-6-luna",
    ]  # fmt: skip


def test_scn_fac_24_no_forge_token_trust_all_or_ci_variable_reaches_the_cli(tmp_path):
    host = {"GH_TOKEN": "g", "GITHUB_TOKEN": "g", "CI": "true", "COPILOT_GITHUB_TOKEN": TOKEN, "L4_HOME": str(tmp_path)}
    proc = FakeProc("")
    adapter = CopilotCliAdapter(proc)
    req = request(tmp_path, env={"PATH": str(tmp_path / "bin"), "COPILOT_ALLOW_ALL": "true"}, host_env=host)
    adapter.run(req)
    call = proc.calls[0]
    for name in ("COPILOT_ALLOW_ALL", "GH_TOKEN", "GITHUB_TOKEN", "CI", "COPILOT_GITHUB_TOKEN"):
        assert name not in call["env"]
    assert TOKEN not in " ".join(call["argv"]) and call["argv"][:2] == ["/bin/sh", "-c"]  # behind the loader
    assert not any(
        a in ("--available-tools", "--available-tools=") or a.startswith(("--allow-all", "--yolo"))
        for a in call["argv"]
    )
    assert not (req.result_path.parent / "credential").exists()  # the loader's file does not outlive the run
    empty = request(tmp_path / "second", prompt="  \n", host_env=host)
    with pytest.raises(AdapterError) as refused:
        adapter.run(empty)
    assert str(refused.value) == "the prompt is empty; copilot-cli reads its prompt from stdin"
    assert len(proc.calls) == 1


def test_a_missing_binary_is_refused_with_t1(tmp_path):
    req = request(tmp_path, env={"PATH": str(tmp_path / "empty")})
    with pytest.raises(AdapterError, match="copilot was not found on the agent PATH"):
        CopilotCliAdapter(FakeProc("")).run(req)


def test_an_exe_given_to_the_constructor_skips_the_path_lookup(tmp_path):
    proc = FakeProc("")
    req = request(tmp_path, env={"PATH": str(tmp_path / "empty")})
    CopilotCliAdapter(proc, exe="/replay/copilot").run(req)
    assert proc.calls[0]["argv"][0] == "/replay/copilot"


def test_scn_fac_26_the_judge_argv_names_an_unknown_tool_and_runs_in_the_empty_judge_cwd(tmp_path):
    proc, req = run_mode(tmp_path, "judge", preset_session_id="s")
    call = proc.calls[0]
    argv = copilot_argv(call)
    assert argv[15:] == ["--available-tools=l4_no_tools"]
    assert call["cwd"] == req.result_path.parent / "judge-cwd" and not any(call["cwd"].iterdir())


def test_scn_fac_29_the_delegate_argv_is_the_read_set_in_the_worktree(tmp_path):
    proc, req = run_mode(tmp_path, "read_only", preset_session_id="s")
    argv = copilot_argv(proc.calls[0])
    assert argv[15:] == ["--available-tools=view,grep,glob"] and proc.calls[0]["cwd"] == req.cwd


def test_scn_fac_31_the_implementer_argv_allows_writes_the_gate_binary_and_the_result_directory(tmp_path):
    policy = PermissionPolicy("implement", gate_prefix=".venv/bin/python -m pytest")
    proc, req = run_mode(tmp_path, "implement", permission_policy=policy, preset_session_id="s")
    argv = copilot_argv(proc.calls[0])
    step = req.result_path.parent
    assert argv[15:] == ["--allow-tool=write", "--allow-tool=shell(.venv/bin/python:*)", "--add-dir", str(step)]
    assert proc.calls[0]["cwd"] == req.cwd
    assert gate_rule(None) == [] and gate_rule("  ") == [] and gate_rule("make test") == ["--allow-tool=shell(make:*)"]
    bare, _ = run_mode(tmp_path / "b", "implement", preset_session_id="s")
    assert "--allow-tool=write" in copilot_argv(bare.calls[0]) and not any(
        a.startswith("--allow-tool=shell") for a in copilot_argv(bare.calls[0])
    )


def test_scn_fac_33_an_mcp_server_is_injected_through_a_file_and_its_own_allow_rule(tmp_path):
    servers = [McpServer("serena", "uvx", ("serena", "start"), (("K", "v"),)), McpServer("other", "o")]
    policy = PermissionPolicy("implement", gate_prefix="pytest -q")
    proc, req = run_mode(tmp_path, "implement", permission_policy=policy, mcp_servers=servers, preset_session_id="s")
    step = req.result_path.parent
    config = step / "copilot-mcp.json"
    assert json.loads(config.read_text()) == {"mcpServers": {s.name: s.config_entry() for s in servers}}
    assert json.loads(config.read_text())["mcpServers"]["serena"]["command"] == "uvx"
    assert copilot_argv(proc.calls[0])[15:] == [
        "--allow-tool=write", "--allow-tool=shell(pytest:*)", "--add-dir", str(step),
        "--additional-mcp-config", f"@{config}", "--allow-tool=serena", "--allow-tool=other",
    ]  # fmt: skip
    for mode in ("judge", "read_only"):  # a judge or reader gets no tool server
        other, _ = run_mode(tmp_path / mode, mode, mcp_servers=servers, preset_session_id="s")
        assert "--additional-mcp-config" not in other.calls[0]["argv"]
        assert not (tmp_path / mode / "step" / "copilot-mcp.json").exists()


def test_the_run_passes_the_stream_reader_and_a_copilot_stop_watcher(tmp_path):
    proc, _ = run_mode(tmp_path, "implement")
    call = proc.calls[0]
    assert call["reader"] is copilot_signals and isinstance(call["on_line"], CopilotStop)
    assert run_mode(tmp_path / "2", "implement")[0].calls[0]["on_line"] is not call["on_line"]  # one per run


def test_scn_fac_37_a_run_stopped_on_the_first_429_is_rate_limited_with_t8(tmp_path):
    proc, req = run_mode(tmp_path, "implement", recorded("error-429-retrying.jsonl"))
    call = proc.calls[0]
    assert json.loads(call["stopped_at"])["type"] == "model.call_failure"  # before the assistant.turn_retry line
    out = CopilotCliAdapter(FakeProc(recorded("error-429-retrying.jsonl"))).run(request(tmp_path / "again"))
    assert out.status == "rate_limited" and out.limit is not None
    assert (
        out.detail
        == "copilot-cli hit a rate limit (HTTP 429); the harness stopped the run (it never waits for a limit)"
    )
    assert (out.limit.kind, out.limit.source, out.limit.resets_at) == ("rate_limit", "copilot.model_call_failure", None)


def test_twenty_denied_calls_in_a_row_end_as_permission_blocked(tmp_path):
    stream = "\n".join([denied(f"c{n}") for n in range(25)]) + "\n"
    out = CopilotCliAdapter(FakeProc(stream)).run(request(tmp_path))
    assert out.status == "permission_blocked" and "20 denied tool calls in a row" in (out.detail or "")


def test_the_usage_file_and_a_leftover_result_file_are_removed_before_the_spawn(tmp_path):
    req = request(tmp_path)
    step = req.result_path.parent
    step.mkdir(parents=True)
    (step / "copilot-usage.json").write_text("{}")
    req.result_path.write_text(json.dumps({"status": "stale"}))
    proc = FakeProc("")
    CopilotCliAdapter(proc).run(req)
    assert proc.calls[0]["seen"] == {"copilot-usage.json": False, "result.json": False}


def test_the_run_reads_the_usage_file_and_the_result_file_the_cli_wrote(tmp_path):
    class Writes(FakeProc):
        def run(self, argv, env, cwd, **kw):
            step = Path(env["COPILOT_HOME"]).parent
            (step / "copilot-usage.json").write_text((RECORDED / "implement-bash.usage.json").read_text())
            (step / "result.json").write_text(json.dumps(VERDICT))
            return super().run(argv, env, cwd, **kw)

    out = CopilotCliAdapter(Writes(recorded("implement-bash.jsonl"))).run(request(tmp_path, result_schema=SCHEMA))
    assert out.status == "ok" and out.structured == VERDICT and out.usage.output_tokens > 0


def test_capabilities_are_the_contract_of_5_1():
    assert CopilotCliAdapter().capabilities() == AgentCaps(
        "prompt_contract", False, True, False, False, True, False, True, served_model=True
    )
    assert CopilotCliAdapter().experimental is True


def test_write_home_removes_what_was_there_and_writes_only_settings(tmp_path):
    home = tmp_path / "copilot-home"
    (home / "session-state").mkdir(parents=True)
    (home / "session-state" / "old").write_text("x")
    assert write_home(home) == home and sorted(p.name for p in home.iterdir()) == ["settings.json"]
    assert (home / "settings.json").read_text() == json.dumps(copilot_cli.HOME_SETTINGS, indent=2)


@pytest.mark.parametrize("dangling", [False, True])
def test_write_home_replaces_a_planted_link_and_leaves_its_target_alone(tmp_path, dangling):
    """An implementer may write its step directory (`--add-dir`): a `copilot-home` link it left there is removed, never
    followed, whether or not its target exists."""
    target = tmp_path / "elsewhere"
    if not dangling:
        target.mkdir()
        (target / "keep").write_text("x")
    home = tmp_path / "step" / "copilot-home"
    home.parent.mkdir()
    home.symlink_to(target)
    assert write_home(home) == home and not home.is_symlink()
    assert sorted(p.name for p in home.iterdir()) == ["settings.json"]
    assert dangling or sorted(p.name for p in target.iterdir()) == ["keep"]


def test_write_run_cache_replaces_a_leftover_file_and_a_planted_pkg_directory_with_the_link(tmp_path):
    environ = {"L4_HOME": str(tmp_path / "l4")}
    step = tmp_path / "step"
    cache = step / "xdg-cache"
    (cache / "copilot" / "pkg" / "darwin-arm64").mkdir(parents=True)  # a package an agent planted
    (cache / "left").write_text("x")
    target = tmp_path / "l4" / "copilot-cache" / "copilot" / "pkg"
    for exists in (False, True):  # the link is made whether or not its target exists
        if exists:
            target.mkdir(parents=True)
        assert write_run_cache(step, environ) == cache
        link = cache / "copilot" / "pkg"
        assert link.is_symlink() and os.readlink(link) == str(target)
        assert sorted(p.name for p in cache.iterdir()) == ["copilot"]
    assert cache != tmp_path / "l4" / "copilot-cache"


def test_the_run_cache_is_never_the_l4_cache_in_any_mode(tmp_path):
    for mode in ("judge", "read_only", "implement"):
        proc, _ = run_mode(tmp_path / mode, mode, host_env={"L4_HOME": str(tmp_path / "l4")})
        assert proc.calls[0]["env"]["XDG_CACHE_HOME"] != str(tmp_path / "l4" / "copilot-cache")


# the parse


def test_scn_fac_27_a_judge_reply_with_prose_around_the_json_is_the_verdict(tmp_path):
    text = with_last_content(recorded("judge-hello.jsonl"), "Here is my verdict:\n" + json.dumps(VERDICT))
    out = judge(text, tmp_path)
    assert out.status == "ok" and out.structured == VERDICT and out.model_resolved == "qwen3.5:2b"
    assert out.session_id and out.exit_code == 0
    bare = judge(recorded("judge-hello.jsonl"), tmp_path)
    assert bare.status == "error" and bare.final_text == "L4-OK"
    assert (bare.detail or "").startswith("structured output missing")


def test_scn_fac_28_a_judge_that_called_a_tool_gives_no_verdict(tmp_path):
    text = with_last_content(recorded("delegate-view.jsonl"), json.dumps(VERDICT))
    out = judge(text, tmp_path)
    assert out.status == "error" and out.detail == "copilot-cli judge called a tool (view)" and out.structured is None


def test_scn_fac_29_the_delegate_reads_and_answers_after_its_last_read(tmp_path):
    facts = stream_facts(copilot_cli.events(recorded("delegate-view.jsonl")))
    assert facts["tools"] == ["view"] and "hello" in facts["last_message"] and facts["result_seen"] is True
    text = with_last_content(recorded("delegate-view.jsonl"), json.dumps(VERDICT))
    out = parse(text, exit_code=0, raw_events_path=tmp_path / "e", mode="read_only", schema=SCHEMA)
    assert out.status == "ok" and out.structured == VERDICT and out.last_message == json.dumps(VERDICT)
    plain = parse(recorded("delegate-view.jsonl"), exit_code=0, raw_events_path=tmp_path / "e", mode="read_only")
    assert plain.detail.startswith("structured output missing")  # the recorded reply holds no JSON object


def test_scn_fac_30_a_delegate_that_ran_a_non_read_tool_gives_no_reply_and_rg_counts_as_a_read(tmp_path):
    out = parse(recorded("implement-bash.jsonl"), exit_code=0, raw_events_path=tmp_path / "e", mode="read_only")
    assert out.status == "error" and out.structured is None
    assert out.detail == "copilot-cli delegate called a tool outside the read set (bash)"
    lines = [json.loads(line) for line in recorded("implement-bash.jsonl").splitlines()]
    for event in lines:
        if event["type"] == "tool.execution_start":
            event["data"]["toolName"] = "rg"
    rg = with_last_content("\n".join(json.dumps(e) for e in lines) + "\n", json.dumps(VERDICT))
    ok = parse(rg, exit_code=0, raw_events_path=tmp_path / "e", mode="read_only", schema=SCHEMA)
    assert ok.status == "ok" and ok.structured == VERDICT
    two = recorded("implement-bash.jsonl").replace('"toolName":"bash"', '"toolName":"edit"')
    names = parse(two, exit_code=0, raw_events_path=tmp_path / "e", mode="read_only")
    assert "(edit)" in names.detail


def test_scn_fac_32_a_denial_is_recorded_and_the_result_file_decides(tmp_path):
    out = parse(recorded("implement-denied.jsonl"), exit_code=0, raw_events_path=tmp_path / "e", schema=SCHEMA)
    assert out.permission_denials == [{"tool_name": "bash"}] and out.structured is None and out.status == "error"
    done = parse(
        recorded("implement-bash.jsonl"), exit_code=0, raw_events_path=tmp_path / "e",
        result_text='{"status": "green"}', schema=SCHEMA,
    )  # fmt: skip
    assert done.status == "ok" and done.structured == {"status": "green"} and done.permission_denials == []
    no_schema = parse(recorded("implement-denied.jsonl"), exit_code=0, raw_events_path=tmp_path / "e")
    assert no_schema.result_problem == "missing" and no_schema.status == "ok"  # no schema: the gates decide


def test_scn_fac_34_the_recorded_errors_map_to_statuses(tmp_path):
    def run(name: str):
        return parse(recorded(name), exit_code=1, raw_events_path=tmp_path / "e")

    auth = run("error-401.jsonl")
    assert auth.status == "auth" and auth.limit.kind == "auth" and auth.limit.source == "copilot.session_error"
    assert auth.detail == "copilot-cli could not authenticate (COPILOT_GITHUB_TOKEN is missing, expired or rejected)"
    quota = run("error-402.jsonl")
    assert quota.status == "quota" and quota.limit.kind == "credits" and quota.limit.source == "copilot.session_error"
    assert quota.detail == "copilot-cli reported that the AI credits are used up (session.error 402)"
    server = run("error-500.jsonl")
    assert server.status == "error" and server.transient and server.api_status == 500
    assert server.detail == "copilot-cli reported an error (query, status 500)"


def test_a_session_error_429_is_a_rate_limit_and_an_unknown_error_names_none(tmp_path):
    stream = event_line("session.error", errorType="query", statusCode=429, message="m")
    out = parse(stream, exit_code=1, raw_events_path=tmp_path / "e")
    assert out.status == "rate_limited" and out.detail == "copilot-cli reported a rate limit (session.error 429)"
    assert (
        out.limit.kind == "rate_limit" and out.limit.source == "copilot.session_error" and out.limit.resets_at is None
    )
    odd = parse(event_line("session.error", message="m"), exit_code=1, raw_events_path=tmp_path / "e")
    assert odd.status == "error" and odd.detail == "copilot-cli reported an error (unknown, status none)"
    assert odd.transient is False


def test_scn_fac_35_no_credential_is_an_auth_failure_with_no_stream(tmp_path):
    stderr = "Error: No authentication information found.\n\nCopilot can be authenticated with GitHub ..."
    out = parse("", exit_code=1, raw_events_path=tmp_path / "e", stderr_text=stderr)
    assert out.status == "auth" and out.detail == "copilot-cli found no credential (set COPILOT_GITHUB_TOKEN)"
    rejected = parse(
        "", exit_code=1, raw_events_path=tmp_path / "e", stderr_text=firstcall("bad-token.stderr.txt"),
    )  # fmt: skip
    assert rejected.status == "auth" and rejected.limit.kind == "auth" and rejected.limit.source == "copilot.stderr"
    assert (
        rejected.detail == "copilot-cli could not authenticate (COPILOT_GITHUB_TOKEN is missing, expired or rejected)"
    )
    assert firstcall("bad-token.exit.txt").strip() == "1"


def test_a_403_in_the_rejected_token_text_is_auth_and_without_a_status_it_is_a_retryable_error(tmp_path):
    first = "Error: Authentication token found but could not be validated."
    forbidden = parse(
        "", exit_code=1, raw_events_path=tmp_path / "e",
        stderr_text=f"{first}\n\n  Failed to fetch PAT user login (403): GitHub returned: Forbidden\n",
    )  # fmt: skip
    assert forbidden.status == "auth" and forbidden.limit.source == "copilot.stderr"
    alone = parse("", exit_code=1, raw_events_path=tmp_path / "e", stderr_text=first + "\n")
    assert alone.status == "error" and alone.transient is True and alone.limit is None
    assert alone.detail == "copilot-cli could not validate COPILOT_GITHUB_TOKEN (no 401 or 403: the network?)"


def test_scn_fac_36_a_cold_package_cache_and_an_unknown_exit_are_errors_that_name_the_cause(tmp_path):
    cold = parse(
        "", exit_code=1, raw_events_path=tmp_path / "e",
        stderr_text="Error: Failed to extract bundled package to /x: ENOENT",
    )  # fmt: skip
    assert cold.status == "error" and cold.detail == (
        "copilot-cli could not extract its bundled package (the L4 package cache is cold or not writable): "
        "run l4 doctor --fix"
    )
    other = parse("", exit_code=3, raw_events_path=tmp_path / "e", stderr_text="")
    assert other.status == "error" and other.detail == "copilot-cli exited with code 3"


def test_the_judge_auto_stream_names_its_model_reply_and_usage(tmp_path):
    """Recorded on a GitHub-routed Copilot Free account (F39, F40, F41)."""
    text, usage = firstcall("judge-auto.jsonl"), json.loads(firstcall("judge-auto.usage.json"))
    out = parse(text, exit_code=0, raw_events_path=tmp_path / "e", mode="judge", usage_document=usage)
    assert out.final_text == "L4-OK" and out.model_resolved == "gpt-6-luna"
    assert out.session_id == "869e1304-3ad8-4aa7-9148-1a38c5f973b7" and out.exit_code == 0
    assert stream_facts(copilot_cli.events(text))["tools"] == []
    assert (out.usage.input_tokens, out.usage.output_tokens, out.usage.cached_input_tokens) == (2938, 8, 0)
    assert out.usage.credits is not None and abs(out.usage.credits - 0.0371175) < 1e-12
    assert out.usage.credits_source == "copilot.usage_file" and out.usage.cost_usd is None
    ok = parse(
        with_last_content(text, json.dumps(VERDICT)), exit_code=0, raw_events_path=tmp_path / "e", mode="judge",
        schema=SCHEMA,
    )  # fmt: skip
    assert ok.status == "ok" and ok.structured == VERDICT


def test_a_run_that_failed_after_auto_routing_takes_the_chosen_model(tmp_path):
    lines = firstcall("judge-auto.jsonl").splitlines()
    cut = next(i for i, line in enumerate(lines) if json.loads(line)["type"] == "assistant.message")
    head = "\n".join(lines[:cut]) + "\n"
    assert "assistant.message" not in {e["type"] for e in copilot_cli.events(head)}
    out = parse(head, exit_code=1, raw_events_path=tmp_path / "e")
    assert out.model_resolved == "gpt-6-luna" and out.status == "error"
    # a served model that follows wins over the routing event
    both = firstcall("judge-auto.jsonl").replace(
        '"model":"gpt-6-luna","providerId"', '"model":"gpt-6-sol","providerId"'
    )
    assert parse(both, exit_code=0, raw_events_path=tmp_path / "e", mode="judge").model_resolved == "gpt-6-sol"


# the stop watcher and the rate-limit statuses


def test_scn_fac_37_the_watcher_stops_on_the_first_429_call_failure_before_any_retry():
    lines = recorded("error-429-retrying.jsonl").splitlines()
    first_failure = next(n for n, x in enumerate(lines, 1) if '"model.call_failure"' in x and '"statusCode":429' in x)
    first_retry = next(n for n, x in enumerate(lines, 1) if '"assistant.turn_retry"' in x)
    watcher = CopilotStop()
    assert watcher.reason is None
    assert feed(watcher, lines)[0] == first_failure < first_retry
    assert watcher.reason == "rate_limit"


def test_the_watcher_stops_on_a_rate_limit_retry_when_no_429_failure_came_before_it():
    retry = event_line("assistant.turn_retry", reason="rate_limit")
    watcher = CopilotStop()
    assert feed(watcher, [event_line("session.info", message="m"), retry]) == [2] and watcher.reason == "rate_limit"


def test_the_watcher_never_stops_a_server_error_or_a_transient_auth_retry():
    for name in ("error-500.jsonl", "error-401.jsonl"):
        watcher = CopilotStop()
        assert feed(watcher, recorded(name).splitlines()) == [] and watcher.reason is None


def test_the_watcher_ignores_a_non_json_line_a_json_array_and_deep_nesting():
    watcher = CopilotStop()
    lines = ["not json", "[1, 2, 3]", "null", "7", '"x"', "[" * 100000, "{" * 100000, "", event_line("x")]
    assert feed(watcher, lines) == [] and watcher.reason is None
    assert feed(watcher, [event_line("model.call_failure", statusCode="429")]) == []  # a string is no status


def test_scn_fac_39_twenty_denials_in_a_row_stop_the_run_and_a_success_resets_the_count(tmp_path):
    watcher = CopilotStop()
    assert feed(watcher, [denied()] * 20) == [20] and watcher.reason == "denials"
    other = CopilotStop()
    assert feed(other, [*[denied()] * 19, succeeded(), *[denied()] * 19]) == [] and other.reason is None
    out = parse(
        "\n".join([denied()] * 20), exit_code=0, raw_events_path=tmp_path / "e", stop="denials",
    )  # fmt: skip
    assert out.status == "permission_blocked" and out.detail == (
        "copilot-cli was stopped after 20 denied tool calls in a row: its permission rules refuse what it tries"
    )


def test_parse_with_stop_rate_limit_is_t8_with_the_failure_source_and_no_reset_time(tmp_path):
    lines = recorded("error-429-retrying.jsonl").splitlines()
    cut = "\n".join(lines[:6]) + "\n"  # up to and including the first 429 failure
    out = parse(cut, exit_code=143, raw_events_path=tmp_path / "e", stop="rate_limit")
    assert out.status == "rate_limited" and out.detail == (
        "copilot-cli hit a rate limit (HTTP 429); the harness stopped the run (it never waits for a limit)"
    )
    assert out.limit.kind == "rate_limit" and out.limit.source == "copilot.model_call_failure"
    assert out.limit.resets_at is None and out.limit.model == out.model_resolved
    retry_first = event_line("assistant.turn_retry", reason="rate_limit")
    by_retry = parse(retry_first, exit_code=143, raw_events_path=tmp_path / "e", stop="rate_limit")
    assert by_retry.limit.source == "copilot.turn_retry"
    # the watcher's stop wins over a timeout flag and a session.error in the same stream
    both = parse(cut, exit_code=143, raw_events_path=tmp_path / "e", stop="rate_limit", timed_out=True)
    assert both.status == "rate_limited" and both.detail.startswith("copilot-cli hit a rate limit")


def test_scn_fac_38_a_run_that_stalled_while_the_cli_waited_out_a_429_is_a_rate_limit(tmp_path):
    cut = "\n".join(recorded("error-429-retrying.jsonl").splitlines()[:6]) + "\n"
    out = parse(cut, exit_code=143, raw_events_path=tmp_path / "e", timed_out=True)
    assert (
        out.status == "rate_limited" and out.detail == "copilot-cli was waiting out a rate limit when the run timed out"
    )
    assert out.limit.kind == "rate_limit" and out.limit.source == "copilot.model_call_failure"
    retry = parse(
        event_line("assistant.turn_retry", reason="rate_limit"), exit_code=143, raw_events_path=tmp_path / "e",
        timed_out=True,
    )  # fmt: skip
    assert retry.status == "rate_limited" and retry.limit.source == "copilot.turn_retry"


def test_a_timeout_with_no_rate_limit_is_a_timeout_and_an_interrupt_is_cancelled(tmp_path):
    plain = parse(recorded("judge-hello.jsonl").replace('"exitCode":0', '"exitCode":1'), exit_code=143,
                  raw_events_path=tmp_path / "e", timed_out=True)  # fmt: skip
    assert plain.status == "timeout"
    retrying_500 = parse(recorded("error-500.jsonl"), exit_code=143, raw_events_path=tmp_path / "e", timed_out=True)
    assert retrying_500.status == "timeout"
    cut = "\n".join(recorded("error-429-retrying.jsonl").splitlines()[:6]) + "\n"
    assert parse(cut, exit_code=143, raw_events_path=tmp_path / "e", interrupted=True).status == "cancelled"
    # a run that finished (a `result` event came) is not "waiting out" a limit, even if it timed out afterwards
    finished = cut + json.dumps({"type": "result", "sessionId": "s", "exitCode": 1}) + "\n"
    assert parse(finished, exit_code=1, raw_events_path=tmp_path / "e", timed_out=True).status == "timeout"


# the usage document


def test_scn_fac_40_tokens_and_ai_credits_are_recorded_never_as_dollars():
    first = usage_of(json.loads(recorded("implement-bash.usage.json")))
    assert (first.input_tokens, first.output_tokens, first.cached_input_tokens) == (21350, 63, 20891)
    assert first.credits is None and first.cost_usd is None and first.context_peak_tokens is None
    doc = {"totalNanoAiu": 2_500_000_000, "modelMetrics": {"m": {"usage": {"inputTokens": 10, "outputTokens": 2}}}}
    usage = usage_of(doc)
    assert (usage.input_tokens, usage.output_tokens, usage.credits, usage.cost_usd) == (10, 2, 2.5, None)
    assert usage.credits_source == "copilot.usage_file"
    assert usage_of(None).input_tokens == 0 and usage_of({"totalNanoAiu": True}).credits is None
    assert usage_of({"totalNanoAiu": 0}).credits is None


def test_read_usage_reads_a_regular_file_and_gives_zero_usage_for_a_link_or_a_large_file(tmp_path):
    path = tmp_path / "copilot-usage.json"
    assert usage_of(read_usage(path)).input_tokens == 0  # missing
    path.write_text(recorded("implement-bash.usage.json"))
    assert usage_of(read_usage(path)).input_tokens == 21350
    link = tmp_path / "link.json"
    os.symlink(path, link)
    assert usage_of(read_usage(link)) == usage_of(None)
    big = tmp_path / "big.json"
    big.write_text(json.dumps({"pad": "x" * (2 * 1024 * 1024), "modelMetrics": {"m": {"usage": {"inputTokens": 5}}}}))
    assert usage_of(read_usage(big)).input_tokens == 0
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\xff\xfe not json")
    assert usage_of(read_usage(bad)).input_tokens == 0
    assert usage_of(read_usage(tmp_path)).input_tokens == 0  # a directory


# the GitHub-routed recording of task 8.1 (SCN-FAC-49, SCN-FAC-51)

JUDGE_SCHEMA = {
    "type": "object", "required": ["verdict"],
    "properties": {"verdict": {"enum": ["PASS", "FAIL"]}, "reason": {"type": "string"}},
}  # fmt: skip
ANSWER_SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
RESULT_SCHEMA = {
    "type": "object", "required": ["status", "summary"],
    "properties": {"status": {"enum": ["done", "failed", "partial"]}, "summary": {"type": "string"}},
}  # fmt: skip


def parse_routed(leg: str, tmp_path: Path):
    """The recorded leg parsed the way its mode does: `(stream text, RunResult)`."""
    text, usage = routed(f"{leg}.jsonl"), json.loads(routed(f"{leg}.usage.json"))
    mode, schema = {
        "judge-auto": ("judge", JUDGE_SCHEMA), "delegate-read": ("read_only", ANSWER_SCHEMA),
        "implement-serena": ("implement", RESULT_SCHEMA),
    }[leg]  # fmt: skip
    result_text = routed("implement-serena.result.json") if mode == "implement" else None
    out = parse(
        text, exit_code=0, raw_events_path=tmp_path / "e", mode=mode, usage_document=usage, schema=schema,
        result_text=result_text,
    )  # fmt: skip
    return text, out


def test_scn_fac_49_recorded_versions_lists_the_routed_copilot_recording():
    assert load()["copilot-cli"] == ["1.0.102"]


def test_scn_fac_49_the_routed_judge_on_auto_parses(tmp_path):
    text, out = parse_routed("judge-auto", tmp_path)
    session = next(e["sessionId"] for e in copilot_cli.events(text) if e.get("type") == "result")
    assert out.status == "ok" and out.structured == {"verdict": "PASS", "reason": "2 plus 2 equals 4."}
    assert out.model_resolved == "gpt-6-luna" and out.session_id == session
    assert stream_facts(copilot_cli.events(text))["tools"] == []
    assert out.usage.credits is not None and abs(out.usage.credits - 0.024147) < 1e-12
    assert out.usage.credits_source == "copilot.usage_file" and out.usage.cost_usd is None


def test_scn_fac_49_the_routed_delegate_reads_with_view_only(tmp_path):
    text, out = parse_routed("delegate-read", tmp_path)
    assert out.status == "ok" and out.structured == {"answer": "L4 recording note 8.1"}
    assert stream_facts(copilot_cli.events(text))["tools"] == ["view"] and out.model_resolved == "gpt-6-luna"


def test_scn_fac_49_the_routed_implementer_with_serena_writes_its_result(tmp_path):
    text, out = parse_routed("implement-serena", tmp_path)
    assert out.status == "ok" and out.structured["status"] == "done" and out.permission_denials == []
    assert stream_facts(copilot_cli.events(text))["tools"] == [
        "serena-initial_instructions",
        "apply_patch",
        "bash",
        "bash",
    ]
    assert out.model_resolved == "gpt-6-luna"
    assert out.usage.credits is not None and abs(out.usage.credits - 0.307273) < 1e-12


def test_scn_fac_49_the_routed_rejected_token_is_auth(tmp_path):
    out = parse(
        "", exit_code=int(routed("bad-token.exit.txt")), raw_events_path=tmp_path / "e",
        stderr_text=routed("bad-token.stderr.txt"),
    )  # fmt: skip
    assert out.status == "auth" and out.limit.kind == "auth" and out.limit.source == "copilot.stderr"


def test_scn_fac_51_a_pinned_model_the_account_does_not_offer_is_a_model_mismatch(tmp_path):
    stderr, code = routed("judge-pinned-refused.stderr.txt"), int(routed("judge-pinned-refused.exit.txt"))
    out = parse("", exit_code=code, raw_events_path=tmp_path / "e", mode="judge", stderr_text=stderr)
    detail = (
        "model_mismatch: copilot-cli could not set gpt-6-luna "
        "(the account does not offer it: pin a model it offers, or use auto)"
    )
    assert out.status == "error" and out.detail == detail and out.limit is None and out.transient is False
    assert out.detail.startswith(MODEL_MISMATCH_DETAIL)
    usage = json.loads(routed("judge-pinned-refused.usage.json"))
    assert usage["totalUserRequests"] == 0 and usage["totalNanoAiu"] == 0  # nothing billed
    hello = copilot_cli._hello_failure("", stderr, code, stream_facts([]), tmp_path / "e")
    assert hello == (detail, None, "other")


def test_the_routed_streams_parse_as_the_real_adapter_parsed_them_on_the_runner(tmp_path):
    runs = json.loads(routed("runs.json"))
    for leg in ("judge-auto", "delegate-read", "implement-serena"):
        _, out = parse_routed(leg, tmp_path)
        want = runs[leg]
        assert (out.status, out.model_resolved, out.structured) == (
            want["status"], want["model_resolved"], want["structured"],
        )  # fmt: skip
        assert abs(out.usage.credits - want["usage"]["credits"]) < 1e-12


def test_the_adapter_writes_the_mcp_file_shape_the_cli_loaded(tmp_path):
    server = McpServer(name="serena", command="/bin/serena", args=("start-mcp-server",), env=(("CI", "true"),))
    path = CopilotCliAdapter._write_mcp_config(request(tmp_path, mcp_servers=[server]), tmp_path / "copilot-mcp.json")
    mine, recorded_file = json.loads(path.read_text()), json.loads(routed("implement-serena.mcp.json"))
    assert sorted(mine) == sorted(recorded_file) == ["mcpServers"]
    entry = mine["mcpServers"]["serena"]
    assert sorted(entry) == sorted(recorded_file["mcpServers"]["serena"]) == ["args", "command", "env"]
    assert isinstance(entry["args"], list) and entry["env"] == {"CI": "true"}
