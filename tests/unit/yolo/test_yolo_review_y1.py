"""The final review of yolo-mode, findings 1, 2, 3, 11 and 12 (L4-YOLO-009, -010, -012): a unit out of the plan is never
merged, a unit past implementation is adopted, a merged unit that was archived is still integrated, the `--unit`
preview is the step's own checks, and a failing plan step does not fail the units that are in no plan."""

import logging

import pytest

import l4.orchestrator as orch
from l4.exitcodes import ExitCode
from l4.outcome import CommandResult
from l4.yolo.commands import Extend, resume_blocker
from l4.yolo.digest import plan_digest
from l4.yolo.model import ProfileResult
from l4.yolo.state import fold_plan

from .yolo_cycle_world import CycleWorld, ev, unit_id

A, B = unit_id("a"), unit_id("b")


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def st(w, pid="p1"):
    return fold_plan(pid, w.events(pid))


def reactivate_without_a(w):
    """A person removes `a` from the plan file; the plan is reviewed and activated again."""
    text = w.plan(deps={}, batches=[{"id": "b1", "units": [{"id": B}]}])
    return text


def activate_again(w, text):
    w.units = ["b"]
    w.reviewed(text, order=[B])
    w.seed(ev("plan.activated", plan_digest=plan_digest(text), digests=w.digests(["b"]), limits={}, by="a", reason="x"))
    w.units = ["a", "b"]


# --- finding 1 -------------------------------------------------------------------------------------------------------


def test_the_activation_forgets_a_current_unit_that_the_new_order_does_not_hold():
    events = [
        ev("plan.admitted", plan_digest="d1", order=[A, B], merge="auto"),
        ev("plan.reviewed", plan_digest="d1", units={}, batches={}),
        ev("plan.activated", plan_digest="d1", digests={}, limits={}),
        ev("unit.dispatched", unit=A, run="r0"),
        ev("plan.stopped", reason="inputs_changed", unit="plan"),
        ev("plan.admitted", plan_digest="d2", order=[B], merge="auto"),
        ev("plan.reviewed", plan_digest="d2", units={}, batches={}),
    ]
    assert fold_plan("p1", events).current == A  # not activated yet: nothing changes
    state = fold_plan("p1", [*events, ev("plan.activated", plan_digest="d2", digests={}, limits={})])
    assert state.status == "active" and state.current is None


def test_a_unit_removed_from_the_plan_is_not_merged_and_the_step_does_not_raise(world):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    text2 = reactivate_without_a(world)
    head = world.unit_branch("a")
    world.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    snaps = {"a": world.in_review("a", head)}
    before = world.tip()
    world.step(snaps)  # the plan file changed: inputs_changed
    assert st(world).stop_reason == "inputs_changed" and world.tip() == before
    activate_again(world, text2)
    assert st(world).current is None
    step = world.step(snaps)  # must not raise StopIteration, must not merge a
    assert world.tip() == before and "unit.merged" not in world.kinds()
    assert A not in step.allow
    assert st(world).status == "active" and st(world).stop_unit is None


def test_a_stale_current_unit_is_not_stopped_on_and_not_merged_by_the_step(world):
    """Even a ledger that still names a unit out of the plan as current (activated by an older harness)."""
    world.plan(deps={}, batches=[{"id": "b1", "units": [{"id": B}]}])
    world.units = ["b"]
    world.activate()
    world.units = ["a", "b"]
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    assert st(world).current == A
    head = world.unit_branch("a")
    world.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    before = world.tip()
    world.step({"a": world.in_review("a", head)})
    assert world.tip() == before and "unit.merged" not in world.kinds()
    world.step({"a": world.snapshot("a", "halted", halt_reason="x")})
    assert st(world).stop_unit != A and st(world).status == "active"


# --- finding 2 -------------------------------------------------------------------------------------------------------


def test_an_auto_plan_adopts_a_unit_in_review_and_merges_it_in_the_same_step(world):
    world.plan()
    world.activate()
    head = world.unit_branch("a")
    world.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    step = world.step({"a": world.in_review("a", head)})
    kinds = world.kinds()
    assert "unit.dispatched" in kinds and "unit.merged" in kinds and "unit.integrated" in kinds
    dispatched = next(e for e in world.events() if e.type == "unit.dispatched")
    assert dispatched.data["adopted"] is True and dispatched.data["attempt"] == 1 and dispatched.data["unit"] == A
    assert kinds.index("plan.charged") < kinds.index("unit.dispatched")  # the charge, as a normal dispatch
    assert world.landed(head) and step.start_next_run
    assert st(world).integrated.keys() == {A} and st(world).used.runs == 1


def test_a_human_plan_adopts_a_unit_in_review_and_waits_for_the_person(world):
    world.plan(merge="human")
    world.activate()
    head = world.unit_branch("a")
    snaps = {"a": world.in_review("a", head)}
    before = world.tip()
    step = world.step(snaps)
    assert st(world).current == A and st(world).status == "active"
    assert next(e for e in world.events() if e.type == "unit.dispatched").data["adopted"] is True
    assert world.tip() == before and not step.start_next_run and step.allow == {A}
    n = len(world.events())
    world.step(snaps)
    assert len(world.events()) == n  # nothing more is recorded while the person has not merged


def test_a_unit_the_plan_cannot_run_or_adopt_makes_the_plan_wait_with_a_reason(world):
    world.plan()
    world.activate()
    snaps = {"a": world.snapshot("a", "halted", halt_reason="boom")}
    world.step(snaps)
    waiting = [e for e in world.events() if e.type == "plan.waiting"]
    assert len(waiting) == 1 and waiting[0].data["reason"] == "unit_halted" and waiting[0].data["unit"] == A
    assert st(world).status == "waiting"
    n = len(world.events())
    world.step(snaps)
    world.step(snaps)
    assert len(world.events()) == n  # no flapping between waiting and resumed while the cause is there
    snaps = {"a": world.snapshot("a", None)}  # the person retried: the unit can run
    world.step(snaps)
    assert st(world).status == "active" and st(world).current == A


# --- finding 3 -------------------------------------------------------------------------------------------------------


def archived_world(world):
    world.plan(merge="human")
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    world.profile_result = lambda rev, prof: ProfileResult("fail", rev, prof, detail="test failed")
    world.step({"a": world.snapshot("a", "merged")})  # a person merged a; its check fails
    assert st(world).stop_reason == "postcheck_failed" and A in st(world).merged
    world.profile_result = lambda rev, prof: ProfileResult("pass", rev, prof)
    world.seed(ev("plan.resumed", by="alice", reason="fixed"))
    world.units = ["b"]  # discover: the archived change is not a unit any more


def test_a_merged_unit_that_moved_to_the_archive_is_post_checked_and_integrated(world):
    archived_world(world)
    world.step({"b": world.snapshot("b", None)})
    assert st(world).status == "active" and A in st(world).integrated
    assert "unit.integrated" in world.kinds()


def test_resume_does_not_refuse_unit_missing_for_a_merged_unit():
    from l4.yolo.model import PlanState

    state = PlanState(plan_id="p1", status="stopped", stop_reason="unit_missing", stop_unit=A, merged={A: "abc"})
    assert resume_blocker("p1", state, [], None, {B: None}, Extend()) is None
    gone = state.model_copy(update={"merged": {}})
    blocker = resume_blocker("p1", gone, [], None, {B: None}, Extend())
    assert blocker is not None and "not among the units" in blocker.message


def test_a_merged_unit_whose_head_the_target_does_not_hold_is_still_missing(world):
    world.plan(merge="human")
    world.activate()
    head = world.unit_branch("a")  # on its branch only, not in the target
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("unit.merged", unit=A, head=head))
    world.units = ["b"]
    world.step({"b": world.snapshot("b", None)})
    assert st(world).status == "stopped" and st(world).stop_reason == "unit_missing" and st(world).stop_unit == A


# --- finding 11 ------------------------------------------------------------------------------------------------------


def test_a_named_run_of_the_eligible_unit_is_refused_until_the_plan_dispatched_it(world):
    world.plan()
    world.activate()
    before = world.kinds()
    step = world.step({"a": world.snapshot("a", None)}, read_only=True)
    assert step.allow == frozenset() and "not the current unit of plan p1" in step.refusals[A]
    assert world.kinds() == before


def test_a_named_run_of_the_current_unit_is_allowed(world):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    step = world.step({"a": world.snapshot("a", "implementing")}, read_only=True)
    assert step.allow == {A}


def test_a_named_run_is_refused_when_the_plan_file_is_not_the_activated_one(world):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    world.plan(deps={})  # the file on the target is another file now
    step = world.step({"a": world.snapshot("a", "implementing")}, read_only=True)
    assert step.allow == frozenset() and "changed after the activation" in step.refusals[A]


def test_a_named_run_is_refused_when_a_limit_is_reached(world):
    world.plan(limits={"max_runs": 1})
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("plan.charged", unit=A, attempt=1, cost_usd=0, runs=1))
    step = world.step({"a": world.snapshot("a", "implementing")}, read_only=True)
    assert step.allow == frozenset() and "limit_runs" in step.refusals[A]


# --- finding 12 ------------------------------------------------------------------------------------------------------


@pytest.fixture
def run(tmp_path, monkeypatch):
    world = CycleWorld(tmp_path, units=("a", "b", "c"))
    chosen: list[list[str]] = []

    def discover(cfg, git, providers, wanted=()):
        return [(p, s) for p, s in world.found({}) if not wanted or s.ref.id in wanted]

    monkeypatch.setattr(orch, "load_app_config", lambda app: (app, world.cfg))
    monkeypatch.setattr(orch, "preflight_run_config", lambda app, cfg: None)
    monkeypatch.setattr(orch, "require_framework", lambda cfg, repo: None)
    monkeypatch.setattr(orch, "refresh_refs", lambda app, cfg, git, **_: None)
    monkeypatch.setattr(orch, "providers_for", lambda cfg, repo, environ: [])
    monkeypatch.setattr(orch, "discover", discover)
    monkeypatch.setattr(orch, "perform_follow_ups", lambda app, cfg, git, snaps: [])
    monkeypatch.setattr(orch, "log_artefacts", lambda *a: None)

    def run_units(app, cfg, git, picked, *, adapters, accepted=None, activated=None, began=None):
        chosen.append([ref.id for _, ref in picked])
        return CommandResult(ExitCode.OK, [])

    monkeypatch.setattr(orch, "run_units", run_units)

    def boom(*a, **k):
        raise RuntimeError("the ref could not be listed: token=SECRET")

    monkeypatch.setattr(orch, "yolo_step", boom)
    world.plan(batches=[{"id": "b1", "units": [{"id": A}, {"id": B, "depends_on": [A]}]}])
    return world, chosen


def test_a_failing_plan_step_does_not_fail_the_units_in_no_plan(run, caplog):
    world, chosen = run
    with caplog.at_level(logging.WARNING):
        result = orch.run_command(world.app)
    assert result.code == ExitCode.OK and chosen == [[unit_id("c")]]  # c is in no plan: it runs; a and b are held
    assert any(r.getMessage().startswith("plan step failed: RuntimeError: ") for r in caplog.records)
    assert world.git.run("ls-remote", "origin", "refs/l4/plans/*").stdout.strip() == ""  # nothing recorded


def test_a_failing_plan_step_keeps_the_plan_units_held_and_lets_the_others_run(run, monkeypatch):
    world, chosen = run
    found = {s.ref.id: s for _, s in world.found({"c": world.snapshot("c", "implementing")})}
    monkeypatch.setattr(
        orch,
        "discover",
        lambda cfg, git, providers, wanted=(): [
            (p, found[s.ref.id]) for p, s in world.found({}) if not wanted or s.ref.id in wanted
        ],
    )
    monkeypatch.setattr(orch, "next_action", lambda facts: ("implement", "x"))
    result = orch.run_command(world.app)
    assert result.code == ExitCode.OK and chosen == [[unit_id("c")]]
    named = orch.run_command(world.app, units=(A,))
    assert named.code == ExitCode.HALTED and "held by plan p1" in named.units[0].exit_reason
    assert "SECRET" not in named.units[0].exit_reason


# --- finding 11: l4 run --dry-run -------------------------------------------------------------------------------------


def test_a_dry_run_shows_a_unit_a_plan_holds_as_held_not_as_runnable(tdd_repo, capsys, raw):
    import json

    from l4.cli import main

    unit = "openspec:add-discount-codes"
    plan = {
        "schema": "l4/delivery-plan@1", "plan_id": "p1", "target": "main", "merge": "human",
        "batches": [{"id": "b1", "units": [{"id": unit}]}],
    }  # fmt: skip
    (tdd_repo.repo / ".l4" / "plans").mkdir(parents=True, exist_ok=True)
    (tdd_repo.repo / ".l4" / "plans" / "p1.json").write_text(json.dumps(plan), encoding="utf-8")
    # the plan file is on the target, as the plan step reads it (`plan_source`, LOW-5): a file only in the working
    # tree holds nothing in a real run, so the dry run must not show it held either
    raw(tdd_repo.repo, "add", ".l4/plans/p1.json")
    raw(tdd_repo.repo, "commit", "-q", "-m", "plan p1")
    raw(tdd_repo.repo, "push", "-q", "origin", "main")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    tdd_repo.write_config()

    def dry(*flags):
        code = main(["run", "--dry-run", *flags, "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ)
        return code, capsys.readouterr().out

    code, out = dry()
    assert code == 0 and "prompt:" not in out and "command:" not in out  # nothing would start
    assert "would exit 0" in out.splitlines()[-1]
    code, out = dry("--unit", unit)
    assert "held: held by plan p1 (new)" in out and "prompt:" not in out
    assert out.strip().splitlines()[-1] == "would exit 13"
