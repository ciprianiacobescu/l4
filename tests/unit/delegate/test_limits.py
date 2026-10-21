"""The delegate's limits, pure over the ledger and the plan (delegate-answers 7.1; L4-DLG-009; design D10;
SCN-DLG-27, SCN-DLG-28, SCN-DLG-29, SCN-DLG-29a, SCN-DLG-36a)."""

from datetime import UTC, datetime

from l4.config.schema import DelegateCfg
from l4.delegate.limits import PlanCost, answers_used, delegate_cost, limit_reached
from l4.state.fold import fold
from l4.state.ledger import LedgerEvent

STAMP = datetime(2026, 10, 18, 10, tzinfo=UTC)
CFG = DelegateCfg()  # 2 attempts, 3 answers per task, 3.0 per answer, 15.0 per unit, share 0.25


def ev(seq: int, event_type: str, **data) -> LedgerEvent:
    return LedgerEvent(STAMP, "r-1", "u", seq, event_type, data)


def raised(seq: int, qid: str = "Q-003", **extra) -> LedgerEvent:
    return ev(seq, "question.raised", id=qid, kind="technical", **extra)


def result(seq: int, qid: str, status: str, *, tasks=("3.1",), target=None, cost=0.4, **extra) -> LedgerEvent:
    data = {"question": qid, "status": status, "tasks": list(tasks), "cost_usd": cost, **extra}
    return ev(seq, "delegate.result", **({"target": target} if target else {}), **data)


def reached(events, qid="Q-009", tasks=("3.1",), target=None, plan=None, cfg=CFG):
    return limit_reached(qid, tasks, target, events, plan, cfg)


def test_attempts_per_question():  # SCN-DLG-36a
    events = [raised(1), result(2, "Q-003", "deferred", reason="timeout")]
    assert reached(events, "Q-003") is None  # one deferral: one attempt left
    events.append(result(3, "Q-003", "deferred", reason="timeout"))
    assert reached(events, "Q-003") == "delegate attempts used (2)"
    # a new raise of the same id starts again: only the attempts after the latest question.raised count
    assert reached([*events, raised(4)], "Q-003") is None
    assert reached(events, "Q-004") is None  # another question
    one = DelegateCfg(max_attempts_per_question=1)
    assert reached(events[:2], "Q-003", cfg=one) == "delegate attempts used (1)"


def test_a_fix_unit_question_has_its_own_key():
    events = [ev(1, "question.raised", id="Q-003", fix_unit="u-fix-1"), result(2, "u-fix-1/Q-003", "deferred")]
    assert reached(events, "Q-003") is None and reached(events, "u-fix-1/Q-003") is None
    events.append(result(3, "u-fix-1/Q-003", "deferred"))
    assert reached(events, "u-fix-1/Q-003") == "delegate attempts used (2)"


def test_answers_per_task_and_per_target():  # SCN-DLG-27
    answered = [result(n, f"Q-00{n}", "answered", tasks=("3.1",)) for n in (1, 2, 3)]
    assert reached(answered[:2]) is None
    assert reached(answered) == "delegate answer limit of task 3.1 reached (3)"
    assert reached(answered, tasks=("3.2",)) is None  # another task
    assert reached(answered, tasks=("3.2", "3.1")) == "delegate answer limit of task 3.1 reached (3)"
    # escalated and discarded replies are no answers
    mixed = [result(1, "Q-001", "escalated"), result(2, "Q-002", "discarded"), result(3, "Q-003", "answered")]
    assert reached(mixed) is None and answers_used(mixed, "3.1") == 1
    # a fix unit's answer counts for the parent's task it records
    fixes = [result(n, f"u-fix-{n}/Q-001", "answered", tasks=("3.1",)) for n in (1, 2)]
    assert reached([*answered[:1], *fixes]) == "delegate answer limit of task 3.1 reached (3)"
    # a verdict question holds no task: it counts per target
    verdicts = [result(n, f"Q-0{n}", "answered", tasks=(), target="C-0a1b2c3d") for n in (1, 2, 3)]
    assert reached(verdicts, tasks=(), target="C-0a1b2c3d") == "delegate answer limit of target C-0a1b2c3d reached (3)"
    assert reached(verdicts, tasks=(), target="F-11112222") is None


def test_the_unit_cap():  # SCN-DLG-29
    cfg = DelegateCfg(max_cost_usd_per_unit=6.0)
    spent = [ev(1, "budget.cost", usd=2.5, role="delegate", profile="delegate-opus", question="Q-001"),
             ev(2, "budget.cost", usd=1.5, role="delegate", profile="delegate-opus", question="Q-002")]  # fmt: skip
    assert reached(spent, cfg=cfg) == "the delegate's cost cap of the unit is used ($4.00 of $6.00)"
    assert reached(spent[:1], cfg=cfg) is None  # $3.50 left covers one answer of $3.00
    other_role = [ev(1, "budget.cost", usd=9.0, role="judge", profile="judge-opus")]
    assert reached(other_role, cfg=cfg) is None and delegate_cost(other_role) == 0.0


def test_what_is_left_must_cover_one_answer():
    cfg = DelegateCfg(max_cost_usd_per_unit=15.0)
    assert reached([ev(1, "budget.cost", usd=12.0, role="delegate")], cfg=cfg) is None  # exactly 3.0 left
    assert reached([ev(1, "budget.cost", usd=12.01, role="delegate")], cfg=cfg) is not None


def test_an_unknown_cost_counts_at_the_cap():
    unknown = [result(n, f"Q-00{n}", "escalated", tasks=(), cost=None) for n in (1, 2, 3, 4)]
    assert delegate_cost(unknown, per_answer=3.0) == 12.0
    assert reached(unknown) is None  # 12.0 of 15.0: exactly one answer left
    assert reached([*unknown, result(5, "Q-005", "escalated", tasks=(), cost=None)]) is not None
    known = [result(1, "Q-001", "answered", tasks=(), cost=0.5), ev(2, "budget.cost", usd=0.5, role="delegate")]
    assert delegate_cost(known, per_answer=3.0) == 0.5  # a known cost is counted once, from budget.cost
    no_call = [result(1, "Q-001", "deferred", tasks=(), cost=None, reason="soft_deadline", called=False)]
    assert delegate_cost(no_call, per_answer=3.0) == 0.0  # nothing was called


def test_the_plan_share():  # SCN-DLG-28
    plan = PlanCost(max_cost_usd=40.0, delegate_cost_usd=8.5)
    assert reached([], plan=plan) == "the delegate's share of the plan's cost is used ($8.50 of $10.00)"
    assert reached([], plan=PlanCost(40.0, 7.0)) is None  # $3.00 left
    # an extension of the cost limit raises the share: the caller passes the limit in force
    assert reached([], plan=PlanCost(max_cost_usd=60.0, delegate_cost_usd=8.5)) is None
    assert (
        reached([], plan=PlanCost(max_cost_usd=40.0, delegate_cost_usd=8.5), cfg=DelegateCfg(plan_cost_share=0.5))
        is None
    )


def test_no_share_without_a_plan_cost_limit():
    assert reached([], plan=PlanCost(max_cost_usd=None, delegate_cost_usd=500.0)) is None
    assert reached([], plan=None) is None


def test_the_first_limit_that_holds_is_named():
    events = [raised(1), result(2, "Q-009", "deferred"), result(3, "Q-009", "deferred")]
    plan = PlanCost(40.0, 9.9)
    assert reached(events, plan=plan) == "delegate attempts used (2)"


def test_the_delegate_cost_is_unit_cost():  # SCN-DLG-29a
    events = [
        ev(1, "budget.cost", usd=0.7, role="delegate", profile="delegate-opus", question="Q-003"),
        ev(2, "budget.cost", usd=0.5, role="delegate", profile="delegate-sol", question="Q-004"),
        ev(3, "budget.cost", usd=2.0, profile="codex-sol", task="1.1"),
    ]
    state = fold(events, "u")
    assert state.cost_usd == 3.2  # the fold that `plan.charged{cost_usd}` takes (`Cycle._charged`) sums every role
    assert delegate_cost(events) == 1.2
