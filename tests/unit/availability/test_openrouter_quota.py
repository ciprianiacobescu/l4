import json
from datetime import UTC, datetime

import httpx
import pytest

from l4.agents.base import ProbeCtx
from l4.availability.quota import is_openrouter, next_boundary, openrouter_quota
from l4.config.schema import Profile

from .conftest import RECORDED

V1 = RECORDED / "openrouter-api" / "v1"
NOW = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)  # a Wednesday
PROFILE = Profile(adapter="opencode", model="openrouter/google/gemini-3.5-flash", vendor="google")


def recorded(name: str) -> dict:
    return json.loads((V1 / name).read_text())["data"]


def ctx_for(tmp_path, *, key: str | None = "sk-or-test-SECRET", usd: float = 0.5) -> ProbeCtx:
    environ = {"OPENROUTER_API_KEY": key} if key else {}
    return ProbeCtx(environ=environ, cwd=tmp_path, run=lambda *a: None, min_remaining_usd=usd, now=lambda: NOW)


def client(credits: dict | None, key_info: dict | None, seen: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        body = credits if request.url.path.endswith("/credits") else key_info
        return httpx.Response(200, json={"data": body})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_negative_balance_is_credits_with_credits_cooldown(tmp_path):
    seen: list[httpx.Request] = []
    out = openrouter_quota(
        PROFILE, ctx_for(tmp_path), client=client(recorded("get_credits.json"), recorded("get_key.json"), seen)
    )
    assert not out.ok and out.reason == "credit balance $-0.03 < $0.50"
    assert out.limit.kind == "credits" and out.limit.resets_at is None  # the credits cool-down applies, not a reset
    assert [r.url.path for r in seen] == ["/api/v1/credits", "/api/v1/key"]
    assert all(r.headers["authorization"] == "Bearer sk-or-test-SECRET" for r in seen)
    assert "SECRET" not in repr(out)


def test_enough_balance_and_key_room_is_ok_and_reports_both_numbers(tmp_path):
    out = openrouter_quota(
        PROFILE, ctx_for(tmp_path), client=client({"total_credits": 15, "total_usage": 7.5}, recorded("get_key.json"))
    )
    assert out.ok and not out.skipped
    assert out.detail == {"quota_balance_usd": 7.5, "key_limit_remaining_usd": 2.5}


def test_a_binding_key_limit_is_a_rate_limit_ending_at_the_next_boundary(tmp_path):
    key = {**recorded("get_key.json"), "limit_remaining": 0.1, "limit_reset": "weekly"}
    out = openrouter_quota(PROFILE, ctx_for(tmp_path), client=client({"total_credits": 15, "total_usage": 1}, key))
    assert not out.ok and out.reason == "key limit $0.10 < $0.50"
    assert out.limit.kind == "rate_limit" and out.limit.resets_at == datetime(2026, 10, 12, tzinfo=UTC)  # next Monday


@pytest.mark.parametrize(
    ("limit_reset", "expected"),
    [
        ("daily", datetime(2026, 10, 8, tzinfo=UTC)),
        ("weekly", datetime(2026, 10, 12, tzinfo=UTC)),
        ("monthly", datetime(2026, 11, 1, tzinfo=UTC)),
        (None, None),
        ("hourly", None),
    ],
)
def test_key_limit_boundaries(limit_reset, expected):
    assert next_boundary(limit_reset, NOW) == expected
    assert next_boundary("monthly", datetime(2026, 12, 20, tzinfo=UTC)) == datetime(2027, 1, 1, tzinfo=UTC)


def test_no_key_an_error_or_a_strange_answer_skips_the_step_instead_of_failing_the_profile(tmp_path):
    assert openrouter_quota(PROFILE, ctx_for(tmp_path, key=None), client=client({}, {})).skipped

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    down = openrouter_quota(PROFILE, ctx_for(tmp_path), client=httpx.Client(transport=httpx.MockTransport(boom)))
    assert down.ok and down.skipped and down.detail["quota_unrecognised"]
    odd = openrouter_quota(PROFILE, ctx_for(tmp_path), client=client({"surprise": 1}, {}))
    assert odd.ok and odd.skipped and odd.detail["quota_unrecognised"]


def test_the_profile_decides_whether_it_is_openrouter_backed():
    assert is_openrouter(PROFILE)
    assert is_openrouter(Profile(backend="openai-chat", base_url="https://openrouter.ai/api/v1", model="x"))
    assert not is_openrouter(Profile(adapter="opencode", model="opencode/big-pickle"))
    assert not is_openrouter(Profile(backend="openai-chat", base_url="http://localhost:11434/v1", model="x"))


def test_the_profiles_own_key_variable_is_the_one_read(tmp_path):
    profile = PROFILE.model_copy(update={"api_key_env": "MY_OR_KEY"})
    ctx = ProbeCtx(environ={"MY_OR_KEY": "k"}, cwd=tmp_path, run=lambda *a: None)
    seen: list[httpx.Request] = []
    openrouter_quota(profile, ctx, client=client({"total_credits": 5, "total_usage": 1}, {}, seen))
    assert seen and seen[0].headers["authorization"] == "Bearer k"
