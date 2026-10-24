"""The OpenCode v2 parser (L4-OCV-006 detection, -007, -008, -009, -011; SCN-OCV-13 to -20 and -23 unit part). Every
test reads the recorded 2.0.32 fixtures; a test that needs a shape nobody has recorded says "synthetic" and builds it
in memory (nothing is written under the fixture directory). Each [U] fact (design D13) stays on its named fallback, and
the test that pins the fallback carries its name."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.agents.base import RunResult
from l4.agents.opencode_v2 import OpenCodeV2Adapter, _scan_v2, strip_leading_think, usage_from_export

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "opencode" / "2.0.32"
CLI_MAJOR = Path(__file__).parents[2] / "fixtures" / "cli_major" / "opencode"
NOW = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)
JUDGE_SCHEMA = {"type": "object", "required": ["verdict"], "properties": {"verdict": {"type": "string"}}}


def lines(name: str) -> list[str]:
    return (RECORDED / name).read_text().splitlines()


def recorded_export() -> dict:
    return json.loads((RECORDED / "text-no-step-finish.export.json").read_text())


def succeeded(outcome: str = "succeeded") -> dict:
    """A synthetic export that says only the outcome (no recorded export exists for the ask-loop run)."""
    return {"info": {"outcome": outcome}, "messages": []}


def parse(source: str | list[str], tmp_path: Path, **kw) -> RunResult:
    kw.setdefault("exit_code", 0)
    kw.setdefault("step_bound", 200)
    kw.setdefault("now", NOW)
    stream = lines(source) if isinstance(source, str) else source
    return OpenCodeV2Adapter().parse(stream, raw_events_path=tmp_path / "raw-001.jsonl", **kw)


def event(kind: str, **fields) -> str:
    return json.dumps({"type": kind, "sessionID": "ses_x", **fields})


def text(value: str) -> str:
    return event("text", part={"type": "text", "text": value})


def denied_call(tool: str = "shell") -> str:
    state = {"status": "error", "input": {"command": "ls"}, "error": "Permission denied: " + tool}
    return event("tool_use", part={"type": "tool", "tool": tool, "state": state})


def v2_error(status: int | None, message: str = "m", kind: str = "unknown", body: str = "") -> list[str]:
    error: dict = {"type": kind, "message": message, "response": {"body": body}}
    if status is not None:
        error["status"] = status
    return [event("step_start", part={}), event("error", error=error)]


# --- SCN-OCV-13: a run that reached its step bound is never ok (not_ok_named, U7) ---


def test_bounded_run_is_never_ok_not_ok_named(tmp_path):
    """The recorded `steps: 3` ask loop has 3 `step_start` events and two rejected tool calls, exit 0. The bound rule
    comes before the export rule, so no export and a synthetic `succeeded` export give the same status."""
    for export in (None, succeeded()):
        out = parse("ask-loop-steps3.jsonl", tmp_path, judge=True, step_bound=3, export=export)
        assert out.status == "permission_blocked" and out.exit_code == 0
        assert [d["tool_name"] for d in out.permission_denials] == ["read", "shell"]


def test_a_bounded_run_without_denials_is_a_step_bound_error_not_ok_named(tmp_path):
    """Synthetic: the recorded ask loop with its `tool_use` lines removed (in memory)."""
    stream = [line for line in lines("ask-loop-steps3.jsonl") if json.loads(line)["type"] != "tool_use"]
    for export in (None, succeeded()):
        out = parse(stream, tmp_path, judge=True, step_bound=3, export=export)
        assert out.status == "error" and out.permission_denials == []
        assert out.detail == "step_bound: opencode2 stopped at agents.build.steps 3"


def test_a_run_below_its_bound_is_not_bounded(tmp_path):
    out = parse("ask-loop-steps3.jsonl", tmp_path, judge=True, step_bound=4, export=succeeded())
    assert not (out.detail or "").startswith("step_bound:")


# --- SCN-OCV-14/15/16: status from the export (export_decides U5, not_ok_named U7) ---


def test_recorded_success_without_step_finish_is_ok_by_its_export(tmp_path):
    out = parse("text-no-step-finish.jsonl", tmp_path, export=recorded_export(), result_text='{"status":"done"}')
    assert out.status == "ok" and out.session_id == "ses_eaaf118f5ffeKxj5Y8YnV3DZsF"


def test_recorded_success_with_step_finish_and_no_export_is_ok_export_decides(tmp_path):
    """export_decides (U5): with no export the v1 rule decides, and the last `step_finish` says `stop`."""
    out = parse("hello-ok-step-finish.jsonl", tmp_path, export=None, result_text='{"status":"done"}')
    assert out.status == "ok"


def test_no_export_and_no_final_stop_is_an_error_that_names_the_export_export_decides(tmp_path):
    """export_decides (U5): the stream ends at `text` and the export failed."""
    out = parse("text-no-step-finish.jsonl", tmp_path, export=None, export_problem="exit 1")
    assert out.status == "error"
    assert out.detail == "opencode2 session export failed (exit 1) and the stream has no final stop"


def test_an_export_without_an_outcome_is_unavailable_export_decides(tmp_path):
    """Synthetic: a document with no `info.outcome` is the export-unavailable case, not an unknown outcome."""
    out = parse("text-no-step-finish.jsonl", tmp_path, export={"info": {}, "messages": []})
    assert out.status == "error" and "opencode2 session export failed" in (out.detail or "")
    out = parse("hello-ok-step-finish.jsonl", tmp_path, export={"info": {}}, result_text='{"status":"done"}')
    assert out.status == "ok"


def test_a_stream_with_denials_and_no_export_is_permission_blocked_export_decides(tmp_path):
    out = parse("implement-deny-continues.jsonl", tmp_path, export=None, export_problem="timeout")
    assert out.status == "permission_blocked" and "shell" in (out.detail or "")


def test_another_outcome_is_never_ok_not_ok_named(tmp_path):
    """not_ok_named (U7): the recorded export with `outcome` changed to `failed` (synthetic edit)."""
    export = recorded_export()
    export["info"]["outcome"] = "failed"
    out = parse("text-no-step-finish.jsonl", tmp_path, export=export, result_text='{"status":"done"}')
    assert out.status == "error" and out.detail == "opencode2 session outcome failed"


def test_a_succeeded_export_does_not_hide_a_result_that_does_not_attach(tmp_path):
    out = parse("text-no-step-finish.jsonl", tmp_path, export=recorded_export(), schema={"type": "object"})
    assert out.status == "error" and "result missing" in (out.detail or "")


def test_the_status_order_timeout_then_cancelled_then_error_event_harness_interrupt(tmp_path):
    """harness_interrupt (U10): the harness's own flag decides `cancelled`, not an exit code of 130."""
    both = parse("text-no-step-finish.jsonl", tmp_path, exit_code=-9, timed_out=True, interrupted=True)
    assert both.status == "timeout"
    assert parse("text-no-step-finish.jsonl", tmp_path, exit_code=130, interrupted=True).status == "cancelled"
    failing = parse("error-403-free-tier-network.jsonl", tmp_path, exit_code=1, timed_out=True)
    assert failing.status == "timeout"


def test_a_v1_flag_rejection_is_still_an_unsupported_version(tmp_path):
    """SCN-OCG-07 on the v2 parser: exit 1 with the recorded stderr of a rejected `--dir`."""
    stream = (CLI_MAJOR / "v2-2.0.32.run-help.stdout.txt").read_text().splitlines()
    stderr = (CLI_MAJOR / "v2-2.0.32.run-dir.stderr.txt").read_text()
    out = parse(stream, tmp_path, exit_code=1, stderr_tail=stderr)
    assert out.status == "error" and (out.detail or "").startswith("unsupported_version:")
    assert parse(stream, tmp_path, exit_code=1).detail == "opencode2 exited with code 1"


def test_the_error_event_decides_before_the_exit_code_and_the_bound(tmp_path):
    stream = [*lines("ask-loop-steps3.jsonl"), *v2_error(500, "boom")]
    out = parse(stream, tmp_path, exit_code=1, step_bound=3, export=succeeded())
    assert out.status == "error" and out.detail == "opencode2 reported an error (unknown, status 500), retryable"


# --- SCN-OCV-17: usage from the export (sum_messages U11) ---


def test_usage_from_the_recorded_export():
    usage = usage_from_export(recorded_export())
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens, usage.cached_input_tokens) == (3310, 78, 605)
    assert usage.cost_usd == 0.0 and usage.context_peak_tokens == 3915


def test_parse_takes_usage_from_the_export(tmp_path):
    out = parse("text-no-step-finish.jsonl", tmp_path, export=recorded_export())
    assert (out.usage.input_tokens, out.usage.output_tokens, out.usage.cached_input_tokens) == (3310, 78, 605)
    assert out.usage.cost_usd == 0.0 and out.usage.context_peak_tokens == 3915


def test_without_an_export_usage_is_the_stream_step_finish_sums_sum_messages(tmp_path):
    """sum_messages (U11) names the export path; with no export the `step_finish` parts are summed as in v1."""
    out = parse("hello-ok-step-finish.jsonl", tmp_path, export=None)
    assert (out.usage.input_tokens, out.usage.output_tokens, out.usage.cached_input_tokens) == (983, 11, 70)
    assert out.usage.cost_usd == 0.0 and out.usage.context_peak_tokens == 983 + 70


def test_usage_sum_messages_over_a_synthetic_multi_step_export():
    """sum_messages (U11): no multi-step export is recorded, so the layout is synthetic: one assistant message per step.
    Tokens are summed, the cost falls back to the messages' sum, the peak is the largest single message."""

    def assistant(inp: int, out: int, read: int, write: int, cost: float) -> dict:
        tokens = {"input": inp, "output": out, "reasoning": 9, "cache": {"read": read, "write": write}}
        return {"type": "assistant", "tokens": tokens, "cost": cost}

    export = {
        "info": {"outcome": "succeeded"},
        "messages": [
            {"type": "user", "text": "go"}, assistant(100, 10, 50, 5, 0.5), assistant(200, 20, 300, 0, 0.25),
            {"type": "idle", "outcome": "succeeded"},
        ],
    }  # fmt: skip
    usage = usage_from_export(export)
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens, usage.cached_input_tokens) == (300, 30, 350)
    assert usage.cost_usd == 0.75 and usage.context_peak_tokens == 500
    export["info"]["cost"] = 1.5
    assert usage_from_export(export).cost_usd == 1.5  # type: ignore[union-attr]


def test_an_export_with_no_assistant_message_gives_no_usage():
    assert usage_from_export(None) is None
    assert usage_from_export({"info": {}, "messages": [{"type": "user"}]}) is None


# --- SCN-OCV-18/19: errors and limits (auth_by_status U4, status_only U1) ---


@pytest.mark.parametrize("name", ["error-403-free-tier-denied-tools.jsonl", "error-403-free-tier-network.jsonl"])
def test_both_recorded_free_tier_403s_are_auth_with_no_limit_auth_by_status(tmp_path, name):
    """auth_by_status (U4): the 403 status and `provider.auth` decide, whatever the exit code."""
    out = parse(name, tmp_path, exit_code=1, model="opencode/big-pickle")
    assert out.status == "auth" and out.limit is None
    assert "authenticate" in (out.detail or "")


@pytest.mark.parametrize("status", [401, 403])
def test_a_synthetic_401_or_403_is_auth_auth_by_status(tmp_path, status):
    assert parse(v2_error(status), tmp_path, exit_code=1).status == "auth"


def test_a_synthetic_provider_auth_type_or_the_auth_wording_is_auth_auth_by_status(tmp_path):
    assert parse(v2_error(None, kind="provider.auth"), tmp_path, exit_code=1).status == "auth"
    assert parse(v2_error(None, "Token refresh failed: 401"), tmp_path, exit_code=1).status == "auth"


def test_a_429_is_a_rate_limit_without_a_guessed_reset_status_only(tmp_path):
    """status_only (U1), a synthetic fallback pin and NOT a recorded shape: no v2 429 was ever recorded. Neither the
    message nor `response.body` is read for a reset, even though both say `retry in 9h9m42s`."""
    body = "retry in 9h9m42s"
    error = {"type": "unknown", "message": body, "status": 429, "response": {"body": body}}
    stream = [json.dumps({"type": "error", "error": error})]
    out = parse(stream, tmp_path, exit_code=1, model="opencode-go/m")
    assert out.status == "rate_limited" and out.limit is not None
    assert out.limit.kind == "rate_limit" and out.limit.resets_at is None
    assert out.limit.source == "opencode2.status" and out.limit.model == "opencode-go/m"


def test_a_402_is_quota_credits_status_only(tmp_path):
    """status_only (U1): a synthetic fallback pin, not a recorded shape."""
    out = parse(v2_error(402, "insufficient balance"), tmp_path, exit_code=1)
    assert out.status == "quota" and out.limit is not None and out.limit.kind == "credits"
    assert out.limit.resets_at is None and out.limit.source == "opencode2.status"


def test_a_503_is_a_retryable_error_not_a_limit_status_only(tmp_path):
    """status_only (U1): a synthetic fallback pin. Any status above 500 is retryable and never a limit."""
    out = parse(v2_error(503, "rate limit, retry in 5m"), tmp_path, exit_code=1)
    assert out.status == "error" and out.limit is None
    assert out.detail == "opencode2 reported an error (unknown, status 503), retryable"


def test_another_status_or_none_is_an_error_naming_the_type_and_status(tmp_path):
    out = parse(v2_error(400, "bad"), tmp_path, exit_code=1)
    assert out.status == "error" and out.detail == "opencode2 reported an error (unknown, status 400)"
    out = parse(v2_error(None, "Transport: closed"), tmp_path, exit_code=1)
    assert out.status == "error" and out.detail == "opencode2 reported an error (unknown)"


# --- SCN-OCV-20: denials ---


def test_the_recorded_implement_run_has_one_shell_denial(tmp_path):
    out = parse("implement-deny-continues.jsonl", tmp_path, export=succeeded(), result_text='{"status":"done"}')
    (denial,) = out.permission_denials
    assert denial["tool_name"] == "shell" and "git commit" in denial["tool_input"]["command"]
    assert out.status == "ok"  # the run continued and finished: the denial is recorded, not fatal


def test_the_recorded_unbounded_ask_loop_has_thirty_denials(tmp_path):
    out = parse("ask-loop-unbounded.jsonl", tmp_path, exit_code=1, step_bound=200)
    assert len(out.permission_denials) == 30
    assert {d["tool_name"] for d in out.permission_denials} == {"read", "shell"}


def test_only_a_permission_denied_or_ask_rejected_tool_error_is_a_denial():
    """Synthetic: an error that is neither wording (a failed command) is not a denial; a completed call is not."""
    failed = {"status": "error", "input": {}, "error": "command exited with code 1"}
    stream = [
        event("tool_use", part={"tool": "shell", "state": failed}),
        event("tool_use", part={"tool": "write", "state": {"status": "completed", "input": {}}}),
        denied_call("read"),
    ]
    assert [d["tool_name"] for d in _scan_v2(stream).denials] == ["read"]


# --- SCN-OCV-23: the leaked </think> (strip_leading_think, U9) ---


def test_strip_leading_think_removes_through_a_closing_tag_with_no_opening_one():
    assert strip_leading_think("The user just wants exact reply.</think>L4-OK") == "L4-OK"
    assert strip_leading_think("a</think>  b </think> c ") == "b </think> c"


def test_strip_leading_think_leaves_a_text_with_an_opening_tag_or_no_tag_alone():
    assert strip_leading_think("<think>a</think>b") == "<think>a</think>b"
    assert strip_leading_think("no tags") == "no tags"
    assert strip_leading_think("  padded  ") == "  padded  "


def test_the_recorded_leaked_hello_reads_as_l4_ok_strip_leading_think(tmp_path):
    assert _scan_v2(lines("hello-think-leak.jsonl")).texts == ["L4-OK"]
    out = parse("hello-think-leak.jsonl", tmp_path)
    assert out.final_text == "L4-OK" and out.last_message == "L4-OK"


def test_a_reply_that_is_only_reasoning_stays_empty_strip_leading_think(tmp_path):
    out = parse([text("only reasoning</think>")], tmp_path, judge=True, schema=JUDGE_SCHEMA, export=succeeded())
    assert out.status == "error" and out.structured is None


def test_leaked_reasoning_with_braces_does_not_break_the_judge_slice_strip_leading_think(tmp_path):
    """Synthetic: reasoning that holds `{` and `}` before the leaked closing tag."""
    stream = [text('I could answer {"verdict": "no"} but no.</think>{"verdict": "yes"}')]
    out = parse(stream, tmp_path, judge=True, schema=JUDGE_SCHEMA, export=succeeded())
    assert out.status == "ok" and out.structured == {"verdict": "yes"}


# --- the judge reply comes from last_message through the shared slicer ---


def test_the_judge_reply_is_the_text_after_the_last_tool_call(tmp_path):
    """Synthetic: prose with a `{` before a rejected tool call, then the JSON reply."""
    stream = [text("let me look at {this} first"), denied_call("read"), text('{"verdict": "pass"}')]
    out = parse(stream, tmp_path, judge=True, schema=JUDGE_SCHEMA, export=succeeded())
    assert out.status == "ok" and out.structured == {"verdict": "pass"}
    assert out.last_message == '{"verdict": "pass"}' and "let me look" in (out.final_text or "")
    assert len(out.permission_denials) == 1


def test_a_judge_reply_without_a_valid_object_keeps_the_repair_detail(tmp_path):
    out = parse([text("no json here")], tmp_path, judge=True, schema=JUDGE_SCHEMA, export=succeeded())
    assert out.status == "error" and (out.detail or "").startswith("structured output")
    bad = parse([text('{"other": 1}')], tmp_path, judge=True, schema=JUDGE_SCHEMA, export=succeeded())
    assert bad.status == "error" and bad.rejected == {"other": 1}


def test_the_adapter_has_no_read_only_parse():
    """Amendment E4: the delegate's read-only mode is not served, so `parse` takes no `read_only`."""
    with pytest.raises(TypeError):
        OpenCodeV2Adapter().parse([], exit_code=0, raw_events_path=Path("x"), step_bound=3, read_only=True)  # type: ignore[call-arg]
