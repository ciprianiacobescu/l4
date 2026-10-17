"""Review round 3, area Z2 (the plan step): a merge that is not ready is a wait with its reason on record (M3), the way
out of `unit_rejected` (M2), the plan files of the target (L4), and the charge of a named run (L6a)."""

from datetime import UTC, datetime

import pytest

import l4.yolo.cycle as cycle
from l4.forge.base import PullRequest
from l4.state.fold import fold
from l4.state.ledger import LedgerEvent
from l4.state.lifecycle import TRANSITIONS, Phase
from l4.state.retry import refuse
from l4.yolo.commands import Extend, resume_blocker
from l4.yolo.digest import plan_digest
from l4.yolo.merge import HEAD_LAG_READS, HEAD_LAG_WAIT_S, merge_guarded
from l4.yolo.state import fold_plan

from .test_yolo_merge_guard import BRANCH, PR_URL, FakeForge, World
from .yolo_cycle_world import CycleWorld, ev, unit_id
from .yolo_ledger_world import sh
from .yolo_review_world import PURPOSE_X

A, B = unit_id("a"), unit_id("b")


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def state(world, plan_id="p1"):
    return fold_plan(plan_id, world.events(plan_id))


def kinds(world):
    return world.kinds()


def waiting_events(world):
    return [e for e in world.events() if e.type == "plan.waiting"]


def in_review_world(world, *, pr_base: str | None = "main", **plan):
    """An active `merge: auto` plan whose unit a is in review with a PASS; its PR is aimed at `pr_base` (None: none)."""
    world.plan(**plan)
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    head = world.unit_branch("a")
    if pr_base is not None:
        if pr_base != "main":
            sh(world.repo, "push", "-q", "origin", f"main:refs/heads/{pr_base}")
        world.forge.create_pr("l4/openspec/a", pr_base, "[l4] a", "b", draft=False)
    return head, {"a": world.in_review("a", head)}


def no_sleep(_seconds):
    return None


# --- M3: a merge that stays not ready is a wait ----------------------------------------------------------------------


def test_a_pr_aimed_at_another_branch_makes_the_plan_wait_with_the_reason_on_record(world):
    _, snaps = in_review_world(world, pr_base="other")
    step = world.step(snaps)
    assert step.allow == frozenset({A}) and step.start_next_run is False
    (waiting,) = waiting_events(world)
    assert waiting.data["reason"] == "merge_not_ready" and waiting.data["unit"] == A
    assert "aimed at other, not the target main" in waiting.data["detail"]
    assert state(world).status == "waiting" and state(world).wait_reason == "merge_not_ready"


def test_a_unit_with_no_pr_makes_the_plan_wait_with_the_reason_on_record(world):
    _, snaps = in_review_world(world, pr_base=None)
    world.step(snaps)
    (waiting,) = waiting_events(world)
    assert waiting.data["reason"] == "merge_not_ready" and waiting.data["detail"] == "the unit has no pull request"


def test_the_wait_of_a_merge_that_is_not_ready_is_recorded_once(world):
    _, snaps = in_review_world(world, pr_base=None)
    world.step(snaps)
    n = len(world.events())
    for _ in range(3):  # the same cause, run after run: no new record, no wake-up and wait again
        world.step(snaps)
    assert len(world.events()) == n and state(world).status == "waiting"


def test_a_merge_that_becomes_ready_wakes_the_plan_and_merges_in_the_same_step(world):
    head, snaps = in_review_world(world, pr_base="other")
    world.step(snaps)
    n = len(world.events())
    world.forge._prs[1]["base"] = "main"  # a person aims the PR at the target
    step = world.step(snaps)
    assert [e.type for e in world.events()[n : n + 3]] == ["plan.resumed", "unit.merge_requested", "unit.merged"]
    resumed = world.events()[n].data
    assert resumed["by"] == "harness" and "the merge of openspec:a can go on" in resumed["reason"]
    assert world.landed(head) and step.start_next_run is True


def test_a_merge_that_is_not_ready_for_another_reason_is_recorded_again_once(world):
    _, snaps = in_review_world(world, pr_base="other")
    world.step(snaps)
    world.forge._prs[1]["state"] = "closed"  # the cause changed: the PR is closed now
    world.step(snaps)
    details = [e.data["detail"] for e in waiting_events(world)]
    assert len(details) == 2 and "aimed at other" in details[0] and details[1] == "the unit has no pull request"
    n = len(world.events())
    world.step(snaps)
    assert len(world.events()) == n  # and then once more it holds


def test_a_wait_for_the_merge_ends_when_the_unit_has_work_again(world):
    _, snaps = in_review_world(world, pr_base=None)
    world.step(snaps)
    step = world.step({"a": world.snapshot("a", "verifying")})  # a person pushed to the branch: the unit verifies again
    assert state(world).status == "active"
    assert step.allow == frozenset({A}) and step.start_next_run is True


def test_status_shows_why_the_merge_is_not_ready(tmp_path, capsys):
    from .yolo_cmd_world import A as CA
    from .yolo_cmd_world import CmdWorld
    from .yolo_cmd_world import ev as cev

    cmd = CmdWorld(tmp_path)
    cmd.push_plan()
    admitted = cev("plan.admitted", plan_digest=plan_digest(cmd.plan_text), order=[CA])
    activated = cev("plan.activated", plan_digest="x", digests={}, by="a", reason="go", limits={})
    detail = "the pull request !1 is aimed at other, not the target main"
    cmd.seed("p1", admitted, cmd.reviewed(), activated, cev("unit.dispatched", unit=CA),
             cev("plan.waiting", reason="merge_not_ready", unit=CA, detail=detail))  # fmt: skip
    assert cmd.l4("status", "p1") == 0
    assert f"waiting: merge_not_ready: {detail}" in capsys.readouterr().out


# --- M3: the PR head the forge shows late ----------------------------------------------------------------------------


class LaggingForge(FakeForge):
    """A forge whose PR shows the old head for `lag` reads and the pushed head after."""

    def __init__(self, pr, new_head, lag):
        super().__init__(pr)
        self.new_head, self.lag = new_head, lag

    def get_pr(self, number):
        self.gets.append(number)
        from dataclasses import replace

        return self.pr if len(self.gets) <= self.lag else replace(self.pr, head_sha=self.new_head)


@pytest.fixture
def guard_world(tmp_path, raw, git_environ):
    return World(tmp_path, raw, git_environ)


def lagging(world, lag):
    stale = PullRequest(7, PR_URL, BRANCH, "main", "[l4] x", False, "open", (), head_sha="b" * 40)
    return LaggingForge(stale, world.head, lag)


def guarded(world, forge, sleeps):
    return merge_guarded(world.app, world.cfg, world.git, forge, world.snapshot(), sleep=sleeps.append)


def test_a_pr_head_that_lags_a_push_is_read_again_and_the_merge_goes_on(guard_world):
    sleeps: list[float] = []
    forge = lagging(guard_world, 1)
    out = guarded(guard_world, forge, sleeps)
    assert out.status == "merged" and out.head == guard_world.head
    assert len(forge.gets) == 2 and sleeps == [HEAD_LAG_WAIT_S, HEAD_LAG_WAIT_S] and HEAD_LAG_WAIT_S == 5.0


def test_a_pr_head_that_stays_different_is_read_three_times_then_not_ready(guard_world):
    sleeps: list[float] = []
    forge = lagging(guard_world, 99)
    out = guarded(guard_world, forge, sleeps)
    assert out.status == "not_ready" and "is not the head to merge" in out.detail
    assert len(forge.gets) == HEAD_LAG_READS == 3 and sleeps == [5.0, 5.0, 5.0]


def test_a_pr_head_that_matches_is_not_read_again(guard_world):
    sleeps: list[float] = []
    ok = PullRequest(7, PR_URL, BRANCH, "main", "[l4] x", False, "open", (), head_sha=guard_world.head)
    forge = FakeForge(ok)
    assert guarded(guard_world, forge, sleeps).status == "merged" and forge.gets == [] and sleeps == []


def test_a_forge_that_cannot_be_asked_again_keeps_the_pr_as_it_was_read(guard_world):
    from l4.forge.base import ForgeError

    class Broken(FakeForge):
        def get_pr(self, number):
            raise ForgeError("503")

    stale = PullRequest(7, PR_URL, BRANCH, "main", "[l4] x", False, "open", (), head_sha="b" * 40)
    out = guarded(guard_world, Broken(stale), [])
    assert out.status == "not_ready" and "is not the head to merge" in out.detail


# --- M2: how a rejected unit leaves `rejected` ------------------------------------------------------------------------


def test_no_edge_of_the_lifecycle_leads_to_rejected_and_a_rejection_leaves_the_phase_alone():
    assert [e for e in TRANSITIONS if e.target is Phase.REJECTED] == []
    at = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
    rejected = LedgerEvent(at, "r-20261014T1000Z-0001", A, 1, "unit.rejected", {"reasons": ["the unit has no tasks"]})
    assert fold([rejected], A).phase is None  # the next run of the unit reads its spec again (`_discover`)


def test_retry_does_not_move_a_unit_that_is_rejected(tmp_path):
    from l4.config.schema import L4Config
    from l4.specs.base import Framework, UnitRef
    from l4.state.fold import UnitState

    ref = UnitRef(Framework.OPENSPEC, "a", tmp_path)
    refusal = refuse(ref, UnitState(unit=A, phase="rejected"), L4Config.model_validate({"version": 1}), "x")
    assert refusal is not None and "correct the spec on l4/openspec/a, then the next run reads it again" in str(refusal)


NEW_SPEC = PURPOSE_X + (
    "## ADDED Requirements\n\n### Requirement: R1 fixed\nThe system SHALL work.\n\n#### Scenario: S\n"
    "- **WHEN** x\n- **THEN** y\n"
)


@pytest.fixture
def no_retry(monkeypatch):
    calls: list[str] = []

    def retry(app, cfg, git, provider, ref, **kw):
        calls.append(ref.id)
        raise AssertionError("the plan step never asks `retry` to move a rejected unit")

    monkeypatch.setattr("l4.state.retry.retry_unit", retry)
    return calls


def reject_and_fix(world):
    """The plan stops with `unit_rejected`; the person fixes the spec; the next run records `inputs_changed`, CI
    reviews, and the person activates again. Returns the plan text."""
    text = world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    world.step({"a": world.snapshot("a", "rejected")})
    assert state(world).status == "stopped" and state(world).stop_reason == "unit_rejected"
    world.commit({"openspec/changes/a/specs/x/spec.md": NEW_SPEC}, "fix the spec of a")
    world.push_main()
    world.step({"a": world.snapshot("a", "rejected")})
    assert state(world).stop_reason == "inputs_changed" and state(world).review_digests.get(A) == world.digests()[A]
    world.seed(
        ev("plan.activated", plan_digest=plan_digest(text), digests=world.digests(), limits={}, by="alice", reason="ok")
    )
    return text


def test_a_rejected_unit_whose_spec_was_fixed_runs_again_after_the_activation(world, no_retry):
    reject_and_fix(world)
    assert state(world).status == "active" and state(world).current == A
    n = len(world.events())
    step = world.step({"a": world.snapshot("a", "rejected")})
    assert no_retry == []
    assert step.allow == frozenset({A}) and step.start_next_run is True
    assert [e.type for e in world.events()[n:]] == ["plan.charged", "unit.dispatched"]
    assert state(world).status == "active"


def test_a_unit_that_is_still_rejected_after_its_run_stops_the_plan_again_once(world, no_retry):
    reject_and_fix(world)
    world.step({"a": world.snapshot("a", "rejected")})  # the unit's run
    world.step({"a": world.snapshot("a", "rejected")})  # and it is still rejected
    assert state(world).status == "stopped" and state(world).stop_reason == "unit_rejected"
    assert "is still rejected after its spec was fixed" in state(world).stop_detail
    n = len(world.events())
    world.step({"a": world.snapshot("a", "rejected")})
    assert len(world.events()) == n and no_retry == []


def test_the_documented_path_walks_from_the_unit_rejected_stop_to_the_unit_running_again(world, no_retry):
    """1. the stop; 2. resume is refused and says what to do; 3. the spec is fixed and pushed; 4. the next run records
    inputs_changed and CI reviews; 5. `l4 yolo activate`; 6. the unit runs and is charged to the plan."""
    text = world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    world.step({"a": world.snapshot("a", "rejected")})
    stopped = state(world)
    assert (stopped.status, stopped.stop_reason, stopped.stop_unit) == ("stopped", "unit_rejected", A)
    blocker = resume_blocker("p1", stopped, world.events(), None, {A: "rejected"}, Extend())
    assert (
        blocker is not None
        and "fix the cause, its spec (push it" in blocker.message
        and "the configuration" in blocker.message
    )
    assert "then l4 yolo activate p1" in blocker.message
    world.commit({"openspec/changes/a/specs/x/spec.md": NEW_SPEC}, "fix the spec of a")
    world.push_main()
    world.step({"a": world.snapshot("a", "rejected")})
    assert state(world).stop_reason == "inputs_changed"
    world.seed(
        ev("plan.activated", plan_digest=plan_digest(text), digests=world.digests(), limits={}, by="alice", reason="ok")
    )
    step = world.step({"a": world.snapshot("a", "rejected")})
    assert step.allow == frozenset({A}) and step.start_next_run is True
    assert state(world).used.runs == 1 and state(world).status == "active" and no_retry == []
    step = world.step({"a": world.snapshot("a", "implementing")})  # the unit's own run read the spec and went on
    assert step.allow == frozenset({A}) and state(world).status == "active"


def test_a_unit_without_a_phase_after_a_rejection_is_dispatched_as_usual(world, no_retry):
    """What a real rejection leaves: no phase. The unit's next run reads the spec again."""
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    step = world.step({"a": world.snapshot("a", None)})
    assert step.allow == frozenset({A}) and step.start_next_run is True and no_retry == []


# --- L4: the plan files of the target ---------------------------------------------------------------------------


def active_plan(world):
    world.plan()
    world.activate()
    world.step()  # a is dispatched
    return world


def only_the_dispatch(world, n):
    """The step went on as before: it dispatched the current unit again and stopped nothing."""
    return [e.type for e in world.events()[n:]] == ["plan.charged", "unit.dispatched"]


def test_a_checkout_without_the_plan_file_does_not_stop_the_plan(world):
    active_plan(world)
    sh(world.repo, "checkout", "-q", "-b", "elsewhere")
    sh(world.repo, "rm", "-q", ".l4/plans/p1.json")
    sh(world.repo, "commit", "-qm", "a branch without the plan")
    n = len(world.events())
    step = world.step({"a": world.snapshot("a", "implementing")})
    assert only_the_dispatch(world, n) and state(world).status == "active"
    assert step.allow == frozenset({A})


def test_a_locally_edited_plan_file_does_not_stop_the_plan(world):
    active_plan(world)
    path = world.repo / ".l4" / "plans" / "p1.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"merge": "auto"', '"merge": "human"'), encoding="utf-8")
    n = len(world.events())
    world.step({"a": world.snapshot("a", "implementing")})  # the file is edited and not committed; HEAD is the tip
    assert only_the_dispatch(world, n) and state(world).status == "active"


def test_a_committed_local_edit_of_the_plan_file_does_not_stop_the_plan(world):
    active_plan(world)
    world.commit({".l4/plans/p1.json": "{}\n"}, "break the plan locally")
    n = len(world.events())
    world.step({"a": world.snapshot("a", "implementing")})
    assert only_the_dispatch(world, n) and state(world).status == "active"


def test_a_checkout_that_never_had_plan_files_still_holds_the_units_of_the_target(world):
    world.plan()
    world.activate()
    sh(world.repo, "checkout", "-q", "--orphan", "bare")
    sh(world.repo, "rm", "-rqf", ".")
    world.commit({"README.md": "bare\n"}, "a tree that never had a plan file")
    step = world.step()
    assert step.allow == frozenset({A})  # b waits for a: the plan still holds it
    assert B in step.refusals and "waits for openspec:a" in step.refusals[B]


def test_the_holds_of_a_failed_step_come_from_the_target(world):
    world.plan()
    sh(world.repo, "checkout", "-q", "-b", "elsewhere")
    sh(world.repo, "rm", "-q", ".l4/plans/p1.json")
    sh(world.repo, "commit", "-qm", "a branch without the plan")
    step = cycle.failed_plan_step(world.app, world.found(), RuntimeError("boom"), cfg=world.cfg, git=world.git)
    assert step.allow == frozenset()  # both units are in the plan of the target
    assert all("is held by plan p1" in text for text in step.refusals.values())


def test_the_merge_policy_listing_reads_the_plan_files_of_the_target(world):
    world.plan(merge="auto")
    world.activate()
    sh(world.repo, "checkout", "-q", "-b", "elsewhere")
    sh(world.repo, "rm", "-q", ".l4/plans/p1.json")
    sh(world.repo, "commit", "-qm", "a branch without the plan")
    assert cycle.auto_plan_units(world.app, world.cfg, world.git) == frozenset({A, B})


def test_ci_reads_the_checkout_when_it_is_the_target_head(world):
    world.plan()
    assert cycle.plan_source(world.cfg, world.git) is None  # HEAD is origin/main and nothing is changed
    world.commit({"x.txt": "x\n"}, "ahead")
    assert cycle.plan_source(world.cfg, world.git) == "refs/remotes/origin/main"


def test_the_history_check_looks_at_the_revision_the_files_are_read_from(world):
    world.plan()
    sh(world.repo, "checkout", "-q", "--orphan", "bare")
    sh(world.repo, "rm", "-rqf", ".")
    world.commit({"README.md": "bare\n"}, "bare")
    assert cycle._had_plan_files(world.git) is False
    assert cycle._had_plan_files(world.git, "refs/remotes/origin/main") is True


# --- L6a: a named run of the current unit is charged ------------------------------------------------------------


def test_a_named_run_of_the_current_unit_is_charged_to_the_plan_like_any_run(world):
    world.plan()
    world.activate()
    world.step()  # the plan step dispatches a: run 1
    assert state(world).used.runs == 1
    step = world.step({"a": world.snapshot("a", "implementing")}, read_only=True)
    assert step.allow == frozenset({A})
    assert state(world).used.runs == 2 and kinds(world)[-1] == "plan.charged"


def test_a_named_run_of_a_unit_with_nothing_to_run_is_not_charged(world):
    head, snaps = in_review_world(world, pr_base=None)
    n = len(world.events())
    step = world.step(snaps, read_only=True)
    assert step.allow == frozenset({A}) and len(world.events()) == n


def test_a_named_run_cannot_escape_the_run_limit(world):
    world.plan(limits={"max_runs": 2})
    world.activate()
    world.step()
    world.step({"a": world.snapshot("a", "implementing")}, read_only=True)  # run 2
    step = world.step({"a": world.snapshot("a", "implementing")}, read_only=True)
    assert step.allow == frozenset() and "reached a limit" in step.refusals[A]


def test_a_named_run_of_a_unit_the_plan_did_not_dispatch_is_still_refused(world):
    world.plan()
    world.activate()
    n = len(world.events())
    step = world.step(read_only=True)
    assert step.allow == frozenset() and len(world.events()) == n


def test_a_named_run_of_the_current_unit_leaves_a_waiting_plan_waiting(world):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"), ev("plan.waiting", reason="unit_awaiting_human", unit=A))
    world.step({"a": world.snapshot("a", "implementing")}, read_only=True)  # the cause is gone: the unit may run
    assert state(world).status == "waiting" and state(world).used.runs == 1
