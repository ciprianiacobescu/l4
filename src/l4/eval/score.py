"""Per-cell scoring from the child run's ledger (L4-EVAL-008, 010). The ledger is the evidence: no timer of the eval
itself except wall time, and no agent text.

Implementer cell: `pass` when the task ended `done` (red and green both ok, or a red whose tests already passed) and
the reference judge, when it ran, said PASS; otherwise `fail`, with where it stopped. Judge cell: `pass` when the
verdict of round 1 is the expected one (and has at least the expected number of findings), `fail` otherwise; a judge
that passes the designed-defect unit has `missed_defect: true`.
"""

import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

_FINDING = re.compile(r"^- \[(blocker|major|minor), [a-z]+\]", re.MULTILINE)
_SEVERITY_ORDER = ("blocker", "major", "minor")


def _of(events: Sequence[dict[str, Any]], *types: str) -> list[dict[str, Any]]:
    return [e for e in events if e.get("type") in types]


def _first_round_verdict(events: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    verdicts = _of(events, "verify.verdict")
    return min(verdicts, key=lambda e: (e.get("round") or 0, e.get("seq") or 0)) if verdicts else None


def score_implementer(events: Sequence[dict[str, Any]], expected: dict[str, Any]) -> dict[str, Any]:
    failures = Counter(e.get("phase") for e in _of(events, "task.attempt_failed"))
    red_ok = bool(_of(events, "task.red_ok"))
    done = bool(_of(events, "task.done"))
    attempts = {
        "red": failures["red"] + (1 if red_ok or done else 0),
        "green": failures["green"] + (1 if done and red_ok else 0),
    }
    breaker = next(iter(_of(events, "breaker.tripped")), None)
    blocked = bool(_of(events, "question.raised"))
    verdict_event = _first_round_verdict(events)
    verdict = verdict_event.get("verdict") if verdict_event else None
    halted_at = None
    if breaker is not None and breaker.get("phase") in ("red", "green", "single"):
        halted_at = breaker["phase"]
    passed = done and breaker is None and not blocked
    if passed and verdict is not None and verdict != "PASS":
        passed, halted_at = False, "verify"
    return {
        "outcome": "pass" if passed else "fail",
        "halted_at": halted_at,
        "breaker": breaker.get("reason") if breaker else None,
        "blocked": blocked,
        "attempts": attempts,
        "verdict": verdict,
    }


def _severities(report_text: str | None) -> list[str]:
    section = (
        report_text.split("## Findings", 1)[1].split("\n## ", 1)[0]
        if report_text and "## Findings" in report_text
        else ""
    )
    return _FINDING.findall(section)


def score_judge(
    events: Sequence[dict[str, Any]], expected: dict[str, Any], report_text: str | None = None
) -> dict[str, Any]:
    want = expected.get("judge", {})
    judge_events = _of(events, "verify.judge")
    errors = ["schema" for e in judge_events if e.get("status") == "schema_invalid"]
    verdict_event = _first_round_verdict(events)
    verdict = verdict_event.get("verdict") if verdict_event else None
    findings = int(verdict_event.get("findings") or 0) if verdict_event else 0
    severities = _severities(report_text)
    worst = next((s for s in _SEVERITY_ORDER if s in severities), None)
    agreement = verdict is not None and verdict == want.get("verdict")
    if agreement and verdict != "PASS" and findings < int(want.get("min_findings", 0)):
        agreement = False
    defect = bool(want.get("designed_defect"))
    return {
        "outcome": "pass" if agreement else "fail",
        "verdict": verdict,
        "expected_verdict": want.get("verdict"),
        "agreement": agreement,
        "findings": findings,
        "worst_severity": worst,
        "missed_defect": defect and verdict == "PASS",
        "errors": errors,
        "judge_calls": sum(int(e.get("calls") or 0) for e in judge_events) or len(judge_events),
    }


def cost_of(events: Sequence[dict[str, Any]], *, free: bool) -> dict[str, Any]:
    """The cell's cost: the sum of every `budget.cost` (agent, judge, clarifier); `None` when nothing reported one,
    except `0.0` for a profile declared free in its options. Tokens are summed from `agent.finished`."""
    reported = [e["usd"] for e in _of(events, "budget.cost") if isinstance(e.get("usd"), int | float)]
    agents = _of(events, "agent.finished")
    cost: float | None = round(sum(reported), 6) if reported else (0.0 if free else None)
    return {
        "cost_usd": cost,
        "input_tokens": sum(int(e.get("input_tokens") or 0) for e in agents),
        "output_tokens": sum(int(e.get("output_tokens") or 0) for e in agents),
    }
