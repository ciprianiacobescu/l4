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
    assert f"{B}: BLOCKED" in out and "Next: fix the specs named above, push them, then l4 yolo review p1" in out


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


def test_resume_of_an_active_plan_is_refused(world, capsys):
    active_world(world)
    assert "p1 is active: only a stopped or waiting plan resumes" in resume(world, capsys)


def test_resume_of_a_missing_target_is_refused_while_it_is_missing(world, monkeypatch, capsys):
    active_world(world, ev("plan.stopped", reason="target_missing"))
    monkeypatch.setattr(commands, "_branch_on_origin", lambda ctx, branch: False)
    assert "the target branch is still missing on origin" in resume(world, capsys)


# the limits: refused unless the matching --extend-* raises the limit above the usage


def test_a_cost_limit_needs_more_money(world, capsys):
    active_world(world, ev("plan.charged", unit=A, cost_usd=10.0, runs=1, attempts=1),
                 ev("plan.stopped", reason="limit_cost"))  # fmt: skip
    err = resume(world, capsys)
    assert "has reached the limit $10.00: raise it with --extend-cost USD" in err
    assert "has reached the limit" in resume(world, capsys, "--extend-runs", "3")  # the wrong limit does not help
    assert world.l4("resume", "p1", "--reason", "more", "--extend-cost", "5", "--no-run") == 0
    state = fold_plan("p1", world.events())
    assert state.status == "active" and state.extended.cost_usd == 5.0
    assert world.events()[-1].data["extend"] == {"cost_usd": 5.0}


def test_an_extension_that_does_not_clear_the_usage_is_refused(world, capsys):
    active_world(
        world, ev("plan.charged", unit=A, cost_usd=14.0, runs=1, attempts=1), ev("plan.stopped", reason="limit_cost")
    )
    assert "has reached the limit $14.00" in resume(world, capsys, "--extend-cost", "4")  # 10 + 4 = 14, not above


def test_the_runs_limit(world, capsys):
    active_world(
        world, ev("plan.charged", unit=A, cost_usd=1.0, runs=5, attempts=1), ev("plan.stopped", reason="limit_runs")
    )
    assert "5 runs have reached the limit 5: raise it with --extend-runs N" in resume(world, capsys)
    assert world.l4("resume", "p1", "--reason", "more", "--extend-runs", "2", "--no-run") == 0
    assert fold_plan("p1", world.events()).extended.runs == 2


def test_the_attempts_limit_of_the_stopped_unit(world, capsys):
    """SCN-YOLO-27's stop: a unit restarted twice used 3 attempts against a limit of 2."""
    active_world(world, ev("plan.charged", unit=B, attempt=3, cost_usd=1.0, runs=3),
                 ev("plan.stopped", reason="limit_attempts", unit=B))  # fmt: skip
    assert "openspec:add-b used 3 attempts, the limit is 2: raise it with --extend-attempts N" in resume(world, capsys)
    assert world.l4("resume", "p1", "--reason", "one more", "--extend-attempts", "1", "--no-run") == 0
    assert fold_plan("p1", world.events()).extended.attempts == {"*": 1}


def test_the_deadline(world, monkeypatch, capsys):
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
