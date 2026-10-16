import json
from pathlib import Path

import pytest

from l4.agents.base import AdapterError, McpServer, PermissionPolicy, RunRequest
from l4.agents.codex import CodexAdapter, drop_nulls, strictify_schema
from l4.config.schema import Profile
from l4.schemacheck import validate

FIXTURES = Path(__file__).parents[2] / "fixtures"
RECORDED = FIXTURES / "recorded" / "codex" / "0.160.0"
CANONICAL = json.loads((FIXTURES / "schemas" / "implementer-result.schema.json").read_text())
STRICT = json.loads((RECORDED / "implementer-result.strict.schema.json").read_text())

# [U] the usage-limit turn.failed was never reproduced (spikes/00-summary 3.6); this is the message research/02 quotes
USAGE_LIMIT = {"type": "turn.failed", "error": {"message": "You’ve hit your usage limit. Try again at 3:45 PM."}}


def request(tmp_path: Path, **kw) -> RunRequest:
    kw.setdefault("profile", Profile(adapter="codex", model="gpt-6-luna", vendor="openai"))
    return RunRequest(
        role="implementer", cwd=tmp_path / "wt", prompt="p", result_path=tmp_path / "res" / "result.json",
        raw_events_path=tmp_path / "raw" / "events.jsonl", env={"PATH": "/usr/bin"}, **kw,
    )  # fmt: skip


def lines(name: str) -> list[str]:
    return (RECORDED / name).read_text().splitlines()


def parse(name_or_lines, tmp_path, *, exit_code=0, result_text=None, schema=CANONICAL, **kw):
    events = lines(name_or_lines) if isinstance(name_or_lines, str) else name_or_lines
    return CodexAdapter().parse(
        events, exit_code=exit_code, result_text=result_text, schema=schema, raw_events_path=tmp_path / "e", **kw
    )


def test_strictified_canonical_schema_equals_the_recorded_strict_schema():
    assert strictify_schema(CANONICAL) == STRICT
    assert "$id" not in strictify_schema(CANONICAL)


def test_strictify_does_not_mutate_its_input():
    before = json.dumps(CANONICAL, sort_keys=True)
    strictify_schema(CANONICAL)
    assert json.dumps(CANONICAL, sort_keys=True) == before


def test_strict_schema_round_trip(tmp_path):
    for name in ("green-ok", "blocked", "red-ok", "red-ok-no-stub-new-kwarg"):
        text = (RECORDED / f"{name}.result.json").read_text()
        reply = json.loads(text)
        assert validate(reply, STRICT) == [], name  # what codex was allowed to say
        out = parse(f"{name}.jsonl", tmp_path, result_text=text)
        assert out.status == "ok", (name, out.detail)
        assert out.structured == drop_nulls(reply)
        assert validate(out.structured, CANONICAL) == []


def test_drop_nulls_removes_none_values_at_every_depth_only():
    assert drop_nulls({"a": None, "b": [{"c": None, "d": 1}], "e": {"f": None}, "g": 0, "h": ""}) == {
        "b": [{"d": 1}], "e": {}, "g": 0, "h": "",
    }  # fmt: skip


def test_a_result_valid_only_after_nulls_are_dropped_is_ok_and_one_that_is_not_valid_is_an_error(tmp_path):
    good = json.dumps({**json.loads((RECORDED / "red-ok.result.json").read_text()), "summary": "s"})
    assert parse("red-ok.jsonl", tmp_path, result_text=good).status == "ok"
    bad = json.dumps({"status": "maybe"})
    out = parse("red-ok.jsonl", tmp_path, result_text=bad)
    assert out.status == "error" and "result" in (out.detail or "") and out.structured is None
    assert parse("red-ok.jsonl", tmp_path, result_text=None).status == "error"
    assert parse("red-ok.jsonl", tmp_path, result_text="not json").status == "error"


def test_commands_never_use_full_auto(tmp_path):
    adapter = CodexAdapter()
    for policy in (PermissionPolicy("implement"), PermissionPolicy("read_only")):
        argv = adapter.build_command(request(tmp_path, permission_policy=policy), exe="/bin/codex", schema_path=None)
        assert "--full-auto" not in argv and "--dangerously-bypass-approvals-and-sandbox" not in argv


def test_implementer_command_follows_the_confirmed_invocation(tmp_path):
    req = request(tmp_path, profile=Profile(adapter="codex", model="gpt-6-luna", options={"reasoning_effort": "high"}))
    schema = tmp_path / "res" / "schema.json"
    argv = CodexAdapter().build_command(req, exe="/x/codex", schema_path=schema)
    assert argv == [
        "/x/codex", "exec", "--json", "-m", "gpt-6-luna", "-c", "model_reasoning_effort=high", "-s",
        "workspace-write", "--ignore-user-config", "--ignore-rules", "-c", "project_doc_max_bytes=0",
        "--output-schema", str(schema),
        "-o", str(req.result_path), "-",
    ]  # fmt: skip


def test_read_only_policy_and_missing_model_and_schema(tmp_path):
    req = request(tmp_path, profile=Profile(adapter="codex"), permission_policy=PermissionPolicy("read_only"))
    argv = CodexAdapter().build_command(req, exe="codex", schema_path=None)
    assert argv[argv.index("-s") + 1] == "read-only" and "-m" not in argv and "--output-schema" not in argv
    assert argv[-1] == "-"


def test_thread_usage_and_final_text_are_extracted(tmp_path):
    out = parse("green-ok.jsonl", tmp_path, result_text=(RECORDED / "green-ok.result.json").read_text())
    assert out.session_id == "01a1023b-cda8-7d52-ac99-679e58450abc" and out.exit_code == 0
    assert out.usage.input_tokens > 0 and out.usage.output_tokens > 0 and out.usage.cost_usd is None
    assert out.final_text


def test_turn_failed_usage_limit_is_quota(tmp_path):
    out = parse([json.dumps(USAGE_LIMIT)], tmp_path, exit_code=1)
    assert out.status == "quota" and out.limit is not None
    assert out.limit.kind == "usage_limit" and out.limit.tool == "codex" and out.limit.source == "text"


def test_a_usage_limit_message_gives_the_reset_time(tmp_path):
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    event = {"type": "turn.failed", "error": {"message": "You've hit your usage limit. Try again in 5 hours."}}
    out = CodexAdapter().parse([json.dumps(event)], exit_code=1, raw_events_path=tmp_path / "e.jsonl", now=now)
    assert out.status == "quota" and out.limit is not None
    assert out.limit.kind == "usage_limit" and out.limit.resets_at == now + timedelta(hours=5)


def test_invalid_json_schema_is_a_configuration_error_never_quota(tmp_path):
    out = parse("output-schema-nonstrict-400.jsonl", tmp_path, exit_code=1)
    assert out.status == "error" and out.limit is None and "schema" in (out.detail or "")


def test_unsupported_model_is_a_configuration_error(tmp_path):
    out = parse((RECORDED / "exec_hello_bad_model.jsonl").read_text().splitlines(), tmp_path, exit_code=1)
    assert out.status == "error" and out.limit is None


def test_timeout_and_interrupt_win_over_what_the_stream_says(tmp_path):
    assert parse("green-ok.jsonl", tmp_path, timed_out=True).status == "timeout"
    assert parse("green-ok.jsonl", tmp_path, interrupted=True).status == "cancelled"


def test_exit_code_zero_alone_is_not_ok(tmp_path):
    out = parse(['{"type":"thread.started","thread_id":"t"}'], tmp_path, exit_code=0, schema=None)
    assert out.status == "error"  # no turn.completed
    assert parse(["garbage", "{broken", '{"type":"turn.completed","usage":{}}'], tmp_path, schema=None).status == "ok"


def test_nonzero_exit_without_a_failure_event_is_an_error(tmp_path):
    out = parse(['{"type":"turn.completed","usage":{}}'], tmp_path, exit_code=2, schema=None)
    assert out.status == "error" and "2" in (out.detail or "")


@pytest.mark.parametrize("name", ["green-ok", "blocked"])
def test_blocked_and_done_both_parse_as_ok_runs(tmp_path, name):
    text = (RECORDED / f"{name}.result.json").read_text()
    assert parse(f"{name}.jsonl", tmp_path, result_text=text).structured["status"] == json.loads(text)["status"]


def test_a_codex_that_prints_nothing_is_killed_by_the_stall_watchdog_as_a_timeout(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "codex").write_text("#!/bin/sh\nexec /bin/sleep 30\n")
    (bin_dir / "codex").chmod(0o755)
    (tmp_path / "wt").mkdir()
    req = request(tmp_path, stall_timeout_s=1)
    req.env = {"PATH": str(bin_dir)}
    result = CodexAdapter().run(req)
    assert result.status == "timeout"


# [U] the real shape of a mid-run limit is unrecorded; this is the top-level `error` event codex 0.160 prints for
# fatal errors that are not a turn failure. Replace with the recording the first time a limit is hit on the runner.
TOP_LEVEL_LIMIT = {"type": "error", "message": "You've hit your usage limit. Try again at 3:45 PM."}


def test_a_top_level_error_event_with_a_nonzero_exit_is_classified_like_turn_failed(tmp_path):
    out = parse([json.dumps(TOP_LEVEL_LIMIT)], tmp_path, exit_code=1)
    assert out.status == "quota" and out.limit is not None and out.limit.kind == "usage_limit"


def test_an_unrecognised_error_event_is_an_error_not_quota(tmp_path):
    out = parse(['{"type":"error","message":"stream disconnected"}'], tmp_path, exit_code=1)
    assert out.status == "error" and out.limit is None


def test_a_nonfatal_error_notice_in_a_successful_run_does_not_fail_it(tmp_path):
    notice = '{"type":"error","message":"Reconnecting... 1/5 (usage limit lookup failed)"}'
    out = parse([notice, '{"type":"turn.completed","usage":{}}'], tmp_path, exit_code=0, schema=None)
    assert out.status == "ok"


def test_an_array_without_items_borrows_them_from_the_same_property_elsewhere():
    """The judge verdict schema leaves `findings[].evidence` open; OpenAI-strict rejects "array schema missing items"
    (live, codex 0.160.0 on the runner, 2026-10-04)."""
    from l4.verifier.judge import JUDGE_SCHEMA

    strict = strictify_schema(JUDGE_SCHEMA)
    findings = strict["properties"]["findings"]["items"]["properties"]["evidence"]
    criteria = strict["properties"]["criteria"]["items"]["properties"]["evidence"]
    assert findings["items"] == criteria["items"] and findings["items"]["additionalProperties"] is False
    assert "items" not in JUDGE_SCHEMA["properties"]["findings"]["items"]["properties"]["evidence"]  # input untouched


def test_an_array_without_items_and_without_a_donor_is_a_configuration_error():
    from l4.agents.base import AdapterError

    with pytest.raises(AdapterError, match="items"):
        strictify_schema({"type": "object", "properties": {"x": {"type": "array"}}, "required": ["x"]})


def test_mcp_servers_become_config_overrides_and_none_leaves_argv_alone(tmp_path):
    plain = request(tmp_path, profile=Profile(adapter="codex", model="m"))
    args, env = ("start-mcp-server", "--project", "/wt"), (("A", 'x"y'), ("B", "2"))
    server = McpServer("serena", "/bin/serena", args, env, 30)
    with_mcp = request(tmp_path, profile=Profile(adapter="codex", model="m"), mcp_servers=[server])
    base = CodexAdapter().build_command(plain, exe="codex", schema_path=None)
    argv = CodexAdapter().build_command(with_mcp, exe="codex", schema_path=None)
    assert argv.count("-c") == base.count("-c") + 4
    rows = [argv[i + 1] for i, a in enumerate(argv) if a == "-c" and argv[i + 1].startswith("mcp_servers.")]
    assert rows == [
        'mcp_servers.serena.command="/bin/serena"',
        'mcp_servers.serena.args=["start-mcp-server", "--project", "/wt"]',
        'mcp_servers.serena.env={"A" = "x\\"y", "B" = "2"}',
        "mcp_servers.serena.startup_timeout_sec=30",
    ]
    stripped = [
        a for i, a in enumerate(argv)
        if not (a.startswith("mcp_servers.") or (a == "-c" and argv[i + 1].startswith("mcp_servers.")))
    ]  # fmt: skip
    assert stripped == base  # the rest of the command is untouched


def test_an_mcp_server_name_that_is_not_a_bare_key_is_refused(tmp_path):
    bad = request(tmp_path, mcp_servers=[McpServer("a.b", "/x")])
    with pytest.raises(AdapterError):
        CodexAdapter().build_command(bad, exe="codex", schema_path=None)


def test_mcp_env_on_argv_carries_no_url_credentials_and_is_valid_toml(tmp_path):
    import tomllib

    env = (("HTTP_PROXY", "http://user:pw@proxy.test:3128"), ("NOTE", "keep a@b"), ("RAW", "a\x7fb\x01c"))
    server = McpServer("serena", "/s", (), env, 30)
    req = request(tmp_path, profile=Profile(adapter="codex", model="m"), mcp_servers=[server])
    argv = CodexAdapter().build_command(req, exe="codex", schema_path=None)
    row = next(a for a in argv if a.startswith("mcp_servers.serena.env="))
    assert "pw" not in row and "user" not in row
    table = tomllib.loads("env = " + row.removeprefix("mcp_servers.serena.env="))["env"]
    assert table == {"HTTP_PROXY": "http://proxy.test:3128", "NOTE": "keep a@b", "RAW": "a\x7fb\x01c"}


def test_a_judge_or_read_only_request_gets_no_mcp_flags_even_with_servers(tmp_path):
    server = McpServer("serena", "/bin/serena", ("start-mcp-server",), (("A", "1"),), 30)
    for mode in ("judge", "read_only"):
        req = request(tmp_path, profile=Profile(adapter="codex", model="m"), mcp_servers=[server],
                      permission_policy=PermissionPolicy(mode))  # fmt: skip
        argv = CodexAdapter().build_command(req, exe="codex", schema_path=None)
        assert not any("mcp_servers" in a for a in argv), mode


def test_result_problem_names_how_the_native_result_failed(tmp_path):  # SCN-FAC-16 native part, SCN-FAC-17
    missing = parse("red-ok.jsonl", tmp_path, result_text=None)
    assert missing.status == "error" and missing.result_problem == "missing"
    broken = parse("red-ok.jsonl", tmp_path, result_text="not json")
    assert broken.status == "error" and broken.detail == "result invalid: not JSON"
    assert broken.result_problem == "not_json"
    bad = {"status": "maybe"}
    invalid = parse("red-ok.jsonl", tmp_path, result_text=json.dumps(bad))
    assert invalid.status == "error" and invalid.result_problem == "invalid" and invalid.rejected == bad
    assert "result invalid: " in (invalid.detail or "")
    good = parse("red-ok.jsonl", tmp_path, result_text=(RECORDED / "red-ok.result.json").read_text())
    assert good.status == "ok" and good.result_problem is None


def test_last_message_is_the_last_agent_message_and_final_text_is_unchanged(tmp_path):  # SCN-FAC-17
    def message(text):
        return json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": text}})

    stream = [
        json.dumps({"type": "thread.started", "thread_id": "t"}), message("first"), message("second"),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}),
    ]  # fmt: skip
    out = parse(stream, tmp_path, schema=None)
    assert out.last_message == "second" and out.final_text == "second"
    none = parse([stream[0], stream[3]], tmp_path, schema=None)
    assert none.last_message is None and none.final_text is None


def test_codex_reports_no_context_peak(tmp_path):  # SCN-FAC-19
    out = parse("red-ok.jsonl", tmp_path, result_text=(RECORDED / "red-ok.result.json").read_text())
    assert out.usage.context_peak_tokens is None and out.usage.context_peak_percent is None


def test_the_runner_gets_the_requests_watch_and_the_codex_reader(tmp_path):
    from l4.agents.activity import ActivityWatch, codex_signals
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
    (bin_dir / "codex").write_text("#!/bin/sh\n")
    (bin_dir / "codex").chmod(0o755)
    (tmp_path / "wt").mkdir(exist_ok=True)
    watch = ActivityWatch(0, lambda beat: None)
    for w in (watch, None):
        req = request(tmp_path, watch=w)
        req.env = {"PATH": str(bin_dir)}
        CodexAdapter(Spy()).run(req)
    assert seen[0]["watch"] is watch and seen[0]["reader"] is codex_signals
    assert seen[1]["watch"] is None
