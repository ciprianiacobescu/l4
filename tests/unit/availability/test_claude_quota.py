"""agent-factory 2.2: Claude quota from `/usage` text (or the latest rate_limit_event), and limits seen by hello."""

import json
from datetime import UTC, datetime

import pytest

from l4.agents.claude_code import ClaudeCodeAdapter
from l4.config.schema import Profile
from l4.doctor.context import CmdResult

from .conftest import RECORDED

CLAUDE = RECORDED / "claude-code" / "2.1.288"
PROFILE = Profile(adapter="claude-code", model="claude-haiku-4-5", auth="subscription", vendor="anthropic")
NOW = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)


def usage_json(name: str) -> str:
    return (CLAUDE / name).read_text()


def ctx_with(make_ctx, usage: str, **kw):
    return make_ctx(
        {("-p",): CmdResult(0, usage, ""), ("--version",): CmdResult(0, "2.1.288 (Claude Code)\n", "")},
        now=lambda: NOW,
        **kw,
    )


def test_usage_runs_the_confirmed_command_under_utc_and_reports_the_most_used_window(make_ctx):
    ctx, run = ctx_with(make_ctx, usage_json("usage_subscription_utc.json"))
    out = ClaudeCodeAdapter().probe(PROFILE, "quota", ctx)
    assert out.ok and not out.skipped
    assert out.detail["quota_used_percent"] == 59 and out.detail["quota_window"] == "session"
    argv, _, env, _ = next(c for c in run.calls if c[0][1] == "-p")
    assert argv[1:] == ["-p", "--safe-mode", "--no-session-persistence", "--output-format", "json", "/usage"]
    assert env["TZ"] == "UTC" and "L4_FORGE_TOKEN" not in env


def test_a_window_below_the_reserve_fails_with_its_reset_and_a_per_model_weekly_window_counts(make_ctx):
    doc = json.loads(usage_json("usage_subscription_utc.json"))
    doc["result"] = doc["result"].replace("Current week (Fable): 0% used", "Current week (Fable): 96% used")
    ctx, _ = ctx_with(make_ctx, json.dumps(doc))
    out = ClaudeCodeAdapter().probe(PROFILE, "quota", ctx)
    assert not out.ok and out.reason == "weekly (Fable) 96% used, 4% remaining < 10%"
    assert out.limit.resets_at == datetime(2026, 10, 7, 18, 0, tzinfo=UTC) and out.limit.window_minutes == 10080


def test_the_runner_pro_plan_text_parses(make_ctx):
    ctx, _ = ctx_with(make_ctx, usage_json("runner-usage-pro.json"))
    out = ClaudeCodeAdapter().probe(PROFILE, "quota", ctx)
    assert out.ok and out.detail["quota_window"] == "weekly (all models)" and out.detail["quota_used_percent"] == 2


def test_api_key_auth_has_no_windows_and_runs_nothing(make_ctx):
    ctx, run = ctx_with(make_ctx, usage_json("usage_api_key.json"))
    out = ClaudeCodeAdapter().probe(PROFILE.model_copy(update={"auth": "api_key"}), "quota", ctx)
    assert out.ok and out.skipped and [c[0][1] for c in run.calls] == ["--version"]


@pytest.mark.parametrize("stdout", ["not json at all", json.dumps({"is_error": True, "result": "boom"}), "{}"])
def test_unrecognised_usage_text_skips_the_step_and_does_not_fail_the_profile(make_ctx, stdout):
    ctx, _ = ctx_with(make_ctx, stdout)
    out = ClaudeCodeAdapter().probe(PROFILE, "quota", ctx)
    assert out.ok and out.skipped and out.detail["quota_unrecognised"] is True
    doc = json.loads(usage_json("usage_api_key.json"))
    ctx2, _ = ctx_with(make_ctx, json.dumps(doc))  # a successful reply with no `Current ...` lines
    assert ClaudeCodeAdapter().probe(PROFILE, "quota", ctx2).detail["quota_unrecognised"] is True


def test_the_latest_rate_limit_event_is_preferred_over_a_usage_call(make_ctx, monkeypatch):
    import time

    from l4.agents import claude_code
    from l4.availability.quota import Window

    monkeypatch.setattr(claude_code, "_LATEST_WINDOWS", {})
    windows = [Window("session", 97, 300, datetime(2026, 10, 3, 14, 0, tzinfo=UTC))]
    # seen by another instance: the factory builds a new one for every use
    claude_code._LATEST_WINDOWS[PROFILE.auth] = (time.monotonic(), windows)
    ctx, run = ctx_with(make_ctx, usage_json("usage_subscription_utc.json"))
    out = ClaudeCodeAdapter().probe(PROFILE, "quota", ctx)
    assert not out.ok and out.reason == "session 97% used, 3% remaining < 10%"
    assert [c[0][1] for c in run.calls] == ["--version"]  # no /usage call
    claude_code._LATEST_WINDOWS[PROFILE.auth] = (time.monotonic() - 10_000, windows)  # a stale event is ignored
    assert ClaudeCodeAdapter().probe(PROFILE, "quota", ctx).ok


def hello_stream(*, rejected: bool, status: int | None) -> str:
    events = [
        {"type": "system", "subtype": "init"},
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "rejected" if rejected else "allowed",
                "resetsAt": 1791046800,
                "rateLimitType": "five_hour",
            },
        },
        {"type": "result", "is_error": True, "api_error_status": status, "subtype": "success", "result": "limit"},
    ]
    return "\n".join(json.dumps(e) for e in events)


def test_a_rejected_rate_limit_event_in_hello_gives_a_limit_signal(make_ctx):
    ctx, _ = make_ctx(
        {
            ("-p",): CmdResult(1, hello_stream(rejected=True, status=429), ""),
            ("--version",): CmdResult(0, "2.1.288", ""),
        },
        now=lambda: NOW,
    )
    out = ClaudeCodeAdapter().probe(PROFILE, "hello", ctx)
    assert not out.ok and out.limit is not None and out.limit.kind == "usage_limit"
    assert out.limit.resets_at == datetime.fromtimestamp(1791046800, UTC)


def test_a_bare_429_gives_a_rate_limit_without_a_reset_and_a_404_gives_none(make_ctx):
    bare, _ = make_ctx(
        {
            ("-p",): CmdResult(1, hello_stream(rejected=False, status=429), ""),
            ("--version",): CmdResult(0, "2.1.288", ""),
        }
    )
    out = ClaudeCodeAdapter().probe(PROFILE, "hello", bare)
    assert out.limit.kind == "rate_limit" and out.limit.resets_at is None
    missing, _ = make_ctx(
        {
            ("-p",): CmdResult(1, hello_stream(rejected=False, status=404), ""),
            ("--version",): CmdResult(0, "2.1.288", ""),
        }
    )
    assert ClaudeCodeAdapter().probe(PROFILE, "hello", missing).limit is None
