# ruff: noqa: F811
"""`l4 yolo status|cancel|resume|report` (L4-YOLO-013, L4-YOLO-015; SCN-YOLO-26): the plan as an operator reads it, the
cancel, the report, and every refusal of a resume (design D10's table)."""

import json
from datetime import UTC, datetime

import l4.yolo.commands as commands
from l4.yolo.digest import plan_digest
from l4.yolo.model import PlanState
from l4.yolo.state import fold_plan

from .yolo_cmd_world import A, B, ev, forge, plan_doc, world  # noqa: F401

ACTIVATED = ev("plan.activated", plan_digest="x", digests={}, by="alex@example.com", reason="go",
               limits={"max_cost_usd": 10.0, "max_runs": 5, "max_unit_attempts": 2, "deadline": None})  # fmt: skip


def active_world(world, *events):
    world.push_plan()
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), world.reviewed(),
               ACTIVATED, *events)  # fmt: skip
    return world


def phases(monkeypatch, **by_unit):
    """The phases `_read_units` reports (a unit branch with a crafted ledger is not needed to test the table)."""
    real = commands._read_units

    def fake(ctx, rev, wanted, *, intake):
        units = real(ctx, rev, wanted, intake=intake)
        units.phases.update({k.replace("__", ":"): v for k, v in by_unit.items()})
        return units

    monkeypatch.setattr(commands, "_read_units", fake)


# --- status -----------------------------------------------------------------------------------------------------------


def test_status_of_a_reviewed_plan_says_to_activate(world, capsys):
    world.push_plan()
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), world.reviewed())
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert "plan p1: reviewed (target main, merge: human)" in out
    assert f"{B}: not started; held by plan p1 (reviewed)" in out
    assert "Next: l4 yolo activate p1 --reason TEXT" in out


def test_status_of_a_plan_with_no_review_says_to_review(world, capsys):
    world.push_plan()
    assert world.l4("status", "p1") == 0
    assert "Next: l4 yolo review p1" in capsys.readouterr().out


def test_status_of_a_plan_not_ready_says_to_fix_the_specs(world, capsys):
    world.push_plan()
    world.seed("p1", world.reviewed({B: "BLOCKED"}))
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert (
        f"{B}: BLOCKED" in out
        and (
            "Next: l4 yolo findings p1: fix the specs it names and push them, "
            "or review the working tree first (l4 yolo review p1 --worktree)"
        )
        in out
    )


def test_status_of_a_plan_that_is_not_active_says_how_many_units_it_holds(world, capsys):
    world.push_plan()
    assert world.l4("status", "p1") == 0
    assert "holds 2 units; none of them runs until the plan is fixed, completed or its file is removed" in (
        capsys.readouterr().out
    )
    assert world.l4("status", "p1", "--json") == 0
    assert json.loads(capsys.readouterr().out)["plans"][0]["holds"] == 2


def test_status_of_an_active_plan_shows_units_batches_usage_and_waits(world, capsys):
    active_world(
        world,
        ev("unit.dispatched", unit=A, run="r1"),
        ev("plan.charged", unit=A, cost_usd=2.5, runs=1, attempts=1),
    )
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert "plan p1: active" in out and "activated by alex@example.com" in out
    assert f"{A}: not started (current)" in out
    assert f"{B}: not started; waits for {A} (not integrated)" in out
    assert "b1: pending" in out
    assert "usage: $2.50 of $10.00; runs 1 of 5; attempts " + A + " 1 (limit 2 each)" in out
    assert "Next: nothing: CI advances the plan" in out


def test_status_shows_an_integrated_unit_and_a_merged_one(world, capsys):
    active_world(
        world,
        ev("unit.dispatched", unit=A),
        ev("unit.merged", unit=A, head="a" * 40, merge_commit="a" * 40),
        ev("unit.integrated", unit=A, revision="b" * 40),
    )
    assert world.l4("status", "p1") == 0
    assert f"{A}: integrated at {'b' * 10}" in capsys.readouterr().out


def test_status_of_a_stopped_plan_names_the_cause_and_what_clears_it(world, monkeypatch, capsys):
    active_world(world, ev("unit.dispatched", unit=B),
                 ev("plan.stopped", reason="unit_escalated", detail="fix rounds used 3/3", unit=B))  # fmt: skip
    phases(monkeypatch, **{"openspec__add-b": "escalated"})
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert f"stopped: unit_escalated [{B}]: fix rounds used 3/3" in out
    assert f"Next: l4 retry --unit {B} --reason TEXT, then l4 yolo resume p1 --reason TEXT" in out


def test_status_of_a_stopped_plan_whose_cause_is_gone_says_resume(world, monkeypatch, capsys):
    active_world(world, ev("plan.stopped", reason="unit_escalated", unit=B))
    phases(monkeypatch, **{"openspec__add-b": "verifying"})
    assert world.l4("status", "p1") == 0
    assert "Next: l4 yolo resume p1 --reason TEXT" in capsys.readouterr().out


def test_status_of_an_inputs_changed_stop_says_review_again_when_the_spec_moved_on(world, capsys):
    active_world(world, ev("plan.stopped", reason="inputs_changed", unit=B))
    world.push({"openspec/changes/add-b/proposal.md": "# B, reworded\n"})
    assert world.l4("status", "p1") == 0
    assert "Next: l4 yolo review p1" in capsys.readouterr().out


def test_status_of_an_inputs_changed_stop_says_activate_once_it_is_reviewed_again(world, capsys):
    active_world(world, ev("plan.stopped", reason="inputs_changed", unit=B))
    assert world.l4("status", "p1") == 0
    assert "Next: l4 yolo activate p1 --reason TEXT" in capsys.readouterr().out


def test_status_json(world, capsys):
    active_world(world, ev("unit.dispatched", unit=A), ev("plan.charged", unit=A, cost_usd=1.0, runs=1, attempts=1))
    assert world.l4("status", "p1", "--json") == 0
    [plan] = json.loads(capsys.readouterr().out)["plans"]
    assert plan["status"] == "active" and plan["usage"]["cost_limit"] == 10.0 and plan["units"][0]["current"]
    assert plan["batches"] == [{"id": "b1", "units": [A, B], "result": "pending", "revision": None, "detail": None}]


def test_status_without_a_plan_lists_every_plan_file(world, capsys):
    world.push_plan()
    world.push({".l4/plans/p2.json": json.dumps(plan_doc({A: []}, plan_id="p2"))})
    assert world.l4("status") == 0
    out = capsys.readouterr().out
    assert "plan p1: new" in out and "plan p2: new" in out


def test_status_of_an_unknown_plan(world, capsys):
    assert world.l4("status", "nope") == 2
    assert "no plan nope" in capsys.readouterr().err


# --- cancel -----------------------------------------------------------------------------------------------------------


def test_cancel_records_who_and_why(world, capsys):
    active_world(world)
    assert world.l4("cancel", "p1", "--reason", "wrong scope") == 0
    event = world.events()[-1]
    assert event.type == "plan.cancelled" and event.data == {"by": "alex@example.com", "reason": "wrong scope"}
    assert fold_plan("p1", world.events()).status == "cancelled"


def test_cancel_of_a_final_plan_is_refused(world, capsys):
    active_world(world, ev("plan.cancelled", by="a", reason="r"))
    before = world.kinds()
    assert world.l4("cancel", "p1", "--reason", "again") == 2
    assert "p1 is already cancelled" in capsys.readouterr().err and world.kinds() == before


def test_cancel_of_a_plan_with_no_record_says_how_to_drop_it(world, capsys):
    world.push_plan()
    assert world.l4("cancel", "p1", "--reason", "x") == 2
    assert "remove .l4/plans/p1.json" in capsys.readouterr().err


# --- report -----------------------------------------------------------------------------------------------------------


def test_report_prints_the_report_of_the_ref(world, capsys):
    active_world(world)
    store = world.store()
    report = "# Plan p1\nPromotion to main was not performed\n"
    store.append([ev("plan.waiting", reason="x")], files={"report.md": report}, expect=store.read().head)
    assert world.l4("report", "p1") == 0
    assert "Promotion to main was not performed" in capsys.readouterr().out


def test_report_without_a_report(world, capsys):
    active_world(world)
    assert world.l4("report", "p1") == 0
    assert capsys.readouterr().out.strip() == "no report yet"


# --- resume -----------------------------------------------------------------------------------------------------------


def resume(world, capsys, *argv, code=2):
    capsys.readouterr()
    assert world.l4("resume", "p1", "--reason", "x", *argv) == code
    return capsys.readouterr().err if code else capsys.readouterr().out


def test_resume_is_refused_while_the_unit_is_still_escalated(world, monkeypatch, capsys):
    """SCN-YOLO-26."""
    active_world(world, ev("plan.stopped", reason="unit_escalated", unit=B))
    phases(monkeypatch, **{"openspec__add-b": "escalated"})
    before = world.kinds()
    assert "resume: openspec:add-b is still escalated: run l4 retry --unit openspec:add-b first" in resume(
        world, capsys
    )
    assert world.kinds() == before


def test_resume_is_refused_while_the_unit_is_still_halted(world, monkeypatch, capsys):
    active_world(world, ev("plan.stopped", reason="unit_halted", unit=B))
    phases(monkeypatch, **{"openspec__add-b": "halted"})
    assert "is still halted: run l4 retry --unit openspec:add-b first" in resume(world, capsys)


def test_resume_goes_once_the_unit_moved_and_starts_a_run(world, monkeypatch, forge, capsys):
    active_world(world, ev("plan.stopped", reason="unit_escalated", unit=B))
    phases(monkeypatch, **{"openspec__add-b": "verifying"})
    forge.script_start_run("started")
    assert world.l4("resume", "p1", "--reason", "retried") == 0
    event = world.events()[-1]
    assert event.type == "plan.resumed" and event.data["reason"] == "retried" and event.data["extend"] == {}
    assert fold_plan("p1", world.events()).status == "active"
    assert [c.args for c in forge.called("start_run")] == [("main",)]


def test_resume_no_run(world, monkeypatch, forge):
    active_world(world, ev("plan.stopped", reason="merge_refused", unit=A))
    assert world.l4("resume", "p1", "--reason", "protection lifted", "--no-run") == 0
    assert forge.called("start_run") == []


def test_resume_of_an_abandoned_unit_needs_a_reopened_pr_or_a_restart(world, monkeypatch, capsys):
    active_world(world, ev("plan.stopped", reason="unit_abandoned", unit=B))
    phases(monkeypatch, **{"openspec__add-b": "abandoned"})
    err = resume(world, capsys)
    assert "is still abandoned" in err and "l4 restart --unit openspec:add-b" in err


def test_resume_never_clears_a_changed_spec(world, capsys):
    active_world(world, ev("plan.stopped", reason="inputs_changed", unit=B))
    assert "run l4 yolo review p1, then l4 yolo activate p1" in resume(world, capsys)


def test_resume_of_a_rejected_unit_says_to_fix_the_cause_first(world, capsys):  # review #8
    active_world(world, ev("plan.stopped", reason="unit_rejected", unit=B))
    err = resume(world, capsys)
    assert "openspec:add-b was rejected: fix the cause, its spec (push it" in err
    assert "the next run stops the plan with inputs_changed and CI reviews it) or the configuration" in err
    assert "then l4 yolo activate p1" in err


def test_resume_waits_for_the_questions(world, monkeypatch, capsys):
    active_world(world, ev("unit.dispatched", unit=B), ev("plan.waiting", reason="awaiting_human", unit=B))
    phases(monkeypatch, **{"openspec__add-b": "awaiting_human"})
    assert "openspec:add-b is still awaiting_human" in resume(world, capsys)


def test_resume_of_a_waiting_plan_goes_when_capacity_is_back(world, monkeypatch, capsys):
    active_world(world, ev("unit.dispatched", unit=B), ev("plan.waiting", reason="waiting_capacity", unit=B))
    phases(monkeypatch, **{"openspec__add-b": "implementing"})
    assert world.l4("resume", "p1", "--reason", "back", "--no-run") == 0


def test_resume_after_capacity_needs_fix_is_allowed(world, monkeypatch, capsys):
    """SCN-YOLO-91: the cause is gone once a probe succeeds, so the resume goes and the next run probes."""
    active_world(world, ev("unit.dispatched", unit=B), ev("plan.stopped", reason="capacity_needs_fix", unit=B))
    phases(monkeypatch, **{"openspec__add-b": "waiting_capacity"})
    assert world.l4("resume", "p1", "--reason", "key renewed", "--no-run") == 0
    assert fold_plan("p1", world.events()).status == "active"


def test_resume_of_an_active_plan_is_refused(world, capsys):
    active_world(world)
    assert "p1 is active: only a stopped or waiting plan resumes" in resume(world, capsys)


def test_resume_of_a_missing_target_is_refused_while_it_is_missing(world, monkeypatch, capsys):
    active_world(world, ev("plan.stopped", reason="target_missing"))
    monkeypatch.setattr(commands, "_branch_on_origin", lambda ctx, branch: False)
    assert "the target branch is still missing on origin" in resume(world, capsys)


# the limits: refused unless the matching --extend-* raises the limit above the usage


def test_a_cost_limit_needs_more_money(world, monkeypatch, capsys):
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)  # a person raises a limit (L4-YOLO-051)
    active_world(world, ev("plan.charged", unit=A, cost_usd=10.0, runs=1, attempts=1),
                 ev("plan.stopped", reason="limit_cost"))  # fmt: skip
    err = resume(world, capsys)
    assert "has reached the limit $10.00: raise it with --extend-cost USD" in err
    assert "has reached the limit" in resume(world, capsys, "--extend-runs", "3")  # the wrong limit does not help
    assert world.l4("resume", "p1", "--reason", "more", "--extend-cost", "5", "--no-run") == 0
    state = fold_plan("p1", world.events())
    assert state.status == "active" and state.extended.cost_usd == 5.0
    assert world.events()[-1].data["extend"] == {"cost_usd": 5.0}


def test_an_extension_that_does_not_clear_the_usage_is_refused(world, monkeypatch, capsys):
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)  # a person raises a limit (L4-YOLO-051)
    active_world(
        world, ev("plan.charged", unit=A, cost_usd=14.0, runs=1, attempts=1), ev("plan.stopped", reason="limit_cost")
    )
    assert "has reached the limit $14.00" in resume(world, capsys, "--extend-cost", "4")  # 10 + 4 = 14, not above


def test_the_runs_limit(world, monkeypatch, capsys):
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)  # a person raises a limit (L4-YOLO-051)
    active_world(
        world, ev("plan.charged", unit=A, cost_usd=1.0, runs=5, attempts=1), ev("plan.stopped", reason="limit_runs")
    )
    assert "5 runs have reached the limit 5: raise it with --extend-runs N" in resume(world, capsys)
    assert world.l4("resume", "p1", "--reason", "more", "--extend-runs", "2", "--no-run") == 0
    assert fold_plan("p1", world.events()).extended.runs == 2


def test_the_attempts_limit_of_the_stopped_unit(world, monkeypatch, capsys):
    """SCN-YOLO-27's stop: a unit restarted twice used 3 attempts against a limit of 2."""
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)  # a person raises a limit (L4-YOLO-051)
    active_world(world, ev("plan.charged", unit=B, attempt=3, cost_usd=1.0, runs=3),
                 ev("plan.stopped", reason="limit_attempts", unit=B))  # fmt: skip
    assert "openspec:add-b used 3 attempts, the limit is 2: raise it with --extend-attempts N" in resume(world, capsys)
    assert world.l4("resume", "p1", "--reason", "one more", "--extend-attempts", "1", "--no-run") == 0
    assert fold_plan("p1", world.events()).extended.attempts == {"*": 1}


def test_the_deadline(world, monkeypatch, capsys):
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)  # a person raises a limit (L4-YOLO-051)
    doc = plan_doc(limits={"deadline": "2026-10-20T18:00:00Z"})
    world.push_plan(doc)
    activated = ev("plan.activated", plan_digest="x", digests={}, by="a", reason="r",
                   limits={"deadline": "2026-10-20T18:00:00Z", "max_unit_attempts": 2})  # fmt: skip
    world.seed("p1", world.reviewed(), activated, ev("plan.stopped", reason="limit_deadline"))
    monkeypatch.setattr(commands, "_now", lambda: datetime(2026, 10, 21, tzinfo=UTC))
    assert "the deadline 2026-10-20T18:00:00Z has passed" in resume(world, capsys)
    assert "has passed" in resume(world, capsys, "--extend-deadline", "2026-10-20T20:00:00Z")
    assert world.l4("resume", "p1", "--reason", "later", "--extend-deadline", "2026-10-25T00:00:00Z", "--no-run") == 0
    assert world.events()[-1].data["extend"] == {"deadline": "2026-10-25T00:00:00Z"}


def test_a_bad_extension_is_a_usage_error(world, capsys):
    active_world(world, ev("plan.stopped", reason="limit_cost"))
    assert "--extend-cost must be more than 0" in resume(world, capsys, "--extend-cost", "-1")
    assert "not an ISO 8601 time" in resume(world, capsys, "--extend-deadline", "tomorrow")


def test_resume_blocker_is_pure_and_total():
    state = PlanState(plan_id="p1", status="stopped", stop_reason="something_new")
    assert commands.resume_blocker("p1", state, [], None, {}, commands.Extend()) is None  # an unknown cause: --reason


def _legacy_review_world(world, *events):
    """A plan reviewed under the first review prompt (no prompt_version in the ledger), activated, then `events`."""
    world.push_plan()
    old = world.reviewed()
    old.data.pop("prompt_version")
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), old,
               ev("plan.activated", plan_digest=plan_digest(world.plan_text), digests={A: world.digest(A),
                  B: world.digest(B)}, limits={"max_runs": 1}, by="a", reason="r"), *events)  # fmt: skip
    return world


def test_a_limit_stop_after_an_activation_under_an_older_prompt_shows_no_stale_review(world, capsys):
    """LOW-4: the plan needs a resume, not a new review; the note about the prompt is for a plan that needs one."""
    _legacy_review_world(world, ev("plan.charged", unit=A, attempt=1, cost_usd=0.0, runs=1),
                         ev("plan.stopped", reason="limit_runs", detail="1 of 1 runs", unit=A))  # fmt: skip
    capsys.readouterr()
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert "stale" not in out and "the review prompt changed" not in out and "review: current" in out


def test_inputs_changed_after_an_older_prompt_review_still_asks_for_a_new_review(world, capsys):
    _legacy_review_world(world, ev("plan.stopped", reason="inputs_changed", detail="plan", unit=None))
    capsys.readouterr()
    assert world.l4("status", "p1") == 0
    assert "review: stale (the review prompt changed)" in capsys.readouterr().out


def test_the_next_line_of_a_limit_stop_is_one_resume_command(world, capsys):
    """LOW-5: `l4 yolo resume p1 --reason TEXT --extend-runs N`, not that command followed by a second resume."""
    active_world(
        world, ev("plan.charged", unit=A, cost_usd=1.0, runs=5, attempts=1), ev("plan.stopped", reason="limit_runs")
    )
    capsys.readouterr()
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    nxt = next(line for line in out.splitlines() if line.startswith("Next:"))
    assert nxt == "Next: l4 yolo resume p1 --reason TEXT --extend-runs N"


# --- a limit of an active plan, by a person (L4-YOLO-050, L4-YOLO-051) ------------------------------------------


def tty(monkeypatch, on: bool = True):
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: on)


def agent_env(world, marker="CLAUDECODE"):
    world.app.environ[marker] = "1"


ALLOW_EXTEND = {".l4/config.yaml": "yolo:\n  extend_by_agents: true\n"}


def runs_world(world, used=82, limit=90):
    """An active plan with `limit` runs, `used` of them charged."""
    activated = ev("plan.activated", plan_digest="x", digests={}, by="alex@example.com", reason="go",
                   limits={"max_runs": limit, "max_unit_attempts": 2})  # fmt: skip
    world.push_plan()
    charge = ev("plan.charged", unit=A, attempt=1, cost_usd=1.0, runs=used)
    admitted = ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B])
    world.seed("p1", admitted, world.reviewed(), activated, ev("unit.dispatched", unit=A), charge)
    return world


def test_scn_yolo_130_a_run_limit_of_an_active_plan_is_raised_before_the_stop(world, monkeypatch, forge, capsys):
    runs_world(world)
    tty(monkeypatch)
    capsys.readouterr()
    code = world.l4("resume", "p1", "--reason", "three units left", "--extend-runs", "20")
    out = capsys.readouterr().out
    assert code == 0
    last = world.events()[-1]
    assert last.type == "plan.extended" and last.data["actor"] == "person" and last.data["agent_key"] is False
    assert last.data["reason"] == "three units left" and last.data["extend"] == {"runs": 20}
    assert last.data["limits_before"]["runs"] == 90 and last.data["limits_after"]["runs"] == 110
    assert "plan.resumed" not in world.kinds() and forge.called("start_run") == []
    assert fold_plan("p1", world.events()).status == "active"
    assert "runs 90 -> 110" in out and "nothing resumed and no run started" in out


def test_scn_yolo_130_a_limit_table_names_all_four_figures(world, monkeypatch):
    runs_world(world)
    tty(monkeypatch)
    assert world.l4("resume", "p1", "--reason", "more", "--extend-runs", "2", "--extend-attempts", "1") == 0
    before, after = world.events()[-1].data["limits_before"], world.events()[-1].data["limits_after"]
    assert set(before) == set(after) == {"cost_usd", "runs", "attempts", "deadline"}
    assert (before["attempts"], after["attempts"]) == (2, 3) and after["runs"] == 92


def test_no_run_does_not_matter_for_an_extension_of_an_active_plan(world, monkeypatch, forge):
    runs_world(world)
    tty(monkeypatch)
    assert world.l4("resume", "p1", "--reason", "more", "--extend-runs", "2", "--no-run") == 0
    assert forge.called("start_run") == []


def test_scn_yolo_132_an_active_plan_is_not_resumed_without_an_extension(world, monkeypatch, capsys):
    runs_world(world)
    tty(monkeypatch)
    before = world.kinds()
    err = resume(world, capsys)
    assert "p1 is active: only a stopped or waiting plan resumes" in err
    for option in ("--extend-cost", "--extend-runs", "--extend-attempts", "--extend-deadline"):
        assert option in err
    assert world.kinds() == before


def test_scn_yolo_133_an_extension_that_changes_no_limit_is_refused(world, monkeypatch, capsys):
    tty(monkeypatch)
    world.push_plan(plan_doc(limits={}))
    activated = ev("plan.activated", plan_digest="x", digests={}, by="a", reason="r",
                   limits={"deadline": "2026-10-20T18:00:00Z", "max_unit_attempts": 2})  # fmt: skip
    world.seed("p1", world.reviewed(), activated)
    before = world.kinds()
    assert "p1 has no run limit: --extend-runs changes nothing" in resume(world, capsys, "--extend-runs", "5")
    assert "p1 has no cost limit: --extend-cost changes nothing" in resume(world, capsys, "--extend-cost", "5")
    err = resume(world, capsys, "--extend-deadline", "2026-10-20T12:00:00Z")
    assert "--extend-deadline 2026-10-20T12:00:00Z is not later than the deadline in force 2026-10-20T18:00:00Z" in err
    assert world.kinds() == before


def test_scn_yolo_133_a_plan_without_a_deadline_is_not_given_one_by_an_extension(world, monkeypatch, capsys):
    runs_world(world)
    tty(monkeypatch)
    err = resume(world, capsys, "--extend-deadline", "2026-10-25T00:00:00Z")
    assert "p1 has no deadline: --extend-deadline sets none" in err and world.kinds()[-1] != "plan.extended"


def test_scn_yolo_134_an_agent_cannot_raise_a_limit_of_an_active_or_a_stopped_plan(world, monkeypatch, capsys):
    tty(monkeypatch, False)
    agent_env(world)
    runs_world(world)
    before = world.kinds()
    err = resume(world, capsys, "--extend-runs", "5")
    assert "resume: raising a plan's limits is a person's decision (CLAUDECODE is set)" in err
    assert 'Fix: a person runs: l4 yolo resume p1 --reason "..." --extend-runs 5' in err
    assert "yolo.extend_by_agents: true" in err and world.kinds() == before
    world.seed("p1", ev("plan.stopped", reason="limit_runs"))  # the same plan, stopped
    stopped = world.kinds()
    err = resume(world, capsys, "--extend-runs", "5", "--extend-attempts", "1")
    assert "raising a plan's limits is a person's decision" in err
    assert 'Fix: a person runs: l4 yolo resume p1 --reason "..." --extend-runs 5 --extend-attempts 1' in err
    assert world.kinds() == stopped


def test_an_agent_without_a_terminal_and_without_a_marker_is_told_the_terminal(world, monkeypatch, capsys):
    tty(monkeypatch, False)
    runs_world(world)
    assert "(stdin is not a terminal)" in resume(world, capsys, "--extend-runs", "5")


def test_a_resume_of_a_stopped_plan_without_an_extension_is_still_an_agents_to_make(world, monkeypatch):
    tty(monkeypatch, False)
    agent_env(world)
    active_world(world, ev("plan.stopped", reason="merge_refused", unit=A))
    assert world.l4("resume", "p1", "--reason", "protection lifted", "--no-run") == 0


def test_the_key_lets_an_agent_raise_the_limit_of_an_active_plan_and_the_event_says_so(world, monkeypatch):
    tty(monkeypatch, False)
    agent_env(world)
    runs_world(world)
    world.push(ALLOW_EXTEND, "agents may extend")
    assert world.l4("resume", "p1", "--reason", "three units left", "--extend-runs", "20") == 0
    event = world.events()[-1]
    assert event.type == "plan.extended" and event.data["extend"] == {"runs": 20}
    assert (event.data["actor"], event.data["marker"], event.data["agent_key"]) == ("agent", "CLAUDECODE", True)


def stopped_at_runs(world):
    return active_world(
        world, ev("plan.charged", unit=A, cost_usd=1.0, runs=5, attempts=1), ev("plan.stopped", reason="limit_runs")
    )


def test_the_key_lets_an_agent_resume_a_stopped_plan_with_more_runs_and_the_event_says_so(world, monkeypatch):
    tty(monkeypatch, False)
    agent_env(world, "AI_AGENT")
    active_world(
        world, ev("plan.charged", unit=A, cost_usd=1.0, runs=5, attempts=1), ev("plan.stopped", reason="limit_runs")
    )
    world.push(ALLOW_EXTEND, "agents may extend")
    assert world.l4("resume", "p1", "--reason", "more", "--extend-runs", "2", "--no-run") == 0
    event = world.events()[-1]
    assert event.type == "plan.resumed" and event.data["extend"] == {"runs": 2}
    assert (event.data["actor"], event.data["marker"], event.data["agent_key"]) == ("agent", "AI_AGENT", True)


def test_a_person_extension_of_a_stopped_plan_records_the_actor_and_no_key(world, monkeypatch):
    tty(monkeypatch)
    active_world(
        world, ev("plan.charged", unit=A, cost_usd=1.0, runs=5, attempts=1), ev("plan.stopped", reason="limit_runs")
    )
    assert world.l4("resume", "p1", "--reason", "more", "--extend-runs", "2", "--no-run") == 0
    event = world.events()[-1]
    assert (event.data["actor"], event.data["agent_key"]) == ("person", False)


def test_the_key_is_read_from_the_base_branch_and_false_keeps_the_refusal(world, monkeypatch, capsys):
    tty(monkeypatch, False)
    agent_env(world)
    runs_world(world)
    world.push({".l4/config.yaml": "yolo:\n  extend_by_agents: false\n"}, "agents may not extend")
    assert "a person's decision" in resume(world, capsys, "--extend-runs", "5")


def test_scn_yolo_136_the_status_shows_the_extension_and_the_next_line_names_the_option(world, monkeypatch, capsys):
    runs_world(world)
    tty(monkeypatch)
    assert world.l4("resume", "p1", "--reason", "three units left", "--extend-runs", "20") == 0
    capsys.readouterr()
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert "runs 82 of 110" in out
    assert "extended: runs 90 -> 110 by alex@example.com (person): three units left" in out
    assert "Next: nothing: CI advances the plan at each run" in out
    assert "l4 yolo resume p1 --reason TEXT --extend-runs N" in out
    assert world.l4("status", "p1", "--json") == 0
    (plan,) = json.loads(capsys.readouterr().out)["plans"]
    (ext,) = plan["extensions"]
    assert ext["extend"] == {"runs": 20} and ext["limits_before"]["runs"] == 90 and ext["limits_after"]["runs"] == 110
    assert (ext["actor"], ext["agent_key"], ext["reason"]) == ("person", False, "three units left")


def test_the_status_of_a_plan_never_extended_lists_no_extension(world, capsys):
    runs_world(world)
    assert world.l4("status", "p1", "--json") == 0
    (plan,) = json.loads(capsys.readouterr().out)["plans"]
    assert plan.get("extensions", []) == []


# --- after an answer (L4-YOLO-052, L4-YOLO-053) ----------------------------------------------------------------------


def answered(monkeypatch, *units):
    """Wrap `commands._read_units` like `phases()` and mark `units` as answered: their answers are pushed and no run
    has read them."""
    real = commands._read_units

    def fake(ctx, rev, wanted, *, intake):
        found = real(ctx, rev, wanted, intake=intake)
        found.answered.update(units)
        return found

    monkeypatch.setattr(commands, "_read_units", fake)


def halted_for(monkeypatch, unit, reason):
    """Wrap `commands._read_units` and give `unit` the halt reason its ledger would show."""
    real = commands._read_units

    def fake(ctx, rev, wanted, *, intake):
        found = real(ctx, rev, wanted, intake=intake)
        found.halt_reasons[unit] = reason
        return found

    monkeypatch.setattr(commands, "_read_units", fake)


def waiting_for_answer(world, monkeypatch, detail="the unit waits for an answer (open: Q-003)"):
    active_world(
        world, ev("unit.dispatched", unit=B), ev("plan.waiting", reason="unit_awaiting_human", unit=B, detail=detail)
    )
    phases(monkeypatch, **{"openspec__add-b": "awaiting_human"})


def test_scn_yolo_137_the_resume_of_a_waiting_plan_goes_once_the_answer_is_pushed(world, monkeypatch, forge, capsys):
    waiting_for_answer(world, monkeypatch)
    answered(monkeypatch, B)
    forge.script_start_run("started")
    assert world.l4("resume", "p1", "--reason", "answered") == 0
    assert world.events()[-1].type == "plan.resumed" and world.events()[-1].data["reason"] == "answered"
    assert fold_plan("p1", world.events()).status == "active"
    assert [c.args for c in forge.called("start_run")] == [("main",)]


def test_scn_yolo_138_an_open_question_still_refuses_the_resume_and_the_refusal_says_what_happens(
    world, monkeypatch, capsys
):
    waiting_for_answer(world, monkeypatch)
    before = world.kinds()
    err = resume(world, capsys)
    assert (
        "openspec:add-b is still awaiting_human: answer its questions first (l4 questions --unit openspec:add-b)" in err
    )
    assert "continues by itself at the run that reads the answer" in err and "no resume is needed" in err
    assert world.kinds() == before


def test_scn_yolo_139_the_status_of_a_plan_that_waits_for_an_answer_does_not_send_the_person_to_a_resume(
    world, monkeypatch, capsys
):
    waiting_for_answer(world, monkeypatch)
    assert world.l4("status", "p1") == 0
    nxt = capsys.readouterr().out.split("Next: ", 1)[1]
    assert "l4 questions --unit openspec:add-b" in nxt
    assert "l4 questions answer Q-NNN --unit openspec:add-b --text TEXT" in nxt
    assert "pushes the answer and starts a run" in nxt and "continues by itself" in nxt
    assert "l4 yolo resume" not in nxt


def test_scn_yolo_140_the_status_after_the_answer_says_the_next_run_reads_it_and_how_to_start_it(
    world, monkeypatch, capsys
):
    waiting_for_answer(world, monkeypatch)
    answered(monkeypatch, B)
    monkeypatch.setattr(commands, "how_to_start", lambda app, cfg, base: f"gh workflow run l4.yml --ref {base}")
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    nxt = out.split("Next: ", 1)[1]
    assert "the answers of openspec:add-b are pushed and the next run reads them" in nxt
    assert "the plan then continues by itself" in nxt
    assert "l4 yolo resume p1 --reason TEXT" in nxt and "gh workflow run l4.yml --ref main" in nxt
    assert "answer the questions" not in nxt


def test_the_status_after_the_answer_shows_the_live_reason_not_the_stale_open_question(world, monkeypatch, capsys):
    """Owner decision 8: the wait detail recorded when the plan began to wait said `open: Q-003`."""
    waiting_for_answer(world, monkeypatch)
    assert world.l4("status", "p1") == 0
    assert "(open: Q-003)" in capsys.readouterr().out  # while the question is open, the recorded detail stands
    answered(monkeypatch, B)
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert "(open: Q-003)" not in out
    assert "waiting: unit_awaiting_human: the answer is recorded and the next run reads it" in out
    assert world.l4("status", "p1", "--json") == 0
    (plan,) = json.loads(capsys.readouterr().out)["plans"]
    assert (
        plan["wait"] == "unit_awaiting_human"
        and plan["wait_detail"] == "the answer is recorded and the next run reads it"
    )


def test_an_answer_for_another_unit_does_not_change_the_wait_detail(world, monkeypatch, capsys):
    waiting_for_answer(world, monkeypatch)
    answered(monkeypatch, A)
    assert world.l4("status", "p1") == 0
    assert "(open: Q-003)" in capsys.readouterr().out


# --- a plan stopped on a unit escalated with its own way out (owner decision 6) --------------------------------------


def test_a_plan_stopped_on_judge_view_rejected_names_the_units_way_out_before_the_retry(world, monkeypatch, capsys):
    active_world(world, ev("plan.stopped", reason="unit_escalated", unit=B))
    phases(monkeypatch, **{"openspec__add-b": "escalated"})
    halted_for(monkeypatch, B, "judge_view_rejected")
    err = resume(world, capsys)
    assert "resume: openspec:add-b is still escalated: a fix unit cannot shrink the diff" in err
    assert "l4 restart --unit openspec:add-b" in err and "--replace" in err
    assert world.l4("status", "p1") == 0
    nxt = capsys.readouterr().out.split("Next: ", 1)[1]
    assert nxt.startswith("a fix unit cannot shrink the diff the judge could not see")
    assert nxt.index("l4 restart --unit openspec:add-b") < nxt.index("l4 retry --unit openspec:add-b")
    assert nxt.rstrip().endswith("then l4 yolo resume p1 --reason TEXT")


def test_a_plan_stopped_on_a_unit_escalated_for_another_reason_still_says_retry_first(world, monkeypatch, capsys):
    active_world(world, ev("plan.stopped", reason="unit_escalated", unit=B))
    phases(monkeypatch, **{"openspec__add-b": "escalated"})
    halted_for(monkeypatch, B, "fix_rounds_exhausted")
    assert "is still escalated: run l4 retry --unit openspec:add-b first" in resume(world, capsys)
