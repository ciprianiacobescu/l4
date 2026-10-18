"""The merge waits for the repository's CI on H (L4-YOLO-042, L4-YOLO-043, L4-YOLO-013; SCN-YOLO-105, SCN-YOLO-107,
SCN-YOLO-112..119). `yolo.merge.require_ci` defaults to false: red, running or unreadable CI on H always blocks, and a
commit that no CI ran on merges on record unless `require_ci` is true."""

from datetime import UTC, datetime, timedelta

import pytest

from l4.forge.base import ForgeError

from .yolo_cycle_world import CycleWorld, MergingForge, ev, unit_id
from .yolo_review_world import make_cfg

A = unit_id("a")


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def ready(world: CycleWorld, **state):
    """An active `merge: auto` plan whose unit `a` is in review with a PASS at its recorded H, with an open PR."""
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    head = world.unit_branch("a")
    world.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    resolved = {key: value(head) if callable(value) else value for key, value in state.items()}
    return head, world.in_review("a", head, **resolved)


def base_head(world: CycleWorld) -> str:
    return world.git.rev_parse("refs/remotes/origin/main")


def configure(world: CycleWorld, **merge) -> None:
    world.cfg = make_cfg(forge={"type": "local", "base_branch": "main", "merge_policy": "auto"}, yolo={"merge": merge})


def waits(world: CycleWorld) -> list:
    return [e for e in world.events() if e.type == "plan.waiting"]


def merged(world: CycleWorld) -> list[dict]:
    return [e.data for e in world.events() if e.type == "unit.merged"]


def test_running_ci_on_h_holds_the_merge(world):
    """SCN-YOLO-112"""
    head, snap = ready(world, ci=(("test", "running"),))
    world.step({"a": snap})
    assert "unit.merge_requested" not in world.kinds()
    detail = waits(world)[-1]
    assert detail.data["reason"] == "merge_not_ready"
    assert "the repository CI is still running on the hand-off commit" in detail.data["detail"]
    assert head[:10] in detail.data["detail"]


def test_a_ci_wait_is_recorded_once_and_chains_no_run(world):
    """SCN-YOLO-107"""
    head, snap = ready(world, ci=(("test", "running"),))
    world.step({"a": snap})
    count = len(waits(world))
    for _ in range(2):
        step = world.step({"a": snap})
        assert step.start_next_run is False
    assert len(waits(world)) == count == 1


def test_the_wait_ends_when_h_is_green(world):
    """SCN-YOLO-113"""
    head, snap = ready(world, ci=(("test", "running"),))
    world.step({"a": snap})
    world.forge.script_jobs(head, [("test", "success")], replace=True)
    world.step({"a": snap})
    assert [m["ci"] for m in merged(world)] == ["green"]


def test_red_ci_on_h_not_yet_recorded_is_not_merged(world):
    """SCN-YOLO-114"""
    head, snap = ready(world, ci=(("test", "failed"),))
    world.forge.script_jobs(base_head(world), [("test", "success")])
    world.step({"a": snap})
    assert "unit.merged" not in world.kinds()
    detail = waits(world)[-1].data["detail"]
    assert "test" in detail and "the next sweep records it" in detail


def test_red_ci_on_h_blocks_even_when_no_ci_is_required(world):
    configure(world, require_ci=False)
    head, snap = ready(world, ci=(("test", "failed"),))
    world.forge.script_jobs(base_head(world), [("test", "success")])
    world.step({"a": snap})
    assert "unit.merged" not in world.kinds()


def test_a_job_red_on_h_and_on_the_base_does_not_hold_the_merge(world):
    """SCN-YOLO-115"""
    head, snap = ready(world, ci=(("lint", "failed"),))
    world.forge.script_jobs(base_head(world), [("lint", "failed")])
    step = world.step({"a": snap})
    (data,) = merged(world)
    assert data["ci"] == "preexisting" and data["ci_jobs"] == ["lint"]
    assert any("red as on the base: lint" in action for action in step.actions)


def test_no_ci_on_h_merges_on_record_by_default(world):
    """SCN-YOLO-118: `yolo.merge.require_ci` defaults to false."""
    head, snap = ready(world, ci=None)
    step = world.step({"a": snap})
    (data,) = merged(world)
    assert data["ci"] == "not_run" and "ci_jobs" not in data
    assert "yolo.merge.require_ci" in (world.forge.note(1) or "")  # the same warning is a note on the merged PR
    assert any(
        head[:10] in action and "no CI of the repository ran" in action and "yolo.merge.require_ci" in action
        for action in step.actions
    )


def test_require_ci_true_waits_for_a_ci_and_names_the_fix(world):
    """SCN-YOLO-116"""
    configure(world, require_ci=True)
    head, snap = ready(world, ci=None)
    world.step({"a": snap})
    assert "unit.merged" not in world.kinds()
    detail = waits(world)[-1].data["detail"]
    assert "no CI of the repository ran on the hand-off commit" in detail and "yolo.merge.require_ci: false" in detail


def test_a_preexisting_record_now_red_on_h_alone_names_the_retry(world):
    """SCN-YOLO-119"""
    head, snap = ready(world, ci_heads=lambda h: {h: "preexisting"}, ci=(("lint", "failed"),))
    world.forge.script_jobs(base_head(world), [("lint", "success")])
    world.step({"a": snap})
    assert "unit.merged" not in world.kinds()
    detail = waits(world)[-1].data["detail"]
    assert "lint" in detail and "l4 retry --unit openspec:a" in detail


class Unreadable(MergingForge):
    def list_pipeline_jobs(self, sha, *, settled=False):
        raise ForgeError("HTTP 502", status=502)


def test_unreadable_ci_is_not_green(world):
    """SCN-YOLO-117"""
    head, snap = ready(world)
    forge = Unreadable(origin=world.origin)
    forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    configure(world, require_ci=False)
    world.step({"a": snap}, forge=forge)
    assert "unit.merged" not in world.kinds()
    assert "could not be read" in waits(world)[-1].data["detail"]


def test_a_fast_forward_merge_records_h_and_green_ci(world):
    """SCN-YOLO-105, plan side"""
    head, snap = ready(world)
    configure(world, method="fast-forward")
    world.step({"a": snap})
    (data,) = merged(world)
    assert data["head"] == data["merge_commit"] == head and data["ci"] == "green"
    assert world.tip() == head


def test_a_squash_merge_records_green_ci(world):
    head, snap = ready(world)
    world.step({"a": snap})
    (data,) = merged(world)
    assert data["head"] == head and data["ci"] == "green"


@pytest.mark.parametrize("require_ci", [False, True])
@pytest.mark.parametrize("status", ["canceled", "manual"])
def test_a_cancelled_or_held_job_blocks_whatever_require_ci_says(world, status, require_ci):
    """F1 (SCN-YOLO-121): not green, not a fix round: the wait names the job and says to re-run it."""
    configure(world, require_ci=require_ci)
    head, snap = ready(world, ci=(("test", status),))
    world.step({"a": snap})
    assert "unit.merged" not in world.kinds()
    detail = waits(world)[-1].data["detail"]
    assert "test" in detail and "re-run it" in detail and head[:10] in detail


def test_a_job_that_did_not_pass_is_red_not_green(world):
    """F1: a failed job (GitHub's action_required and stale map to it) is the new-red path, with the base green."""
    configure(world, require_ci=True)
    head, snap = ready(world, ci=(("test", "failed"), ("lint", "success")))
    world.forge.script_jobs(base_head(world), [("test", "success")])
    world.step({"a": snap})
    assert "unit.merged" not in world.kinds()


def test_every_project_job_skipped_is_not_run(world):
    """F1 (SCN-YOLO-123): all skipped is `not_run`: the default merges on record, `require_ci: true` waits."""
    head, snap = ready(world, ci=(("test", "skipped"),))
    world.step({"a": snap})
    assert [m["ci"] for m in merged(world)] == ["not_run"]


def test_ci_not_created_yet_waits_inside_the_window(world):
    """F2 (SCN-YOLO-122): no CI yet, three minutes after the hand-off, is `running`: the default does not merge, and the
    wait chains no run. The same state ten minutes later is `not_run` and merges on record."""
    recent = datetime.now(UTC) - timedelta(minutes=3)
    head, snap = ready(world, ci=None, ready_at=recent)
    step = world.step({"a": snap})
    assert "unit.merged" not in world.kinds() and step.start_next_run is False
    assert (
        "still running" in waits(world)[-1].data["detail"] and "less than 10 minutes" in waits(world)[-1].data["detail"]
    )
    old = datetime.now(UTC) - timedelta(minutes=11)
    world.step({"a": world.in_review("a", head, ci=None, ready_at=old)})
    assert [m["ci"] for m in merged(world)] == ["not_run"]


class Requires(MergingForge):
    """A forge whose base branch requires `lint`, which H has not reported (`unreadable`: no endpoint could be read)."""

    required: list[str] = ["lint"]
    unreadable = False

    def required_checks(self, branch):
        return self.required, self.unreadable


@pytest.mark.parametrize("require_ci", [False, True])
def test_an_unreported_required_check_blocks_after_the_window_whatever_require_ci_says(world, require_ci):
    """m1 (SCN-YOLO-126): never `not_run`, never the "no CI of the repository ran" warning."""
    configure(world, require_ci=require_ci)
    head, snap = ready(world)
    forge = Requires(origin=world.origin)
    forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    forge.script_jobs(head, [("test", "success")])
    step = world.step({"a": snap}, forge=forge)
    assert "unit.merged" not in world.kinds()
    detail = waits(world)[-1].data["detail"]
    assert "the required check lint has not reported on" in detail and "GitHub will refuse the merge" in detail
    assert not any("no CI of the repository ran" in action for action in step.actions)


def test_required_checks_that_could_not_be_read_are_said_once_in_the_report(world):
    """m2 (SCN-YOLO-127)"""
    head, snap = ready(world)
    forge = Requires(origin=world.origin)
    forge.required, forge.unreadable = [], True
    forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    forge.script_jobs(head, [("test", "success")])
    step = world.step({"a": snap}, forge=forge)
    assert [m["ci"] for m in merged(world)] == ["green"]
    assert sum("required checks" in action and "could not be read" in action for action in step.actions) == 1


def test_a_running_wait_names_the_unfinished_jobs(world):
    """m4"""
    head, snap = ready(world, ci=(("test", "running"), ("lint", "pending")))
    world.step({"a": snap})
    assert "unfinished: lint, test" in waits(world)[-1].data["detail"]


def test_a_repository_that_cannot_start_any_ci_does_not_wait_for_the_window(world):
    """m7 (SCN-YOLO-128): the local forge defines no workflow, requires nothing and has no status: not_run at once."""
    head, snap = ready(world, ci=None, ready_at=datetime.now(UTC) - timedelta(minutes=1))
    forge = Requires(origin=world.origin)
    forge.required = []
    forge.workflow_files = lambda: ["l4.yml"]
    forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    world.step({"a": snap}, forge=forge)
    assert [m["ci"] for m in merged(world)] == ["not_run"]


@pytest.mark.parametrize("require_ci", [False, True])
def test_a_cancelled_push_run_with_a_skipped_twin_is_not_green(world, require_ci):
    """X1 (SCN-YOLO-123): not_run, so merged on record by default and waiting with `require_ci: true`."""
    configure(world, require_ci=require_ci)
    twins = (
        ("build", "canceled", {"workflow": "tests.yml", "event": "push"}),
        ("build", "skipped", {"workflow": "tests.yml", "event": "pull_request"}),
    )
    head, snap = ready(world, ci=twins)
    world.step({"a": snap})
    if require_ci:
        assert "unit.merged" not in world.kinds()
        assert "no CI of the repository ran" in waits(world)[-1].data["detail"]
    else:
        assert [m["ci"] for m in merged(world)] == ["not_run"]
