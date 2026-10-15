"""Review round 6, area Z7: the wait of a unit with nothing to run is not the wait of a run that never started it."""

from dataclasses import replace

from l4.state.status import UnitSnapshot
from l4.yolo.state import fold_plan

from .test_yolo_review_z6 import never_started, step, world  # noqa: F401 - the fixture
from .yolo_cycle_world import unit_id

A = unit_id("a")


def no_tasks(world, name):  # noqa: F811
    snap = world.snapshot(name, None)
    return UnitSnapshot(ref=snap.ref, state=snap.state, source=snap.source, tasks=[])


def test_a_unit_with_nothing_to_run_waits_once_and_the_triggers_add_nothing(world):  # noqa: F811
    world.plan(deps={}, limits={"max_runs": 5})
    world.activate()
    after = []
    for i in range(6):
        world.app = replace(world.app, run_id=f"r-20261014T1000Z-{i:04d}")
        s = world.step({"a": no_tasks(world, "a"), "b": world.snapshot("b", None)})
        assert s.allow == (frozenset({A}) if i == 0 else frozenset()) and s.start_next_run is False
        after.append(len(world.events()))
    kinds = world.kinds()
    assert kinds.count("plan.waiting") == 1 and kinds.count("plan.resumed") == 0
    assert after[1:] == [after[0]] * 5  # silence after the first wait
    waiting = [e for e in world.events() if e.type == "plan.waiting"]
    assert waiting[0].data["reason"] == "unit_not_started"
    assert fold_plan("p1", world.events()).used.runs == 0


def test_a_run_that_never_started_the_unit_waits_with_its_own_reason(world):  # noqa: F811
    world.plan(deps={})
    world.activate()
    never_started(world, step(world))
    step(world)
    waiting = [e for e in world.events() if e.type == "plan.waiting"]
    assert [e.data["reason"] for e in waiting] == ["run_not_started"]
    assert fold_plan("p1", world.events()).wait_reason == "run_not_started"


def test_a_unit_skipped_because_another_run_holds_its_lease_is_not_recorded_as_not_started(monkeypatch):
    from types import SimpleNamespace

    from l4 import orchestrator
    from l4.orchestrator import UnitRunResult, _busy

    monkeypatch.setattr(
        orchestrator, "load_snapshot", lambda *a, **k: SimpleNamespace(state=SimpleNamespace(phase="implementing"))
    )
    monkeypatch.setattr(
        orchestrator, "run_unit_in_worktree", lambda app, cfg, git, provider, ref, **kw: _busy("implementing", ref)
    )
    cfg = SimpleNamespace(
        forge=SimpleNamespace(branch_prefix="l4/"), ci=SimpleNamespace(time_budget="auto", soft_deadline_margin="20m")
    )
    app = SimpleNamespace(redactor=SimpleNamespace(redact_text=lambda t: t), environ={})
    out = orchestrator.run_units(app, cfg, None, [(object(), SimpleNamespace(id=A))], adapters=None)
    assert out.not_started == {} and out.began == []
    assert isinstance(_busy(None, SimpleNamespace(id=A)), UnitRunResult)


def test_the_next_line_of_a_run_not_started_wait_agrees_with_the_runbook():
    from l4.yolo.commands import _next_line
    from l4.yolo.state import PlanState

    st = PlanState(plan_id="p1", status="waiting", wait_reason="run_not_started")
    line = _next_line("p1", st, None, None)
    assert "next trigger" in line and "l4 yolo resume p1" in line


def _no_plan_file_and_a_failed_fetch(tmp_path, ledger_status):
    from .test_yolo_review_z6 import broken_origin
    from .yolo_cycle_world import CycleWorld, ev
    from .yolo_ledger_world import sh

    w = CycleWorld(tmp_path, units=("a", "b", "c"))
    w.plan(deps={})
    w.activate()
    if ledger_status == "cancelled":
        w.seed(ev("plan.cancelled", by="x", reason="done"))
    snaps = {n: w.snapshot(n, "implementing") for n in "abc"}
    w.step(snaps)  # the ledger ref is fetched into the clone
    sh(w.repo, "rm", "-q", ".l4/plans/p1.json")
    sh(w.repo, "commit", "-q", "-m", "drop the plan")
    w.push_main()
    good = broken_origin(w)
    try:
        return w.step(snaps)
    finally:
        sh(w.repo, "remote", "set-url", "origin", good)


def test_no_plan_file_and_no_open_plan_in_the_clone_lets_every_unit_run_when_the_fetch_fails(tmp_path):
    assert _no_plan_file_and_a_failed_fetch(tmp_path, "cancelled").allow is None


def test_no_plan_file_but_an_open_plan_in_the_clone_holds_every_unit_when_the_fetch_fails(tmp_path):
    assert _no_plan_file_and_a_failed_fetch(tmp_path, "active").allow == frozenset()


def _app():
    from types import SimpleNamespace

    return SimpleNamespace(redactor=SimpleNamespace(redact_text=lambda t: t), environ={})


def test_the_detail_of_a_git_failure_keeps_the_cause_not_the_command_line(monkeypatch):
    from types import SimpleNamespace

    from l4 import orchestrator
    from l4.vcs.errors import GitError

    monkeypatch.setattr(orchestrator, "_phase_of", lambda *a, **k: "none")
    cause = "fatal: 'l4/openspec/add-discount-codes' is already used by worktree at '/cache/worktrees/openspec/x'"
    argv = ["/opt/homebrew/bin/git", "-c", "core.hooksPath=/dev/null", "worktree", "add", "--quiet", "-B", "l4/x", "/p"]
    done = orchestrator._failed_unit(
        _app(), SimpleNamespace(), None, None, SimpleNamespace(id=A), GitError(argv, 128, cause + "\n"), "none"
    )
    reason = done.outcome.exit_reason
    assert "already used by worktree" in reason and reason.endswith("(git exit 128)")
    assert "core.hooksPath" not in reason


def test_another_error_keeps_its_first_line(monkeypatch):
    from types import SimpleNamespace

    from l4 import orchestrator

    monkeypatch.setattr(orchestrator, "_phase_of", lambda *a, **k: "none")
    done = orchestrator._failed_unit(
        _app(), SimpleNamespace(), None, None, SimpleNamespace(id=A), RuntimeError("one\ntwo"), "none"
    )
    assert done.outcome.exit_reason == "internal error: RuntimeError: one"


def test_the_fetch_cause_prefers_the_fatal_line_to_a_warning_first_line():
    from l4.vcs.errors import GitError
    from l4.yolo.cycle import fetch_cause

    err = GitError(["git", "fetch"], 128, "warning: redirecting to https://x.example/y.git/\nfatal: unable to access\n")
    assert fetch_cause(_app(), err) == "fatal: unable to access (git exit 128)"
    only = GitError(["git", "fetch"], 1, "warning: only a warning\n")
    assert fetch_cause(_app(), only) == "warning: only a warning (git exit 1)"
