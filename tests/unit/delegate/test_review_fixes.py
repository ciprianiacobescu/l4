# ruff: noqa: F401, F811  (the fixtures are imported by name)
"""Fixes from the independent review of delegate-answers (F1 to F12): each test was written first, from the reviewer's
reproduction, and failed before the fix."""

import dataclasses
from datetime import timedelta

import pytest

from l4.agents.base import LimitSignal
from l4.agents.fake import FakeAdapter, Step
from l4.delegate import run as pass_module

from .conftest import blocked, escalation, reply
from .test_pass import QUESTIONS, outcomes, results  # noqa: F401  (outcomes is a fixture)

SOFT = {"time_budget": "30m", "soft_deadline_margin": "20m"}  # 10 minutes left every run, delegate.timeout is 15m


def test_f1_soft_deadline_deferrals_are_bounded(delegate_run, outcomes, fake_clock):  # noqa: F811
    """L4-DLG-013 / D9: deferrals count as attempts, so the chain of free runs ends in an escalation."""
    delegate_run([blocked("technical")], ci=SOFT)
    for _ in range(5):
        fake_clock.advance(timedelta(minutes=1))
        last = delegate_run([], ci=SOFT)
    rs = results(last)
    assert [r["status"] for r in rs] == ["deferred", "deferred", "escalated"]
    assert len(last.events("delegate.asked")) == 0
    # the run that escalates asks for no further run, and later runs do nothing for the decided question
    assert [o.start_run for o in outcomes] == [True, True, False, False, False, False]
    assert len(rs) == 3


# -- F2: an unknown model vetoes (D3: fail safe) ----------------------------------------------------


def _independence():
    from l4.config.schema import Profile
    from l4.delegate.independence import Asker, delegate_constraint

    return Profile, Asker, delegate_constraint


def test_f2_a_delegate_profile_with_no_model_is_vetoed_under_model_independence():
    Profile, Asker, delegate_constraint = _independence()
    check = delegate_constraint([Asker("impl", "claude-opus-5-5")], "model")
    reason = check("dlg", Profile(adapter="claude-code"))
    assert reason is not None and "no known model" in reason
    assert (
        delegate_constraint([Asker("impl", "claude-opus-5-5")], "profile")("dlg", Profile(adapter="claude-code"))
        is None
    )


def test_f2_an_asker_with_no_resolvable_model_vetoes_every_candidate():
    Profile, Asker, delegate_constraint = _independence()
    dlg = Profile(adapter="codex", model="gpt-6.1-sol")
    unknown = delegate_constraint([Asker("impl", None)], "model", profiles={"impl": Profile(adapter="codex")})
    reason = unknown("dlg", dlg)
    assert reason is not None and "impl" in reason and "no known model" in reason
    unlisted = delegate_constraint([Asker("impl", None)], "model")  # no configuration to resolve it from
    assert unlisted("dlg", dlg) is not None
    known = delegate_constraint(
        [Asker("impl", None)], "model", profiles={"impl": Profile(adapter="codex", model="a-1")}
    )
    assert known("dlg", dlg) is None
    assert delegate_constraint([Asker("impl", None)], "profile")("dlg", dlg) is None  # profile mode: the name rules
    assert delegate_constraint([], "model")("dlg", dlg) is None  # an intake question has no asker


# -- F3: the model that served the call is checked against the askers -------------------------------


def test_f3_the_served_model_of_the_call_is_checked_against_the_askers(delegate_run, monkeypatch):
    monkeypatch.setattr(FakeAdapter.__init__, "__kwdefaults__", {"probes": None, "served_model": True})
    asker_step = dataclasses.replace(blocked("technical"), model="shared-model-9")
    answer = dataclasses.replace(reply(), model="shared-model-9")  # the delegate's CLI served the asker's model
    run = delegate_run([asker_step, answer])
    (res,) = run.events("delegate.result")
    assert res["status"] == "discarded" and "independence: model shared-model-9 asked the question" in res["reason"]
    assert res["called"] is True and res["model"] == "shared-model-9"
    assert run.events("question.answered") == []
    line = next(x for x in run.pushed(QUESTIONS).splitlines() if "Escalated by" in x)
    assert "shared-model-9" in line


def test_f3_another_served_model_still_answers(delegate_run, monkeypatch):
    monkeypatch.setattr(FakeAdapter.__init__, "__kwdefaults__", {"probes": None, "served_model": True})
    asker_step = dataclasses.replace(blocked("technical"), model="shared-model-9")
    answer = dataclasses.replace(reply(), model="delegate-model-1")
    run = delegate_run([asker_step, answer])
    assert [r["status"] for r in run.events("delegate.result")] == ["answered"]


# -- F10: the Escalated by line neutralises HTML comments -------------------------------------------


def test_f10_escalated_by_line_neutralises_html_comments(delegate_run):
    from .conftest import escalation

    run = delegate_run([blocked("product"), escalation(why="cannot check <!-- hidden from the reader --> this")])
    line = next(x for x in run.pushed(QUESTIONS).splitlines() if "Escalated by" in x)
    assert "<!--" not in line and "-->" not in line and "cannot check" in line


# -- F11: the cost of a call that hit a limit is recorded -------------------------------------------


def _limited(cost):
    from l4.agents.base import LimitSignal
    from l4.agents.fake import Step

    return Step(
        status="quota", cost_usd=cost, limit=LimitSignal("fake", None, "usage_limit", None, "test", "limit reached")
    )


def test_f11_the_cost_of_a_limited_call_is_recorded(delegate_run):
    profiles = {"dlg2": {"adapter": "fake", "vendor": "dlgco2", "model": "delegate-model-2"}}
    run = delegate_run(
        [blocked("technical"), _limited(1.10), reply(cost=0.30)], roles={"delegate": ["dlg", "dlg2"]}, profiles=profiles
    )
    assert [e["profile"] for e in run.events("delegate.asked")] == ["dlg", "dlg2"]
    costs = [e["usd"] for e in run.events("budget.cost") if e.get("role") == "delegate"]
    assert costs == [1.10, 0.30]
    assert [r["status"] for r in run.events("delegate.result")] == ["answered"]


def test_f11_an_unpriced_limited_call_counts_at_the_cap():
    from l4.delegate.limits import delegate_cost
    from l4.state.ledger import LedgerEvent

    def result(**data):
        return LedgerEvent("2026-10-18T10:00:00Z", "r-1", "u", 1, "delegate.result", {"called": True, **data})

    assert delegate_cost([result(question="Q-001", cost_usd=None)], 2.0) == 2.0
    assert delegate_cost([result(question="Q-001", cost_usd=None, unpriced_calls=1)], 2.0) == 4.0
    assert delegate_cost([result(question="Q-001", cost_usd=0.3, unpriced_calls=1)], 2.0) == 2.0
