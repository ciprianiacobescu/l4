"""`l4 run` with delivery plans (L4-YOLO-010, L4-YOLO-012): the plan's `allow` filters what runs, a unit named with
`--unit` that the plan does not let run exits 13 before any lease, the next run is started once, and a repository with
no plan file behaves as before. The discovery, the unit runs and the forge are replaced; the plan step is real."""

import logging

import pytest

import l4.orchestrator as orch
from l4.exitcodes import ExitCode
from l4.forge.base import ForgeError
from l4.forge.local import LocalForge
from l4.outcome import CommandResult
from l4.yolo.store import PlanStore

from .yolo_cycle_world import CycleWorld, ev, unit_id

A, B = unit_id("a"), unit_id("b")


class Runner:
    """What `run_units` was asked to run."""

    def __init__(self) -> None:
        self.chosen: list[list[str]] = []
        self.activated: list[object] = []

    def __call__(self, app, cfg, git, chosen, *, adapters, accepted=None, activated=None, began=None):
        self.chosen.append([ref.id for _, ref in chosen])
        self.activated.append(activated)
        return CommandResult(ExitCode.OK, [])


class StartRunForge(LocalForge):
    def __init__(self, answer="started", error=None):
        super().__init__()
        self.answer, self.error, self.started = answer, error, []

    def start_run(self, ref):
        self.started.append(ref)
        if self.error:
            raise self.error
        return self.answer


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


@pytest.fixture
def run(world, monkeypatch):
    runner, forge = Runner(), StartRunForge()
    snapshots = {}

    def discover(cfg, git, providers, wanted=()):
        return [(p, s) for p, s in world.found(snapshots) if not wanted or s.ref.id in wanted]

    monkeypatch.setattr(orch, "load_app_config", lambda app: (app, world.cfg))
    monkeypatch.setattr(orch, "preflight_run_config", lambda app, cfg: None)
    monkeypatch.setattr(orch, "require_framework", lambda cfg, repo: None)
    monkeypatch.setattr(orch, "refresh_refs", lambda app, cfg, git, **_: None)
    monkeypatch.setattr(orch, "providers_for", lambda cfg, repo, environ: [])
    monkeypatch.setattr(orch, "discover", discover)
    monkeypatch.setattr(orch, "perform_follow_ups", lambda app, cfg, git, snaps: [])
    monkeypatch.setattr(orch, "run_units", runner)
    monkeypatch.setattr(orch, "make_forge", lambda cfg, environ, repo=None, **kw: forge)
    monkeypatch.setattr(orch, "log_artefacts", lambda *a: None)
    monkeypatch.setattr(
        "l4.yolo.cycle.review_plan_costed", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no review here"))
    )

    def go(**kw):
        return orch.run_command(world.app, **kw)

    go.runner, go.forge, go.snapshots = runner, forge, snapshots
    return go


def test_a_repository_with_no_plan_file_runs_exactly_as_before(world, run):
    result = run()
    assert run.runner.chosen == [[A, B]] and result.code == ExitCode.OK
    assert run.forge.started == []
    assert world.git.run("ls-remote", "origin", "refs/l4/plans/*").stdout.strip() == ""
    assert run(units=(B,)).code == ExitCode.OK and run.runner.chosen[-1] == [B]  # --unit is not filtered either


def test_scn_yolo_30_units_of_a_plan_that_is_not_active_do_not_start(world, run):
    world.plan()
    world.reviewed()
    result = run()
    assert run.runner.chosen == [] and result.code == ExitCode.OK  # "nothing to do": the plan holds both
    refused = run(units=(A,))
    assert refused.units[0].exit_reason == "run: openspec:a is held by plan p1 (reviewed)"


def test_scn_yolo_21_a_direct_run_cannot_jump_the_order(world, run):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    before = world.kinds()
    result = run(units=(B,))
    assert result.code == ExitCode.HALTED
    (outcome,) = result.units
    assert outcome.exit_reason == "run: openspec:b waits for openspec:a (not integrated) (plan p1)"
    assert run.runner.chosen == [] and world.kinds() == before  # no lease, no run, nothing recorded
    assert run.forge.started == []


def test_a_named_unit_that_a_plan_holds_exits_13_with_the_plan_and_its_status(world, run):
    world.plan()
    world.seed(ev("plan.admitted", plan_digest="d", order=[A, B]))
    result = run(units=(A,))
    assert result.code == ExitCode.HALTED
    assert result.units[0].exit_reason == "run: openspec:a is held by plan p1 (admitted)"


def test_a_unit_outside_the_active_plan_exits_13(run, world):
    world.plan(deps={}, batches=[{"id": "b1", "units": [{"id": A}]}])
    world.activate(order=[A])
    result = run(units=(B,))
    assert result.code == ExitCode.HALTED
    assert result.units[0].exit_reason == "run: openspec:b is not in the active plan p1"


def test_the_current_unit_may_be_named_and_its_run_is_only_charged(world, run):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))  # the eligible unit is the step's to dispatch (review #11)
    before = world.kinds()
    result = run(units=(A,))
    assert result.code == ExitCode.OK and run.runner.chosen == [[A]]
    assert world.kinds() == [*before, "plan.charged"]  # a named run does not step the plan, it is charged (L4-YOLO-012)


def test_a_dispatched_unit_that_its_run_rejects_is_on_the_plan_ledger_and_the_next_run_stops_the_plan(
    world, run, monkeypatch
):
    world.plan()
    world.activate()
    why = "rejected: gates.test.command is not configured: there is no test oracle"
    monkeypatch.setattr(
        orch, "run_units", lambda *a, **k: CommandResult(ExitCode.REJECTED, [], rejected={A: why})
    )  # the run of the dispatched unit exits 14
    result = run()
    assert result.code == ExitCode.REJECTED and run.forge.started == ["main"]
    assert world.kinds()[-3:] == ["plan.charged", "unit.dispatched", "unit.rejected"]
    run()  # the next run: the step stops the plan, the unit is not dispatched again
    assert world.kinds()[-1] == "plan.stopped" and world.kinds().count("unit.dispatched") == 1
    assert run.forge.started == ["main"]
    assert [e for e in world.events() if e.type == "plan.stopped"][0].data["detail"] == why


def test_a_rejection_the_plan_ledger_cannot_record_does_not_change_the_run_result(world, run, monkeypatch, caplog):
    world.plan()
    world.activate()
    monkeypatch.setattr(orch, "run_units", lambda *a, **k: CommandResult(ExitCode.REJECTED, [], rejected={A: "x"}))
    append = PlanStore.append

    def failing(self, events, **kw):
        events = list(events)
        if any(e.type == "unit.rejected" for e in events):
            raise ValueError("boom")
        return append(self, events, **kw)

    monkeypatch.setattr(PlanStore, "append", failing)
    caplog.set_level(logging.WARNING)
    result = run()
    assert result.code == ExitCode.REJECTED
    assert any("the rejection of" in r.getMessage() for r in caplog.records)


def test_an_active_plan_runs_only_its_dispatched_unit_and_starts_the_next_run_once(world, run):
    world.plan()
    world.activate()
    run()
    assert run.runner.chosen == [[A]]
    assert world.kinds()[-2:] == ["plan.charged", "unit.dispatched"]
    assert run.forge.started == ["main"]


def test_a_plan_step_with_no_work_left_starts_no_run_and_runs_no_unit(world, run):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("plan.waiting", reason="unit_awaiting_human", unit=A))
    run.snapshots["a"] = world.snapshot("a", "awaiting_human")  # the question is still open: the cause is still there
    run()
    assert run.runner.chosen == [] and run.forge.started == []


def test_a_forge_that_cannot_start_the_run_is_a_warning_not_a_failure(world, run, caplog):
    world.plan()
    world.activate()
    run.forge.error = ForgeError("boom")
    with caplog.at_level(logging.WARNING):
        result = run()
    assert result.code == ExitCode.OK
    assert any("next run was not started" in r.getMessage() for r in caplog.records)


def test_the_answer_of_start_run_is_logged(world, run, caplog):
    world.plan()
    world.activate()
    with caplog.at_level(logging.INFO):
        run()
    assert any("next run on main: started" in r.getMessage() for r in caplog.records)


def test_an_allowed_unit_carries_its_frozen_digest_and_a_held_unit_does_not(world, run):
    world.plan()
    world.activate()
    run()
    assert run.runner.chosen == [[A]]
    plan_id, digests = run.runner.activated[-1]
    assert plan_id == "p1" and digests == {A: world.digests()[A]}  # B is held by the order: no digest


def test_the_preview_of_a_named_run_carries_the_digest_of_the_current_unit(world, run):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    run(units=(A,))
    plan_id, digests = run.runner.activated[-1]
    assert plan_id == "p1" and digests == {A: world.digests()[A]}


def test_a_run_with_no_plan_carries_no_digest(world, run):
    run()
    assert run.runner.activated == [None]


# --- no usable sandbox: a CI job stops the plan, a local run refuses (L4-YOLO-093, L4-SEC-041) ---------------


@pytest.fixture
def sandboxless(world, run, monkeypatch):
    """`run_command` with the real `_run_units` and a `run_unit_in_worktree` that, once the unit has started, selects
    the sandbox as `build_services` does; no bwrap exists and the config says `auto`."""
    from dataclasses import replace

    from l4.config.schema import SandboxCfg
    from l4.sandbox.select import select_sandbox
    from l4.services import SystemClock

    world.cfg = world.cfg.model_copy(update={"sandbox": SandboxCfg(mode="auto")})
    monkeypatch.setattr("l4.sandbox.select.resolve_tool", lambda *a, **k: None)
    monkeypatch.setattr(orch, "load_snapshot", lambda *a, **k: world.snapshot("a", "implementing"))
    started: list[str] = []

    def real_units(app, cfg, git, chosen, *, adapters, accepted=None, activated=None, began=None):
        waits = orch.RunWaits()
        waits.began = began or SystemClock().now()
        return orch._run_units(
            app, cfg, git, chosen, adapters=adapters, accepted=accepted, activated=activated, clock=SystemClock(),
            waits=waits,
        )  # fmt: skip

    def unit_run(app, cfg, git, provider, ref, *, waits=None, **kw):
        started.append(ref.id)
        waits.started.add(ref.id)  # the lease and the ledger exist, then the sandbox is selected
        select_sandbox(cfg.sandbox, app.environ, repo=app.repo)

    monkeypatch.setattr(orch, "run_units", real_units)
    monkeypatch.setattr(orch, "run_unit_in_worktree", unit_run)
    run.snapshots["a"] = world.snapshot("a", "implementing")
    world.plan(limits={"max_runs": 50})
    world.activate()

    def go(**env):
        world.app = replace(world.app, environ={**world.app.environ, **env})
        return orch.run_command(world.app)

    go.started = started
    return go


def test_scn_yolo_255_in_a_github_job_without_a_sandbox_the_unit_fails_its_setup_and_the_plan_stops(world, sandboxless):
    result = sandboxless(GITHUB_ACTIONS="true")
    assert result.code == ExitCode.DOCTOR_FAILED and sandboxless.started == [A]
    assert "bwrap" in result.setup_failed[A] or "sandbox" in result.setup_failed[A].lower()
    assert "unit.setup_failed" in world.kinds()
    sandboxless(GITHUB_ACTIONS="true")  # the next step
    assert world.kinds()[-1] == "plan.stopped"
    stopped = [e for e in world.events() if e.type == "plan.stopped"][0]
    assert stopped.data["reason"] == "setup_failed"


def test_scn_sec_107_a_local_run_without_a_sandbox_leaves_the_plan_alone(world, sandboxless):
    before = world.kinds()
    result = sandboxless()
    assert result.code == ExitCode.DOCTOR_FAILED and sandboxless.started == []
    assert world.kinds() == before and "unit.setup_failed" not in world.kinds()
