"""The Copilot CLI adapter `l4.agents.copilot_cli` (copilot-cli 2.1): the parse, the stop watcher and the usage
document, against streams recorded on Copilot CLI 1.0.102 in BYOK mode (a local OpenAI-compatible model) and against
the first GitHub-routed calls (`1.0.102-firstcalls`)."""

import json
import os
from pathlib import Path

from l4.agents import copilot_cli
from l4.agents.base import PermissionPolicy, RunRequest
from l4.agents.copilot_cli import (
    CopilotCliAdapter,
    CopilotStop,
    build_command,
    parse,
    read_usage,
    stream_facts,
    usage_of,
)
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "copilot-cli" / "1.0.102-byok"
FIRSTCALLS = Path(__file__).parents[2] / "fixtures" / "recorded" / "copilot-cli" / "1.0.102-firstcalls"
PROFILE = Profile(adapter="copilot-cli", model="claude-sonnet-5.5")
SCHEMA = {"type": "object", "required": ["status"], "properties": {"status": {"type": "string"}}}
VERDICT = {"status": "pass"}


def recorded(name: str) -> str:
    return (RECORDED / name).read_text(encoding="utf-8")


def firstcall(name: str) -> str:
    return (FIRSTCALLS / name).read_text(encoding="utf-8")


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
    (tmp_path / "bin").mkdir(exist_ok=True)
    exe = tmp_path / "bin" / "copilot"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    (tmp_path / "wt").mkdir(exist_ok=True)
    return RunRequest(
        role="implementer", cwd=tmp_path / "wt", result_path=tmp_path / "step" / "result.json",
        raw_events_path=tmp_path / "raw" / "events.jsonl", **kw,
    )  # fmt: skip


class FakeProc:
    def __init__(self, stdout: str = "") -> None:
        self.calls: list[dict] = []
        self.stdout = stdout

    def run(self, argv, env, cwd, *, stdout_path, timeout_s, stdin=None, stderr_path=None, on_line=None, **kw):
        self.calls.append({"argv": list(argv), "env": dict(env), "stdin": stdin, "cwd": cwd})
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(self.stdout)
        for line in self.stdout.splitlines():
            if on_line is not None and on_line(line):
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
