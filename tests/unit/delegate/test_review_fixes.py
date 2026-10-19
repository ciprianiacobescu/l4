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


# -- F2: an unknown model vetoes (D3: fail safe) ---------------------------------------------------------------------


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
