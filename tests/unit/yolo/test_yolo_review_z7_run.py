"""Review round 6, area Z7, through the real `run_command`: one trigger runs a unit that never starts once (LOW-1), and
the plan ledger is read after a run only when something must be written (LOW-4)."""

from dataclasses import replace

import l4.orchestrator as orch
from l4.exitcodes import ExitCode
from l4.outcome import CommandResult, UnitOutcome
from l4.vcs.git import Git
from l4.yolo.state import fold_plan

from .test_yolo_cycle_run import run, world  # noqa: F401 - the fixtures
from .yolo_cycle_world import unit_id

A = unit_id("a")
WHY = "cannot prepare the worktree: the unit branch is not usable"


def test_the_first_run_that_never_starts_the_unit_chains_no_run(world, run, monkeypatch):  # noqa: F811
    calls = []

    def runner(app, cfg, git, chosen, *, adapters, accepted=None, activated=None):
        ids = [ref.id for _, ref in chosen]
        calls.append(ids)
        out = UnitOutcome(unit=A, phase_before="none", phase_after="none", exit_reason=WHY)
        return CommandResult(ExitCode.INTERNAL_ERROR, [out], not_started={A: (1, WHY)} if A in ids else {}, began=[])

    monkeypatch.setattr(orch, "run_units", runner)
    world.plan(deps={}, limits={"max_runs": 20})
    world.activate()
    for i in range(3):
        world.app = replace(world.app, run_id=f"r-20261015T1100Z-{i:04d}")
        before = len(run.forge.started)
        run()
        assert len(calls) == i + 1  # one trigger runs the unit once
        assert len(run.forge.started) == before  # and starts no next run
    st = fold_plan("p1", world.events())
    assert st.status == "waiting" and st.wait_reason == "run_not_started" and st.used.runs == 3


def test_a_run_that_started_the_unit_still_chains_the_next_run(world, run, monkeypatch):  # noqa: F811
    def runner(app, cfg, git, chosen, *, adapters, accepted=None, activated=None):
        out = UnitOutcome(unit=A, phase_before="none", phase_after="implementing")
        return CommandResult(ExitCode.OK, [out], began=[ref.id for _, ref in chosen])

    monkeypatch.setattr(orch, "run_units", runner)
    world.plan(deps={})
    world.activate()
    run()
    assert len(run.forge.started) == 1


def _calls(monkeypatch):
    """The git network calls and a marker where `run_units` ran, in order."""
    calls = []
    original = Git.run

    def spy(self, *args, **kw):
        if args and args[0] in ("fetch", "ls-remote", "push"):
            calls.append(args[0])
        return original(self, *args, **kw)

    monkeypatch.setattr(Git, "run", spy)
    return calls


def test_no_network_call_follows_a_normal_run_in_ci(world, run, monkeypatch):  # noqa: F811
    calls = _calls(monkeypatch)

    def runner(app, cfg, git, chosen, *, adapters, accepted=None, activated=None):
        calls.append("|run|")
        out = UnitOutcome(unit=A, phase_before="none", phase_after="implementing")
        return CommandResult(ExitCode.OK, [out], began=[ref.id for _, ref in chosen])

    monkeypatch.setattr(orch, "run_units", runner)
    world.app.environ["GITHUB_ACTIONS"] = "true"
    world.plan(deps={})
    world.activate()
    run()
    assert calls[calls.index("|run|") + 1 :] == []


def test_a_pending_not_started_record_is_cleared_by_the_run_that_starts_the_unit(world, run, monkeypatch):  # noqa: F811
    def failing(app, cfg, git, chosen, *, adapters, accepted=None, activated=None):
        out = UnitOutcome(unit=A, phase_before="none", phase_after="none", exit_reason=WHY)
        return CommandResult(ExitCode.INTERNAL_ERROR, [out], not_started={A: (1, WHY)}, began=[])

    def starting(app, cfg, git, chosen, *, adapters, accepted=None, activated=None):
        out = UnitOutcome(unit=A, phase_before="none", phase_after="implementing")
        return CommandResult(ExitCode.OK, [out], began=[ref.id for _, ref in chosen])

    world.plan(deps={})
    world.activate()
    monkeypatch.setattr(orch, "run_units", failing)
    run()
    monkeypatch.setattr(orch, "run_units", starting)
    world.app = replace(world.app, run_id="r-20261015T1100Z-0009")
    run()
    assert "unit.started" in world.kinds()
