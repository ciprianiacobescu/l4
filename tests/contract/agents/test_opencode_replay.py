"""Recorded `opencode run --format json` streams (1.18.33, spikes 01/02/05) replayed through `OpenCodeAdapter.parse`."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.agents.opencode import OpenCodeAdapter
from l4.schemacheck import validate

FIXTURES = Path(__file__).parents[2] / "fixtures"
RECORDED = FIXTURES / "recorded" / "opencode" / "1.18.33"
CANONICAL = json.loads((FIXTURES / "schemas" / "implementer-result.schema.json").read_text())
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def lines(name: str) -> list[str]:
    return (RECORDED / f"{name}.jsonl").read_text().splitlines()


def parse(name: str, tmp_path: Path, *, exit_code: int = 0, **kw):
    kw.setdefault("model", "opencode/big-pickle")
    return OpenCodeAdapter().parse(lines(name), exit_code=exit_code, raw_events_path=tmp_path / "e", now=NOW, **kw)


def test_green_run_is_ok_with_text_cost_and_result_file(tmp_path):
    text = (RECORDED / "green-ok.result.json").read_text()
    out = parse("green-ok", tmp_path, result_text=text, schema=CANONICAL)
    assert out.status == "ok", out.detail
    assert out.structured is not None and out.structured["phase"] == "green"
    assert out.session_id == "ses_efdbef142ffeFcvVope0DDiQLt"
    assert out.model_resolved is None  # run mode never reports the served model
    assert out.final_text and out.final_text.strip()
    assert out.usage.cost_usd is not None and out.usage.output_tokens > 0


def test_cost_is_the_sum_of_every_step_finish(tmp_path):
    out = parse("error-429-free-tier-quota", tmp_path, exit_code=1)
    steps = [json.loads(line) for line in lines("error-429-free-tier-quota")]
    expected = sum(e["part"].get("cost", 0) for e in steps if e["type"] == "step_finish")
    assert expected > 0 and out.usage.cost_usd == pytest.approx(expected)


def test_result_file_missing_or_invalid_is_an_error_not_ok(tmp_path):
    assert parse("green-ok", tmp_path, result_text=None, schema=CANONICAL).status == "error"
    out = parse("green-ok", tmp_path, result_text='{"status": "maybe"}', schema=CANONICAL)
    assert out.status == "error" and "result invalid" in (out.detail or "") and out.structured is None
    assert parse("green-ok", tmp_path, result_text="not json", schema=CANONICAL).status == "error"


def test_nulls_in_the_result_file_are_dropped_before_validation(tmp_path):
    reply = json.loads((RECORDED / "green-ok.result.json").read_text())
    reply["questions"] = None
    out = parse("green-ok", tmp_path, result_text=json.dumps(reply), schema=CANONICAL)
    assert out.status == "ok" and "questions" not in (out.structured or {})


def test_permission_rejection_exit0_is_permission_blocked(tmp_path):
    out = parse("permission-ask-autorejected", tmp_path)
    assert out.status == "permission_blocked"
    assert out.permission_denials and out.permission_denials[0]["tool_name"] == "write"


def test_402_credits_is_quota_without_a_reset(tmp_path):
    out = parse("error-openrouter-insufficient-credits", tmp_path, exit_code=1)
    assert out.status == "quota" and out.limit is not None
    assert out.limit.kind == "credits" and out.limit.resets_at is None
    assert out.limit.source.startswith("opencode.statusCode")


def test_429_is_rate_limited_and_takes_the_reset_from_the_google_body(tmp_path):
    out = parse("error-429-free-tier-quota", tmp_path, exit_code=1)
    assert out.status == "rate_limited" and out.limit is not None
    assert out.limit.kind == "rate_limit"
    assert out.limit.resets_at is not None
    assert 9 * 3600 < (out.limit.resets_at - NOW).total_seconds() < 9.2 * 3600


def test_the_error_wins_over_an_earlier_tool_calls_finish(tmp_path):
    # the stream ends `step_finish tool-calls` then `error`: the error decides, not the last reason
    assert parse("error-429-free-tier-quota", tmp_path, exit_code=1).status == "rate_limited"


@pytest.mark.parametrize("name", ["error-auth-token-refresh-401", "auth-error-openai-oauth"])
def test_token_refresh_401_is_auth_and_starts_no_cooldown(tmp_path, name):
    out = parse(name, tmp_path, exit_code=1)
    assert out.status == "auth" and out.limit is None


def test_503_is_a_plain_error(tmp_path):
    out = parse("error-upstream-503", tmp_path, exit_code=1)
    assert out.status == "error" and out.limit is None and "503" in (out.detail or "")
    assert out.transient is True and out.api_status == 503  # named only as `[503]` in the message (L4-AVL-006)


def test_a_stream_that_stops_mid_tool_calls_without_a_rejection_is_an_error(tmp_path):
    cut = lines("green-ok")[:-2]  # drop the final text and the `stop` finish
    out = OpenCodeAdapter().parse(cut, exit_code=0, raw_events_path=tmp_path / "e", now=NOW)
    assert out.status == "error" and "tool-calls" in (out.detail or "")


def test_timeout_and_interrupt_win_over_everything(tmp_path):
    assert parse("green-ok", tmp_path, timed_out=True).status == "timeout"
    assert parse("green-ok", tmp_path, interrupted=True).status == "cancelled"


def test_nonzero_exit_without_an_error_event_is_an_error(tmp_path):
    out = parse("hello-ok-stdin-prompt", tmp_path, exit_code=2)
    assert out.status == "error" and "2" in (out.detail or "")


def test_hello_reply_is_the_text_part(tmp_path):
    out = parse("hello-ok-stdin-prompt", tmp_path)
    assert out.status == "ok" and (out.final_text or "").strip() == "L4-OK"


JUDGE_SCHEMA = {
    "type": "object", "required": ["verdict", "criteria"],
    "properties": {"verdict": {"enum": ["pass", "fail"]}, "criteria": {"type": "array"}},
}  # fmt: skip


@pytest.mark.parametrize("name", ["judge-ok-openrouter-gpt-5.4-mini", "judge-ok-openrouter-gpt-5.4-mini-run2"])
def test_judge_reply_is_sliced_from_the_first_brace_to_the_last(tmp_path, name):
    out = parse(name, tmp_path, judge=True, schema=JUDGE_SCHEMA)
    assert out.status == "ok", out.detail
    assert out.structured is not None and validate(out.structured, JUDGE_SCHEMA) == []


def test_judge_reply_without_json_or_with_the_wrong_shape_is_a_structured_output_error(tmp_path):
    out = parse("hello-ok-stdin-prompt", tmp_path, judge=True, schema=JUDGE_SCHEMA)
    assert out.status == "error" and (out.detail or "").startswith("structured output")
    demanding = {"type": "object", "required": ["x"]}
    wrong = parse("judge-ok-openrouter-gpt-5.4-mini", tmp_path, judge=True, schema=demanding)
    assert wrong.status == "error" and (wrong.detail or "").startswith("structured output")


def _events(name: str) -> list[dict]:
    out = []
    for line in lines(name):
        try:
            event = json.loads(line)
        except ValueError:
            continue  # the adapter skips a line that is not JSON
        if isinstance(event, dict):
            out.append(event)
    return out


def _sum_tokens(part: dict) -> int:
    tokens = part["tokens"]
    return tokens["input"] + tokens["cache"]["read"] + tokens["cache"]["write"]


def _text_after_last_tool(events: list[dict]) -> str | None:
    last = max((i for i, e in enumerate(events) if e["type"] == "tool_use"), default=-1)
    texts = [e["part"]["text"] for e in events[last + 1 :] if e["type"] == "text"]
    return "\n".join(texts) or None


@pytest.mark.parametrize("name", ["red-ok", "green-ok", "blocked", "red-already-satisfied-claimed"])
def test_last_message_is_the_text_after_the_last_tool_use(tmp_path, name):  # SCN-FAC-17
    events = _events(name)
    assert any(e["type"] == "tool_use" for e in events)
    out = parse(name, tmp_path)
    assert out.last_message == _text_after_last_tool(events)
    assert out.final_text == "\n".join(e["part"]["text"] for e in events if e["type"] == "text")


def test_last_message_is_shorter_than_the_final_text_when_text_comes_before_a_tool_call(tmp_path):  # SCN-FAC-17
    out = parse("red-ok", tmp_path)
    assert out.final_text is not None and out.last_message != out.final_text
    assert out.last_message is None or len(out.last_message) < len(out.final_text)


@pytest.mark.parametrize("name", ["red-ok", "green-ok", "blocked"])
def test_context_peak_is_the_largest_per_call_context(tmp_path, name):  # SCN-FAC-18
    finishes = [e["part"] for e in _events(name) if e["type"] == "step_finish"]
    out = parse(name, tmp_path)
    assert out.usage.context_peak_tokens == max(_sum_tokens(p) for p in finishes)
    assert out.usage.input_tokens == sum(p["tokens"]["input"] for p in finishes)  # unchanged
    assert out.usage.context_peak_percent is None


def _finish(inp: int, read: int, write: int) -> str:
    part = {"reason": "stop", "tokens": {"input": inp, "output": 1, "cache": {"read": read, "write": write}}}
    return json.dumps({"type": "step_finish", "part": part})


def test_context_peak_of_three_calls(tmp_path):  # SCN-FAC-18
    stream = [_finish(5000, 3000, 1000), _finish(1600, 20000, 0), _finish(15000, 0, 0)]
    out = OpenCodeAdapter().parse(stream, exit_code=0, raw_events_path=tmp_path / "e", now=NOW)
    assert out.usage.context_peak_tokens == 21600 and out.usage.input_tokens == 21600


def test_no_tool_use_means_the_whole_text_is_the_last_message(tmp_path):
    text = json.dumps({"type": "text", "part": {"text": "all of it"}})
    out = OpenCodeAdapter().parse([text, _finish(1, 0, 0)], exit_code=0, raw_events_path=tmp_path / "e", now=NOW)
    assert out.last_message == "all of it"
