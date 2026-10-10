"""agent-factory 4.3: one zero-token `codex app-server` session gives the auth and the quota step."""

import dataclasses
from datetime import UTC, datetime

import pytest

from l4.agents.codex import CodexAdapter
from l4.config.schema import Profile
from l4.doctor.context import CmdResult

from ._rpc_helpers import fake_rpc, recording, silent_rpc

PROFILE = Profile(adapter="codex", model="gpt-6.1-sol", auth="subscription", vendor="openai")
VERSION = ("--version",)


@pytest.fixture
def codex_ctx(make_ctx):
    def build(rec, *, sent=None, **kw):
        ctx, run = make_ctx({VERSION: CmdResult(0, "codex-cli 0.160.0\n", "")}, **kw)
        return dataclasses.replace(ctx, rpc=fake_rpc(rec, sent)), run

    return build


def test_weekly_window_exhausted_while_five_hour_ok(codex_ctx):
    rec = recording("app_server_account_and_rate_limits_chatgpt.json")
    bucket = rec["rate_limits_read"]["result"]["rateLimitsByLimitId"]["codex"]
    bucket["secondary"]["usedPercent"] = 100
    bucket["primary"]["usedPercent"] = 4
    ctx, run = codex_ctx(rec)
    out = CodexAdapter().probe(PROFILE, "quota", ctx)
    assert not out.ok and out.reason == "weekly window 100% used, 0% remaining"
    assert out.limit.kind == "usage_limit" and out.limit.window_minutes == 10080
    assert out.limit.resets_at == datetime.fromtimestamp(1791636743, UTC)
    assert [c[0][1] for c in run.calls] == ["--version"]  # no `codex exec`: not a single model request


def test_a_healthy_session_reports_the_most_used_window(codex_ctx):
    rec = recording("app_server_account_and_rate_limits_chatgpt.json")
    rec["rate_limits_read"]["result"]["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = 49
    out = CodexAdapter().probe(PROFILE, "quota", codex_ctx(rec)[0])
    assert out.ok and not out.skipped
    assert out.detail["quota_used_percent"] == 49 and out.detail["quota_window"] == "5h window"


def test_reset_credits_are_never_redeemed_and_only_read_methods_are_sent(codex_ctx):
    sent: list = []
    rec = recording("app_server_account_and_rate_limits_chatgpt.json")
    ctx, _ = codex_ctx(rec, sent=sent)
    adapter = CodexAdapter()
    adapter.probe(PROFILE, "auth", ctx)
    adapter.probe(PROFILE, "quota", ctx)
    methods = {m["method"] for messages in sent for m in messages}
    assert methods == {"initialize", "initialized", "account/read", "account/rateLimits/read"}
    assert not any("reset" in m.lower() and "credit" in m.lower() for m in methods)


def test_an_api_key_login_has_no_rate_limit_query_so_the_step_is_skipped(codex_ctx):
    rec = recording("app_server_api_key_login.json")
    out = CodexAdapter().probe(PROFILE, "quota", codex_ctx(rec)[0])
    assert out.ok and out.skipped and not out.detail.get("quota_unrecognised")


def test_an_answer_the_probe_does_not_know_skips_the_step_and_does_not_fail_the_profile(codex_ctx, make_ctx):
    ctx, _ = make_ctx({VERSION: CmdResult(0, "codex-cli 0.160.0", "")})
    silent = dataclasses.replace(ctx, rpc=silent_rpc())
    out = CodexAdapter().probe(PROFILE, "quota", silent)
    assert out.ok and out.skipped and out.detail["quota_unrecognised"] is True
    rec = recording("app_server_account_and_rate_limits_chatgpt.json")
    rec["rate_limits_read"] = {"result": {"rateLimitsByLimitId": {}}}
    assert CodexAdapter().probe(PROFILE, "quota", codex_ctx(rec)[0]).detail["quota_unrecognised"]


def test_auth_keeps_type_and_plan_and_drops_every_identity_field(codex_ctx):
    rec = recording("app_server_account_and_rate_limits_chatgpt.json")
    rec["account_read"]["result"]["account"]["email"] = "alice@example.com"
    rec["account_read"]["result"]["workspaceRouting"]["chatgptAccountId"] = "acct-123"
    out = CodexAdapter().probe(PROFILE, "auth", codex_ctx(rec)[0])
    assert out.ok and out.detail == {"logged_in": True, "auth_method": "chatgpt", "plan": "plus"}
    assert not any(secret in repr(out) for secret in ("alice", "acct-123", "example.com"))


def test_auth_fails_for_a_logged_out_codex_and_for_an_api_key_login(codex_ctx):
    out = CodexAdapter().probe(PROFILE, "auth", codex_ctx(recording("app_server_logged_out.json"))[0])
    assert not out.ok and out.reason == "codex is not logged in (ChatGPT login required)"
    keyed = CodexAdapter().probe(PROFILE, "auth", codex_ctx(recording("app_server_api_key_login.json"))[0])
    assert not keyed.ok and "ChatGPT" in keyed.reason
    gone = CodexAdapter().probe(PROFILE, "auth", codex_ctx({})[0])
    assert not gone.ok and "unrecognised" in gone.reason


def test_the_runner_recording_gives_a_plus_plan_with_room(codex_ctx):
    rec = recording("runner-app-server.json")
    adapter, ctx = CodexAdapter(), codex_ctx(rec)[0]
    assert adapter.probe(PROFILE, "auth", ctx).detail["plan"] == "plus"
    assert adapter.probe(PROFILE, "quota", ctx).ok


def test_api_key_profiles_skip_the_quota_step_without_any_session(codex_ctx):
    sent: list = []
    ctx, _ = codex_ctx(recording("app_server_api_key_login.json"), sent=sent)
    out = CodexAdapter().probe(PROFILE.model_copy(update={"auth": "api_key"}), "quota", ctx)
    assert out.ok and out.skipped and sent == []


def test_the_profile_reserve_applies_to_the_codex_windows(codex_ctx):
    rec = recording("app_server_account_and_rate_limits_chatgpt.json")
    rec["rate_limits_read"]["result"]["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = 70
    ctx, _ = codex_ctx(rec)
    assert CodexAdapter().probe(PROFILE, "quota", ctx).ok
    strict = PROFILE.model_copy(update={"min_remaining_percent": 40})
    out = CodexAdapter().probe(strict, "quota", ctx)
    assert not out.ok and out.reason == "5h window 70% used, 30% remaining < 40% (profile reserve)"
