import json
from datetime import UTC, datetime

from l4.availability.quota import (
    Window,
    codex_windows,
    evaluate_windows,
    parse_usage,
    rate_limit_event_windows,
    window_label,
)

from .conftest import RECORDED

NOW = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
R5 = datetime(2026, 10, 3, 14, 32, tzinfo=UTC)
RW = datetime(2026, 10, 9, 0, 0, tzinfo=UTC)
CLAUDE = RECORDED / "claude-code" / "2.1.288"
CODEX = RECORDED / "codex" / "0.160.0"


def five_hour(used: float, resets=R5) -> Window:
    return Window("5h window", used, 300, resets)


def weekly(used: float, resets=RW) -> Window:
    return Window("weekly window", used, 10080, resets)


def run(windows, reserve=10.0, profile_reserve=False, extra=None):
    return evaluate_windows(
        "codex", "gpt-6", windows, reserve=reserve, reserve_is_profile=profile_reserve, source="codex.rateLimits",
        extra_exhausted=extra,
    )  # fmt: skip


def test_quota_threshold_reason_text():
    out = run([five_hour(95), weekly(3)])
    assert not out.ok and out.reason == "5h window 95% used, 5% remaining < 10%"
    assert out.limit.kind == "usage_limit" and out.limit.resets_at == R5
    assert out.limit.window_minutes == 300 and out.limit.used_percent == 95


def test_an_exhausted_window_reads_like_the_spec_line_and_ends_at_its_reset():
    out = run([five_hour(100), weekly(3)])
    assert out.reason == "5h window 100% used, 0% remaining"  # SPEC 8.4: the reset is added by the console line
    assert out.limit.resets_at == R5 and out.limit.used_percent == 100


def test_weekly_window_exhausted_while_five_hour_is_fine_binds_on_the_weekly_one():
    out = run([five_hour(5), weekly(100)])
    assert not out.ok and out.reason == "weekly window 100% used, 0% remaining"
    assert out.limit.window_minutes == 10080 and out.limit.resets_at == RW


def test_when_several_windows_bind_the_cooldown_ends_at_the_latest_reset():
    out = run([five_hour(100), weekly(97)])
    assert out.limit.resets_at == RW  # an early re-probe must not find the weekly window still binding
    assert out.reason.startswith("5h window 100% used")  # the most used window is named
    assert out.reason.endswith("; cool-down follows the weekly window reset")  # the reset shown is another window's


def test_a_binding_window_without_a_reset_gives_a_limit_without_one():
    out = run([Window("session", 100, 300, None)])
    assert not out.ok and out.limit.resets_at is None


def test_all_windows_fine_is_ok_and_reports_the_most_used_one():
    out = run([Window("session", 49, 300, R5), Window("weekly (all models)", 17.5, 10080, RW)])
    assert out.ok and not out.skipped and out.limit is None
    assert out.detail["quota_used_percent"] == 49 and out.detail["quota_window"] == "session"
    assert [w["name"] for w in out.detail["windows"]] == ["session", "weekly (all models)"]
    assert out.detail["windows"][0]["resets_at"] == "2026-10-03T14:32:00Z"


def test_profile_reserve_overrides_global():
    windows = [five_hour(75)]  # 25% remaining
    assert run(windows, reserve=10).ok
    out = run(windows, reserve=30, profile_reserve=True)
    assert not out.ok and out.reason == "5h window 75% used, 25% remaining < 30% (profile reserve)"
    assert run(windows, reserve=20, profile_reserve=True).ok
    # an exhausted window needs no reserve to be named
    assert run([five_hour(100)], reserve=30, profile_reserve=True).reason == "5h window 100% used, 0% remaining"
    # a reserve of 0 still refuses a window with nothing left
    assert not run([five_hour(100)], reserve=0, profile_reserve=True).ok
    assert run([five_hour(99)], reserve=0, profile_reserve=True).ok


def test_an_extra_exhaustion_flag_fails_the_step_even_with_room_in_every_window():
    out = run([five_hour(10), weekly(10)], extra="ordinaryUsageAllowed is false")
    assert not out.ok and out.reason == "ordinaryUsageAllowed is false" and out.limit.kind == "usage_limit"
    assert out.limit.resets_at is None  # no window binds: the default cool-down applies


def test_window_labels():
    assert [window_label(m) for m in (300, 10080, 60, 90, 1440, None)] == [
        "5h window", "weekly window", "1h window", "90m window", "1d window", "window",
    ]  # fmt: skip


def codex_result(name="app_server_account_and_rate_limits_chatgpt.json"):
    return json.loads((CODEX / name).read_text())["rate_limits_read"]["result"]


def test_codex_picks_the_bucket_of_the_model_else_codex():
    result = codex_result()
    windows, extra = codex_windows(result, "gpt-6")
    assert [(w.name, w.used_percent, w.window_minutes) for w in windows] == [
        ("5h window", 0, 300), ("weekly window", 0, 10080),
    ]  # fmt: skip
    assert windows[0].resets_at == datetime.fromtimestamp(1791049943, UTC) and extra is None
    result["rateLimitsByLimitId"]["codex_gpt_6"] = {
        "limitId": "codex_gpt_6", "normalModelSlug": "gpt-6",
        "primary": {"usedPercent": 100, "windowDurationMins": 300, "resetsAt": 1791049943},
        "secondary": None, "spendControlReached": False, "rateLimitReachedType": None,
    }  # fmt: skip
    own, _ = codex_windows(result, "gpt-6")
    assert [(w.used_percent, w.window_minutes) for w in own] == [(100, 300)]  # a window that is null is not evaluated
    other, _ = codex_windows(result, "gpt-7")
    assert [w.used_percent for w in other] == [0, 0]


def test_codex_flags_beyond_the_percentages_exhaust_the_profile():
    result = codex_result()
    result["ordinaryUsageAllowed"] = False
    assert codex_windows(result, None)[1] == "ordinaryUsageAllowed is false"
    result = codex_result()
    result["rateLimitsByLimitId"]["codex"]["rateLimitReachedType"] = "primary"
    assert codex_windows(result, None)[1] == "rate limit reached (primary)"
    result = codex_result()
    result["rateLimitsByLimitId"]["codex"]["spendControlReached"] = True
    assert codex_windows(result, None)[1] == "spend control reached"


def test_the_runner_codex_recording_parses():
    windows, extra = codex_windows(codex_result("runner-app-server.json"), None)
    assert [w.used_percent for w in windows] == [0, 3] and extra is None


def test_parse_usage_of_the_max_plan_recording():
    text = json.loads((CLAUDE / "usage_subscription_utc.json").read_text())["result"]
    windows = parse_usage(text, datetime(2026, 10, 3, 9, 0, tzinfo=UTC))
    assert [(w.name, w.used_percent) for w in windows] == [
        ("session", 59), ("weekly (all models)", 17), ("weekly (Fable)", 0),
    ]  # fmt: skip
    assert windows[0].resets_at == datetime(2026, 10, 3, 15, 0, tzinfo=UTC) and windows[0].window_minutes == 300
    assert windows[1].resets_at == datetime(2026, 10, 7, 18, 0, tzinfo=UTC) and windows[1].window_minutes == 10080


def test_parse_usage_of_the_runner_pro_plan_recording():
    text = json.loads((CLAUDE / "runner-usage-pro.json").read_text())["result"]
    windows = parse_usage(text, datetime(2026, 10, 4, 9, 0, tzinfo=UTC))
    assert [(w.name, w.used_percent) for w in windows] == [("session", 0), ("weekly (all models)", 2)]
    assert windows[0].resets_at is None  # a fresh session window has no reset yet
    assert windows[1].resets_at == datetime(2026, 10, 8, 11, 59, tzinfo=UTC)


def test_parse_usage_of_unrecognised_text_is_empty():
    assert parse_usage("Something else entirely", NOW) == []
    assert parse_usage(json.loads((CLAUDE / "usage_api_key.json").read_text())["result"], NOW) == []


def test_rate_limit_event_windows():
    info = {
        "status": "allowed", "resetsAt": 1791039600, "rateLimitType": "five_hour",
        "unifiedWindows": {
            "five_hour": {"utilization": 0.61, "resetsAt": 1791039600},
            "seven_day": {"utilization": 0.17, "resetsAt": 1791396000},
        },
    }  # fmt: skip
    windows = rate_limit_event_windows(info)
    assert [(w.name, w.used_percent, w.window_minutes) for w in windows] == [
        ("session", 61, 300), ("weekly (all models)", 17, 10080),
    ]  # fmt: skip
    assert rate_limit_event_windows({"status": "allowed"}) == []
