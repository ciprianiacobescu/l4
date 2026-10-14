# ruff: noqa: F811
"""`l4 yolo review` and `l4 yolo activate` (L4-YOLO-005; SCN-YOLO-10, -11): the review request, the local review, every
refusal of activation and what activation records."""

import pytest

from l4.forge.base import ForgeError, ForgeUnavailable
from l4.yolo.digest import plan_digest
from l4.yolo.model import PlanMoved, ReviewResult, Verdict
from l4.yolo.store import PlanStore

from .yolo_cmd_world import A, B, auto_world, ev, forge, plan_doc, world  # noqa: F401


def reviewed_world(world, **kwargs):
    world.push_plan(**kwargs)
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), world.reviewed())
    return world


# --- review ---------------------------------------------------------------------------------------------------------


def test_review_asks_ci_to_review_and_starts_a_run(world, forge, capsys):
    world.push_plan()
    forge.script_start_run("started")
    assert world.l4("review", "p1") == 0
    out = capsys.readouterr().out
    assert "review requested" in out and "run started on main" in out
    assert [c.args for c in forge.called("start_run")] == [("main",)]
    assert world.store().read().head is None  # CI writes the review, not the command


def test_review_no_run_starts_nothing(world, forge):
    world.push_plan()
    assert world.l4("review", "p1", "--no-run") == 0
    assert forge.called("start_run") == []


def test_review_of_a_current_review_starts_no_run(world, forge, capsys):
    reviewed_world(world)
    assert world.l4("review", "p1") == 0
    assert "already reviewed" in capsys.readouterr().out
    assert forge.called("start_run") == []


def test_review_of_a_plan_that_is_not_admitted_says_so(world, forge, capsys):
    world.push_plan(plan_doc(target="release"))
    assert world.l4("review", "p1") == 2
    assert "not admitted" in capsys.readouterr().out
    assert forge.called("start_run") == []


def test_review_of_an_active_plan_is_refused(world, forge, capsys):
    reviewed_world(world)
    world.seed("p1", ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a", reason="r"))
    assert world.l4("review", "p1") == 2
    assert "p1 is active" in capsys.readouterr().err


def fake_judge(monkeypatch, verdicts):
    seen = {}

    def review(app, cfg, plan, units, *, git, rev, digest_of=None, **kw):
        seen["rev"] = rev
        result = {}
        for uid, info in units.items():
            result[uid] = Verdict(verdicts.get(uid, "READY"), digest=digest_of(git, rev, info.folder))
        return ReviewResult(result, {}), 0.25

    monkeypatch.setattr("l4.yolo.commands.review_plan_costed", review)
    return seen


def test_review_local_records_admitted_and_reviewed_like_ci(world, forge, monkeypatch, capsys):
    world.push_plan()
    fake_judge(monkeypatch, {B: "NEEDS_REVISION"})
    assert world.l4("review", "p1", "--local") == 0
    assert world.kinds() == ["plan.admitted", "plan.reviewed"]
    admitted, reviewed = world.events()
    assert admitted.data["order"] == [A, B] and admitted.data["plan_digest"] == plan_digest(world.plan_text)
    assert reviewed.data["plan_digest"] == plan_digest(world.plan_text)
    assert reviewed.data["units"][A] == {
        "verdict": "READY", "digest": world.digest(A), "findings": [], "assumptions": [], "missing": [],
    }  # fmt: skip
    assert reviewed.data["units"][B]["verdict"] == "NEEDS_REVISION" and reviewed.data["cost_usd"] == 0.25
    out = capsys.readouterr().out
    assert f"{B}: NEEDS_REVISION" in out
    assert forge.called("start_run") == []  # the review ran here


def test_review_local_of_a_refused_plan_records_plan_refused(world, monkeypatch, capsys):
    world.push_plan(plan_doc(target="release"))
    fake_judge(monkeypatch, {})
    assert world.l4("review", "p1", "--local") == 2
    assert world.kinds() == ["plan.refused"]
    assert world.events()[0].data["findings"][0]["code"] == "target_mismatch"


# --- activate: the refusals -----------------------------------------------------------------------------------------


def refused(world, capsys, *argv):
    capsys.readouterr()
    assert world.l4("activate", "p1", "--reason", "go", *argv) == 2
    return capsys.readouterr().err


def test_a_plan_never_reviewed_is_refused(world, capsys):
    world.push_plan()
    assert "has not been reviewed: run l4 yolo review p1" in refused(world, capsys)
    assert world.store().read().head is None


def test_a_review_for_older_inputs_is_refused(world, forge, capsys):
    """SCN-YOLO-10."""
    reviewed_world(world)
    world.push(
        {
            "openspec/changes/add-b/specs/b/spec.md": "## ADDED Requirements\n\n### Requirement: B counts\n"
            "The `count()` function SHALL return 2.\n\n#### Scenario: Counting\n- **WHEN** `count()` is called\n"
            "- **THEN** it returns 2\n"
        }
    )
    before = world.kinds()
    assert "review is for other inputs: run l4 yolo review p1" in refused(world, capsys)
    assert world.kinds() == before and forge.called("start_run") == []


def test_a_review_for_another_plan_file_is_refused(world, capsys):
    reviewed_world(world)
    world.push_plan(plan_doc(limits={"max_cost_usd": 99}))
    assert "review is for other inputs" in refused(world, capsys)


def test_a_harness_tick_does_not_make_the_review_stale(world, forge, capsys):
    reviewed_world(world)
    world.push(
        {
            "openspec/changes/add-b/tasks.md": "## 1. B\n\n- [x] 1.1 Add `count()`\n",
            "openspec/changes/add-b/verification.md": "ok\n",
        }
    )
    forge.script_start_run("started")
    assert world.l4("activate", "p1", "--reason", "go") == 0


def test_units_not_ready_are_named_with_the_first_line_of_their_findings(world, capsys):
    world.push_plan()
    findings = {B: [{"criterion": "contradiction", "severity": "blocking", "text": "B contradicts A\nsecond line"}]}
    world.seed("p1", world.reviewed({B: "NEEDS_REVISION"}, findings))
    err = refused(world, capsys)
    assert f"{B}: NEEDS_REVISION: contradiction: B contradicts A" in err
    assert "second line" not in err and A not in err.replace(B, "")


def test_a_batch_that_is_not_ready_is_named(world, capsys):
    world.push_plan()
    event = world.reviewed()
    event.data["batches"] = {"b1": {"verdict": "BLOCKED", "digest": None, "findings": []}}
    world.seed("p1", event)
    assert "batch b1: BLOCKED: no finding recorded" in refused(world, capsys)


def test_merge_auto_against_a_human_merge_policy_is_refused(world, capsys):
    reviewed_world(world, doc=plan_doc(merge="auto"))
    err = refused(world, capsys)
    assert "not admitted" in err and "merge_policy: merge: auto needs forge.merge_policy: auto" in err


def test_a_target_missing_on_origin_is_refused(world, monkeypatch, capsys):
    reviewed_world(world)
    import l4.yolo.commands as commands

    monkeypatch.setattr(commands, "_branch_on_origin", lambda ctx, branch: False)
    monkeypatch.setattr(commands, "_sync", lambda ctx, who: ctx.git.rev_parse("refs/remotes/origin/main") or "")
    world.clone.run("fetch", "origin")
    assert "the target main is not on origin" in refused(world, capsys)


def test_another_plan_active_on_the_target_is_refused(world, capsys):
    reviewed_world(world)
    other = plan_doc({A: []}, plan_id="p2")
    world.push({".l4/plans/p2.json": __import__("json").dumps(other)})
    world.seed("p2", ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a", reason="r"))
    err = refused(world, capsys)
    assert "plan p2 is already active, waiting or stopped on main" in err and "l4 yolo cancel p2" in err


def test_an_active_plan_is_not_activated_twice(world, capsys):
    reviewed_world(world)
    world.seed("p1", ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a", reason="r"))
    assert "p1 is already active" in refused(world, capsys)


def test_a_cancelled_plan_cannot_be_activated(world, capsys):
    reviewed_world(world)
    world.seed("p1", ev("plan.cancelled", by="a", reason="r"))
    assert "p1 is cancelled" in refused(world, capsys)


def test_a_plan_stopped_for_another_reason_points_at_resume(world, capsys):
    reviewed_world(world)
    world.seed(
        "p1",
        ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a", reason="r"),
        ev("plan.stopped", reason="unit_escalated", unit=A),
    )
    assert "l4 yolo resume p1 --reason TEXT" in refused(world, capsys)


def test_a_reason_is_required(world, capsys):
    reviewed_world(world)
    assert world.l4("activate", "p1", "--reason", "  ") == 2
    assert "--reason must say why" in capsys.readouterr().err


# --- activate: success ----------------------------------------------------------------------------------------------


def test_activation_freezes_the_inputs_and_starts_a_run(world, forge, capsys):
    """SCN-YOLO-11."""
    reviewed_world(world)
    forge.script_start_run("started")
    assert world.l4("activate", "p1", "--reason", "go") == 0
    activated = world.events()[-1]
    assert activated.type == "plan.activated"
    assert activated.data["digests"] == {A: world.digest(A), B: world.digest(B)}
    assert activated.data["plan_digest"] == plan_digest(world.plan_text)
    assert activated.data["limits"]["max_cost_usd"] == 40 and activated.data["limits"]["max_unit_attempts"] == 2
    assert activated.data["by"] == "alex@example.com" and activated.data["reason"] == "go"
    assert [c.args for c in forge.called("start_run")] == [("main",)]
    assert "run started on main" in capsys.readouterr().out


def test_no_run_activates_without_starting_one(world, forge):
    reviewed_world(world)
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    assert world.kinds()[-1] == "plan.activated" and forge.called("start_run") == []


@pytest.mark.parametrize("failure", [ForgeUnavailable("no token"), ForgeError("HTTP 422", status=422)])
def test_a_start_that_fails_prints_the_manual_way_and_exits_0(world, forge, monkeypatch, capsys, failure):
    reviewed_world(world)

    def fails(ref):
        raise failure

    monkeypatch.setattr(forge, "start_run", fails)
    assert world.l4("activate", "p1", "--reason", "go") == 0
    assert "start a run with: " in capsys.readouterr().out
    assert world.kinds()[-1] == "plan.activated"


def test_a_merge_auto_plan_activates_when_the_policy_agrees(auto_world, forge):
    reviewed_world(auto_world, doc=plan_doc(merge="auto"))
    assert auto_world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    assert auto_world.events()[-1].data["merge"] == "auto"


def test_a_stopped_plan_is_activated_again_after_inputs_changed_and_keeps_its_usage(world, forge):
    reviewed_world(world)
    world.seed(
        "p1",
        ev("plan.activated", plan_digest="x", digests={A: "old"}, limits={}, by="a", reason="r"),
        ev("plan.charged", unit=A, cost_usd=3.0, runs=1, attempts=1),
        ev("plan.stopped", reason="inputs_changed", unit=A),
    )
    world.seed("p1", world.reviewed())
    assert world.l4("activate", "p1", "--reason", "again", "--no-run") == 0
    from l4.yolo.state import fold_plan

    state = fold_plan("p1", world.events())
    assert state.status == "active" and state.used.cost_usd == 3.0 and state.digests[A] == world.digest(A)


def test_a_lost_lease_says_the_plan_moved(world, monkeypatch, capsys):
    reviewed_world(world)
    original = PlanStore.append

    def raced(self, events, *, files=None, expect):
        other = PlanStore(world.remote_clone(), "p1")
        original(other, [ev("plan.waiting", reason="x")], expect=other.read().head)
        return original(self, events, files=files, expect=expect)

    monkeypatch.setattr(PlanStore, "append", raced)
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 2
    assert "the plan moved: run the command again" in capsys.readouterr().err
    assert "plan.activated" not in world.kinds()
    assert PlanMoved  # the exception the message comes from
