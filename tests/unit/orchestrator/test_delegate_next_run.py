# ruff: noqa: F811  (delegate_run is a fixture imported by name)
"""After an answer the run asks the forge for the next run on the base (delegate-answers 10.1; L4-DLG-007, D4, D13;
SCN-DLG-24): once for the whole `l4 run`, as `l4 questions answer` does, in a plan and outside one; a refused start is
a log line; an escalation, a deferral that is not the soft deadline's, and a run with no pass start nothing."""

from types import SimpleNamespace

import pytest

import l4.orchestrator as orch
from l4.exitcodes import ExitCode
from l4.forge.base import ForgeError, ForgeUnavailable
from l4.outcome import CommandResult, UnitOutcome
from l4.yolo.cycle import PlanStep

from ..delegate.conftest import (  # noqa: F401
    blocked,
    delegate_run,
    escalation,
    no_hooks_but_the_delegate,
    publish_base,
    reply,
)


class Forge:
    def __init__(self, error=None):
        self.started, self.error = [], error

    def start_run(self, ref):
        self.started.append(ref)
        if self.error:
            raise self.error
        return "started"


@pytest.fixture
def forge(monkeypatch):
    forge = Forge()
    monkeypatch.setattr(orch, "make_forge", lambda cfg, environ, repo=None, **kw: forge)
    return forge


def test_an_answer_outside_a_plan_starts_one_run(delegate_run, forge, capsys):  # SCN-DLG-24
    run = delegate_run([blocked("technical", "technical"), reply("Q-001"), reply("Q-002")])
    assert run.code == 11 and forge.started == ["main"]  # two answers, one request
    assert "next run on main: started" in capsys.readouterr().err


def test_one_request_for_two_answered_units(monkeypatch):
    def fake(app, cfg, git, provider, ref, **kw):
        outcome = UnitOutcome(unit=ref.id, phase_before="awaiting_human", phase_after="awaiting_human")
        return orch.UnitRunResult(outcome, ExitCode.AWAITING_HUMAN, delegate_answered=True)

    monkeypatch.setattr(orch, "run_unit_in_worktree", fake)
    monkeypatch.setattr(orch, "load_snapshot", lambda *a, **k: SimpleNamespace(state=SimpleNamespace(phase="x")))
    cfg = SimpleNamespace(forge=SimpleNamespace(branch_prefix="l4/"), ci=SimpleNamespace(time_budget="auto"))
    cfg.ci.soft_deadline_margin = "20m"
    app = SimpleNamespace(environ={}, redactor=SimpleNamespace(redact_text=lambda t: t))
    units = [(object(), SimpleNamespace(id=f"openspec:{n}")) for n in "ab"]
    result = orch.run_units(app, cfg, None, units, adapters=None)
    assert list(result.delegate_answered) == ["openspec:a", "openspec:b"]
    step = PlanStep(allow=None)
    assert orch.after_delegate(step, result).start_next_run is True  # one decision, whatever the number of units
    assert orch.after_delegate(step, CommandResult(ExitCode.OK)).start_next_run is False


def test_a_refused_start_is_a_log_line(delegate_run, forge, capsys):
    forge.error = ForgeError("the token cannot start a run")
    run = delegate_run([blocked("technical"), reply()])
    assert run.code == 11  # the answer stands, the exit is the unit's
    assert "next run was not started" in capsys.readouterr().err
    forge.error = ForgeUnavailable("no token")
    again = delegate_run([blocked("technical")])  # nothing left to ask in the already answered unit
    assert again.code == 11


def test_no_answer_starts_nothing(delegate_run, forge):
    run = delegate_run([blocked("technical"), escalation()])
    assert run.code == 11 and forge.started == []


def test_the_soft_deadline_starts_one_run(delegate_run, forge):  # SCN-DLG-12
    ci = {"time_budget": "30m", "soft_deadline_margin": "20m"}
    delegate_run([blocked("technical")], ci=ci)
    assert forge.started == ["main"]


# -- the order of the merge (L4-DLG-026): the plan's request, the continuation, the answer ---------------------


def merged(*, answered=True, continuation=None, deferred=(), steps=1, left=None, plan_request=False):
    step = PlanStep(allow=None, start_next_run=plan_request)
    result = CommandResult(
        ExitCode.AWAITING_HUMAN, delegate_answered=["openspec:a"] if answered else [], continuation=continuation,
        deferred=list(deferred), steps_started=steps, first_check_left_s=left,
    )  # fmt: skip
    return orch.merge_next_run(step, result).start_next_run


def test_an_answer_with_no_step_started_starts_one_run():  # SCN-DLG-89
    # unit B was handed back at its first check with no step started: the plan's request is dropped, the answer's stays
    assert merged(plan_request=True, deferred=["openspec:b"], steps=0, left=0.0) is True
    assert merged(plan_request=False, deferred=["openspec:b"], steps=0, left=0.0) is True
    assert merged(answered=False, plan_request=True, deferred=["openspec:b"], steps=0, left=0.0) is False


@pytest.mark.parametrize("queued", ["dispatched", "already_queued"])
def test_a_dispatched_continuation_carries_the_answer(queued):  # SCN-DLG-90
    assert merged(continuation=queued, deferred=["openspec:b"], left=300.0) is False
    assert merged(continuation=queued, plan_request=True, deferred=["openspec:b"], left=300.0) is False
    assert merged(continuation=None, deferred=["openspec:b"], left=300.0) is True  # no continuation: the answer asks


def test_an_unsupported_continuation_still_lets_the_answer_ask():
    assert merged(continuation="unsupported", deferred=["openspec:b"], left=300.0) is True


def test_an_escalation_or_a_cooling_deferral_starts_nothing(delegate_run, forge):
    from l4.agents.base import LimitSignal  # noqa: F401

    escalated = delegate_run([blocked("technical"), escalation()])
    assert escalated.code == 11 and forge.started == []
    assert merged(answered=False) is False  # a cool-down deferral answers nothing: no flag, no request
