"""Review round 4, area z4: a named run of a blocked plan unit is refused (LOW-4), the head-lag re-read happens once
(LOW-1), the plan files are read after a fetch outside CI (L4), a rejection by the unit's run stops the plan (M2)."""

import json

import pytest

from l4.yolo.digest import plan_digest
from l4.yolo.state import fold_plan

from .yolo_cycle_world import CycleWorld, ev, unit_id
from .yolo_review_world import PURPOSE_X

A, B = unit_id("a"), unit_id("b")


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path, units=("a", "b"))


def state(world):
    return fold_plan("p1", world.events())


# --- LOW-4: a named run of a plan unit that has a blocker ----------------------------------------------------------


@pytest.mark.parametrize("with_current", [False, True], ids=["ledger_without_current", "activation_with_current"])
def test_a_named_run_of_a_current_unit_with_a_blocker_is_refused(world, with_current):
    text = world.plan()  # b depends on a
    world.reviewed(text)
    extra = {"current": B} if with_current else {}
    world.seed(
        ev("plan.activated", plan_digest=plan_digest(text), digests=world.digests(), limits={}, by="alice", **extra),
        ev("unit.dispatched", unit=B, run="r0"),  # an older ledger dispatched b before a was integrated
    )
    assert state(world).current == B
    step = world.step({"a": world.snapshot("a", None), "b": world.snapshot("b", "implementing")}, read_only=True)
    assert step.allow == frozenset()
    assert step.refusals[B] == f"waits for the plan step: {B} waits for {A} (not integrated) (plan p1)"


def test_a_named_run_of_a_current_unit_without_a_blocker_is_still_allowed(world):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    step = world.step({"a": world.snapshot("a", "implementing")}, read_only=True)
    assert step.allow == {A}


# --- LOW-1: the PR head is read again once, when the wait is first recorded ---------------------------------------


@pytest.fixture
def lagging(world):
    from dataclasses import replace

    from l4.forge.local import LocalForge

    class OtherHead(LocalForge):
        def find_pr(self, head_branch):
            pr = super().find_pr(head_branch)
            return None if pr is None else replace(pr, head_sha="b" * 40)

        def get_pr(self, number):
            return replace(super().get_pr(number), head_sha="b" * 40)

    world.forge = OtherHead()
    world.plan(deps={})
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    head = world.unit_branch("a")
    world.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    return {"a": world.in_review("a", head), "b": world.snapshot("b", None)}


def test_the_head_is_read_again_in_the_run_that_records_the_wait_and_not_in_later_runs(world, lagging):
    first, second, third = [], [], []
    world.step(lagging, sleep=first.append)
    assert state(world).wait_reason == "merge_not_ready"
    world.step(lagging, sleep=second.append)
    world.step(lagging, sleep=third.append)
    assert first == [5.0] * 3 and second == [] and third == []
    assert next(e for e in world.events() if e.type == "plan.waiting").data["head"] == lagging["a"].review.head


def test_a_preview_never_reads_the_head_again(world, lagging):
    sleeps = []
    step = world.step(lagging, sleep=sleeps.append, read_only=True)
    assert sleeps == [] and step.allow == {A} and "plan.waiting" not in world.kinds()


def test_a_wait_recorded_for_another_cause_does_not_count_as_this_wait(world, lagging):
    world.step(lagging, sleep=lambda _s: None)
    world.seed(ev("plan.waiting", reason="unit_awaiting_human", unit=A, detail="x"))
    sleeps = []
    world.step(lagging, sleep=sleeps.append)
    assert sleeps == [5.0] * 3  # the latest wait of the unit is another one: this one is recorded for the first time


def test_a_wait_recorded_without_a_head_is_asked_again_and_recorded_with_it(world, lagging):
    world.seed(ev("plan.waiting", reason="merge_not_ready", unit=A, detail="old ledger"))  # no head
    sleeps = []
    world.step(lagging, sleep=sleeps.append)
    assert sleeps == [5.0] * 3 and [e.data.get("head") for e in world.events() if e.type == "plan.waiting"][-1]


# --- M2: a unit that the plan dispatched and its run rejected ------------------------------------------------------


def rejects(world, step, why="the unit has no tasks"):
    """What `run_command` does after a dispatched unit's run exited 14."""
    from l4.yolo.cycle import record_rejections

    record_rejections(world.app, world.cfg, world.git, step, {A: why})


def test_a_plan_whose_unit_is_rejected_by_its_run_stops_instead_of_dispatching_it_again(world):
    world.plan(limits={"max_runs": 50})
    world.activate()
    runs = []
    for _ in range(6):  # r1: the run rejects the unit every time; the snapshot has no phase
        step = world.step({"a": world.snapshot("a", None)})
        runs.append(step.start_next_run)
        if step.start_next_run:
            rejects(world, step)
    assert runs == [True, False, False, False, False, False]
    done = state(world)
    assert (done.status, done.stop_reason, done.stop_unit) == ("stopped", "unit_rejected", A)
    assert "the unit has no tasks" in done.stop_detail and done.used.runs == 1
    stopped = [e for e in world.events() if e.type == "plan.stopped"]
    assert len(stopped) == 1 and stopped[0].data["digest"] == world.digests()[A]


def test_a_rejection_is_recorded_only_for_the_unit_the_step_let_run(world):
    world.plan()
    world.activate()
    step = world.step({"a": world.snapshot("a", None)})
    from l4.yolo.cycle import record_rejections

    record_rejections(world.app, world.cfg, world.git, step, {B: "x"})  # b is not the dispatched unit
    assert "unit.rejected" not in world.kinds()
    rejects(world, step)
    rejects(world, step)  # recorded once
    assert world.kinds().count("unit.rejected") == 1


def test_a_rejection_is_not_recorded_on_a_plan_that_is_not_active(world):
    world.plan()
    world.activate()
    step = world.step({"a": world.snapshot("a", None)})
    world.seed(ev("plan.cancelled", reason="x"))
    rejects(world, step)
    assert "unit.rejected" not in world.kinds()


def test_the_dispatch_after_a_fixed_spec_is_rejected_again_and_stops_the_plan_once_more(world):
    text = world.plan()
    world.activate()
    rejects(world, world.step({"a": world.snapshot("a", None)}))
    world.step({"a": world.snapshot("a", None)})
    assert state(world).stop_reason == "unit_rejected"
    world.commit({"openspec/changes/a/specs/x/spec.md": FIXED_SPEC}, "fix the spec of a")
    world.push_main()
    world.step({"a": world.snapshot("a", None)})
    assert state(world).stop_reason == "inputs_changed"
    world.seed(
        ev("plan.activated", plan_digest=plan_digest(text), digests=world.digests(), limits={}, by="alice", reason="ok")
    )
    step = world.step({"a": world.snapshot("a", None)})  # the corrected spec: the unit's next run reads it
    assert step.allow == frozenset({A}) and step.start_next_run is True
    rejects(world, step, "still wrong")
    world.step({"a": world.snapshot("a", None)})
    assert (
        state(world).stop_reason == "unit_rejected"
        and "still rejected after its spec was fixed" in state(world).stop_detail
    )


FIXED_SPEC = PURPOSE_X + (
    "## ADDED Requirements\n\n### Requirement: R1 fixed\nThe system SHALL work.\n\n#### Scenario: S\n"
    "- **WHEN** x\n- **THEN** y\n"
)


def test_a_unit_that_went_on_after_a_rejection_is_not_stopped_for_it(world):
    world.plan()
    world.activate()
    rejects(world, world.step({"a": world.snapshot("a", None)}))
    world.seed(ev("unit.dispatched", unit=A, run="r2"))  # a person's activation or a later dispatch
    step = world.step({"a": world.snapshot("a", "implementing")})
    assert step.allow == frozenset({A}) and state(world).status == "active"


def test_a_named_run_of_a_unit_the_last_run_rejected_is_refused(world):
    world.plan()
    world.activate()
    rejects(world, world.step({"a": world.snapshot("a", None)}))
    step = world.step({"a": world.snapshot("a", None)}, read_only=True)
    assert step.allow == frozenset() and "was rejected by its last run" in step.refusals[A]


# --- L4: the plan files are read after the target is fetched (outside CI) -----------------------------------------


def edit_plan_elsewhere_and_reactivate(world):
    """A person edits the plan in another clone, and the plan is reviewed and activated again at the new digest. This
    clone has not fetched since."""
    import subprocess

    from .yolo_ledger_world import _env, sh

    other = world.root / "other"
    subprocess.run(["git", "clone", "-q", str(world.origin), str(other)], check=True, env=_env())
    sh(other, "config", "user.name", "p")
    sh(other, "config", "user.email", "p@x.invalid")
    sh(other, "checkout", "-q", "main")
    path = other / ".l4/plans/p1.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["limits"] = {"max_runs": 50}
    text = json.dumps(doc, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    sh(other, "commit", "-qam", "edit plan")
    sh(other, "push", "-q", "origin", "main")
    digest = plan_digest(text)
    units = {u: {"verdict": "READY", "digest": d, "findings": []} for u, d in world.digests().items()}
    world.seed(
        ev("plan.stopped", reason="inputs_changed", detail="x", unit="plan"),
        ev("plan.admitted", plan_digest=digest, order=[A, B], merge="auto"),
        ev("plan.reviewed", plan_digest=digest, units=units, batches={}),
        ev("plan.activated", plan_digest=digest, digests=world.digests(), limits={"max_runs": 50}, by="alice",
           reason="go", current=A),
    )  # fmt: skip
    return text


@pytest.mark.parametrize("case", ["head_is_the_stale_tip", "local_branch_and_no_tracking_ref"])
def test_a_bare_run_on_a_clone_that_has_not_fetched_does_not_stop_a_plan_that_was_edited_and_activated(world, case):
    from .yolo_ledger_world import sh

    world.plan(deps={})
    world.activate()
    world.step({"a": world.snapshot("a", None)})
    edit_plan_elsewhere_and_reactivate(world)
    if case != "head_is_the_stale_tip":
        sh(world.repo, "checkout", "-q", "-b", "mywork")
        world.commit({"notes.txt": "x\n"}, "local work")
        sh(world.repo, "update-ref", "-d", "refs/remotes/origin/main")
    world.step({"a": world.snapshot("a", "implementing"), "b": world.snapshot("b", None)})
    assert state(world).status == "active" and state(world).stop_reason is None
    assert [e for e in world.events() if e.type == "plan.stopped"][-1].data["reason"] == "inputs_changed"  # seeded one


def test_a_target_that_cannot_be_fetched_writes_nothing_and_no_unit_of_the_plan_runs(world, caplog):
    from .yolo_ledger_world import sh

    world.plan(deps={})
    world.activate()
    world.step({"a": world.snapshot("a", None)})
    before = world.events()
    good = sh(world.repo, "remote", "get-url", "origin")
    sh(world.repo, "remote", "set-url", "origin", str(world.root / "no-such-origin.git"))
    try:
        with caplog.at_level("WARNING"):
            step = world.step({"a": world.snapshot("a", "implementing")})
            preview = world.step({"a": world.snapshot("a", "implementing")}, read_only=True)
    finally:
        sh(world.repo, "remote", "set-url", "origin", good)
    assert step.allow == frozenset() and preview.allow == frozenset() and step.start_next_run is False
    assert any(a.startswith("plan step skipped: the target main could not be fetched") for a in step.actions)
    assert len([r for r in caplog.records if "no plan step in this run" in r.getMessage()]) == 2
    assert world.events() == before  # not a stop, not a charge


def test_in_ci_the_target_is_not_fetched_again(world, monkeypatch):
    world.plan()
    world.activate()
    monkeypatch.setitem(world.app.environ, "GITHUB_ACTIONS", "true")
    asked = []
    fetch = type(world.git).fetch

    def spy(self, remote, *, refspecs=(), **kw):
        asked.extend(refspecs)
        return fetch(self, remote, refspecs=refspecs, **kw)

    monkeypatch.setattr(type(world.git), "fetch", spy)
    world.step({"a": world.snapshot("a", None)})
    assert "unit.dispatched" in world.kinds() and asked and not any("refs/heads/" in r for r in asked)


def test_outside_ci_the_target_is_fetched_before_the_plan_files_are_read(world, monkeypatch):
    world.plan()
    world.activate()
    asked = []
    fetch = type(world.git).fetch

    def spy(self, remote, *, refspecs=(), **kw):
        asked.extend(refspecs)
        return fetch(self, remote, refspecs=refspecs, **kw)

    monkeypatch.setattr(type(world.git), "fetch", spy)
    world.step({"a": world.snapshot("a", None)})
    assert asked[0] == "+refs/heads/main:refs/remotes/origin/main"


def test_a_clone_without_an_origin_is_read_as_before(world):
    from .yolo_ledger_world import sh

    world.plan()
    sh(world.repo, "remote", "remove", "origin")
    assert cycle_fetch_failure(world) is None


def cycle_fetch_failure(world):
    from l4.yolo.cycle import _fetch_failure

    return _fetch_failure(world.app, world.cfg, world.git)
