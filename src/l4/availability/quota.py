"""The `quota` step (SPEC L4-AVL-001, L4-AVL-009): remaining usage per window, read without spending a model request.

Sources: `codex app-server` (`account/rateLimits/read`), Claude's `/usage` text or its latest `rate_limit_event`, and
OpenRouter's `/credits` and `/key` for profiles that spend credits. A source that answers in a shape this module does
not know makes the step `skipped` with `quota_unrecognised` (never a failure: a drifted `/usage` text must not empty
a judge chain; `binary`, `auth` and `hello` still catch real breakage). A profile is exhausted when ANY window has
less than the reserve left; its cool-down then ends at the latest reset among the windows that bind.
"""

import json
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx

from l4.agents.base import LimitSignal, ProbeCtx, ProbeResult
from l4.availability.limits import parse_reset
from l4.availability.rpc import run_rpc_session
from l4.availability.steps import StepTimedOut, step_run, step_seconds, timeout_reason
from l4.config.schema import Profile

SESSION_MINUTES, WEEK_MINUTES = 300, 10080
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_EPOCH = datetime.min.replace(tzinfo=UTC)
_USAGE_LINE = re.compile(
    r"^Current (?P<what>session|week \((?P<scope>[^)]+)\)): (?P<pct>\d+)% used(?: · resets (?P<reset>.+?))?\s*$", re.M
)
_RPC_ERROR_UNSUPPORTED = -32600  # `account/rateLimits/read` with an API-key login
_CODEX_REQUESTS = (  # the only methods this module ever sends; reset credits are never redeemed
    {"method": "initialize", "id": 1, "params": {"clientInfo": {"name": "l4-probe", "version": "0.0.1"}}},
    {"method": "initialized"},
    {"method": "account/rateLimits/read", "id": 2},
)


def now_of(ctx: ProbeCtx) -> datetime:
    return ctx.now() if ctx.now else datetime.now(UTC)


@dataclass(frozen=True)
class Window:
    name: str
    used_percent: float
    window_minutes: int | None
    resets_at: datetime | None

    @property
    def remaining(self) -> float:
        return 100 - self.used_percent

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name, "used_percent": self.used_percent, "window_minutes": self.window_minutes,
            "resets_at": self.resets_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if self.resets_at else None,
        }  # fmt: skip


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value) if float(value).is_integer() else round(float(value), 1)


def _g(value: float) -> str:
    return f"{value:g}"


def window_label(minutes: int | None) -> str:
    if minutes == WEEK_MINUTES:
        return "weekly window"
    if minutes is None or minutes <= 0:
        return "window"
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d window"
    if minutes % 60 == 0:
        return f"{minutes // 60}h window"
    return f"{minutes}m window"


def reserve_of(profile: Profile, ctx: ProbeCtx) -> tuple[float, bool]:
    """The reserve in force and whether it is the profile's own (G15)."""
    if profile.min_remaining_percent is not None:
        return profile.min_remaining_percent, True
    return ctx.min_remaining_percent, False


def unrecognised(why: str) -> ProbeResult:
    return ProbeResult("quota", True, {"quota_unrecognised": True, "quota_note": why}, skipped=True)


def skipped(why: str) -> ProbeResult:
    return ProbeResult("quota", True, {"quota_note": why}, skipped=True)


def evaluate_windows(
    tool: str,
    model: str | None,
    windows: Sequence[Window],
    *,
    reserve: float,
    reserve_is_profile: bool,
    source: str,
    extra_exhausted: str | None = None,
) -> ProbeResult:
    """Fails when any window has less than `reserve` left (a window with nothing left always fails, also at a
    reserve of 0). The reason is the SPEC 8.4 text; the cool-down ends at the latest reset of the windows that bind."""
    if not windows and extra_exhausted is None:
        return unrecognised("no usage window in the answer")
    binding = [w for w in windows if w.remaining < reserve or w.remaining <= 0]
    listing = [w.to_json() for w in windows]
    if not binding and extra_exhausted is None:
        top = max(windows, key=lambda w: w.used_percent)
        detail = {"quota_used_percent": top.used_percent, "quota_window": top.name, "windows": listing}
        return ProbeResult("quota", True, detail)
    resets = [w.resets_at for w in binding if w.resets_at is not None]
    if binding:
        worst = max(binding, key=lambda w: (w.used_percent, w.resets_at or _EPOCH))
        reason = f"{worst.name} {_g(worst.used_percent)}% used, {_g(worst.remaining)}% remaining"
        if worst.remaining > 0:
            reason += f" < {_g(reserve)}%" + (" (profile reserve)" if reserve_is_profile else "")
        latest = max((w for w in binding if w.resets_at is not None), key=lambda w: w.resets_at or _EPOCH, default=None)
        if latest is not None and latest.resets_at != worst.resets_at:  # the reset shown belongs to another window
            reason += f"; cool-down follows the {latest.name} reset"
        limit = LimitSignal(
            tool, model, "usage_limit", max(resets, default=None), source, "", worst.window_minutes,
            worst.used_percent,
        )  # fmt: skip
    else:
        assert extra_exhausted is not None
        reason, limit = extra_exhausted, LimitSignal(tool, model, "usage_limit", None, source, "")
    return ProbeResult("quota", False, {"windows": listing}, reason=reason, limit=limit)


def _codex_window(raw: object) -> Window | None:
    if not isinstance(raw, Mapping):
        return None
    used, minutes = _number(raw.get("usedPercent")), raw.get("windowDurationMins")
    if used is None:
        return None
    resets = raw.get("resetsAt")
    window = minutes if isinstance(minutes, int) else None
    when = (
        datetime.fromtimestamp(resets, UTC)
        if isinstance(resets, int | float) and not isinstance(resets, bool)
        else None
    )
    return Window(window_label(window), used, window, when)


def codex_windows(result: Mapping[str, Any], model: str | None) -> tuple[list[Window], str | None]:
    """The windows of the bucket whose `normalModelSlug` is the model, else `codex`; plus why the bucket is exhausted
    beyond its percentages (`ordinaryUsageAllowed`, `rateLimitReachedType`, `spendControlReached`)."""
    buckets = result.get("rateLimitsByLimitId")
    buckets = buckets if isinstance(buckets, Mapping) else {}
    bucket = next(
        (b for b in buckets.values() if model and isinstance(b, Mapping) and b.get("normalModelSlug") == model), None
    )
    bucket = bucket or buckets.get("codex") or result.get("rateLimits")
    if not isinstance(bucket, Mapping):
        return [], None
    windows = [w for w in (_codex_window(bucket.get("primary")), _codex_window(bucket.get("secondary"))) if w]
    extra = None
    if result.get("ordinaryUsageAllowed") is False:
        extra = "ordinaryUsageAllowed is false"
    elif bucket.get("rateLimitReachedType") is not None:
        extra = f"rate limit reached ({bucket['rateLimitReachedType']})"
    elif bucket.get("spendControlReached") is True:
        extra = "spend control reached"
    return windows, extra


def codex_quota(profile: Profile, exe: str, env: Mapping[str, str], ctx: ProbeCtx) -> ProbeResult:
    rpc = ctx.rpc or run_rpc_session
    seconds, started = step_seconds(ctx), time.monotonic()
    answers = rpc([exe, "app-server"], ctx.cwd, env, seconds, _CODEX_REQUESTS)
    reply = answers.get(2)
    if reply is None and time.monotonic() - started >= seconds:
        raise StepTimedOut(timeout_reason("codex", seconds, "quota"))
    if not isinstance(reply, Mapping):
        return unrecognised("codex app-server gave no rate-limit answer")
    error = reply.get("error")
    if isinstance(error, Mapping):
        if error.get("code") == _RPC_ERROR_UNSUPPORTED:
            return skipped("no rate-limit query for this login")
        return unrecognised("codex app-server refused the rate-limit query")
    result = reply.get("result")
    if not isinstance(result, Mapping):
        return unrecognised("codex app-server answered without a result")
    windows, extra = codex_windows(result, profile.model)
    reserve, own = reserve_of(profile, ctx)
    return evaluate_windows(
        "codex", profile.model, windows, reserve=reserve, reserve_is_profile=own, source="codex.rateLimits",
        extra_exhausted=extra,
    )  # fmt: skip


def parse_usage(text: str, now: datetime) -> list[Window]:
    """Claude's `/usage` text (run with `TZ=UTC`): one window per `Current ...` line. The reset may be absent (a fresh
    session window) and is written "Oct 3 at 3pm (UTC)" or "Oct 8, 11:59am (UTC)"; a year is its next occurrence."""
    windows = []
    for line in _USAGE_LINE.finditer(text):
        weekly = line["what"] != "session"
        name = f"weekly ({line['scope']})" if weekly else "session"
        resets = parse_reset(f"resets {line['reset']}", now) if line["reset"] else None
        windows.append(Window(name, int(line["pct"]), WEEK_MINUTES if weekly else SESSION_MINUTES, resets))
    return windows


def rate_limit_event_windows(info: Mapping[str, Any]) -> list[Window]:
    """`rate_limit_event.rate_limit_info.unifiedWindows` (`utilization` is a fraction): session and weekly (all
    models). It has no per-model weekly window; only the `/usage` text does."""
    unified = info.get("unifiedWindows")
    if not isinstance(unified, Mapping):
        return []
    found = []
    for key, name, minutes in (
        ("five_hour", "session", SESSION_MINUTES),
        ("seven_day", "weekly (all models)", WEEK_MINUTES),
    ):
        entry = unified.get(key)
        used = (
            _number(entry.get("utilization") * 100)
            if isinstance(entry, Mapping) and isinstance(entry.get("utilization"), int | float)
            else None
        )
        resets = entry.get("resetsAt") if isinstance(entry, Mapping) else None
        if used is not None:
            when = datetime.fromtimestamp(resets, UTC) if isinstance(resets, int | float) else None
            found.append(Window(name, used, minutes, when))
    return found


def claude_quota(
    profile: Profile, exe: str, env: Mapping[str, str], ctx: ProbeCtx, *, latest: Sequence[Window] = ()
) -> ProbeResult:
    """`latest`: windows of the newest `rate_limit_event` this process saw; preferred over a `/usage` call."""
    if profile.auth == "api_key":
        return skipped("api_key auth has no usage windows")
    windows = list(latest)
    if not windows:
        argv = [exe, "-p", "--safe-mode", "--no-session-persistence", "--output-format", "json", "/usage"]
        done = step_run(ctx, "claude", "quota", argv, {**env, "TZ": "UTC"})
        try:
            reply = json.loads(done.stdout or "")
        except ValueError:
            return unrecognised("claude /usage gave no JSON")
        text = reply.get("result") if isinstance(reply, dict) and not reply.get("is_error") else None
        windows = parse_usage(text, now_of(ctx)) if isinstance(text, str) else []
    reserve, own = reserve_of(profile, ctx)
    return evaluate_windows(
        "claude-code", profile.model, windows, reserve=reserve, reserve_is_profile=own, source="claude.usage"
    )


_KIRO_CREDITS = re.compile(r"Credits \(\s*([\d.]+)\s+of\s+([\d.]+)")
_KIRO_RESET = re.compile(r"resets on (\d{4}-\d{2}-\d{2})")


def parse_kiro_usage(text: str) -> list[Window]:
    """kiro-cli's headless `/usage` (no model call): `Credits (0.18 of 1000 covered in plan), 0.0%` and, on the header
    line, `resets on 2026-11-01` (00:00 UTC, the 1st of the month). One window; none when the text is not that."""
    credits = _KIRO_CREDITS.search(text)
    if credits is None or float(credits[2]) <= 0:
        return []
    reset = _KIRO_RESET.search(text)
    resets = datetime.fromisoformat(reset[1]).replace(tzinfo=UTC) if reset else None
    used = _number(float(credits[1]) / float(credits[2]) * 100) or 0
    return [Window("credits", used, None, resets)]


def kiro_quota(profile: Profile, exe: str, env: Mapping[str, str], ctx: ProbeCtx) -> ProbeResult:
    done = step_run(ctx, "kiro-cli", "quota", [exe, "chat", "--no-interactive", "/usage"], env)
    windows = parse_kiro_usage(done.stdout or "") if done.returncode == 0 else []
    reserve, own = reserve_of(profile, ctx)
    result = evaluate_windows(
        "kiro-cli", profile.model, windows, reserve=reserve, reserve_is_profile=own, source="kiro.usage"
    )
    credits = _KIRO_CREDITS.search(done.stdout or "") if windows else None
    if credits is not None:  # the plan's own count, kept apart from the stream's metered credits (they disagree)
        result.detail.update(
            credits_used=float(credits[1]), credits_included=float(credits[2]), credits_source="kiro.usage"
        )
    return result


def is_openrouter(profile: Profile) -> bool:
    host = urlparse(profile.base_url).hostname if profile.base_url else None
    return (profile.model or "").startswith("openrouter/") or host == "openrouter.ai"


def next_boundary(limit_reset: object, now: datetime) -> datetime | None:
    """The next reset of an OpenRouter key limit: midnight UTC daily, Monday midnight weekly, the 1st monthly [U]."""
    today = datetime(now.year, now.month, now.day, tzinfo=UTC)
    if limit_reset == "daily":
        return today + timedelta(days=1)
    if limit_reset == "weekly":
        return today + timedelta(days=7 - today.weekday())
    if limit_reset == "monthly":
        return datetime(now.year + (now.month == 12), now.month % 12 + 1, 1, tzinfo=UTC)
    return None


def _body(response: httpx.Response) -> Mapping[str, Any] | None:
    try:
        body = response.json()
    except ValueError:
        return None
    inner = body.get("data", body) if isinstance(body, dict) else None
    return inner if isinstance(inner, dict) else None


def openrouter_quota(profile: Profile, ctx: ProbeCtx, *, client: httpx.Client | None = None) -> ProbeResult:
    """`GET /credits` (balance = total_credits - total_usage) and `GET /key` (`limit_remaining`, `limit_reset`),
    both free. Below `min_remaining_usd` the step fails: no credits left is `credits` (no reset; the credits
    cool-down applies), a binding key limit is `rate_limit` ending at its next boundary."""
    key = ctx.environ.get(profile.api_key_env or "OPENROUTER_API_KEY")
    if not key:
        return skipped("no OpenRouter key in the probe environment")
    base = OPENROUTER_BASE
    if profile.base_url:  # the key goes to OpenRouter only, whatever host the config names
        parsed = urlparse(profile.base_url)
        if parsed.scheme == "https" and parsed.hostname == "openrouter.ai":
            base = profile.base_url.rstrip("/")
    http = client or httpx.Client(timeout=step_seconds(ctx))
    try:
        credits = _body(http.get(f"{base}/credits", headers={"Authorization": f"Bearer {key}"}))
        key_info = _body(http.get(f"{base}/key", headers={"Authorization": f"Bearer {key}"}))
    except httpx.HTTPError:
        return unrecognised("OpenRouter did not answer")
    finally:
        if client is None:
            http.close()
    total, used = (credits or {}).get("total_credits"), (credits or {}).get("total_usage")
    if not isinstance(total, int | float) or not isinstance(used, int | float):
        return unrecognised("OpenRouter /credits had no balance")
    balance, minimum, model = round(total - used, 4), ctx.min_remaining_usd, profile.model
    tool = profile.adapter or f"backend:{profile.backend}"
    detail: dict[str, Any] = {"quota_balance_usd": balance}
    if balance < minimum:
        reason = f"credit balance ${balance:.2f} < ${minimum:.2f}"
        return ProbeResult(
            "quota", False, detail, reason, LimitSignal(tool, model, "credits", None, "openrouter.credits", "")
        )
    remaining = (key_info or {}).get("limit_remaining")
    if isinstance(remaining, int | float) and not isinstance(remaining, bool):
        detail["key_limit_remaining_usd"] = remaining
        if remaining < minimum:
            resets = next_boundary((key_info or {}).get("limit_reset"), now_of(ctx))
            reason = f"key limit ${remaining:.2f} < ${minimum:.2f}"
            return ProbeResult(
                "quota",
                False,
                detail,
                reason,
                LimitSignal(tool, model, "rate_limit", resets, "openrouter.key", ""),
            )
    return ProbeResult("quota", True, detail)
