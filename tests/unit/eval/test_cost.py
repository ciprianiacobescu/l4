from l4.eval.score import cost_of

from ._ledgers import ev

AGENT = {"task": "1.1", "phase": "red", "status": "ok", "exit_code": 0, "detail": None, "model": None}


def test_cost_sums_the_budget_events_of_every_role() -> None:
    events = [
        ev("budget.cost", usd=0.25, profile="a", task="1.1"),
        ev("budget.cost", usd=0.5, profile="j", role="judge"),
        ev("budget.cost", usd=0.125, profile="c", role="clarifier"),
    ]
    assert cost_of(events, free=False) == {"cost_usd": 0.875, "input_tokens": 0, "output_tokens": 0}


def test_a_cell_whose_agent_reports_no_cost_is_null_not_zero() -> None:
    events = [ev("agent.finished", input_tokens=10, output_tokens=2, **AGENT)]
    assert cost_of(events, free=False)["cost_usd"] is None


def test_a_profile_declared_free_costs_zero() -> None:
    events = [ev("agent.finished", input_tokens=10, output_tokens=2, **AGENT)]
    assert cost_of(events, free=True)["cost_usd"] == 0.0


def test_a_reported_cost_wins_over_the_free_declaration() -> None:
    assert cost_of([ev("budget.cost", usd=0.5, profile="a")], free=True)["cost_usd"] == 0.5


def test_tokens_are_summed_from_agent_finished() -> None:
    events = [
        ev("agent.finished", input_tokens=100, output_tokens=10, **AGENT),
        ev("agent.finished", input_tokens=50, output_tokens=5, **{**AGENT, "phase": "green"}),
    ]
    out = cost_of(events, free=True)
    assert out["input_tokens"] == 150 and out["output_tokens"] == 15


def test_a_missing_token_count_counts_as_zero() -> None:
    events = [ev("agent.finished", input_tokens=None, output_tokens=None, **AGENT)]
    assert cost_of(events, free=False)["input_tokens"] == 0
