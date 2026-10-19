# ruff: noqa: F811
"""`l4 yolo` after the final review of yolo-mode (findings 6, 8 and 13): resume and status read the live figures the
plan step checks the limits on, a plan stopped for a rejected unit says what really gets it going again, and the
activation records where the attempts of each unit start."""

import json

import l4.yolo.commands as commands
from l4.yolo.digest import plan_digest
from l4.yolo.state import fold_plan

from .test_yolo_commands_activate import reviewed_world
from .test_yolo_commands_manage import ACTIVATED, active_world, phases, resume
from .yolo_cmd_world import A, B, ev, forge, plan_doc, world  # noqa: F401


def attempt_refs(world, name, count):
    sha = world.remote.rev_parse("refs/heads/main")
    for n in range(1, count + 1):
        world.remote.run("update-ref", f"refs/l4/attempts/openspec/{name}/{n}", sha)


# --- #6: resume and status use the figures of the step --------------------------------------------------------------


def test_resume_is_refused_for_the_attempt_a_restart_made_after_the_stop(world, monkeypatch, capsys):
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)  # a person raises a limit (L4-YOLO-051)
    active_world(
        world,
        ev("unit.dispatched", unit=B),
        ev("plan.charged", unit=B, attempt=2, cost_usd=1.0, runs=2),
        ev("plan.stopped", reason="limit_attempts", unit=B),
    )
    attempt_refs(world, "add-b", 2)  # `l4 restart` twice: the unit is on attempt 3 of 2
    assert "openspec:add-b used 3 attempts, the limit is 2: raise it with --extend-attempts N" in resume(world, capsys)
    assert world.l4("resume", "p1", "--reason", "one more", "--extend-attempts", "1", "--no-run") == 0


def test_resume_is_refused_for_the_cost_the_unit_shows_beyond_its_charge(world, monkeypatch, capsys):
    active_world(
        world,
        ev("unit.dispatched", unit=B),
        ev("plan.charged", unit=B, attempt=1, cost_usd=0.0, runs=1),
        ev("plan.stopped", reason="limit_cost"),
    )
    real = commands._read_units

    def costly(ctx, rev, wanted, *, intake):
        units = real(ctx, rev, wanted, intake=intake)
        units.costs[B] = 12.0
        return units

    monkeypatch.setattr(commands, "_read_units", costly)
    assert "the cost $12.00 has reached the limit $10.00: raise it with --extend-cost USD" in resume(world, capsys)


def test_status_shows_the_attempt_and_cost_the_step_would_check(world, capsys):
    active_world(world, ev("unit.dispatched", unit=B), ev("plan.charged", unit=B, attempt=1, cost_usd=1.0, runs=1))
    attempt_refs(world, "add-b", 1)
    assert world.l4("status", "p1", "--json") == 0
    usage = json.loads(capsys.readouterr().out)["plans"][0]["usage"]
    assert usage["attempts"] == {B: 2} and usage["cost_usd"] == 1.0


# --- #8: the way out of unit_rejected -------------------------------------------------------------------------------


def rejected_world(world):
    reviewed_world(world)
    world.seed(
        "p1",
        ev(
            "plan.activated",
            plan_digest=plan_digest(world.plan_text),
            digests={A: world.digest(A), B: world.digest(B)},
            limits={},
            by="a",
            reason="r",
        ),  # fmt: skip
        ev("unit.dispatched", unit=B),
        ev("plan.stopped", reason="unit_rejected", unit=B, digest=world.digest(B)),
    )


def test_review_of_a_rejected_plan_with_the_same_spec_says_to_fix_the_cause(world, forge, capsys):
    rejected_world(world)
    assert world.l4("review", "p1") == 0
    out = capsys.readouterr().out
    assert (
        f"{B} was rejected and its spec has not changed: fix the cause" in out
        and "The configuration: nothing to review" in out
    )
    assert "stops the plan with inputs_changed and CI reviews it" in out and "review requested" not in out
    assert forge.called("start_run") == []


def test_review_of_a_rejected_plan_with_a_fixed_spec_says_ci_notices_it(world, forge, capsys):
    rejected_world(world)
    world.push({"openspec/changes/add-b/proposal.md": "# B, fixed\n"}, "fix b")
    assert world.l4("review", "p1", "--no-run") == 0
    out = capsys.readouterr().out
    assert f"the spec of {B} changed; the next run on main records inputs_changed and CI reviews the plan" in out


def test_activation_of_a_unit_that_stays_rejected_needs_a_fixed_spec_or_a_restart(world, monkeypatch, capsys):
    rejected_world(world)
    phases(monkeypatch, **{"openspec__add-b": "rejected"})
    assert world.l4("activate", "p1", "--reason", "again") == 2
    err = capsys.readouterr().err
    assert f"{B} was rejected, is still rejected and its spec has not changed" in err and "l4 restart --unit" in err
    phases(monkeypatch, **{"openspec__add-b": None})  # restarted: no phase, the plan may go on with it
    assert world.l4("activate", "p1", "--reason", "restarted", "--no-run") == 0


def test_status_of_a_rejected_plan_names_the_fix(world, capsys):
    rejected_world(world)
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert f"Next: fix the cause of the rejection of {B}: its spec (push it; the next run records inputs_changed" in out
    assert "or the configuration, then l4 yolo activate p1" in out


# --- #13: where the attempts of each unit start ---------------------------------------------------------------------


def test_activation_records_the_attempt_refs_each_unit_has(world):
    reviewed_world(world)
    attempt_refs(world, "add-greeting", 2)
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    activated = world.events()[-1]
    assert activated.data["attempt_base"] == {A: 2, B: 0}
    assert fold_plan("p1", world.events()).attempt_base == {A: 2, B: 0}
    assert ACTIVATED  # the world of the manage tests is the same plan
