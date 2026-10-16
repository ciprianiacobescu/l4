# ruff: noqa: F811
"""A spec push to the unit branch re-enters the unit by itself (L4-OPS-014, design D13, SCN-OPS-20..22): the next
`l4 run` takes `spec_edited` to `implementing`, records `unit.retried{reason: "spec edited"}` and, for a unit escalated
at a limit, one more round once per head."""

import pytest

from l4.exitcodes import ExitCode

from .ops_world import (  # noqa: F401
    BRANCH,
    NAME,
    REWORDED_SPEC,
    UNIT,
    UNIT_REL,
    escalate,
    events,
    failing_reds,
    happy,
    person_pushes,
    stamp,
    world,
)


def phase_changes(world):
    return [(e["from"], e["to"], e["trigger"]) for e in events(world.remote) if e["type"] == "phase.changed"]


def escalate_settled(world, *, spawned: int = 3, feedback: bool = False) -> str:
    """`escalated` at a limit, as `ops_world.escalate` does it, but with every fix unit done: nothing is left open for
    the run that follows to drive."""
    rows: list[tuple[str, dict]] = []
    for i in range(1, spawned + 1):
        unit = f"{NAME}-fix-{i}"
        rows += [("fix.spawned", {"fix_unit": unit, "round": i, **({"feedback_only": True} if feedback else {})}),
                 ("fix.done", {"fix_unit": unit})]  # fmt: skip
    reason = "feedback_rounds_exhausted" if feedback else "fix_rounds_exhausted"
    rows.append(("phase.changed", {"from": "verifying", "to": "escalated", "trigger": "verify_fail_exhausted",
                                   "exit_code": 13, "reason": reason, "detail": f"{reason} {spawned}"}))  # fmt: skip
    return stamp(world, *rows)


def head(world) -> str:
    return world.remote.run("rev-parse", BRANCH).stdout.strip()


def test_a_spec_push_to_an_escalated_unit_starts_it_again(world):
    """SCN-OPS-20: no `l4 retry`; the extra round and the retry are recorded, the unit implements."""
    world.run(failing_reds())
    escalate_settled(world)
    pushed = person_pushes(world, {f"{UNIT_REL}/proposal.md": "## Why\nreworded\n"})
    result = world.run(happy())
    log = events(world.remote)
    [extended] = [e for e in log if e["type"] == "budget.extended"]
    assert (extended["fix_rounds"], extended["signal"]) == (1, f"spec_edit:{pushed}")
    [retried] = [e for e in log if e["type"] == "unit.retried"]
    assert (retried["reason"], retried["signal"], retried["by"]) == ("spec edited", f"spec_edit:{pushed}", "push")
    assert ("escalated", "implementing", "spec_edited") in phase_changes(world)
    assert [e["type"] for e in log if e["type"] in ("budget.extended", "unit.retried")] == [
        "budget.extended",
        "unit.retried",
    ]
    assert result.code == ExitCode.OK and "unit.resumed" not in [e["type"] for e in log]


def test_the_same_head_grants_one_round_once(world):
    world.run(failing_reds())
    escalate_settled(world)
    pushed = person_pushes(world, {f"{UNIT_REL}/proposal.md": "reworded\n"})
    world.run(happy())
    rounds = [e for e in events(world.remote) if e["type"] == "budget.extended"]
    assert [e["signal"] for e in rounds] == [f"spec_edit:{pushed}"]
    assert pushed != head(world)  # the run's own commits ended the tail: a later run takes nothing
    before = len(events(world.remote))
    world.run(happy())
    assert len([e for e in events(world.remote) if e["type"] == "unit.retried"]) == 1
    assert len(events(world.remote)) >= before


def test_a_halted_unit_gets_no_extra_round(world):
    world.run(failing_reds())
    person_pushes(world, {f"{UNIT_REL}/proposal.md": "reworded\n"})
    world.run(happy())
    log = events(world.remote)
    assert "budget.extended" not in [e["type"] for e in log]
    assert ("halted", "implementing", "spec_edited") in phase_changes(world)


def test_a_feedback_limit_stop_gets_a_feedback_round(world):
    world.run(failing_reds())
    escalate_settled(world, spawned=5, feedback=True)
    person_pushes(world, {f"{UNIT_REL}/proposal.md": "reworded\n"})
    world.run(happy())
    [extended] = [e for e in events(world.remote) if e["type"] == "budget.extended"]
    assert extended["feedback_rounds"] == 1 and "fix_rounds" not in extended


def test_a_verified_unit_is_verified_again_after_a_reworded_requirement(world):
    """SCN-OPS-21: it is not handed off on the old verdict."""
    world.run(failing_reds())
    stamp(world, ("phase.changed", {"from": "verifying", "to": "verified", "trigger": "verify_pass"}))
    person_pushes(world, {f"{UNIT_REL}/specs/greeting/spec.md": REWORDED_SPEC})
    world.run(happy())
    changes = phase_changes(world)
    at = changes.index(("verified", "implementing", "spec_edited"))
    after = [c[1] for c in changes[at:]]
    assert after[:3] == [
        "implementing",
        "implemented",
        "verifying",
    ]  # verified again, not handed off on the old verdict


def test_answers_alone_are_not_a_spec_edit(world):
    """SCN-OPS-22: only `questions.md` changed, so the answers path decides and no `spec_edited` edge is taken."""
    world.run(failing_reds())
    stamp(
        world,
        ("question.raised", {"id": "Q-001", "kind": "blocking"}),
        ("phase.changed", {"from": "implementing", "to": "awaiting_human", "trigger": "questions_blocking"}),
    )
    person_pushes(world, {f"{UNIT_REL}/questions.md": "# Questions\n"})
    world.run(happy())
    assert "spec_edited" not in [c[2] for c in phase_changes(world)]
    assert "unit.retried" not in [e["type"] for e in events(world.remote)]


def test_a_code_only_push_in_verifying_is_not_a_spec_edit(world):
    world.run(failing_reds())
    stamp(world, ("phase.changed", {"from": "implemented", "to": "verifying", "trigger": "verification_started"}))
    person_pushes(world, {"src/greeting.py": "# a fix\n"})
    world.run(happy())
    assert "spec_edited" not in [c[2] for c in phase_changes(world)]


@pytest.mark.parametrize("phase", ["halted", "escalated"])
def test_a_stopped_unit_whose_push_changes_only_code_stays_stopped(world, phase):
    world.run(failing_reds())
    if phase == "escalated":
        escalate_settled(world)
    person_pushes(world, {"src/greeting.py": "# a fix\n"})
    before = events(world.remote)
    result = world.run(happy())
    assert result.code == ExitCode.OK  # no unit is actionable: nothing ran
    assert events(world.remote) == before and head(world)


def test_a_stopped_unit_with_a_spec_edit_is_not_refused_by_a_run_of_that_unit(world):
    """L4-OPS-010 stays for a unit nobody edited; with a spec edit the run takes `spec_edited` (L4-OPS-014)."""
    from l4.orchestrator import _refuse_stopped
    from l4.specs.base import Framework, UnitRef
    from l4.state.fold import UnitState
    from l4.state.review import SpecEdit

    state = UnitState(unit=UNIT, phase="halted", halt_detail="task 1.1 failed")
    ref = UnitRef(Framework.OPENSPEC, NAME, world.app.repo / UNIT_REL)
    assert _refuse_stopped(world.app, state, ref).exit_code == ExitCode.HALTED  # type: ignore[union-attr]
    assert _refuse_stopped(world.app, state, ref, SpecEdit(("a" * 40,), "b" * 40, "a" * 40)) is None


def test_a_run_of_a_unit_escalated_with_no_convertible_finding_is_told_the_feedback_way(world):
    """SCN-OPS-38 (L4-OPS-022): the refusal of `l4 run --unit` names feedback before the retry."""
    from l4.orchestrator import _refuse_stopped
    from l4.specs.base import Framework, UnitRef
    from l4.state.fold import UnitState

    state = UnitState(
        unit=UNIT, phase="escalated", halt_reason="no_convertible_finding", halt_detail="no finding can be converted"
    )
    ref = UnitRef(Framework.OPENSPEC, NAME, world.app.repo / UNIT_REL)
    refused = _refuse_stopped(world.app, state, ref)
    assert refused is not None and "l4 feedback add --unit" in refused.outcome.exit_reason
    assert "a retry alone repeats the same verdict" in refused.outcome.exit_reason


def test_the_plan_and_a_named_run_take_a_halted_unit_with_a_spec_edit(world):
    from l4.planner import facts_of, next_action
    from l4.state.status import snapshots

    world.run(failing_reds())
    person_pushes(world, {"src/greeting.py": "# code only\n"})
    app = world.app
    from l4.config.redaction import load_app_config

    app, cfg = load_app_config(app)
    (row,) = snapshots(app, cfg, (UNIT,))
    assert row.spec_edit is None and next_action(facts_of(row))[0] == "none"
    pushed = person_pushes(world, {f"{UNIT_REL}/proposal.md": "reworded\n"})
    (row,) = snapshots(app, cfg, (UNIT,))
    assert next_action(facts_of(row)) == ("implement", f"spec edited after halted: {pushed[:10]}")


def test_a_spec_edit_on_a_halted_unit_is_not_hinted_for_a_retry(world):
    """The hint says "add the label or run l4 retry" for a push the run does not take; a spec edit it does."""
    from types import SimpleNamespace

    from l4.ci.sweeper import Sweeper
    from l4.state.review import SpecEdit

    snapshot = SimpleNamespace(spec_edit=SpecEdit(("a" * 40,), "b" * 40, "a" * 40))
    assert Sweeper._push_hint(SimpleNamespace(), snapshot, "l4:retry") is None  # type: ignore[arg-type]
