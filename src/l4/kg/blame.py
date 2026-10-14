"""Who should act on a recorded problem, from recorded fields only (L4-KG-007, design D6, SCN-KG-14, SCN-KG-15).

`classify(kind, data)` is one pure function over a table. `kind` is the name of the record: `finding`, `question`,
`stop` (its `code`), `round` (its `verdict` and its `findings`), or a ledger event type (`guard.secret`,
`task.attempt_failed`, ...). `data` holds the fields the rules read. The table has one row per blame value, in the order
of D6, and the first row with a matching rule wins, so a finding that is a spec gap and also from a person is `spec`.
Anything no rule names is `unknown`. The value says who should act; it never says who was at fault. No rule reads free
text, and no model is asked (L4-KG-007).
"""

from collections.abc import Callable, Mapping
from typing import Any

BLAME_VALUES = ("security", "spec", "environment", "verifier", "agent", "unknown")

_ENVIRONMENT_EVENTS = frozenset({"verify.error", "gate.hung", "ci.preexisting", "availability.limit"})
_AGENT_EVENTS = frozenset({"guard.violation", "guard.test_tamper", "task.attempt_failed", "feedback.not_addressed"})
_SPEC_QUESTIONS = frozenset({"product", "ambiguous"})

Rule = Callable[[str, Mapping[str, Any]], bool]


def _has_spec_gap(findings: Any) -> bool:
    return isinstance(findings, list | tuple) and any(
        isinstance(f, Mapping) and f.get("spec_gap") is True for f in findings
    )


def _security(kind: str, data: Mapping[str, Any]) -> bool:
    return kind == "guard.secret" or (kind == "stop" and data.get("code") == "secret_in_push")


def _spec(kind: str, data: Mapping[str, Any]) -> bool:
    if kind == "finding":
        return data.get("spec_gap") is True
    if kind == "question":
        return data.get("kind") in _SPEC_QUESTIONS
    return kind == "round" and data.get("verdict") == "NEEDS_HUMAN" and _has_spec_gap(data.get("findings"))


def _environment(kind: str, data: Mapping[str, Any]) -> bool:
    return kind in _ENVIRONMENT_EVENTS or (kind == "stop" and data.get("code") == "baseline_failed")


def _verifier(kind: str, data: Mapping[str, Any]) -> bool:
    return (
        kind == "judge.reply_repaired"
        or (kind == "finding" and data.get("source") == "human")
        or (kind == "stop" and data.get("code") == "verifier_errors")
    )


def _agent(kind: str, data: Mapping[str, Any]) -> bool:
    return kind in _AGENT_EVENTS or (kind == "finding" and data.get("source") == "deterministic")


TABLE: tuple[tuple[str, Rule], ...] = (
    ("security", _security),
    ("spec", _spec),
    ("environment", _environment),
    ("verifier", _verifier),
    ("agent", _agent),
)


def classify(kind: str, data: Mapping[str, Any] | None = None) -> str:
    fields = data or {}
    for blame, rule in TABLE:
        if rule(kind, fields):
            return blame
    return "unknown"
