"""The stop details of `inputs_changed` name the digests, where the unit is read and the files (yolo-guardrails D1 M11
to M13; SCN-YOLO-184)."""

import json

import pytest

from l4.yolo.digest import plan_digest
from l4.yolo.readiness import PROMPT_VERSION
from l4.yolo.state import fold_plan

from .yolo_cycle_world import CycleWorld, ev, unit_id

A, B = unit_id("a"), unit_id("b")
SPEC_B_FILE = "openspec/changes/b/specs/x/spec.md"
NEW_SPEC = "## ADDED Requirements\n### Requirement: B\nB SHALL do something else.\n"


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def state(world):
    return fold_plan("p1", world.events())


def origin(world) -> str:
    return world.git.rev_parse("refs/remotes/origin/main") or ""


def activate_with_revs(world, *, revs: bool = True) -> str:
    """The plan reviewed (the review recorded the revisions it read when `revs`), then activated."""
    text = world.plan()
    world.reviewed(text)
    sha = origin(world)
    if revs:
        digests = world.digests()
        units = {u: {"verdict": "READY", "digest": d, "findings": []} for u, d in digests.items()}
        world.seed(
            ev(
                "plan.reviewed",
                plan_digest=plan_digest(text),
                prompt_version=PROMPT_VERSION,
                units=units,
                batches={},
                target_rev=sha,
                unit_revs={A: sha, B: sha},
            )  # fmt: skip
        )
    world.seed(
        ev(
            "plan.activated",
            plan_digest=plan_digest(text),
            digests=world.digests(),
            limits={},
            by="alice",
            reason="go",
        )
    )
    return text


def change_b(world) -> str:
    world.commit({SPEC_B_FILE: NEW_SPEC}, "change b")
    return world.push_main()


def test_a_spec_change_after_the_activation_is_named_in_the_stop_detail(world):
    activate_with_revs(world)
    frozen = world.digests()[B]
    change_b(world)
    world.step()
    got = state(world)
    now = world.digests()[B]
    assert (got.status, got.stop_reason, got.stop_unit) == ("stopped", "inputs_changed", B)
    assert got.stop_detail == (
        f"the spec of {B} changed after the activation: spec digest {frozen[:8]} frozen at the activation, "
        f"{now[:8]} now on origin/main ({origin(world)[:7]}); changed: {SPEC_B_FILE}"
    )


def test_a_plan_file_change_after_the_activation_names_both_digests(world):
    text = activate_with_revs(world)
    world.commit(
        {".l4/plans/p1.json": json.dumps({**json.loads(text), "merge": "human"}, indent=2) + "\n"}, "edit plan"
    )
    world.push_main()
    world.step()
    got = state(world)
    new = plan_digest((world.repo / ".l4/plans/p1.json").read_text())
    assert got.stop_reason == "inputs_changed" and got.stop_unit == "plan"
    assert got.stop_detail == (
        f"the plan file .l4/plans/p1.json changed after the activation: digest {plan_digest(text)[:8]} frozen at "
        f"the activation, {new[:8]} now on origin/main ({origin(world)[:7]})"
    )


def test_a_fixed_rejected_spec_names_the_digests(world):
    world.plan()
    world.activate()
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    world.step({"a": world.snapshot("a", "rejected")})
    assert state(world).stop_reason == "unit_rejected"
    rejected = world.digests()[A]
    world.commit({"openspec/changes/a/specs/x/spec.md": NEW_SPEC}, "fix a")
    world.push_main()
    world.step({"a": world.snapshot("a", "rejected")})
    got = state(world)
    assert got.stop_reason == "inputs_changed" and got.stop_unit == A
    assert got.stop_detail.startswith(f"the spec of {A} changed after it was rejected: ")
    assert (
        f"spec digest {rejected[:8]} at the rejection, {world.digests()[A][:8]} now on origin/main (" in got.stop_detail
    )


def test_without_unit_revs_the_detail_names_no_file(world):
    activate_with_revs(world, revs=False)
    frozen = world.digests()[B]
    change_b(world)
    world.step()
    detail = state(world).stop_detail
    assert detail.startswith(f"the spec of {B} changed after the activation: spec digest {frozen[:8]} frozen")
    assert "changed:" not in detail.split("changed after the activation", 1)[1]
