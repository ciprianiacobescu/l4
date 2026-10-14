"""The plan step and the commands on the shared rules of the fix wave (design R1..R12): the frozen plan file, the
request to merge recorded before the push, every merged unit post-checked, plans that hold their units, a waiting plan
that goes on by itself, and the judge's failures that record nothing."""

import json

import pytest

from l4.availability.errors import RoleUnavailable
from l4.yolo.commands import Extend, resume_blocker
from l4.yolo.cycle import plan_holds, review_batches, unreadable_plan_files
from l4.yolo.model import ReviewResult, Verdict
from l4.yolo.plans import plan_files
from l4.yolo.readiness import JudgeFailed
from l4.yolo.state import fold_plan

from .yolo_cycle_world import CycleWorld, ev, unit_id

A, B = unit_id("a"), unit_id("b")


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def state(world):
    return fold_plan("p1", world.events())


def last(world, kind):
    return [e for e in world.events() if e.type == kind][-1].data


def merge_ready(world, **plan):
    world.plan(**plan)
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    head = world.unit_branch("a")
    world.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    return head, {"a": world.in_review("a", head)}


# --- R2: the activated plan is frozen (review #2) ---------------------------------------------------


def test_scn_yolo_32_an_edited_plan_file_stops_an_active_plan_and_is_reviewed_not_run(world):
    text = world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    edited = json.loads(text)
    edited["limits"] = {"max_runs": 99}
    world.commit({".l4/plans/p1.json": json.dumps(edited, indent=2) + "\n"}, "edit the active plan")
    world.push_main()
    activated = state(world).activated_digest
    step = world.step({"a": world.snapshot("a", "implementing")})
    got = state(world)
    assert (got.status, got.stop_reason, got.stop_unit) == ("stopped", "inputs_changed", "plan")
    assert step.allow == frozenset() and step.start_next_run is False
    world.step({"a": world.snapshot("a", "implementing")})  # the edited file is reviewed, never run
    assert world.kinds()[-2:] == ["plan.admitted", "plan.reviewed"]
    after = state(world)
    assert after.status == "stopped" and after.activated_digest == activated and after.review_plan_digest != activated


def test_a_plan_file_that_is_no_longer_a_plan_stops_the_active_plan(world):
    world.plan()
    world.activate()
    world.commit({".l4/plans/p1.json": '{"schema": "l4/delivery-plan@1", "plan_id": "p1", "parallel": true}\n'})
    world.push_main()
    step = world.step({"a": world.snapshot("a", "implementing")})
    got = state(world)
    assert (got.status, got.stop_reason, got.stop_unit) == ("stopped", "inputs_changed", "plan")
    assert step.allow == frozenset()


# --- R5: the request to merge is recorded before the push -------------------------------------------


def test_the_request_to_merge_is_recorded_with_the_lease_before_the_push(world, monkeypatch):
    head, snaps = merge_ready(world)
    seen = {}
    import l4.yolo.cycle as cycle

    real = cycle.merge_guarded

    def watching(*args, before_push=None, **kw):
        def ask(to_be):
            seen["tip_at_request"] = world.tip()
            answer = before_push(to_be)
            seen["recorded"] = "unit.merge_requested" in world.kinds()
            return answer

        return real(*args, before_push=ask, **kw)

    monkeypatch.setattr(cycle, "merge_guarded", watching)
    world.step(snaps)
    assert seen["recorded"] is True and seen["tip_at_request"] != head and world.tip() == head
    request = [e.data for e in world.events() if e.type == "unit.merge_requested"][0]
    assert request["unit"] == A and request["head"] == head and request["pr"] == 1 and request["target_before"]


@pytest.mark.parametrize("how", ["plan.cancelled", "plan.stopped"])
def test_a_plan_cancelled_or_stopped_before_the_push_does_not_merge(world, monkeypatch, how):
    head, snaps = merge_ready(world)
    import l4.yolo.cycle as cycle

    real = cycle.merge_guarded

    def racing(*args, before_push=None, **kw):
        def ask(to_be):
            world.seed(ev(how, by="bob", reason="stop"))  # a person acts between the step's read and the push
            return before_push(to_be)

        return real(*args, before_push=ask, **kw)

    monkeypatch.setattr(cycle, "merge_guarded", racing)
    tip = world.tip()
    step = world.step(snaps)
    assert world.tip() == tip and step.allow == frozenset() and step.start_next_run is False
    assert "unit.merge_requested" not in world.kinds() and "unit.merged" not in world.kinds()
    assert state(world).status in ("cancelled", "stopped")


# --- R10: every merged unit is post-checked (review #13) --------------------------------------------


def test_a_unit_a_person_merged_while_it_was_not_current_is_post_checked_first(tmp_path):
    world = CycleWorld(tmp_path, units=("a", "b"))
    world.plan(merge="human", deps={})
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))  # a is the current unit, in review
    step = world.step({"a": world.in_review("a", "f" * 40), "b": world.snapshot("b", "merged")})
    assert world.kinds()[-4:] == ["unit.merged", "unit.postcheck", "unit.integrated", "plan.charged"]
    assert last(world, "unit.integrated")["unit"] == B and last(world, "unit.merged")["by"] == "person"
    got = state(world)
    assert got.current == A and set(got.integrated) == {B}
    assert step.start_next_run is True and step.allow == frozenset()


def test_a_merged_unit_the_step_pushed_is_post_checked_before_anything_is_dispatched(world):
    active_plan = world.plan()
    del active_plan
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("unit.merged", unit=A, head="h", merge_commit="h"))
    step = world.step({"a": world.snapshot("a", "in_review")})  # the push happened, the profile did not run
    assert last(world, "unit.integrated")["unit"] == A and step.allow == frozenset()


# --- R8: holding (review #8, #20) -------------------------------------------------------------------


def test_an_invalid_plan_file_holds_the_units_it_names_and_a_non_json_file_is_reported(world):
    broken = {"schema": "l4/delivery-plan@1", "plan_id": "p2", "target": "main", "merge": "human", "parallel": True,
              "batches": [{"id": "b1", "units": [{"id": A}]}]}  # fmt: skip
    world.commit({".l4/plans/p2.json": json.dumps(broken), ".l4/plans/p3.json": "not json at all"})
    world.push_main()
    files = plan_files(world.repo)
    states = {f.plan_id: fold_plan(f.plan_id, []) for f in files}
    holds = plan_holds(files, states, {A: None, B: None}, "main")
    assert set(holds) == {A} and holds[A].reason == "held by plan p2 (invalid)"
    (note,) = unreadable_plan_files(files)
    assert ".l4/plans/p3.json" in note and "holds no unit" in note
    step = world.step()
    assert step.allow == frozenset({B}) and step.refusals[A] == "is held by plan p2 (invalid)"


def test_a_unit_that_another_plan_lists_is_refused_at_admission_of_the_second_plan(tmp_path):
    world = CycleWorld(tmp_path, units=("a", "b", "c"))
    world.plan(deps={}, batches=[{"id": "b1", "units": [{"id": A}]}])
    world.plan(plan_id="p2", deps={}, batches=[{"id": "b1", "units": [{"id": A}, {"id": unit_id("c")}]}])
    world.step()  # p1 is reviewed
    world.step()  # p2 is refused: A is p1's
    refused = [e.data for e in world.events("p2") if e.type == "plan.refused"][-1]
    assert [f["code"] for f in refused["findings"]] == ["held_by_other_plan"]
    assert "p1" in refused["findings"][0]["text"] and "plan.reviewed" in world.kinds("p1")


# --- R11: the review, unit_missing, batches ---------------------------------------------------------


def test_the_ci_review_records_a_batches_entry_for_every_batch_of_several_units(world):
    world.plan()
    world.step()
    assert set(last(world, "plan.reviewed")["batches"]) == {"b1"}


def test_a_batch_the_judge_could_not_read_is_recorded_as_blocked(world):
    world.plan()
    from l4.yolo.plans import plan_files as read

    (file,) = read(world.repo)
    done = review_batches(file.plan, ReviewResult({A: Verdict("READY")}, {}))
    assert done["b1"].verdict == "BLOCKED" and "not reviewed" in done["b1"].findings[0]["text"]


def test_unit_missing_blocks_a_resume_until_the_unit_is_back(world):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("plan.stopped", reason="unit_missing", unit=A))
    got = state(world)
    blocker = resume_blocker("p1", got, world.events(), None, {B: None}, Extend())
    assert blocker is not None and "not among the units of the target" in blocker.message
    assert resume_blocker("p1", got, world.events(), None, {A: "implementing", B: None}, Extend()) is None


# --- R9: a judge that fails records nothing ---------------------------------------------------------


def test_a_judge_error_records_nothing_and_starts_no_next_run(world, monkeypatch):
    world.plan()

    def failing(*args, **kw):
        raise JudgeFailed("the judge timed out")

    monkeypatch.setattr("l4.yolo.cycle.review_plan_costed", failing)
    head = world.store().read().head
    step = world.step()
    assert world.store().read().head == head and step.start_next_run is False
    assert any("no judge could run" in a for a in step.actions)
    assert issubclass(JudgeFailed, RoleUnavailable)


# --- a waiting plan goes on by itself ---------------------------------------------------------------


def waiting_plan(world):
    world.plan()
    world.activate()
    world.seed(
        ev("unit.dispatched", unit=A, run="r0"),
        ev("plan.waiting", reason="unit_awaiting_human", unit=A, detail="open"),
    )
    assert state(world).status == "waiting"


def test_an_answered_question_wakes_a_waiting_plan_and_the_same_step_dispatches(world, monkeypatch):
    waiting_plan(world)
    asleep = world.step({"a": world.snapshot("a", "awaiting_human")})  # the question is still open: nothing happens
    assert state(world).status == "waiting" and "plan.resumed" not in world.kinds()
    assert asleep.allow == frozenset() and asleep.refusals[A] == "is held by plan p1 (waiting)"
    assert asleep.start_next_run is False
    monkeypatch.setattr("l4.planner.answers_unblock", lambda questions, tasks: ("Q-001",))  # the person answered
    step = world.step({"a": world.snapshot("a", "awaiting_human")})
    resumed = last(world, "plan.resumed")
    assert resumed["by"] == "harness" and resumed["reason"] == "the cause is gone: openspec:a is awaiting_human"
    assert state(world).status == "active"
    assert world.kinds()[-3:] == ["plan.resumed", "unit.dispatched", "plan.charged"]
    assert step.allow == frozenset({A}) and step.start_next_run is True


def test_a_unit_that_is_no_longer_waiting_wakes_the_plan_and_a_merge_goes_on(world):
    waiting_plan(world)
    head = world.unit_branch("a")
    world.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    step = world.step({"a": world.in_review("a", head)})
    assert last(world, "plan.resumed")["reason"] == "the cause is gone: openspec:a is in_review"
    assert world.tip() == head and last(world, "unit.integrated")["unit"] == A
    assert step.start_next_run is True


def test_the_unit_of_a_waiting_plan_whose_cause_is_gone_may_run_with_l4_run_unit(world):
    waiting_plan(world)
    step = world.step({"a": world.snapshot("a", "implementing")}, read_only=True)
    assert step.allow == frozenset({A})
    assert state(world).status == "waiting"  # a read-only step records nothing


# --- the report and the status on the per-attempt figures (R1) --------------------------------------


def test_the_report_shows_what_every_attempt_of_a_unit_cost_and_skips_the_review_key(world):
    from l4.yolo.report import render_report

    world.plan()
    (file,) = plan_files(world.repo)
    events = [
        ev("plan.charged", unit=A, attempt=1, cost_usd=2.0, runs=2),
        ev("plan.charged", unit=A, attempt=2, cost_usd=1.5, runs=1),
        ev("plan.charged", unit=A, attempt=2, cost_usd=1.5, runs=1),  # the same charge twice counts once
        ev("plan.charged", unit="plan:review", attempt=0, cost_usd=0.5, runs=0),
    ]
    text = render_report(
        repository="r", plan=file.plan, state=fold_plan("p1", events), events=events, target_revision="abc",
        units={}, generated_at="t",
    )  # fmt: skip
    assert "- Usage: $3.50, 3 run(s), 2 attempt(s)" in text
    assert "- Cost: $4.00" in text and "- Of which the readiness review: $0.50" in text
    assert "plan:review" not in text.split("## Usage")[0]
