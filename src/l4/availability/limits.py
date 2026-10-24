"""Limit signals (SPEC L4-AVL-002): every probe or run failure that means "out of capacity" becomes one `LimitSignal`.

Structured sources come first (Codex `resetsAt`, Claude `rate_limit_event`, OpenCode `error.data.statusCode`); the
text parser is the last resort and also serves the `/usage` reader. Things that look like limits and are not (a
Claude 404, a Codex 400, `Token refresh failed: 401`, a 503) return None, so they never start a cool-down.
"""

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from l4.agents.base import LimitSignal

EXCERPT_LIMIT = 200
_WINDOW_MINUTES = {"five_hour": 300, "seven_day": 10080}
_MONTH_NAMES = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MONTHS = {name: number for number, name in enumerate(_MONTH_NAMES, 1)}
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?")
_IN = re.compile(r"\b(?:retry|try again|available again|resets?)\s+in\s+(?P<body>(?:\d+(?:\.\d+)?\s*[a-z]+\s*)+)", re.I)
_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)(?![a-z])", re.I)
_AT = re.compile(
    r"\b(?:resets?|try again|retry|available again|until)(?:\s+(?:at|on))?\s+"
    r"(?:(?P<mon>[A-Za-z]{3})[a-z]*\.?\s+(?P<day>\d{1,2})(?:,\s*(?P<year>\d{4}))?(?:,|\s+at)?\s+)?"
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>[ap]m)?(?:\s*\((?P<tz>[^)]+)\))?",
    re.I,
)
_LIMIT_WORDS = re.compile(
    r"usage limit|rate[- ]limit|quota|limit reached|limit exceeded|credits?\b|too many requests|resource_exhausted|"
    r"spend limit|\b429\b",
    re.I,
)


def excerpt(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:EXCERPT_LIMIT]


def _zone(name: str | None) -> tzinfo | None:
    if name is None or name.strip().upper() in ("UTC", "Z", "GMT"):
        return UTC
    try:
        return ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _from_epoch_or_iso(value: object) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, UTC)
    if isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return None
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return None


def _relative(text: str, now: datetime) -> datetime | None:
    found = _IN.search(text)
    if found is None:
        return None
    seconds = 0.0
    for amount, unit in _UNIT.findall(found.group("body")):
        seconds += float(amount) * {"h": 3600, "m": 60, "s": 1}[unit[0].lower()]
    return now + timedelta(seconds=seconds) if seconds else None


def _absolute(text: str, now: datetime) -> datetime | None:
    found = _AT.search(text)
    if found is None:
        return None
    hour, minute, ampm = int(found["h"]), int(found["m"] or 0), (found["ampm"] or "").lower()
    if not ampm and found["m"] is None:
        return None  # a bare number is not a time of day
    if ampm:
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    zone = _zone(found["tz"])
    if zone is None or hour > 23 or minute > 59:
        return None
    try:
        if found["mon"]:
            month = _MONTHS.get(found["mon"].lower())
            if month is None:
                return None
            years = [int(found["year"])] if found["year"] else [now.year, now.year + 1]
            for year in years:
                candidate = datetime(year, month, int(found["day"]), hour, minute, tzinfo=zone)
                if candidate.astimezone(UTC) >= now - timedelta(days=1):
                    return candidate.astimezone(UTC)
            return None
        today = now.astimezone(zone).date()
        candidate = datetime(today.year, today.month, today.day, hour, minute, tzinfo=zone)
        if candidate.astimezone(UTC) <= now:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC)
    except ValueError:
        return None


def parse_reset(text: str, now: datetime) -> datetime | None:
    """A reset time from free text: an ISO stamp, "retry in 9h9m42s", or "resets Oct 8, 11:59am (UTC)" and its kin.
    The year of a date is its next occurrence. Without a zone the time is UTC. None when no time is recognised."""
    iso = _ISO.search(text)
    if iso is not None and (moment := _from_epoch_or_iso(iso.group(0))) is not None:
        return moment.astimezone(UTC)
    return _relative(text, now) or _absolute(text, now)


def _text_kind(text: str) -> Literal["usage_limit", "rate_limit", "spend_limit", "credits"]:
    lowered = text.lower()
    if "credit" in lowered:
        return "credits"
    if "spend" in lowered:
        return "spend_limit"
    if "usage limit" in lowered or "quota" in lowered:
        return "usage_limit"
    return "rate_limit"


def _from_text(tool: str, model: str | None, text: str, now: datetime) -> LimitSignal | None:
    if not _LIMIT_WORDS.search(text):
        return None
    return LimitSignal(tool, model, _text_kind(text), parse_reset(text, now), "text", excerpt(text))


_NOT_A_LIMIT: Literal[False] = False


def _claude(model: str | None, info: Mapping[str, Any]) -> LimitSignal | None | Literal[False]:
    if isinstance(info.get("api_error_status"), int) and info["api_error_status"] != 429:
        return _NOT_A_LIMIT  # a 404 (bad model) or an auth failure is a configuration problem
    if info.get("status") != "rejected":
        return _NOT_A_LIMIT
    kind_name = str(info.get("rateLimitType") or "")
    window = next((minutes for prefix, minutes in _WINDOW_MINUTES.items() if kind_name.startswith(prefix)), None)
    unified = info.get("unifiedWindows")
    entry = unified.get(kind_name) if isinstance(unified, Mapping) else None
    used = entry.get("utilization") if isinstance(entry, Mapping) else None
    return LimitSignal(
        "claude-code", model, "usage_limit" if window else "rate_limit", _from_epoch_or_iso(info.get("resetsAt")),
        "claude.rate_limit_event", excerpt(f"claude {kind_name or 'limit'} rejected"), window,
        round(float(used) * 100, 1) if isinstance(used, int | float) else None,
    )  # fmt: skip


def _codex(model: str | None, window: Mapping[str, Any]) -> LimitSignal | None:
    if "resetsAt" not in window and "usedPercent" not in window:
        return None
    minutes, used = window.get("windowDurationMins"), window.get("usedPercent")
    return LimitSignal(
        "codex", model, "usage_limit", _from_epoch_or_iso(window.get("resetsAt")), "codex.rateLimits",
        excerpt(f"codex window {minutes} min {used}% used"),
        minutes if isinstance(minutes, int) else None, float(used) if isinstance(used, int | float) else None,
    )  # fmt: skip


def _limit_source(data: Mapping[str, Any]) -> str | None:
    body = data.get("responseBody")
    if not isinstance(body, str):
        return None
    found = re.search(r'"limit_source"\s*:\s*"([a-z_]+)"', body)
    return found.group(1) if found else None


def _opencode(model: str | None, now: datetime, payload: Mapping[str, Any]) -> LimitSignal | None | Literal[False]:
    error = payload.get("error")
    data = (error if isinstance(error, Mapping) else payload).get("data")
    data = data if isinstance(data, Mapping) else payload
    status = data.get("statusCode")
    if not isinstance(status, int):
        return None
    message = str(data.get("message") or "")
    if status == 402:
        source = _limit_source(data)
        return LimitSignal(
            "opencode", model, "credits", None, f"opencode.statusCode:{source}" if source else "opencode.statusCode",
            excerpt(message),
        )  # fmt: skip
    if status != 429:
        return _NOT_A_LIMIT
    headers = data.get("responseHeaders")
    wait = headers.get("retry-after") if isinstance(headers, Mapping) else None
    resets = now + timedelta(seconds=float(wait)) if isinstance(wait, str) and wait.isdigit() else None
    return LimitSignal(
        "opencode", model, "rate_limit", resets or parse_reset(message, now), "opencode.statusCode", excerpt(message)
    )


def _is_opencode_v2(payload: Mapping[str, Any]) -> bool:
    """A v2 `error` event (`{type, message, status, response}`): `error.status` and no `error.data` (v1's shape)."""
    error = payload.get("error")
    body = error if isinstance(error, Mapping) else payload
    return "status" in body and "data" not in body


def _opencode_v2(model: str | None, now: datetime, payload: Mapping[str, Any]) -> LimitSignal | None:
    """A limit from a v2 `error` event, by its `status` alone. Fallback `status_only` (U1, L4-OCV-009): no v2 402 or
    429 was ever recorded, so where `retry-after` lives is unknown. The message, `response.body` and headers are never
    read for a reset, and `normalise_limit` runs no text fallback for this shape: a 429 gets the default cool-down."""
    error = payload.get("error")
    body = error if isinstance(error, Mapping) else payload
    status = body.get("status")
    if isinstance(status, bool) or status not in (402, 429):
        return None  # any other status (an auth 403, a retryable 5xx) is not a limit
    kind: Literal["credits", "rate_limit"] = "credits" if status == 402 else "rate_limit"
    return LimitSignal("opencode", model, kind, None, "opencode2.status", excerpt(str(body.get("message") or "")))


def normalise_limit(
    tool: str,
    model: str | None,
    *,
    structured: Mapping[str, Any] | None = None,
    text: str | None = None,
    now: datetime,
) -> LimitSignal | None:
    """`structured` is what the tool's own machine-readable output carries: Claude's `rate_limit_info`, a Codex rate
    window, an OpenCode `error` event. It wins when it says "limit" and also when it says "not a limit"; its reset
    time wins over any in `text`, which only fills in a reset the structured source lacks (OpenCode's Google body)."""
    signal: LimitSignal | None | Literal[False] = None
    if tool == "opencode" and structured is not None and _is_opencode_v2(structured):
        return _opencode_v2(model, now, structured)  # status_only (U1): never `text`, never a parsed reset
    if structured is not None:
        if tool == "claude-code":
            signal = _claude(model, structured)
        elif tool == "codex":
            signal = _codex(model, structured)
        elif tool == "opencode":
            signal = _opencode(model, now, structured)
    if signal is _NOT_A_LIMIT:
        return None
    if signal is None:
        return _from_text(tool, model, text, now) if text else None
    assert not isinstance(signal, bool)
    if (
        signal.resets_at is None
        and signal.kind != "credits"
        and text
        and (moment := parse_reset(text, now)) is not None
    ):
        signal = LimitSignal(
            signal.tool, signal.model, signal.kind, moment, signal.source, signal.raw_excerpt, signal.window_minutes,
            signal.used_percent,
        )  # fmt: skip
    return signal
