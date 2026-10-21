"""The cost of every adapter is bounded, known or not (L4-DLG-020; SCN-DLG-69, 70): a zero cost is known, Kiro's credits
are recorded as credits and counted at the cap, a run with no cost counts at the cap."""

import pytest

from l4.delegate.limits import delegate_cost
from l4.delegate.lines import line
from l4.state.ledger import LedgerEvent

from ..agents.cli_streams import kiro_call, kiro_chunk, kiro_metering, kiro_stream, oc_finish, oc_text, oc_tool
from .cli_adapters import KIRO_PROFILE, OPENCODE_PROFILE, ScriptedKiro, ScriptedOpenCode
from .conftest import blocked
from .test_pass import results, status_of
from .test_pass_adapters import text_of


def opencode_lines(question: str, cost: float | None) -> list[str]:
    return [oc_tool("read"), oc_finish("tool-calls", cost), oc_text(text_of(question)), oc_finish("stop", cost)]


def ledger_cost(run) -> list[dict]:
    return [e for e in run.events("budget.cost") if e.get("role") == "delegate"]


def test_a_zero_cost_is_known(delegate_run, install_cli):  # SCN-DLG-69
    script = [opencode_lines(f"Q-00{n}", 0) for n in (1, 2, 3)]
    adapter = install_cli("opencode", ScriptedOpenCode(script))
    run = delegate_run(
        [blocked("technical", "technical", "technical")], profiles={"dlg": OPENCODE_PROFILE},
        delegate={"max_cost_usd_per_unit": 6.0},
    )  # fmt: skip
    done = results(run)
    assert [(r["status"], r["cost_usd"]) for r in done] == [("answered", 0)] * 3
    assert len(adapter.requests) == 3  # a third question is asked: two free answers left $6.00 of $6.00
    assert [status_of(run, f"Q-00{n}") for n in (1, 2, 3)] == ["answered"] * 3
    assert all("counted_usd" not in r for r in done)
    assert delegate_cost([LedgerEvent("t", "r", "u", i, "delegate.result", r) for i, r in enumerate(done)], 3.0) == 0


def test_an_opencode_run_with_no_cost_counts_at_the_cap(delegate_run, install_cli):
    script = [opencode_lines(f"Q-00{n}", None) for n in (1, 2, 3)]
    adapter = install_cli("opencode", ScriptedOpenCode(script))
    run = delegate_run(
        [blocked("technical", "technical", "technical")], profiles={"dlg": OPENCODE_PROFILE},
        delegate={"max_cost_usd_per_unit": 6.0},
    )  # fmt: skip
    done = results(run)
    assert [r["status"] for r in done] == ["answered", "answered", "escalated"]
    assert done[0]["cost_usd"] is None and done[0]["counted_usd"] == 3.0
    assert "cost cap of the unit is used" in done[2]["reason"] and len(adapter.requests) == 2
    assert not ledger_cost(run)  # nothing was reported, nothing is recorded as spent


@pytest.fixture
def kiro_reply():
    body = "Here it is.\n" + text_of()
    return kiro_stream(kiro_call("read"), kiro_metering(1.0, 0.84), kiro_chunk(body), final=body)


def test_kiro_credits_are_recorded_and_counted_at_the_cap(delegate_run, install_cli, kiro_reply):  # SCN-DLG-70
    install_cli("kiro-cli", ScriptedKiro([kiro_reply], served="claude-sonnet-4.5"))
    run = delegate_run([blocked("technical")], profiles={"dlg": KIRO_PROFILE})
    (spent,) = ledger_cost(run)
    assert spent["credits"] == pytest.approx(1.84) and spent["credits_source"] == "kiro.stream"
    assert spent["profile"] == "dlg" and spent["question"] == "Q-001" and "usd" not in spent
    (result,) = results(run)
    assert result["credits"] == pytest.approx(1.84) and result["cost_usd"] is None and result["counted_usd"] == 3.0
    events = [LedgerEvent("t", "r", "u", 1, "delegate.result", result)]
    assert delegate_cost(events, 3.0) == 3.0  # counted at the cap, the credits never converted
    assert line(events[0]) == (
        "Q-001 answered by the delegate (claude-sonnet-4.5 via kiro-cli, 1.84 credits; counted at $3.00)"
    )
