"""The plan step after the final review of yolo-mode (findings 4, 5, 6, 7, 8, 9, 13 and 16): a judge that cannot run
does not starve the active plan, every stop charges the live attempt, a person's resume tries the merge once more, a
rejected unit has a way out, a review keeps the active plan's chain of runs, the attempts of a plan start at its
activation, and a lease lost after a paid review is not paid for twice."""

from types import SimpleNamespace

import pytest

from l4.availability.errors import RoleUnavailable
from l4.exitcodes import ExitCode
from l4.implementer.tdd import RoleLimit
from l4.orchestrator import UnitRunResult
from l4.outcome import UnitOutcome
from l4.yolo.digest import plan_digest
from l4.yolo.limits import live_attempt, live_state
from l4.yolo.model import PlanMoved
from l4.yolo.readiness import PROMPT_VERSION
from l4.yolo.state import fold_plan

from .yolo_cycle_world import CycleWorld, ev, unit_id
from .yolo_review_world import PURPOSE_X

A, B, C = unit_id("a"), unit_id("b"), unit_id("c")
FIXED_SPEC = PURPOSE_X + (
    "## ADDED Requirements\n\n### Requirement: R1 fixed\nThe system SHALL work.\n\n"
    "#### Scenario: S\n- **WHEN** x\n- **THEN** y\n"
)


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def state(world, plan_id="p1"):
    return fold_plan(plan_id, world.events(plan_id))


def kinds_after(world, count, plan_id="p1"):
    return [e.type for e in world.events(plan_id)[count:]]


def two_plans(tmp_path):
    w = CycleWorld(tmp_path, units=("a", "b", "c"))
    w.plan(batches=[{"id": "b1", "units": [{"id": A}, {"id": B, "depends_on": [A]}]}])
    w.activate(order=[A, B])
    return w


# --- #4: a judge that cannot run does not block the active plan -----------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        RoleUnavailable("judges", "all cooling down"),
        RoleLimit(SimpleNamespace(detail="usage limit", status="usage_limit")),
    ],
)
def test_a_judge_that_cannot_run_for_a_waiting_plan_does_not_starve_the_active_plan(tmp_path, monkeypatch, error):
    w = two_plans(tmp_path)
    w.plan(plan_id="p2", batches=[{"id": "x", "units": [{"id": C}]}])

    def down(*args, **kwargs):
        raise error

    monkeypatch.setattr("l4.yolo.cycle.review_plan_costed", down)
    for _ in range(2):
        step = w.step()
        assert any("no judge could run" in a for a in step.actions)
    assert w.kinds("p2") == []  # nothing was recorded for the review that waits
    assert state(w).current == A and w.kinds()[-1] == "unit.dispatched"  # p1 went on in the very same run
    assert step.allow == frozenset({A}) and step.start_next_run is True


# --- #5, #6: every stop writes the live charge, resume and status read the same figures -----------------------------


def test_a_stop_charges_the_cost_the_attempt_spent_after_its_last_charge(world):
    world.plan(limits={"max_cost_usd": 5, "max_unit_attempts": 9})
    world.activate()
    world.step({"a": world.snapshot("a", None, cost_usd=0.0)})  # attempt 1 dispatched, charged $0
    world.step({"a": world.snapshot("a", "halted", cost_usd=4.0, halt_reason="x")})
    assert [e.type for e in world.events()][-2:] == ["plan.charged", "plan.stopped"]  # the charge precedes the stop
    assert world.events()[-2].data == {"unit": A, "attempt": 1, "cost_usd": 4.0, "runs": 1}
    assert state(world).used.cost_usd == 4.0
    world.restarts("a", 1)  # `l4 restart`: a new unit ledger
    world.seed(ev("plan.resumed", by="alice", reason="restarted"))
    world.step({"a": world.snapshot("a", "intake", cost_usd=0.0)})
    world.step({"a": world.snapshot("a", "implementing", cost_usd=4.0)})  # attempt 2 spent $4: $8 of $5
    assert state(world).status == "stopped" and state(world).stop_reason == "limit_cost"
    assert state(world).used.cost_usd == 8.0


def test_a_limit_stop_writes_the_live_attempt_so_the_ledger_holds_it(world):
    world.plan(limits={"max_unit_attempts": 2})
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    world.restarts("a", 2)
    world.step({"a": world.snapshot("a", "implementing")})
    folded = state(world)
    assert folded.stop_reason == "limit_attempts" and folded.used.attempts == {A: 3}


def test_the_live_attempt_is_one_function(world):
    world.plan()
    world.activate()
    folded = state(world)
    assert live_attempt(folded, A, 0) == 1 and live_attempt(folded, A, 2) == 3
    assert live_attempt(folded, A, None) == 1
    live = live_state(folded, world.events(), A, 3, 2.5)
    assert live.used.attempts == {A: 3} and live.used.cost_usd == 2.5 and folded.used.cost_usd == 0.0


# --- #7: a person's resume tries the merge once more ----------------------------------------------------------------


def test_a_resume_tries_the_merge_once_more_after_two_stale_merges(world, monkeypatch):
    calls = []

    def retry(app, cfg, git, provider, ref, **kw):
        calls.append(ref.id)
        return UnitRunResult(UnitOutcome(unit=ref.id, phase_before="in_review", phase_after="verifying"), ExitCode.OK)

    monkeypatch.setattr("l4.state.retry.retry_unit", retry)
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    head = world.unit_branch("a")
    world.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    snaps = {"a": world.in_review("a", head)}
    world.seed(ev("unit.merge_refused", unit=A, reason="stale"))
    world.person_moves_target()
    world.step(snaps)
    assert state(world).stop_reason == "merge_refused" and calls == []
    world.seed(ev("plan.resumed", by="alice", reason="the target is quiet now"))
    assert state(world).stale_merges == {}
    world.step(snaps)
    assert calls == [A]  # the merge was tried again and the unit was verified against the moved target


def test_the_harness_waking_a_waiting_plan_keeps_the_stale_count():
    from l4.yolo.state import fold_plan as fold

    events = [
        ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a", reason="r"),
        ev("unit.merge_refused", unit=A, reason="stale"),
        ev("plan.waiting", reason="unit_awaiting_human"),
        ev("plan.resumed", by="harness", reason="the cause is gone"),
    ]
    assert fold("p1", events).stale_merges == {A: 1}


# --- #8: a plan stopped with unit_rejected has a way out ------------------------------------------------------------


def rejected_world(world):
    text = world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    world.step({"a": world.snapshot("a", "rejected")})
    assert state(world).stop_reason == "unit_rejected"
    return text


def test_a_rejected_unit_stop_records_the_spec_digest(world):
    rejected_world(world)
    stop = [e for e in world.events() if e.type == "plan.stopped"][-1].data
    assert stop["unit"] == A and stop["digest"] == world.digests()[A]


def test_an_unchanged_spec_leaves_a_rejected_plan_stopped(world):
    rejected_world(world)
    count = len(world.events())
    world.step({"a": world.snapshot("a", "rejected")})
    assert world.events()[count:] == []


def test_a_fixed_spec_stops_the_plan_with_inputs_changed_and_ci_reviews_it(world):
    rejected_world(world)
    world.commit(world.unit_files("a", spec=FIXED_SPEC), "fix the spec of a")
    world.push_main()
    count = len(world.events())
    world.step({"a": world.snapshot("a", "rejected")})
    got = state(world)
    assert got.status == "stopped" and got.stop_reason == "inputs_changed" and got.stop_unit == A
    assert kinds_after(world, count)[-3:] == [
        "plan.stopped",
        "plan.admitted",
        "plan.reviewed",
    ]  # reviewed in the same run
    assert got.review[A] == "READY"


# The step no longer asks `l4 retry` to move a rejected unit (it refuses one): see test_yolo_review_z2.py for the way
# out of `unit_rejected` (a corrected spec, a review, an activation, then the unit's own next run).


# --- #9: a review keeps the chain of runs of the active plan --------------------------------------------------------


def test_a_review_run_asks_for_the_next_run_while_a_plan_is_active(tmp_path):
    w = two_plans(tmp_path)
    assert w.step({"a": w.snapshot("a", None)}).start_next_run is True
    w.plan(plan_id="p2", batches=[{"id": "x", "units": [{"id": C}]}])
    step = w.step({"a": w.snapshot("a", "implementing")})
    assert w.kinds("p2")[-1] == "plan.reviewed" and step.allow == frozenset()
    assert step.start_next_run is True


def test_a_review_run_with_no_active_plan_asks_for_no_next_run(world):
    world.plan()
    assert world.step().start_next_run is False


# --- #13: the attempts of a plan start at its activation ------------------------------------------------------------


def test_restarts_before_the_plan_are_not_attempts_of_the_plan(world):
    text = world.plan(limits={"max_unit_attempts": 2})
    world.reviewed(text)
    world.restarts("a", 2)  # restarted twice before the activation
    world.seed(
        ev(
            "plan.activated",
            plan_digest=plan_digest(text),
            digests=world.digests(),
            limits={"max_unit_attempts": 2},
            by="alice",
            reason="go",
            attempt_base={A: 2, B: 0},
        )  # fmt: skip
    )
    step = world.step({"a": world.snapshot("a", None)})
    assert step.allow == frozenset({A}) and state(world).used.attempts == {A: 1}
    world.restarts("a", 3)  # one restart inside the plan: attempt 2, still within the limit
    assert world.step({"a": world.snapshot("a", "implementing")}).allow == frozenset({A})
    assert state(world).used.attempts == {A: 2}
    world.restarts("a", 4)  # attempt 3: over the limit of 2
    world.step({"a": world.snapshot("a", "implementing")})
    assert state(world).stop_reason == "limit_attempts"


def test_a_reactivation_keeps_the_first_attempt_base_of_a_unit():
    events = [
        ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a", reason="r", attempt_base={A: 2}),
        ev("plan.stopped", reason="inputs_changed", unit="plan"),
        ev("plan.activated", plan_digest="y", digests={}, limits={}, by="a", reason="r", attempt_base={A: 5, B: 1}),
    ]
    assert fold_plan("p1", events).attempt_base == {A: 2, B: 1}


# --- #16: a lease lost after a paid review does not pay for the review twice ----------------------------------------


def lose_the_lease_once(world, monkeypatch, concurrent):
    """The first append of `plan.reviewed` finds the ref moved: `concurrent` is what another writer put there."""
    from l4.yolo.store import PlanStore

    real = PlanStore.append
    seen = {"lost": False}

    def append(self, events, **kw):
        if not seen["lost"] and any(e.type == "plan.reviewed" for e in events):
            seen["lost"] = True
            real(self, concurrent(), expect=self.read().head)
            raise PlanMoved(self.ref)
        return real(self, events, **kw)

    monkeypatch.setattr(PlanStore, "append", append)


def test_a_lost_lease_after_a_paid_review_appends_the_same_facts_again(world, monkeypatch):
    world.plan()
    lose_the_lease_once(world, monkeypatch, lambda: [ev("unit.postcheck", unit=A, status="pass")])
    world.step()
    assert len(world.judge.requests) == 3  # two units and their batch: asked once
    assert world.kinds() == ["unit.postcheck", "plan.admitted", "plan.reviewed"]


def test_a_review_made_stale_by_another_review_is_dropped_without_a_second_judge_call(world, monkeypatch):
    world.plan()
    text = (world.repo / ".l4/plans/p1.json").read_text()

    def another_review():
        digest = plan_digest(text)
        units = {u: {"verdict": "READY", "digest": d, "findings": []} for u, d in world.digests().items()}
        return [
            ev("plan.admitted", plan_digest=digest, order=[A, B], merge="auto"),
            ev(
                "plan.reviewed",
                plan_digest=digest,
                prompt_version=PROMPT_VERSION,
                units=units,
                batches={"b1": {"verdict": "READY", "findings": []}},
            ),
        ]

    lose_the_lease_once(world, monkeypatch, another_review)
    world.step()
    assert len(world.judge.requests) == 3  # the paid review was dropped, and the other one stands: no second call
    assert world.kinds() == ["plan.admitted", "plan.reviewed"]
