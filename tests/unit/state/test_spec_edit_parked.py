# ruff: noqa: F811
"""A spec edit is never buried under a harness commit (L4-OPS-014, review M3, L3): before any commit of a run, a retry
or a resume, the tail of the unit branch is checked. A phase that can take the edit takes it; any other records
`spec.edit_seen`, and the edit is taken as soon as the unit is in a phase that can (right after `capacity_restored`)."""

import contextlib
import dataclasses

from l4.config.redaction import load_app_config
from l4.exitcodes import ExitCode
from l4.orchestrator import run_unit_in_worktree
from l4.services import load_hooks
from l4.sim.fakes import ProfileRouter, fake_openspec_cli
from l4.sim.runner import scripted_agents
from l4.specs.providers import providers_for
from l4.state.resume import run_resume
from l4.state.status import refresh_refs, select_runnable
from l4.vcs.git import Git

from .ops_world import UNIT, UNIT_REL, escalate, events, failing_reds, happy, person_pushes, stamp, world  # noqa: F401
from .test_retry import phase_changes, retry

PARK = {"to": "waiting_capacity", "trigger": "required_role_unavailable", "retry_after": "2026-01-01T00:00:00Z"}
SPEC = {f"{UNIT_REL}/proposal.md": "## Why\nreworded by a person\n"}


def park(world, source: str) -> None:
    stamp(world, ("phase.changed", {"from": source, **PARK}))


def kinds(world) -> list[str]:
    return [e["type"] for e in events(world.remote)]


def taken(world, pushed: str) -> list[dict]:
    return [e for e in events(world.remote) if e["type"] == "unit.retried" and e.get("signal") == f"spec_edit:{pushed}"]


def test_a_spec_push_while_waiting_for_capacity_is_taken_after_capacity_is_restored(world):
    world.run(failing_reds())
    park(world, "verifying")
    pushed = person_pushes(world, SPEC)
    world.run(happy())
    changes = phase_changes(world)
    assert changes.index(("waiting_capacity", "verifying", "capacity_restored")) < changes.index(
        ("verifying", "implementing", "spec_edited")
    )
    assert "spec.edit_seen" in kinds(world) and len(taken(world, pushed)) == 1


def test_a_spec_push_while_waiting_for_capacity_from_implementing_is_consumed_too(world):
    world.run(failing_reds())
    park(world, "implementing")
    pushed = person_pushes(world, SPEC)
    world.run(happy())
    assert len(taken(world, pushed)) == 1  # `implementing` needs no edge, but the edit is consumed (and reopens)


def test_a_spec_push_while_the_agents_are_still_missing_stays_pending(world):
    world.run(failing_reds())
    stamp(world, ("phase.changed", {"from": "fixing", **PARK}))
    pushed = person_pushes(world, SPEC)
    result = retry(world)  # a retry from waiting_capacity goes back to `fixing`, which has no edge
    assert result.outcome.phase_after == "fixing"
    seen = [e for e in events(world.remote) if e["type"] == "spec.edit_seen"]
    assert [e["head"] for e in seen] == [pushed] and not taken(world, pushed)


def test_l4_retry_from_waiting_capacity_takes_a_persons_spec_edit(world):
    world.run(failing_reds())
    park(world, "verifying")
    person_pushes(world, SPEC)
    result = retry(world)
    assert result.outcome.phase_after == "implementing"
    changes = phase_changes(world)
    assert changes[-2:] == [
        ("waiting_capacity", "verifying", "capacity_restored"),
        ("verifying", "implementing", "spec_edited"),
    ]


def test_l4_retry_from_in_review_takes_a_persons_spec_edit(world):
    assert world.run(happy()).code == ExitCode.OK
    person_pushes(world, SPEC)
    result = retry(world)
    assert result.outcome.phase_after == "implementing"
    assert phase_changes(world)[-1] == ("in_review", "implementing", "spec_edit_after_handoff")


def test_l4_retry_from_in_review_with_a_code_only_commit_verifies_again(world):
    assert world.run(happy()).code == ExitCode.OK
    person_pushes(world, {"src/greeting.py": "# a fix\n"})
    assert retry(world).outcome.phase_after == "verifying"
    assert phase_changes(world)[-1] == ("in_review", "verifying", "retry_requested")


def test_l4_resume_takes_a_persons_spec_edit_of_a_halted_unit(world):
    world.run(failing_reds())
    person_pushes(world, SPEC)
    result = run_resume(world.app, unit=UNIT, reason="spec reworded")
    assert result.units[0].phase_after == "implementing"
    assert phase_changes(world)[-1] == ("halted", "implementing", "spec_edit_since_stop")
    assert "unit.resumed" in kinds(world)


def test_l4_resume_of_an_escalated_unit_takes_the_edit_too(world):
    world.run(failing_reds())
    escalate(world, spawned=3)
    person_pushes(world, SPEC)
    run_resume(world.app, unit=UNIT, reason="spec reworded", extend_fix_rounds=1)
    assert phase_changes(world)[-1] == ("escalated", "implementing", "spec_edit_since_stop")


def test_a_resume_without_a_spec_edit_goes_back_as_before(world):
    world.run(failing_reds())
    person_pushes(world, {"src/greeting.py": "# a fix\n"})
    run_resume(world.app, unit=UNIT, reason="again")
    assert phase_changes(world)[-1] == ("halted", "implementing", "resumed")


# --- L3: `l4 verify` leaves the edit for the next run -----------------------------------------------------------------


def verify_only(world):
    app, cfg = load_app_config(world.app)
    git = Git(app.repo, environ=app.environ)
    refresh_refs(app, cfg, git)
    provider, ref = select_runnable(cfg, git, list(providers_for(cfg, app.repo, app.environ)), UNIT)
    hooks = dataclasses.replace(load_hooks(), handoff=None, fix=None)  # as `run_verify` does
    with fake_openspec_cli():
        return run_unit_in_worktree(
            app, cfg, git, provider, ref, adapters={"fake": ProfileRouter(scripted_agents(happy()))},
            hooks=hooks, take_spec_edit=False,
        )  # fmt: skip


def test_verify_does_not_take_a_spec_edit_and_the_next_run_does(world):
    assert world.run(happy()).code == ExitCode.OK
    stamp(world, ("phase.changed", {"from": "in_review", "to": "verifying", "trigger": "retry_requested"}))
    pushed = person_pushes(world, SPEC)
    assert verify_only(world).outcome.phase_after == "verified"  # it verified the unit, and took no edit
    assert "spec_edited" not in [t for *_, t in phase_changes(world)]
    assert not taken(world, pushed)
    assert [e["head"] for e in events(world.remote) if e["type"] == "spec.edit_seen"] == [pushed]
    world.run(happy())  # the next `l4 run` takes the edit that verify left
    assert len(taken(world, pushed)) == 1
    assert ("verified", "implementing", "spec_edited") in phase_changes(world)


def test_l4_verify_passes_take_spec_edit_false(world, monkeypatch):
    from l4.verifier import ladder

    seen = {}

    def fake(*args, **kwargs):
        seen.update(kwargs)
        raise SystemExit(0)

    world.run(failing_reds())
    stamp(world, ("phase.changed", {"from": "halted", "to": "verifying", "trigger": "resumed"}))
    monkeypatch.setattr(ladder, "run_unit_in_worktree", fake)
    with contextlib.suppress(SystemExit):
        ladder.run_verify(world.app, unit=UNIT)
    assert seen["take_spec_edit"] is False
