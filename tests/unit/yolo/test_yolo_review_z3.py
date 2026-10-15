"""Review round 3, area z3: the exclude semantics (M1, L4-YOLO-017, SCN-YOLO-35), the opencode-go capacity note (L2) and
the opencode cool-down identity (L5). The validator's own cases are in `test_yolo_validate_plan.py`."""

import json

import pytest

from l4.yolo.cycle import plan_holds
from l4.yolo.plans import plan_files
from l4.yolo.state import fold_plan

from .yolo_cycle_world import CycleWorld, ev, unit_id

A, B = unit_id("a"), unit_id("b")


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path, units=("a", "b"))


def plan_with_b_excluded(world) -> str:
    doc = {
        "schema": "l4/delivery-plan@1", "plan_id": "p1", "target": "main", "merge": "auto",
        "batches": [{"id": "b1", "units": [{"id": A}]}],
        "exclude": [{"id": B, "reason": "in review before the plan"}],
    }  # fmt: skip
    text = json.dumps(doc, indent=2) + "\n"
    world.commit({".l4/plans/p1.json": text}, "plan p1")
    world.push_main()
    return text


def snapshots(world):
    return {"a": world.snapshot("a", None), "b": world.snapshot("b", "implementing")}


# --- M1: an excluded unit is held only while a plan is active on the target --------------------------------------


def test_an_excluded_unit_runs_as_without_a_plan_while_its_plan_waits_for_activation(world):
    text = plan_with_b_excluded(world)
    world.reviewed(text, order=[A])
    step = world.step(snapshots(world))
    assert step.allow is not None and B in step.allow
    assert B not in step.refusals


def test_an_excluded_unit_gets_no_new_agent_work_while_its_plan_is_active(world):
    text = plan_with_b_excluded(world)
    world.activate(text, order=[A])
    step = world.step(snapshots(world))
    assert B not in (step.allow or ())
    assert step.refusals[B] == "is not in the active plan p1"
    assert A in step.allow


def test_the_planner_view_says_the_same_for_an_excluded_unit_of_an_active_plan(world):
    text = plan_with_b_excluded(world)
    world.activate(text, order=[A])
    states = {"p1": fold_plan("p1", world.events())}
    holds = plan_holds(plan_files(world.repo), states, {A: "implementing", B: "implementing"}, "main")
    assert holds[B].reason == "not in the active plan p1"


def test_an_excluded_unit_runs_as_without_a_plan_after_its_plan_completes(world):
    text = plan_with_b_excluded(world)
    world.activate(text, order=[A])
    world.seed(ev("plan.completed", revision="abc"))
    step = world.step(snapshots(world))
    assert step.allow is not None and B in step.allow
    assert B not in step.refusals


def test_the_status_lists_an_excluded_unit_with_its_reason(tmp_path, capsys):  # SCN-YOLO-35
    from l4.yolo.digest import plan_digest

    from .yolo_cmd_world import A as CMD_A
    from .yolo_cmd_world import B as CMD_B
    from .yolo_cmd_world import CmdWorld, plan_doc
    from .yolo_cmd_world import ev as cmd_ev

    cmd = CmdWorld(tmp_path)
    cmd.push_plan(plan_doc({CMD_A: []}, exclude=[{"id": CMD_B, "reason": "in review before the plan"}]))
    cmd.seed("p1", cmd_ev("plan.admitted", plan_digest=plan_digest(cmd.plan_text), order=[CMD_A]), cmd.reviewed())
    assert cmd.l4("status", "p1") == 0
    assert f"excluded: {CMD_B} (in review before the plan)" in capsys.readouterr().out


# --- L2: the capacity note names the key variable of the profile ---------------------------------------------------


def capacity_note(profile, *, platform="gitlab"):
    from datetime import UTC, datetime

    from l4.availability.errors import Unready, WaitingCapacity
    from l4.orchestrator import capacity_section

    unready = Unready("p", profile.adapter, profile.auth, "auth", "not set")
    exc = WaitingCapacity("implementer", "x", None, (unready,))
    now = datetime(2026, 10, 7, 11, 0, tzinfo=UTC)
    return capacity_section(
        exc, base="main", now=now, retry_after=None, platform=platform, environment="l4", profiles={"p": profile}
    )


def test_the_capacity_note_names_opencode_api_key_for_an_opencode_go_api_key_profile():
    from l4.config.schema import Profile

    profile = Profile(adapter="opencode", model="opencode-go/deepseek-v4.1-flash", auth="api_key")
    gitlab = capacity_note(profile)
    assert "OPENCODE_API_KEY" in gitlab and "OPENROUTER_API_KEY" not in gitlab
    github = capacity_note(profile, platform="github")
    assert "--secret OPENCODE_API_KEY=<ENV>" in github and "OPENROUTER_API_KEY" not in github


def test_the_capacity_note_is_unchanged_for_other_profiles():
    from l4.config.schema import Profile

    openrouter = Profile(adapter="opencode", model="openrouter/some/model", auth="api_key")
    assert "OPENROUTER_API_KEY" in capacity_note(openrouter)
    claude = Profile(adapter="claude-code", model="m", auth="subscription")
    assert "CLAUDE_CODE_OAUTH_TOKEN" in capacity_note(claude)


# --- L5: rotating OPENCODE_API_KEY clears a cool-down ------------------------------------------------------------


def test_rotating_opencode_api_key_changes_the_identity_of_an_opencode_profile(tmp_path):
    from l4.availability.cooldown import identity_hash
    from l4.config.schema import Profile

    profile = Profile(adapter="opencode", model="opencode-go/deepseek-v4.1-flash", auth="api_key")
    env = {"HOME": str(tmp_path), "OPENCODE_API_KEY": "key-one"}
    assert identity_hash(profile, env) != identity_hash(profile, {**env, "OPENCODE_API_KEY": "key-two"})
    assert identity_hash(profile, env) != identity_hash(profile, {"HOME": str(tmp_path)})
