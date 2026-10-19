"""The delegate's limits, pure over the ledger and the plan (delegate-answers 7.1; L4-DLG-009; design D10).

`limit_reached` answers, before a call: may the delegate be asked this question at all? The reason it returns is the
text of the escalation. Everything it reads is recorded: `delegate.result{question, status, tasks, target, cost_usd}`
for the attempts and the answers (the pass writes `tasks` and `target` on every result, so no questions file is
needed here), `budget.cost{role: delegate, usd}` for the money. The delegate's cost is unit cost: the fold sums every
`budget.cost` into the unit's cost, which is what `plan.charged{cost_usd}` carries, so it also counts against the
plan's `max_cost_usd` like any agent's; the plan's delegate share is a further limit on it."""

from collections.abc import Sequence
from dataclasses import dataclass

from l4.config.schema import DelegateCfg
from l4.state.fold import question_key
from l4.state.ledger import LedgerEvent


@dataclass(frozen=True)
class PlanCost:
    """What the plan says: `max_cost_usd` the limit in force (extensions included, None when the plan has none) and
    `delegate_cost_usd` the delegate's cost recorded on the plan's units."""

    max_cost_usd: float | None
    delegate_cost_usd: float = 0.0

    def share_usd(self, cfg: DelegateCfg) -> float | None:
        return None if self.max_cost_usd is None else self.max_cost_usd * cfg.plan_cost_share


def _money(value: float) -> str:
    return f"${value:.2f}"


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def delegate_cost(events: Sequence[LedgerEvent], per_answer: float = 0.0) -> float:
    """The delegate's spend on these events (the unit's and its fix units'): every `budget.cost{role: delegate}`, and
    `per_answer` for each call whose cost was not reported (a `delegate.result` with no `cost_usd` that made a call, and
    each of its `unpriced_calls`, the limited calls before it):
    Codex reports tokens, and without a price there is no USD, so it counts at the cap."""
    known = sum(
        usd
        for e in events
        if e.type == "budget.cost" and e.data.get("role") == "delegate" and (usd := _number(e.data.get("usd")))
    )
    unknown = sum(
        (1 if _number(e.data.get("cost_usd")) is None else 0) + int(_number(e.data.get("unpriced_calls")) or 0)
        for e in events
        if e.type == "delegate.result" and e.data.get("called", True)
    )  # `unpriced_calls`: calls of the same answer that hit a limit and reported no cost
    return round(known + unknown * per_answer, 6)


def attempts_used(events: Sequence[LedgerEvent], question: str) -> int:
    """The calls and deferrals of the question's current raise: its `delegate.result` events after the latest
    `question.raised` (one per call or deferral, so a timed-out call is not counted twice)."""
    since = max(
        (i for i, e in enumerate(events) if e.type == "question.raised" and question_key(e) == question), default=-1
    )
    return sum(1 for e in events[since + 1 :] if e.type == "delegate.result" and e.data.get("question") == question)


def answers_used(events: Sequence[LedgerEvent], key: str) -> int:
    """The questions the delegate answered that block task `key` (a verdict question: that target)."""
    answered = {
        str(e.data.get("question"))
        for e in events
        if e.type == "delegate.result" and e.data.get("status") == "answered" and key in _keys(e)
    }
    return len(answered)


def _keys(event: LedgerEvent) -> set[str]:
    tasks = event.data.get("tasks")
    keys = {str(t) for t in tasks} if isinstance(tasks, list) else set()
    target = event.data.get("target")
    if not keys and isinstance(target, str):
        keys.add(target)
    return keys


def limit_reached(
    question: str,
    tasks: Sequence[str],
    target: str | None,
    events: Sequence[LedgerEvent],
    plan: PlanCost | None,
    cfg: DelegateCfg,
) -> str | None:
    """The reason the delegate may not be asked `question` (its key: `Q-003`, or `<fix unit>/Q-003`), or None. `tasks`
    are the tasks it blocks and `target` the target of a verdict question; `events` are those of the unit and its fix
    units. Checked in order: attempts, answers per task or target, the unit's cost, the plan's share. A call needs one
    answer's cost (`max_cost_usd_per_answer`) left in each cost limit."""
    attempts = attempts_used(events, question)
    if attempts >= cfg.max_attempts_per_question:
        return f"delegate attempts used ({attempts})"
    keys = [("task", t) for t in tasks] or ([("target", target)] if target else [])
    for noun, key in keys:
        if answers_used(events, key) >= cfg.max_answers_per_task:
            return f"delegate answer limit of {noun} {key} reached ({cfg.max_answers_per_task})"
    spent = delegate_cost(events, cfg.max_cost_usd_per_answer)
    if cfg.max_cost_usd_per_unit - spent < cfg.max_cost_usd_per_answer:
        return f"the delegate's cost cap of the unit is used ({_money(spent)} of {_money(cfg.max_cost_usd_per_unit)})"
    share = plan.share_usd(cfg) if plan is not None else None
    if plan is not None and share is not None and share - plan.delegate_cost_usd < cfg.max_cost_usd_per_answer:
        return f"the delegate's share of the plan's cost is used ({_money(plan.delegate_cost_usd)} of {_money(share)})"
    return None
