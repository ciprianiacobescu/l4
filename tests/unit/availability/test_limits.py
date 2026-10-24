import json
from datetime import UTC, datetime, timedelta

import pytest

from l4.availability.limits import _opencode_v2, normalise_limit, parse_reset

from .conftest import RECORDED

NOW = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
OPENCODE = RECORDED / "opencode" / "1.18.33"


def opencode_error(name: str) -> dict:
    lines = (OPENCODE / name).read_text().splitlines()
    return next(e for e in map(json.loads, lines) if e.get("type") == "error")


def test_structured_reset_beats_text():
    info = {"status": "rejected", "resetsAt": 1791046800, "rateLimitType": "five_hour"}
    signal = normalise_limit("claude-code", "m", structured=info, text="You are out. Resets 6pm (UTC)", now=NOW)
    assert signal is not None and signal.resets_at == datetime.fromtimestamp(1791046800, UTC)
    assert signal.kind == "usage_limit" and signal.source == "claude.rate_limit_event" and signal.window_minutes == 300


def test_claude_event_that_is_not_rejected_is_not_a_limit():
    info = {"status": "allowed", "resetsAt": 1791046800, "rateLimitType": "five_hour"}
    assert normalise_limit("claude-code", "m", structured=info, now=NOW) is None


def test_claude_event_carries_the_used_percent_of_its_window():
    info = {
        "status": "rejected", "resetsAt": 1791046800, "rateLimitType": "seven_day",
        "unifiedWindows": {"seven_day": {"utilization": 1.0, "resetsAt": 1791046800}},
    }  # fmt: skip
    signal = normalise_limit("claude-code", None, structured=info, now=NOW)
    assert signal.used_percent == 100 and signal.window_minutes == 10080


def test_codex_window_is_a_usage_limit_with_its_window_and_percent():
    window = {"usedPercent": 100, "windowDurationMins": 300, "resetsAt": 1791049943}
    signal = normalise_limit("codex", "gpt-6.1-sol", structured=window, now=NOW)
    assert signal.kind == "usage_limit" and signal.window_minutes == 300 and signal.used_percent == 100
    assert signal.resets_at == datetime.fromtimestamp(1791049943, UTC) and signal.model == "gpt-6.1-sol"
    iso = normalise_limit("codex", None, structured={"resetsAt": "2026-10-03T14:32:00Z"}, now=NOW)
    assert iso.resets_at == datetime(2026, 10, 3, 14, 32, tzinfo=UTC)


def test_opencode_429_takes_its_reset_from_the_google_body_text():
    event = opencode_error("error-429-free-tier-quota.jsonl")
    signal = normalise_limit("opencode", "google/gemini", structured=event, now=NOW)
    assert signal.kind == "rate_limit" and signal.source == "opencode.statusCode"
    assert abs((signal.resets_at - NOW - timedelta(hours=9, minutes=9, seconds=37.9)).total_seconds()) < 1
    assert len(signal.raw_excerpt) <= 200 and "\n" not in signal.raw_excerpt


def test_opencode_429_prefers_a_retry_after_header_over_the_body_text():
    event = {
        "error": {
            "data": {"statusCode": 429, "message": "Please retry in 9h0m0s.", "responseHeaders": {"retry-after": "120"}}
        }
    }
    signal = normalise_limit("opencode", None, structured=event, now=NOW)
    assert signal.resets_at == NOW + timedelta(seconds=120)


def test_opencode_402_is_credits_without_a_reset_and_names_its_limit_source():
    signal = normalise_limit(
        "opencode", "openrouter/x", structured=opencode_error("error-openrouter-insufficient-credits.jsonl"), now=NOW
    )
    assert signal.kind == "credits" and signal.resets_at is None
    assert signal.source == "opencode.statusCode:openrouter_credits"


@pytest.mark.parametrize(
    ("tool", "structured", "text"),
    [
        ("claude-code", {"status": "rejected", "api_error_status": 404}, "model not found"),
        ("codex", None, "The 'gpt-x' model is not supported when using Codex with a ChatGPT account (400)"),
        ("opencode", {"error": {"data": {"message": "Token refresh failed: 401"}}}, "Token refresh failed: 401"),
        ("opencode", {"error": {"data": {"statusCode": 503, "message": "overloaded"}}}, "[503] overloaded"),
        ("opencode", {"error": {"data": {"statusCode": 401, "message": "usage limit"}}}, None),
    ],
)  # fmt: skip
def test_configuration_auth_and_upstream_errors_are_not_limits(tool, structured, text):
    assert normalise_limit(tool, None, structured=structured, text=text, now=NOW) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Try again at 3:45 PM", datetime(2026, 10, 3, 15, 45, tzinfo=UTC)),
        ("Try again at 9:00 AM", datetime(2026, 10, 4, 9, 0, tzinfo=UTC)),  # already past today: tomorrow
        ("resets 6pm (Europe/Bucharest)", datetime(2026, 10, 3, 15, 0, tzinfo=UTC)),
        ("resets Oct 3 at 3pm (UTC)", datetime(2026, 10, 3, 15, 0, tzinfo=UTC)),
        ("resets Oct 8, 11:59am (UTC)", datetime(2026, 10, 8, 11, 59, tzinfo=UTC)),
        ("resets Jan 2 at 1am (UTC)", datetime(2027, 1, 2, 1, 0, tzinfo=UTC)),  # the next occurrence of the date
        ("please retry in 9h9m42s", NOW + timedelta(hours=9, minutes=9, seconds=42)),
        ("Retry in 5m", NOW + timedelta(minutes=5)),
        ("try again in 2 hours", NOW + timedelta(hours=2)),
        ("limit reached, available again at 2026-10-05T01:02:00Z", datetime(2026, 10, 5, 1, 2, tzinfo=UTC)),
        ("Try again at 15:45", datetime(2026, 10, 3, 15, 45, tzinfo=UTC)),
    ],
)  # fmt: skip
def test_text_parser_reads_the_locale_tolerant_forms(text, expected):
    assert parse_reset(text, NOW) == expected


def test_text_with_no_time_gives_a_limit_without_a_reset_and_other_text_gives_none():
    signal = normalise_limit("codex", None, text="You've hit your usage limit.", now=NOW)
    assert signal.kind == "usage_limit" and signal.resets_at is None and signal.source == "text"
    assert normalise_limit("codex", None, text="the build failed", now=NOW) is None
    assert parse_reset("nothing here", NOW) is None


def test_text_limit_kinds():
    assert normalise_limit("x", None, text="Insufficient credits to continue", now=NOW).kind == "credits"
    assert normalise_limit("x", None, text="Rate limit exceeded, retry in 30s", now=NOW).kind == "rate_limit"
    assert normalise_limit("x", None, text="Monthly spend limit reached", now=NOW).kind == "spend_limit"


def test_the_excerpt_is_cut_to_200_characters():
    signal = normalise_limit("codex", None, text="usage limit " + "x" * 500, now=NOW)
    assert len(signal.raw_excerpt) == 200


# --- OpenCode v2 (L4-OCV-009): the payload is `error.{type, message, status, response.body}` with no `error.data` ---
# status_only (U1): no v2 429 or 402 was ever recorded, so these are synthetic fallback pins, not recorded shapes.


def v2_event(status: int, message: str = "m", body: str = "") -> dict:
    return {"type": "error", "error": {"type": "unknown", "message": message, "status": status,
                                       "response": {"body": body}}}  # fmt: skip


def test_opencode_v2_429_is_a_rate_limit_without_a_reset_status_only():
    """The message, the body and the caller's text all say `retry in 9h9m42s`; none of them is read."""
    event = v2_event(429, "retry in 9h9m42s", "retry in 9h9m42s")
    signal = normalise_limit("opencode", "opencode-go/m", structured=event, text="retry in 9h9m42s", now=NOW)
    assert signal is not None and signal.kind == "rate_limit" and signal.resets_at is None
    assert signal.source == "opencode2.status" and signal.tool == "opencode" and signal.model == "opencode-go/m"


def test_opencode_v2_402_is_credits_status_only():
    signal = normalise_limit("opencode", None, structured=v2_event(402, "insufficient balance"), now=NOW)
    assert signal is not None and signal.kind == "credits" and signal.resets_at is None
    assert signal.source == "opencode2.status"


@pytest.mark.parametrize("status", [400, 401, 403, 500, 503])
def test_opencode_v2_other_statuses_are_not_limits_whatever_the_text_says_status_only(status):
    event = v2_event(status, "rate limit exceeded, usage limit, retry in 5m")
    assert normalise_limit("opencode", None, structured=event, text="rate limit exceeded, retry in 5m", now=NOW) is None


def test_the_shape_picks_the_v2_reader_and_leaves_the_v1_reader_alone():
    """`error.status` with no `error.data` is v2; `error.data.statusCode` is v1 and keeps its text fallback."""
    assert _opencode_v2(None, NOW, v2_event(429)) is not None
    assert _opencode_v2(None, NOW, {"error": {"data": {"statusCode": 429}}}) is None
    v1 = {"error": {"data": {"statusCode": 429, "message": "retry in 5m"}}}
    signal = normalise_limit("opencode", None, structured=v1, now=NOW)
    assert signal is not None and signal.source == "opencode.statusCode"
    assert signal.resets_at == NOW + timedelta(minutes=5)
    mixed = {"error": {"status": 429, "data": {"statusCode": 503, "message": "overloaded"}}}  # has data: v1 reader
    assert normalise_limit("opencode", None, structured=mixed, now=NOW) is None
