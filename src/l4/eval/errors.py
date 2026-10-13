"""Error classes of an eval cell (L4-EVAL-009, plan D5).

`schema` (a result or a judge reply that broke its schema) and `timeout` (an agent step that timed out) are failures of
the model under test and count in its pass rate. `rate_limit`, `unavailable`, `login` and `setup_cold` say nothing about
the model: they make the cell `invalid` and it is left out of the rate, so a rate-limited free model is not read as a
regression. The detail kept in the scorecard is redacted and short.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from l4.redact import Redactor

DETAIL_MAX = 200
_LIMIT_KINDS = frozenset({"rate_limit", "usage_limit", "spend_limit", "credits"})
_UNAVAILABLE = re.compile(
    r"Endpoint is unavailable|not available in your (?:region|country)|geo[- ]?block|unsupported (?:region|country)",
    re.I,
)
_COLD = re.compile(r"Network connectivity is disabled|--offline", re.I)
_RESULT_INVALID = re.compile(r"result invalid|result is invalid", re.I)
_STATUS = re.compile(r"ended with status (timeout|rate_limited|quota|auth)\b")
_AGENT_STATUS = {"timeout": "timeout", "rate_limited": "rate_limit", "quota": "rate_limit", "auth": "login"}
# the order decides which reason an invalid cell reports when it has several
_INVALID_REASON = (
    ("setup_cold", "setup_offline_cache_cold"), ("login", "login"), ("rate_limit", "rate_limited"),
    ("unavailable", "endpoint_unavailable"),
)  # fmt: skip


@dataclass(frozen=True)
class CellError:
    kind: str  # schema | rate_limit | unavailable | timeout | login | setup_cold | other
    detail: str


def _detail(text: object, redactor: Redactor) -> str:
    return " ".join(redactor.redact_text(str(text or "")).split())[:DETAIL_MAX]


def classify(
    events: Sequence[dict[str, Any]], log_text: str, redactor: Redactor, *, cell_timeout: bool = False,
    setup_tail: str = "",
) -> list[CellError]:  # fmt: skip
    errors: list[CellError] = []
    seen: set[tuple[str, Any, Any]] = set()

    def add(kind: str, detail: object, task: Any = None, phase: Any = None, *, once: bool = True) -> None:
        key = (kind, task, phase) if kind == "timeout" else (kind, None, None)
        if once and kind != "schema":
            if key in seen:
                return
            seen.add(key)
        errors.append(CellError(kind, _detail(detail, redactor)))

    for event in events:
        kind = event.get("type")
        if kind == "agent.finished" and event.get("status") in _AGENT_STATUS:
            add(
                _AGENT_STATUS[event["status"]],
                event.get("detail") or event["status"],
                event.get("task"),
                event.get("phase"),
            )
        elif kind == "availability.limit":
            if event.get("kind") in _LIMIT_KINDS:
                add("rate_limit", event.get("excerpt") or event.get("kind"))
            if _UNAVAILABLE.search(str(event.get("excerpt") or "")):
                add("unavailable", event.get("excerpt"))
        elif kind == "verify.judge":
            status = event.get("status")
            if status == "schema_invalid":
                add("schema", event.get("detail") or "the judge reply broke its schema")
            elif status == "timeout":
                add("timeout", "the judge timed out", "judge", event.get("round"))
            elif status == "limit":
                add("rate_limit", "the judge hit a limit")
            elif status == "error":
                add("other", event.get("detail") or "the judge call failed")
        elif kind == "breaker.tripped" and event.get("reason") != "max_task_attempts":
            add("other", f"breaker: {event.get('reason')}: {event.get('detail') or ''}", once=False)
    for event in events:  # the retry reasons, after the agent statuses so that one cause is not counted twice
        if event.get("type") != "task.attempt_failed":
            continue
        reason = str(event.get("reason") or "")
        if _RESULT_INVALID.search(reason):
            add("schema", reason)
            continue
        match = _STATUS.search(reason)
        if match:
            add(_AGENT_STATUS[match.group(1)], reason, event.get("task"), event.get("phase"))
    if (hit := _UNAVAILABLE.search(log_text)) is not None:
        add("unavailable", hit.group(0))
    if setup_tail and _COLD.search(setup_tail):
        add("setup_cold", "gates.setup could not run offline: the uv cache is cold; run `l4 eval --warm-cache`")
    if cell_timeout:
        add("timeout", "the cell timed out", "cell", None)
    return errors


def invalidating(errors: Sequence[CellError]) -> str | None:
    """The `invalid` reason these errors give a cell, or None when every error counts as a failure of the model."""
    kinds = {e.kind for e in errors}
    for kind, reason in _INVALID_REASON:
        if kind in kinds:
            return reason
    return None
