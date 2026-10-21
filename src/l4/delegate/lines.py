"""How the status commands name the delegate's decisions (delegate-answers 14.1; L4-DLG-011, design D14).

Pure over a unit's ledger events: the latest `delegate.result` of the current raise of each question is what the
delegate decided (answered, escalated, a discarded reply being an escalation) or still defers. `l4 status --unit`
prints one `Delegate:` line per question, `l4 yolo status` the counts of the current unit and the delegate's cost
against its share of the plan's cost limit."""

from collections.abc import Sequence
from typing import Any

from l4.delegate.due import ESCALATED, results_of
from l4.state.fold import question_key
from l4.state.ledger import LedgerEvent

NEEDS_PERSON = "needs a person (the delegate escalated)"  # the REASON of an escalated question in `l4 status`
REASON_WIDTH = 300


def _flat(text: object, limit: int = REASON_WIDTH) -> str:
    return " ".join(str(text).split())[:limit]


def _money(value: float) -> str:
    return f"${value:.2f}"


def decided(events: Sequence[LedgerEvent]) -> tuple[LedgerEvent, ...]:
    """The latest `delegate.result` of the current raise of each question that has one (answered, escalated, discarded
    or deferred), in the order the questions were raised."""
    keys = dict.fromkeys(k for e in events if e.type == "question.raised" and (k := question_key(e)))
    found = []
    for key in keys:
        if results := results_of(events, key):
            found.append(results[-1])
    return tuple(found)


def _label(event: LedgerEvent) -> str:
    return str(event.data.get("id") or str(event.data.get("question") or "?").rpartition("/")[2])


def line(event: LedgerEvent) -> str:
    """One question's sentence: `Q-003 answered by the delegate (claude-opus-5-5 via claude-code, $0.42)`,
    `Q-004 escalated by the delegate: <reason>` or `Q-005 deferred by the delegate until <time>`."""
    data = event.data
    name = str(data.get("question") or _label(event))
    status = data.get("status")
    if status == "answered":
        who = f"{data['model']} via {data['cli']}" if data.get("model") and data.get("cli") else ""
        cost, credits = data.get("cost_usd"), data.get("credits")
        money = _money(float(cost)) if isinstance(cost, int | float) and not isinstance(cost, bool) else ""
        spent = f"{float(credits):.2f} credits" if isinstance(credits, int | float) and credits else ""
        inside = ", ".join(x for x in (who, money or spent) if x)
        counted = data.get("counted_usd")  # no dollar figure: the call counted at the cap against the limits
        if not money and isinstance(counted, int | float) and not isinstance(counted, bool):
            inside += f"; counted at {_money(float(counted))}" if inside else f"counted at {_money(float(counted))}"
        return f"{name} answered by the delegate" + (f" ({inside})" if inside else "")
    if status == "deferred":
        when = data.get("retry_after")
        why = f" until {_flat(when)}" if when else (f": {_flat(data['reason'])}" if data.get("reason") else "")
        return f"{name} deferred by the delegate{why}"
    reason = f": {_flat(data['reason'])}" if data.get("reason") else ""
    return f"{name} escalated by the delegate{reason}"


def status_lines(events: Sequence[LedgerEvent]) -> list[str]:
    """The `Delegate:` lines of `l4 status --unit`, one per question the delegate decided or defers."""
    out = [f"Delegate: {line(e)}" for e in decided(events)]
    for e in events:  # SCN-DLG-55, D15: a delegate's unfreeze is shown as the delegate's, never as a person's
        if e.type == "task.unfrozen" and e.data.get("reason") == "delegate_answer":
            who = e.data.get("model") or e.data.get("profile") or "the delegate"
            paths = ", ".join(str(p) for p in e.data.get("paths") or [])
            task, question = e.data.get("task"), e.data.get("question")
            out.append(f"Delegate: task {task} unfrozen {paths} by {question} (delegate_override, {who})")
    return out


def status_json(events: Sequence[LedgerEvent]) -> list[dict[str, Any]]:
    """The same as data (`l4 status --json`): question, status, and what the record holds of it."""
    rows = []
    for e in decided(events):
        row: dict[str, Any] = {"question": e.data.get("question"), "status": e.data.get("status")}
        for key in (
            "kind", "decision", "profile", "model", "cli", "cost_usd", "credits", "counted_usd", "reason", "retry_after"
        ):  # fmt: skip
            if e.data.get(key) is not None:
                row[key] = e.data[key]
        row["text"] = line(e)
        rows.append(row)
    return rows


def summary(events: Sequence[LedgerEvent]) -> dict[str, Any]:
    """The counts for `l4 yolo status`: answered, escalated, deferred and the first escalation `{question, reason}`."""
    records = decided(events)
    escalated = [e for e in records if e.data.get("status") in ESCALATED]
    first = escalated[0].data if escalated else None
    return {
        "answered": sum(1 for e in records if e.data.get("status") == "answered"),
        "escalated": len(escalated),
        "deferred": sum(1 for e in records if e.data.get("status") == "deferred"),
        **(
            {"first_escalation": {"question": first.get("question"), "reason": _flat(first.get("reason") or "")}}
            if first is not None
            else {}
        ),
    }


def summary_line(counts: dict[str, Any]) -> str:
    """`delegate: 1 answered, 1 escalated (Q-004: <reason>)`, with `, n deferred` when some wait."""
    parts = [f"{counts['answered']} answered", f"{counts['escalated']} escalated"]
    if counts.get("deferred"):
        parts.append(f"{counts['deferred']} deferred")
    first = counts.get("first_escalation")
    tail = f" ({first['question']}: {first['reason']})" if first and first.get("reason") else ""
    return "delegate: " + ", ".join(parts) + tail


def cost_line(cost: float, share: float | None) -> str:
    """`delegate cost $0.42 of $10.00` (the plan's share of its cost limit), or the cost alone for a plan with none."""
    return f"delegate cost {_money(cost)} of {_money(share)}" if share is not None else f"delegate cost {_money(cost)}"
