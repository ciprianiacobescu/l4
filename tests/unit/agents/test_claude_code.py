import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.agents.base import McpServer, PermissionPolicy, RunRequest
from l4.agents.claude_code import ClaudeCodeAdapter
from l4.config.schema import Profile

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "claude-code" / "2.1.288"
SCHEMA = {"type": "object", "required": ["verdict"], "properties": {"verdict": {"enum": ["pass", "fail"]}}}


def request(tmp_path: Path, auth: str = "subscription", **kw) -> RunRequest:
    kw.setdefault("profile", Profile(adapter="claude-code", model="claude-sonnet-5-5", auth=auth))  # type: ignore[arg-type]
    return RunRequest(
        role="judge", cwd=tmp_path / "wt", prompt="p", result_path=tmp_path / "res" / "result.json",
        raw_events_path=tmp_path / "raw" / "events.jsonl", env={"PATH": "/usr/bin"}, **kw,
    )  # fmt: skip


def command(tmp_path, **kw) -> list[str]:
    return ClaudeCodeAdapter().build_command(request(tmp_path, **kw), exe="/x/claude")


def value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def test_subscription_command_matches_the_confirmed_implementer_invocation(tmp_path):
    policy = PermissionPolicy("implement", gate_prefix=".venv/bin/python -m pytest")
    argv = command(
        tmp_path, permission_policy=policy, preset_session_id="11111111-2222-4333-8444-555555555555",
        max_turns=40, max_budget_usd=5.0, result_schema=SCHEMA,
    )  # fmt: skip
    res_dir = str(tmp_path / "res")
    assert argv[:2] == ["/x/claude", "-p"]
    assert value(argv, "--output-format") == "stream-json" and "--verbose" in argv
    assert value(argv, "--model") == "claude-sonnet-5-5" and value(argv, "--max-turns") == "40"
    assert value(argv, "--max-budget-usd") == "5.0"
    assert value(argv, "--session-id") == "11111111-2222-4333-8444-555555555555" and "--resume" not in argv
    assert value(argv, "--permission-mode") == "dontAsk"
    assert "--safe-mode" not in argv and "--bare" not in argv and "--strict-mcp-config" in argv
    assert value(argv, "--setting-sources") == "" and "--disable-slash-commands" in argv
    assert value(argv, "--tools") == "Read,Edit,Write,Glob,Grep,Bash"
    assert value(argv, "--allowedTools") == (
        f"Read,Glob,Grep,Edit(./**),Edit(/{res_dir}/**),Bash(.venv/bin/python -m pytest:*)"
    )
    assert json.loads(value(argv, "--json-schema")) == SCHEMA


def test_api_key_command_has_bare_and_subscription_does_not(tmp_path):
    api = command(tmp_path, auth="api_key")
    sub = command(tmp_path, auth="subscription")
    assert "--bare" in api and "--safe-mode" not in api and "--strict-mcp-config" in api
    assert "--safe-mode" not in sub and "--bare" not in sub and value(sub, "--setting-sources") == ""
    assert "--setting-sources" not in api and "--disable-slash-commands" not in api


def test_resume_replaces_the_preset_session_id(tmp_path):
    argv = command(tmp_path, resume_session_id="aaaaaaaa-2222-4333-8444-555555555555")
    assert value(argv, "--resume") == "aaaaaaaa-2222-4333-8444-555555555555" and "--session-id" not in argv


@pytest.mark.parametrize("auth", ["subscription", "api_key"])
@pytest.mark.parametrize("mode", ["implement", "read_only", "judge"])
def test_no_bare_write_or_edit_allow_rule_is_ever_emitted(tmp_path, auth, mode):
    argv = command(tmp_path, auth=auth, permission_policy=PermissionPolicy(mode, gate_prefix="pytest"))
    rules = value(argv, "--allowedTools").split(",") if "--allowedTools" in argv else []
    assert "Write" not in rules and "Edit" not in rules
    assert not [r for r in rules if r.startswith("Write(")]


def test_the_judge_command_is_tool_less_and_exactly_the_confirmed_one(tmp_path):
    argv = command(tmp_path, permission_policy=PermissionPolicy("judge"), result_schema=SCHEMA)
    assert argv == [
        "/x/claude", "-p", "--model", "claude-sonnet-5-5", "--output-format", "json", "--json-schema",
        json.dumps(SCHEMA, separators=(",", ":")), "--safe-mode", "--strict-mcp-config", "--tools", "",
        "--no-session-persistence", "--max-turns", "3",
    ]  # fmt: skip


def test_read_only_uses_plan_mode_and_read_tools_only(tmp_path):
    argv = command(tmp_path, permission_policy=PermissionPolicy("read_only"))
    assert value(argv, "--permission-mode") == "plan" and value(argv, "--tools") == "Read,Grep,Glob"


def test_the_environment_the_adapter_adds_never_contains_the_retry_watchdog():
    assert "CLAUDE_CODE_RETRY_WATCHDOG" not in ClaudeCodeAdapter().extra_env
    assert ClaudeCodeAdapter().extra_env["CLAUDE_CODE_MAX_RETRIES"] == "1"
    assert ClaudeCodeAdapter().extra_env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"


def test_extra_env_turns_updates_off():  # SCN-PRV-122, L4-PRV-044
    env = ClaudeCodeAdapter().extra_env
    assert env["DISABLE_AUTOUPDATER"] == "1" and env["DISABLE_UPDATES"] == "1"


def result_event(name: str) -> dict:
    return json.loads((RECORDED / name).read_text().splitlines()[-1])


def parse(text: str, tmp_path, *, exit_code=0, schema=None, **kw):
    return ClaudeCodeAdapter().parse(text, exit_code=exit_code, schema=schema, raw_events_path=tmp_path / "e", **kw)


def test_structured_output_and_model_usage_are_mapped_from_the_stream(tmp_path):
    out = parse((RECORDED / "blocked.jsonl").read_text(), tmp_path, schema=None)
    assert out.status == "ok" and out.structured and out.structured["status"] == "blocked"
    assert out.session_id == "8cdf5787-2d1b-4a28-acf2-3173b231ba82"
    assert out.model_resolved and out.usage.cost_usd == pytest.approx(0.0232, abs=1e-4)
    assert out.usage.output_tokens > 0 and out.permission_denials == []


def test_single_document_json_output_of_the_judge_is_parsed(tmp_path):
    out = parse((RECORDED / "judge-structured-output.json").read_text(), tmp_path)
    assert out.status == "ok" and out.structured["verdict"] == "pass"  # type: ignore[index]
    assert out.model_resolved == "claude-sonnet-5-5" and out.final_text and out.usage.cost_usd == 0.068776


def test_permission_denials_are_carried_and_do_not_fail_the_run(tmp_path):
    out = parse((RECORDED / "perm-dontask-denials.jsonl").read_text(), tmp_path)
    assert out.status == "ok" and {d["tool_name"] for d in out.permission_denials} == {"Bash", "Write"}


def test_a_bad_model_is_an_error_even_though_subtype_says_success(tmp_path):
    out = parse((RECORDED / "hello_bad_model.stream.jsonl").read_text(), tmp_path, exit_code=1)
    assert out.status == "error" and out.limit is None


def recorded_result(**over) -> str:
    event = {**result_event("judge-structured-output.json"), **over}
    return json.dumps(event)


# [U] no max-turns / budget / 401 / rejected rate-limit run was recorded: these derive from a recorded result line
@pytest.mark.parametrize(
    ("over", "status"),
    [
        ({"subtype": "error_max_turns", "is_error": True, "result": None, "structured_output": None}, "max_turns"),
        ({"subtype": "error_max_budget_usd", "is_error": True, "result": None, "structured_output": None}, "budget"),
        ({"is_error": True, "api_error_status": 401, "structured_output": None}, "auth"),
        ({"is_error": True, "api_error_status": 403, "structured_output": None}, "auth"),
        ({"is_error": True, "api_error_status": 429, "structured_output": None}, "rate_limited"),
        ({"is_error": True, "api_error_status": 500, "structured_output": None}, "error"),
        ({"subtype": "error_during_execution", "is_error": True}, "error"),
    ],
)
def test_max_turns_null_result_is_not_ok(tmp_path, over, status):
    out = parse(recorded_result(**over), tmp_path, exit_code=1)
    assert out.status == status


def test_a_rejected_rate_limit_event_is_a_limit_with_its_reset_time(tmp_path):
    event = {
        "type": "rate_limit_event",
        "rate_limit_info": {"status": "rejected", "resetsAt": 1791039600, "rateLimitType": "five_hour"},
    }
    text = json.dumps(event) + "\n" + recorded_result(is_error=True, api_error_status=429, structured_output=None)
    out = parse(text, tmp_path, exit_code=1)
    assert out.status == "quota" and out.limit is not None and out.limit.kind == "usage_limit"
    assert out.limit.resets_at == datetime.fromtimestamp(1791039600, UTC)
    assert out.limit.source == "claude.rate_limit_event"


def test_schema_requested_but_structured_output_missing_or_invalid_is_an_error(tmp_path):
    missing = parse(recorded_result(structured_output=None), tmp_path, schema=SCHEMA)
    assert missing.status == "error" and "structured" in (missing.detail or "")
    invalid = parse(recorded_result(structured_output={"verdict": "maybe"}), tmp_path, schema=SCHEMA)
    assert invalid.status == "error" and invalid.structured is None and invalid.final_text


def test_no_result_event_and_timeouts(tmp_path):
    assert parse('{"type":"system"}', tmp_path, exit_code=1).status == "error"
    assert parse("", tmp_path).status == "error"
    assert parse((RECORDED / "blocked.jsonl").read_text(), tmp_path, timed_out=True).status == "timeout"
    assert parse((RECORDED / "blocked.jsonl").read_text(), tmp_path, interrupted=True).status == "cancelled"


def test_the_judge_is_not_armed_with_the_stall_watchdog_because_its_json_output_comes_at_the_end(tmp_path):
    from l4.agents.base import PermissionPolicy, RunRequest
    from l4.agents.claude_code import ClaudeCodeAdapter
    from l4.agents.proc import ProcOutcome
    from l4.config.schema import Profile

    seen: list[object] = []

    class Spy:
        def run(self, argv, env, cwd, **kw):
            seen.append(kw["stall_timeout_s"])
            kw["stdout_path"].parent.mkdir(parents=True, exist_ok=True)
            kw["stdout_path"].write_text("")
            return ProcOutcome(0)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text("#!/bin/sh\n")
    (bin_dir / "claude").chmod(0o755)
    (tmp_path / "wt").mkdir()
    for mode in ("judge", "implement"):
        req = RunRequest(
            profile=Profile(adapter="claude-code", model="sonnet", vendor="anthropic"), role="x", cwd=tmp_path / "wt",
            prompt="p", result_path=tmp_path / "r.json", raw_events_path=tmp_path / mode / "e.jsonl",
            env={"PATH": str(bin_dir)}, permission_policy=PermissionPolicy(mode), stall_timeout_s=60,
        )  # fmt: skip
        ClaudeCodeAdapter(Spy()).run(req)
    assert seen == [None, 60]


def test_mcp_config_is_passed_with_strict_and_allowed_and_absent_servers_change_nothing(tmp_path):
    policy = PermissionPolicy("implement", gate_prefix="pytest")
    plain = command(tmp_path, permission_policy=policy)
    server = McpServer("serena", "/bin/serena", ("start-mcp-server",), (("SERENA_HOME", "/t/h"),))
    config = tmp_path / "res" / "mcp.json"
    argv = ClaudeCodeAdapter().build_command(
        request(tmp_path, permission_policy=policy, mcp_servers=[server]), exe="/x/claude", mcp_config=config
    )
    assert value(argv, "--mcp-config") == str(config) and "--strict-mcp-config" in argv
    assert argv.index("--mcp-config") < argv.index("--strict-mcp-config")
    assert value(argv, "--allowedTools") == value(plain, "--allowedTools") + ",mcp__serena"
    assert "--mcp-config" not in plain
    judge = command(tmp_path)
    assert "--mcp-config" not in judge


def test_run_writes_the_mcp_config_file_for_an_implementer_only(tmp_path):
    """Through `run()`: the file the command names exists with the servers for an implementer, and no judge or reader
    request writes one or names one."""
    from l4.agents.proc import ProcOutcome

    seen: dict[str, list[str]] = {}

    class Spy:
        def run(self, argv, env, cwd, **kw):
            seen[kw["stdout_path"].parent.name] = list(argv)
            kw["stdout_path"].parent.mkdir(parents=True, exist_ok=True)
            kw["stdout_path"].write_text("")
            return ProcOutcome(0)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text("#!/bin/sh\n")
    (bin_dir / "claude").chmod(0o755)
    (tmp_path / "wt").mkdir()
    server = McpServer("serena", "/bin/serena", ("a", "b"), (("K", "v"),))
    for mode in ("judge", "read_only", "implement"):
        req = RunRequest(
            profile=Profile(adapter="claude-code", model="sonnet", vendor="anthropic"), role="x", cwd=tmp_path / "wt",
            prompt="p", result_path=tmp_path / mode / "result.json", raw_events_path=tmp_path / mode / "events.jsonl",
            env={"PATH": str(bin_dir)}, permission_policy=PermissionPolicy(mode), mcp_servers=[server],
        )  # fmt: skip
        ClaudeCodeAdapter(Spy()).run(req)
    written = tmp_path / "implement" / "mcp.json"
    assert json.loads(written.read_text()) == {
        "mcpServers": {"serena": {"command": "/bin/serena", "args": ["a", "b"], "env": {"K": "v"}}}
    }
    assert value(seen["implement"], "--mcp-config") == str(written)
    for mode in ("judge", "read_only"):
        assert not (tmp_path / mode / "mcp.json").exists() and "--mcp-config" not in seen[mode]


def test_build_command_names_no_mcp_server_outside_implement_mode(tmp_path):
    server = McpServer("serena", "/bin/serena", ("start-mcp-server",), (("SERENA_HOME", "/t/h"),))
    config = tmp_path / "res" / "mcp.json"
    for mode in ("judge", "read_only"):
        argv = ClaudeCodeAdapter().build_command(
            request(tmp_path, permission_policy=PermissionPolicy(mode), mcp_servers=[server]),
            exe="/x/claude",
            mcp_config=config,
        )
        assert "--mcp-config" not in argv and not any("mcp__serena" in a for a in argv), mode


def test_the_implementer_loads_no_repo_or_user_guidance_and_keeps_its_mcp_servers(tmp_path):
    """HB-X1 (live, l4-runner, claude 2.1.288): `--safe-mode` drops `--mcp-config` silently, so the subscription
    implementer runs with `--setting-sources ""` (no user/project/local settings, hooks, CLAUDE.md, AGENTS.md or skills;
    `--setting-sources local` still loaded `.claude/settings.local.json` hooks and the auto-memory) and
    `--disable-slash-commands`; the auto-memory is switched off by the environment. The judge and the reader have no
    server to keep and stay on `--safe-mode`."""
    server = McpServer("serena", "/bin/serena", ("start-mcp-server",), (("SERENA_HOME", "/t/h"),))
    config = tmp_path / "res" / "mcp.json"
    argv = ClaudeCodeAdapter().build_command(
        request(tmp_path, auth="subscription", permission_policy=PermissionPolicy("implement"), mcp_servers=[server]),
        exe="/x/claude", mcp_config=config,
    )  # fmt: skip
    assert value(argv, "--mcp-config") == str(config) and "--safe-mode" not in argv
    assert ClaudeCodeAdapter.extra_env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    for mode in ("read_only", "judge"):
        assert "--safe-mode" in command(tmp_path, auth="subscription", permission_policy=PermissionPolicy(mode))


# the result event of live wave A jobs 5709 and 5703: a 529 with no retry-after, cost 0, one turn
OVERLOADED = {
    "is_error": True, "api_error_status": 529, "terminal_reason": "api_error", "num_turns": 1,
    "total_cost_usd": 0, "result": "API Error: 529 Overloaded. This is a server-side issue", "structured_output": None,
}  # fmt: skip


def test_a_529_result_is_transient(tmp_path):
    out = parse(recorded_result(**OVERLOADED), tmp_path, exit_code=1)
    assert out.status == "error" and out.transient is True and out.limit is None
    assert "529" in (out.detail or "")
    again = parse(recorded_result(**{**OVERLOADED, "api_error_status": 503}), tmp_path, exit_code=1)
    assert again.status == "error" and again.transient is True
    named = parse(
        recorded_result(
            **{**OVERLOADED, "api_error_status": None, "result": '{"type":"overloaded_error","message":"Overloaded"}'}
        ),
        tmp_path, exit_code=1,
    )  # fmt: skip
    assert named.status == "error" and named.transient is True


@pytest.mark.parametrize("status", [401, 403, 404, 500, 400])
def test_a_404_or_401_is_not_transient(tmp_path, status):
    out = parse(recorded_result(is_error=True, api_error_status=status, structured_output=None), tmp_path, exit_code=1)
    assert out.transient is False
    assert parse(recorded_result(), tmp_path).transient is False


def test_a_429_stays_rate_limited(tmp_path):
    out = parse(recorded_result(is_error=True, api_error_status=429, structured_output=None), tmp_path, exit_code=1)
    assert out.status == "rate_limited" and out.transient is False and out.limit is not None


def test_structured_output_problems_are_named(tmp_path):  # SCN-FAC-16 native part
    body = json.loads((RECORDED / "judge-structured-output.json").read_text())
    body = body[-1] if isinstance(body, list) else body
    missing = parse(json.dumps({**body, "structured_output": None}), tmp_path, schema=SCHEMA)
    assert missing.status == "error" and missing.result_problem == "missing"
    assert missing.detail and "missing although a schema was requested" in missing.detail
    bad = {"verdict": "maybe"}
    invalid = parse(json.dumps({**body, "structured_output": bad}), tmp_path, schema=SCHEMA)
    assert invalid.status == "error" and invalid.result_problem == "invalid" and invalid.rejected == bad
    good = parse(json.dumps(body), tmp_path, schema=SCHEMA)
    assert good.status == "ok" and good.result_problem is None


def test_last_message_is_the_result_text(tmp_path):  # SCN-FAC-17
    out = parse((RECORDED / "red-ok.jsonl").read_text(), tmp_path)
    assert out.last_message is not None and out.last_message == out.final_text


def test_context_peak_is_the_largest_per_call_sum_of_the_assistant_events(tmp_path):  # SCN-FAC-18
    out = parse((RECORDED / "red-ok.jsonl").read_text(), tmp_path)
    assert out.usage.context_peak_tokens == 2 + 1105 + 12051
    assert out.usage.input_tokens == 10 and out.usage.context_peak_percent is None
    assert parse((RECORDED / "judge-structured-output.json").read_text(), tmp_path).usage.context_peak_tokens is None


def test_the_runner_gets_the_requests_watch_and_the_claude_code_reader(tmp_path):
    from l4.agents.activity import ActivityWatch, claude_code_signals
    from l4.agents.claude_code import ClaudeCodeAdapter
    from l4.agents.proc import ProcOutcome

    seen: list[dict] = []

    class Spy:
        def run(self, argv, env, cwd, **kw):
            seen.append(kw)
            kw["stdout_path"].parent.mkdir(parents=True, exist_ok=True)
            kw["stdout_path"].write_text("")
            return ProcOutcome(0)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text("#!/bin/sh\n")
    (bin_dir / "claude").chmod(0o755)
    (tmp_path / "wt").mkdir(exist_ok=True)
    watch = ActivityWatch(0, lambda beat: None)
    for w in (watch, None):
        req = RunRequest(
            profile=Profile(adapter="claude-code", model="sonnet", vendor="anthropic"), role="x", cwd=tmp_path / "wt",
            prompt="p", result_path=tmp_path / "r.json", raw_events_path=tmp_path / str(bool(w)) / "e.jsonl",
            env={}, permission_policy=PermissionPolicy("implement"), watch=w,
        )  # fmt: skip
        req.env = {"PATH": str(bin_dir)}
        ClaudeCodeAdapter(Spy()).run(req)
    assert seen[0]["watch"] is watch and seen[0]["reader"] is claude_code_signals
    assert seen[1]["watch"] is None
