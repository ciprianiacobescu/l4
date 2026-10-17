"""The plan step of an active plan, one branch of design D10 at a time (L4-YOLO-009..015): dispatch in dependency order,
post-merge checks and integration, batches, completion, stops, waits, limits and a ref that moves."""

import json
import stat
from datetime import UTC, datetime

import pytest

from l4.exitcodes import ExitCode
from l4.orchestrator import UnitRunResult
from l4.outcome import UnitOutcome
from l4.state.fold import LastVerdict
from l4.yolo.model import PlanMoved, ProfileResult
from l4.yolo.state import fold_plan
from l4.yolo.store import PlanStore

from .yolo_cycle_world import CycleWorld, ev, unit_id
from .yolo_review_world import make_cfg

A, B = unit_id("a"), unit_id("b")


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def active(world, **plan):
    world.plan(**plan)
    world.activate()


def kinds(world):
    return world.kinds()


def state(world):
    return fold_plan("p1", world.events())


def last(world, kind):
    return [e for e in world.events() if e.type == kind][-1].data


# --- dispatch and order (L4-YOLO-010) --------------------------------------------------------------


def test_the_first_eligible_unit_is_dispatched_and_the_next_run_is_started(world):
    active(world)
    step = world.step()
    assert step.allow == frozenset({A}) and step.start_next_run is True
    assert kinds(world)[-2:] == ["plan.charged", "unit.dispatched"]
    assert last(world, "unit.dispatched") == {"unit": A, "run": "r-20261014T1000Z-0001"}
    assert state(world).current == A
    assert step.refusals[B] == "waits for openspec:a (not integrated) (plan p1)"  # SCN-YOLO-21's text for `l4 run`


def test_scn_yolo_20_b_starts_only_after_a_is_integrated(world):
    active(world)
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    merged = {"a": world.snapshot("a", "merged")}
    step = world.step(merged)  # a is merged but its check has not run: the step runs the check, not b
    assert step.allow == frozenset() and step.start_next_run is True
    assert world.profile_calls and world.profile_calls[0][1] == "all"
    assert kinds(world)[-4:] == ["unit.merged", "unit.postcheck", "unit.integrated", "plan.charged"]
    assert not world.git.run("branch", "-r", "--list", "origin/l4/openspec/b").stdout.strip()
    step = world.step(merged)  # a later run, after unit.integrated{a}
    assert step.allow == frozenset({B}) and last(world, "unit.dispatched")["unit"] == B


def test_a_receipt_is_written_once_for_an_integrated_unit(world):
    active(world)
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    world.step({"a": world.snapshot("a", "merged")})
    files = world.store().read().files
    receipt = json.loads(files["receipts/openspec-a.json"])
    assert receipt["receipt_id"] == "p1/openspec:a/1" and receipt["unit_id"] == A and receipt["plan_id"] == "p1"
    assert receipt["target"] == "main" and receipt["postcheck"] == "pass" and receipt["spec_digest"]
    assert receipt["integrated_revision"] == state(world).integrated[A]


def test_scn_yolo_22_a_human_merge_plan_orders_without_merging(world):
    world.plan(merge="human")
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    tip = world.tip()
    waiting = world.step({"a": world.in_review("a", "f" * 40)})  # a person has not merged yet: nothing to do
    assert waiting.allow == frozenset({A}) and waiting.start_next_run is False
    assert kinds(world)[-1] == "unit.dispatched"
    world.step({"a": world.snapshot("a", "merged")})  # the person merged the PR of a
    assert state(world).integrated.keys() == {A}
    assert world.tip() == tip  # the harness pushed nothing to the target
    step = world.step({"a": world.snapshot("a", "merged")})
    assert step.allow == frozenset({B})


def test_a_unit_that_has_nothing_to_run_is_allowed_but_not_charged(world):
    active(world)
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    head = world.unit_branch("a")
    n = len(world.events())
    step = world.step({"a": world.in_review("a", head, last_verdict=LastVerdict(round=1, verdict="FAIL", findings=1))})
    # merge: auto, but the verdict is not a PASS: not ready, logged, no record
    assert step.allow == frozenset({A}) and step.start_next_run is False and len(world.events()) == n


# --- the guarded merge (L4-YOLO-008) ---------------------------------------------------------------


def merge_ready(world):
    active(world)
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    head = world.unit_branch("a")
    world.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    return head, {"a": world.in_review("a", head)}


def test_scn_yolo_14_and_24_a_verified_unit_is_merged_integrated_and_the_next_run_is_started(world):
    world.cfg = make_cfg(  # SCN-YOLO-14 is the fast-forward: the squash default has its own tests (SCN-YOLO-76)
        forge={"type": "local", "base_branch": "main", "merge_policy": "auto"},
        yolo={"merge": {"method": "fast-forward"}},
    )
    head, snaps = merge_ready(world)
    step = world.step(snaps)
    assert world.tip() == head
    assert kinds(world)[-6:] == [
        "unit.merge_requested",
        "unit.merged",
        "unit.branch_deleted",  # the merged branch goes (L4-YOLO-033, the default)
        "unit.postcheck",
        "unit.integrated",
        "plan.charged",
    ]
    assert last(world, "unit.merged") == {
        "unit": A, "head": head, "pr": 1, "merge_commit": head, "method": "fast-forward", "raced": False,
    }  # fmt: skip
    assert last(world, "unit.integrated") == {"unit": A, "revision": head}
    assert world.profile_calls == [(head, "all")]
    assert step.start_next_run is True and step.allow == frozenset()
    assert state(world).integrated[A] == head


def test_scn_yolo_15_a_target_that_moved_is_not_merged_and_the_unit_is_verified_again(world, monkeypatch):
    head, snaps = merge_ready(world)
    moved = world.person_moves_target()
    calls = []

    def retry(app, cfg, git, provider, ref, **kw):
        calls.append((ref.id, kw))
        outcome = UnitOutcome(unit=ref.id, phase_before="in_review", phase_after="verifying")
        return UnitRunResult(outcome, ExitCode.OK)

    monkeypatch.setattr("l4.state.retry.retry_unit", retry)
    step = world.step(snaps)
    assert world.tip() == moved  # nothing was pushed
    assert calls[0][0] == A and "the target moved; verify again (plan p1)" in calls[0][1]["reason"]
    assert last(world, "unit.merge_refused")["reason"] == "stale"
    assert state(world).status == "active" and step.start_next_run is True


def test_a_second_stale_merge_stops_the_plan(world, monkeypatch):
    head, snaps = merge_ready(world)
    world.seed(ev("unit.merge_refused", unit=A, reason="stale"))
    world.person_moves_target()
    monkeypatch.setattr("l4.state.retry.retry_unit", lambda *a, **k: pytest.fail("no second retry"))
    world.step(snaps)
    got = state(world)
    assert got.status == "stopped" and got.stop_reason == "merge_refused" and got.stop_unit == A


def test_a_new_attempt_gets_its_own_stale_retry(world, monkeypatch):  # review #1 (also affected), D8
    head, snaps = merge_ready(world)
    world.seed(
        ev("plan.charged", unit=A, attempt=1, cost_usd=0.0, runs=1), ev("unit.merge_refused", unit=A, reason="stale")
    )
    world.restarts("a", 1)  # `l4 restart`: the unit is on attempt 2
    world.step({"a": world.snapshot("a", "implementing")})  # its first dispatch in attempt 2
    assert state(world).stale_merges == {} and state(world).used.attempts == {A: 2}
    world.person_moves_target()
    calls = []

    def retry(app, cfg, git, provider, ref, **kw):
        calls.append(ref.id)
        return UnitRunResult(UnitOutcome(unit=ref.id, phase_before="in_review", phase_after="verifying"), ExitCode.OK)

    monkeypatch.setattr("l4.state.retry.retry_unit", retry)
    step = world.step(snaps)
    assert calls == [A] and state(world).status == "active" and step.start_next_run is True


def test_scn_yolo_16_a_protected_target_stops_the_plan_with_the_forges_message(world):
    world.cfg = make_cfg(  # the push of the fast-forward meets the hook; a squash goes through the forge's merge call
        forge={"type": "local", "base_branch": "main", "merge_policy": "auto"},
        yolo={"merge": {"method": "fast-forward"}},
    )
    head, snaps = merge_ready(world)
    hook = world.origin / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\nwhile read old new ref; do\n"
        "  if [ \"$ref\" = refs/heads/main ]; then echo 'GH006: Protected branch update failed' >&2; exit 1; fi\n"
        "done\n"
    )
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    before = world.tip()
    step = world.step(snaps)
    got = state(world)
    assert got.status == "stopped" and got.stop_reason == "merge_refused"
    assert "Protected branch update failed" in got.stop_detail
    assert world.tip() == before and step.start_next_run is False
    assert world.step(snaps).allow == frozenset()  # a stopped plan dispatches and merges nothing


def test_the_merge_policy_must_still_be_auto(world):
    head, snaps = merge_ready(world)
    world.cfg = world.cfg.model_copy(update={"forge": world.cfg.forge.model_copy(update={"merge_policy": "human"})})
    before = world.tip()
    world.step(snaps)
    assert world.tip() == before and state(world).stop_reason == "merge_refused"


# --- post-merge checks, batches, completion --------------------------------------------------------


def test_scn_yolo_18_a_failing_post_merge_check_stops_the_plan(world):
    active(world)
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    world.profile_result = lambda revision, profile: ProfileResult("fail", revision, profile, detail="gate test failed")
    step = world.step({"a": world.snapshot("a", "merged")})
    got = state(world)
    assert got.status == "stopped" and got.stop_reason == "postcheck_failed" and got.stop_unit == A
    assert last(world, "unit.postcheck")["status"] == "fail" and A not in got.integrated
    assert step.start_next_run is False
    report = world.store().read().files["report.md"]
    assert "postcheck_failed" in report and "Promotion to amaster was not performed" in report
    assert (world.repo / ".l4-out" / "yolo" / "p1.md").read_text() == report
    after = world.step({"a": world.snapshot("a", "merged")})  # the successor is not dispatched
    assert after.allow == frozenset() and kinds(world)[-1] == "plan.stopped"
    assert after.refusals[B] == "is held by plan p1 (stopped)"


def test_an_unknown_profile_is_an_error_and_stops_the_plan(world):
    active(world)
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    world.profile_result = lambda revision, profile: ProfileResult("error", revision, profile, detail="no gate")
    world.step({"a": world.snapshot("a", "merged")})
    assert state(world).stop_reason == "postcheck_failed"


def two_batches(world):
    return [
        {"id": "b1", "acceptance_profile": "smoke", "units": [{"id": A}]},
        {"id": "b2", "depends_on": ["b1"], "units": [{"id": B}]},
    ]


def test_scn_yolo_23_a_failed_batch_check_holds_the_next_batch(world):
    world.plan(batches=two_batches(world), deps={})
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("unit.integrated", unit=A, revision="r1"))
    world.profile_result = lambda revision, profile: ProfileResult("fail", revision, profile, detail="smoke failed")
    step = world.step({"a": world.snapshot("a", "merged")})
    got = state(world)
    assert got.status == "stopped" and got.stop_reason == "batch_failed" and "b1" in got.failed_batches
    assert world.profile_calls[0][1] == "smoke"
    assert kinds(world)[-1] == "plan.stopped" and step.allow == frozenset()


def test_a_passing_batch_check_is_recorded_and_the_next_batch_may_start(world):
    world.plan(batches=two_batches(world), deps={})
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("unit.integrated", unit=A, revision="r1"))
    step = world.step({"a": world.snapshot("a", "merged")})
    assert last(world, "batch.accepted")["batch"] == "b1" and step.start_next_run is True
    step = world.step({"a": world.snapshot("a", "merged")})
    assert step.allow == frozenset({B})


def test_a_batch_without_a_profile_is_accepted_without_a_run(world):
    active(world)
    world.seed(ev("unit.integrated", unit=A, revision="r1"), ev("unit.integrated", unit=B, revision="r2"))
    world.step({"a": world.snapshot("a", "merged"), "b": world.snapshot("b", "merged")})
    assert last(world, "batch.accepted")["profile"] == "none" and world.profile_calls == []


def test_scn_yolo_28_the_completed_plan_hands_off(world):
    active(world)
    world.seed(
        ev("unit.integrated", unit=A, revision="r1"), ev("unit.integrated", unit=B, revision="r2"),
        ev("batch.accepted", batch="b1", revision="r2", profile="none"),
    )  # fmt: skip
    tip = world.tip()
    merged = {"a": world.snapshot("a", "merged"), "b": world.snapshot("b", "merged")}
    step = world.step(merged)
    assert state(world).status == "completed" and step.start_next_run is False
    assert last(world, "plan.completed")["revision"] == tip
    report = world.store().read().files["report.md"]
    assert f"main at {tip}" in report and "Promotion to amaster was not performed" in report
    assert A in report and B in report and "accepted" in report
    assert (world.repo / ".l4-out/yolo/p1.md").read_text() == report
    assert world.tip() == tip  # the target is unchanged
    assert world.step(merged).allow == frozenset({A, B})  # a final plan holds nothing


# --- stops (L4-YOLO-013) ---------------------------------------------------------------------------


@pytest.mark.parametrize("phase", ["halted", "escalated", "abandoned", "rejected"])
def test_the_current_unit_stopping_stops_the_plan(world, phase):
    active(world)
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    world.step({"a": world.snapshot("a", phase, halt_detail="max attempts")})
    got = state(world)
    assert (got.status, got.stop_reason, got.stop_unit) == ("stopped", f"unit_{phase}", A)
    assert got.stop_detail == "max attempts"
    assert "report.md" in world.store().read().files


def test_scn_yolo_25_a_spec_push_to_the_current_unit_stops_the_plan(world):
    active(world)
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    changed = "## ADDED Requirements\n### Requirement: A\nA SHALL do something else.\n"
    world.unit_branch("a", {"openspec/changes/a/specs/x/spec.md": changed})
    step = world.step({"a": world.snapshot("a", "implementing")})
    got = state(world)
    assert (got.status, got.stop_reason, got.stop_unit) == ("stopped", "inputs_changed", A)
    assert (
        step.allow == frozenset() and kinds(world)[-1] == "plan.stopped" and kinds(world).count("unit.dispatched") == 1
    )


def test_the_harnesss_own_writes_to_the_unit_folder_are_not_an_amendment(world):
    active(world)
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    world.unit_branch("a", {
        "openspec/changes/a/tasks.md": "- [x] 1.1 do it\n",
        "openspec/changes/a/verification.md": "PASS\n",
        "openspec/changes/a/.l4/ledger/x.jsonl": "{}\n",
    })  # fmt: skip
    assert world.step({"a": world.snapshot("a", "implementing")}).allow == frozenset({A})
    assert state(world).status == "active"


def test_a_changed_spec_of_a_unit_that_has_not_started_stops_the_plan_too(world):
    active(world)
    world.commit({"openspec/changes/b/proposal.md": "Why: something else.\n"})
    world.push_main()
    world.step()
    got = state(world)
    assert (got.stop_reason, got.stop_unit) == ("inputs_changed", B)


def test_an_integrated_units_moved_folder_is_not_an_amendment(world):
    active(world)
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("unit.integrated", unit=A, revision="r1"))
    world.git.run("rm", "-r", "-q", "openspec/changes/a")  # the OpenSpec archive moved the folder
    world.git.run("commit", "-q", "-m", "archive a")
    world.push_main()
    world.step({"a": world.snapshot("a", "archived")})
    assert state(world).status == "active"


def test_a_missing_target_stops_the_plan(tmp_path):
    world = CycleWorld(tmp_path, base="staging")
    world.plan()
    world.activate()
    world.git.run("push", "origin", "--delete", "staging")
    world.step()
    assert state(world).stop_reason == "target_missing"


@pytest.mark.parametrize(
    ("limits", "restarts", "cost", "reason"),
    [
        ({"max_unit_attempts": 2}, 2, 0.0, "limit_attempts"),  # SCN-YOLO-27: restarted twice = a third attempt
        ({"max_cost_usd": 5}, 0, 5.0, "limit_cost"),
    ],
)
def test_a_limit_stops_the_plan(world, limits, restarts, cost, reason):
    world.plan(limits=limits)
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    world.restarts("a", restarts)
    world.step({"a": world.snapshot("a", "implementing", cost_usd=cost)})
    assert state(world).stop_reason == reason


def test_scn_yolo_27_one_restart_is_within_two_attempts_and_a_resume_extends(world):
    world.plan(limits={"max_unit_attempts": 2})
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    world.restarts("a", 1)
    assert world.step({"a": world.snapshot("a", "implementing")}).allow == frozenset({A})
    world.restarts("a", 2)
    world.step({"a": world.snapshot("a", "implementing")})
    assert state(world).stop_reason == "limit_attempts" and state(world).stop_unit == A
    world.seed(ev("plan.resumed", by="alice", reason="ok", extend={"attempts": 1}))
    assert world.step({"a": world.snapshot("a", "implementing")}).allow == frozenset({A})


def test_scn_yolo_31_a_restart_keeps_the_cost_and_the_attempts_of_the_plan(world):  # review #1, R1
    world.plan(limits={"max_unit_attempts": 3, "max_cost_usd": 100})
    world.activate()
    world.step({"a": world.snapshot("a", None, cost_usd=0.0)})  # attempt 1
    assert last(world, "plan.charged") == {"unit": A, "attempt": 1, "cost_usd": 0.0, "runs": 1}
    world.step({"a": world.snapshot("a", "implementing", cost_usd=2.0)})  # still attempt 1: it costs $2 so far
    assert last(world, "plan.charged") == {"unit": A, "attempt": 1, "cost_usd": 2.0, "runs": 2}
    world.restarts("a", 1)  # `l4 restart`: the unit's ledger starts again at zero
    world.step({"a": world.snapshot("a", "implementing", cost_usd=1.5)})
    assert last(world, "plan.charged") == {"unit": A, "attempt": 2, "cost_usd": 1.5, "runs": 1}
    folded = state(world)
    assert folded.used.cost_usd == 3.5 and folded.used.attempts == {A: 2}
    world.restarts("a", 2)
    world.step({"a": world.snapshot("a", "implementing", cost_usd=0.5)})
    assert state(world).used.cost_usd == 4.0 and state(world).used.attempts == {A: 3}
    world.restarts("a", 3)  # a fourth attempt: past max_unit_attempts 3, stopped before another run is dispatched
    runs = len([e for e in world.events() if e.type == "unit.dispatched"])
    world.step({"a": world.snapshot("a", "implementing", cost_usd=0.0)})
    assert state(world).stop_reason == "limit_attempts" and state(world).stop_unit == A
    assert len([e for e in world.events() if e.type == "unit.dispatched"]) == runs


def test_the_cost_of_every_attempt_counts_against_the_cost_limit(world):  # review #1: a restart zeroes the unit's cost
    world.plan(limits={"max_cost_usd": 5, "max_unit_attempts": 9})
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("plan.charged", unit=A, attempt=1, cost_usd=3.0, runs=1))
    world.restarts("a", 1)
    world.step({"a": world.snapshot("a", "implementing", cost_usd=2.0)})  # 3.0 + 2.0 = 5.0: the limit
    assert state(world).stop_reason == "limit_cost"


def test_the_run_limit_stops_at_the_limit_and_not_one_run_after(world):  # R3: used >= limit
    world.plan(limits={"max_runs": 2})
    world.activate()
    world.seed(
        ev("unit.dispatched", unit=A, run="r0"),
        ev("unit.dispatched", unit=A, run="r1"),
        ev("plan.charged", unit=A, attempt=1, cost_usd=0.0, runs=2),
    )
    assert state(world).status == "active"
    world.step({"a": world.snapshot("a", "implementing")})  # a third dispatch: refused
    assert state(world).stop_reason == "limit_runs"


def test_the_deadline_stops_the_plan_and_a_resume_can_move_it(world):
    world.plan(limits={"deadline": "2026-10-20T18:00:00Z"})
    world.activate()
    late = lambda: datetime(2026, 10, 21, tzinfo=UTC)  # noqa: E731
    world.step(now=late)
    assert state(world).stop_reason == "limit_deadline"
    world.seed(ev("plan.resumed", by="alice", reason="more", extend={"deadline": "2026-10-30T00:00:00Z"}))
    assert world.step(now=late).allow == frozenset({A})


# --- waits -----------------------------------------------------------------------------------------


def test_a_unit_that_waits_for_a_person_makes_the_plan_wait_once(world):
    active(world)
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    step = world.step({"a": world.snapshot("a", "awaiting_human")})
    got = state(world)
    assert got.status == "waiting" and got.wait_reason == "unit_awaiting_human"
    assert step.start_next_run is False
    n = len(world.events())
    again = world.step({"a": world.snapshot("a", "awaiting_human")})  # a waiting plan does nothing more
    assert len(world.events()) == n and again.refusals[A] == "is held by plan p1 (waiting)"


# --- the ref moves ---------------------------------------------------------------------------------


def test_a_moved_ref_is_read_again_once(world, monkeypatch):
    active(world)
    original = PlanStore.append
    seen = []

    def flaky(self, events, *, files=None, expect):
        if not seen:
            seen.append(1)
            raise PlanMoved("moved")
        return original(self, events, files=files, expect=expect)

    monkeypatch.setattr(PlanStore, "append", flaky)
    step = world.step()
    assert step.allow == frozenset({A}) and kinds(world)[-2:] == ["plan.charged", "unit.dispatched"]


def test_a_ref_that_moves_twice_ends_the_step_for_this_run(world, monkeypatch):
    active(world)
    n = len(world.events())

    def moved(self, events, *, files=None, expect):
        raise PlanMoved("moved")

    monkeypatch.setattr(PlanStore, "append", moved)
    step = world.step()
    assert step.allow == frozenset() and step.start_next_run is False and len(world.events()) == n
    assert any("moved twice" in a for a in step.actions)


def test_one_plan_step_per_run_a_review_of_another_plan_dispatches_nothing(tmp_path):
    world = CycleWorld(tmp_path, units=("a", "b", "c"))
    world.plan(deps={}, batches=[{"id": "b1", "units": [{"id": A}, {"id": B, "depends_on": [A]}]}])
    world.activate()
    world.plan(plan_id="p2", deps={}, batches=[{"id": "b1", "units": [{"id": unit_id("c")}]}])
    step = world.step()
    assert world.kinds("p2") == ["plan.admitted", "plan.reviewed"]
    assert step.allow == frozenset() and step.start_next_run is True  # the active plan goes on in the next run (#9)
    assert "unit.dispatched" not in world.kinds()  # the active plan waits for the next run
    assert world.step().allow == frozenset({A})  # nothing left to review: the active plan's step


# --- accepted review findings travel with the unit (L4-YOLO-028) ---------------------------------------


def _accepted(subject, text, reason="the spec is silent on it; use a plain path"):
    return {
        "findings": [{"criterion": "testability", "severity": "major", "text": text}],
        "reason": reason,
        "by": "alice",
        "actor": "person",
    }


def _reactivate_with(world, accepted):
    text = (world.repo / ".l4" / "plans" / "p1.json").read_text(encoding="utf-8")
    from l4.yolo.digest import plan_digest

    world.seed(
        ev("plan.activated", plan_digest=plan_digest(text), digests=world.digests(), limits={}, by="alice",
           reason="go", accepted=accepted)
    )  # fmt: skip


def test_a_dispatch_carries_the_accepted_items_of_the_unit_and_its_batch(world):
    from l4.yolo.findings import finding_id

    active(world)
    _reactivate_with(
        world,
        {A: _accepted(A, "no example"), "batch:b1": _accepted("batch:b1", "order unclear"), B: _accepted(B, "other")},
    )
    step = world.step()
    assert step.allow == frozenset({A})
    items = {i["subject"]: i for i in step.accepted[A]}
    assert set(items) == {A, "batch:b1"}  # B's own item does not travel with A
    one = items[A]
    assert (one["reason"], one["by"], one["actor"]) == ("the spec is silent on it; use a plain path", "alice", "person")
    assert one["findings"] == [
        {"id": finding_id(A, f), **f} for f in _accepted(A, "no example")["findings"]
    ]  # the id is the finding's own


def test_a_unit_with_no_accepted_item_carries_nothing(world):
    active(world)
    _reactivate_with(world, {B: _accepted(B, "other")})
    step = world.step()
    assert step.allow == frozenset({A}) and A not in step.accepted


def test_a_later_run_of_the_current_unit_and_a_preview_carry_the_same_items(world):
    active(world)
    _reactivate_with(world, {A: _accepted(A, "no example")})
    first = world.step()
    again = world.step({"a": world.snapshot("a", "implementing")})  # the current unit's next run
    assert again.allow == frozenset({A}) and again.accepted == first.accepted != {}
    preview = world.step({"a": world.snapshot("a", "implementing")}, read_only=True)
    assert preview.allow == frozenset({A}) and preview.accepted == first.accepted
