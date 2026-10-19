# ruff: noqa: F811
"""`l4 yolo review` and `l4 yolo activate` (L4-YOLO-005; SCN-YOLO-10, -11): the review request, the local review, every
refusal of activation and what activation records."""

import pytest
import yaml

from l4.forge.base import ForgeError, ForgeUnavailable
from l4.yolo.digest import current_unit_digest, plan_digest
from l4.yolo.model import PlanMoved, ReviewResult, Verdict
from l4.yolo.readiness import PROMPT_VERSION
from l4.yolo.store import PlanStore

from .yolo_actor import person  # noqa: F401
from .yolo_cmd_world import PURPOSE_B, A, B, auto_world, ev, forge, plan_doc, world  # noqa: F401


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


def fake_judge(monkeypatch, verdicts, materials=None, findings=None, batches=None):
    """A judge that answers `verdicts` (default READY); `materials` and `findings` give a unit's verdict the material
    key and the findings of an acceptance, `batches` the batch verdicts (default none: a batch is not reviewed)."""
    seen = {}

    def review(app, cfg, plan, units, *, git, rev, digest_of=None, **kw):  # the judge's own digest rule (R3)
        seen["rev"] = rev
        result = {}
        for uid, info in units.items():
            digest = current_unit_digest(git, cfg, uid, info.folder, rev)
            result[uid] = Verdict(
                verdicts.get(uid, "READY"),
                tuple((findings or {}).get(uid, ())),
                digest=digest,
                material=(materials or {}).get(uid),
            )
        return ReviewResult(result, dict(batches or {})), 0.25

    monkeypatch.setattr("l4.yolo.commands.review_plan_costed", review)
    return seen


def test_review_local_records_admitted_and_reviewed_like_ci(world, forge, monkeypatch, capsys):
    world.push_plan()
    fake_judge(monkeypatch, {B: "NEEDS_REVISION"})
    assert world.l4("review", "p1", "--local") == 0
    assert world.kinds() == ["plan.admitted", "plan.reviewed", "plan.charged"]
    admitted, reviewed, charged = world.events()
    assert charged.data == {"unit": "plan:review", "attempt": 0, "cost_usd": 0.25, "runs": 0}  # R1
    assert admitted.data["order"] == [A, B] and admitted.data["plan_digest"] == plan_digest(world.plan_text)
    assert reviewed.data["plan_digest"] == plan_digest(world.plan_text)
    assert reviewed.data["prompt_version"] == PROMPT_VERSION
    assert reviewed.data["units"][A] == {
        "verdict": "READY", "digest": world.digest(A), "findings": [], "assumptions": [], "missing": [],
    }  # fmt: skip
    assert reviewed.data["units"][B]["verdict"] == "NEEDS_REVISION" and reviewed.data["cost_usd"] == 0.25
    out = capsys.readouterr().out
    assert f"{B}: NEEDS_REVISION" in out
    assert forge.called("start_run") == []  # the review ran here


def test_review_local_names_a_holding_acceptance_and_says_activate(world, forge, monkeypatch, capsys):
    """SCN-YOLO-175, the --local part."""
    from .yolo_review_events import TESTABILITY

    world.push_plan()
    world.seed(
        "p1",
        ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]),
        accepted_event(B, "mb", [TESTABILITY]),
    )
    fake_judge(monkeypatch, {B: "NEEDS_REVISION"}, {B: "mb"}, {B: [TESTABILITY]}, {"b1": Verdict("READY")})
    assert world.l4("review", "p1", "--local") == 0
    out = capsys.readouterr().out
    assert f"  {B}: NEEDS_REVISION: " in out
    assert "(accepted by alex@example.com: it does not stop the activation)" in out
    assert "Next: l4 yolo activate p1 --reason TEXT" in out
    fake_judge(monkeypatch, {B: "NEEDS_REVISION"}, {B: "other"}, {B: [TESTABILITY]}, {"b1": Verdict("READY")})
    capsys.readouterr()
    assert world.l4("review", "p1", "--local") == 0
    out = capsys.readouterr().out
    assert "accepted by" not in out and "Next: l4 yolo findings p1" in out  # another material: not held


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
            "openspec/changes/add-b/specs/b/spec.md": PURPOSE_B + "## ADDED Requirements\n\n### Requirement: B counts\n"
            "The `count()` function SHALL return 2.\n\n#### Scenario: Counting\n- **WHEN** `count()` is called\n"
            "- **THEN** it returns 2\n"
        }
    )
    before = world.kinds()
    err = refused(world, capsys)
    assert "activate: the review of p1 is stale against origin/main (" in err and "Fix: l4 yolo review p1" in err
    assert world.kinds() == before and forge.called("start_run") == []


def test_a_review_for_another_plan_file_is_refused(world, capsys):
    reviewed_world(world)
    world.push_plan(plan_doc(limits={"max_cost_usd": 99}))
    assert "activate: the review of p1 is stale against origin/main (" in refused(world, capsys)


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
    assert err.rstrip().endswith("Next: l4 yolo findings p1")


def test_the_line_of_an_item_is_its_most_severe_finding_not_the_first(world, capsys):
    world.push_plan()
    findings = {
        B: [
            {"criterion": "outcome", "severity": "minor", "text": "minor first"},
            {"criterion": "testability", "severity": "major", "text": "major second"},
        ]
    }
    world.seed("p1", world.reviewed({B: "NEEDS_REVISION"}, findings))
    err = refused(world, capsys)
    assert f"{B}: NEEDS_REVISION: testability: major second" in err and "minor first" not in err


def test_a_current_review_that_is_not_ready_names_the_findings_command(world, forge, capsys):
    world.push_plan()
    findings = {B: [{"criterion": "testability", "severity": "major", "text": "no scenario"}]}
    world.seed("p1", world.reviewed({B: "NEEDS_REVISION"}, findings))
    assert world.l4("review", "p1") == 0
    out = capsys.readouterr().out
    assert f"{B}: NEEDS_REVISION: testability: no scenario" in out
    assert out.rstrip().endswith("Next: l4 yolo findings p1")


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
    other = plan_doc({"openspec:elsewhere": []}, plan_id="p2")  # review #15: a unit p2 shares would be held by p2
    world.push({".l4/plans/p2.json": __import__("json").dumps(other)})
    world.seed("p2", ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a", reason="r"))
    err = refused(world, capsys)
    assert "plan p2 is already active, waiting or stopped on main" in err and "l4 yolo cancel p2" in err


def test_a_unit_the_active_plan_lists_is_held_by_it_so_the_other_plan_is_not_admitted(world, capsys):  # review #15
    reviewed_world(world)
    other = plan_doc({A: []}, plan_id="p2")
    world.push({".l4/plans/p2.json": __import__("json").dumps(other)})
    world.seed("p2", ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a", reason="r"))
    assert "held_by_other_plan: unit " + A + " is already listed in plan p2" in refused(world, capsys)


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


# --- acceptances (L4-YOLO-027; SCN-YOLO-62, -66), `accepted: {}` (SCN-YOLO-11), --local ----------------------


def accepted_event(subject, material, findings, *, by="alex@example.com", actor="person", marker=None, reason="go on"):
    from l4.yolo.findings import findings_sha

    return ev(
        "plan.accepted", subject=subject, material=material, findings=findings, findings_sha=findings_sha(findings),
        reason=reason, by=by, actor=actor, marker=marker, verdict="NEEDS_REVISION", prompt_version=PROMPT_VERSION,
    )  # fmt: skip


def accepting_world(world, *events):
    from .yolo_review_events import FAILURES, TESTABILITY, two_rounds

    world.push_plan()
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]))
    two_rounds(world, [TESTABILITY, FAILURES])
    if events:
        world.seed("p1", *events)
    return world


def test_activation_without_acceptances_records_an_empty_accepted(world, forge):
    """SCN-YOLO-11."""
    reviewed_world(world)
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    assert world.events()[-1].data["accepted"] == {}


def test_an_acceptance_that_holds_clears_the_item_and_is_listed(world, forge, capsys):
    """SCN-YOLO-62, the activation part."""
    from .yolo_review_events import FAILURES, TESTABILITY

    both = [TESTABILITY, FAILURES]
    accepting_world(world, accepted_event(A, "m2", both, reason="keep the thresholds"))
    capsys.readouterr()
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    assert (
        "accepted: openspec:add-greeting by alex@example.com (person): keep the thresholds" in capsys.readouterr().out
    )
    assert world.events()[-1].data["accepted"] == {
        A: {"findings": both, "reason": "keep the thresholds", "by": "alex@example.com", "actor": "person"}
    }


def test_agent_acceptances_come_before_a_persons(world, forge, capsys):
    from .yolo_review_events import FAILURES, TESTABILITY, entry, review

    accepting_world(world)
    world.seed(
        "p1",
        review(
            world,
            "2026-10-14T12:00:00Z",
            {
                A: entry(world, A, "NEEDS_REVISION", [FAILURES], "ma3"),
                B: entry(world, B, "NEEDS_REVISION", [TESTABILITY], "mb"),
            },
        ),
        accepted_event(A, "ma3", [FAILURES], reason="ra"),
        accepted_event(B, "mb", [TESTABILITY], by="bot", actor="agent", marker="CLAUDECODE", reason="rb"),
    )
    capsys.readouterr()
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    out = capsys.readouterr().out
    assert out.index(f"accepted: {B}") < out.index(f"accepted: {A}")
    assert (
        "(accepted by an agent)" in out.split(f"accepted: {A}")[0]
        and "(accepted by an agent)" not in out.split(f"accepted: {A}")[1].splitlines()[0]
    )


def test_a_change_of_the_material_voids_the_acceptance(world, capsys):
    """SCN-YOLO-66."""
    from .yolo_review_events import FAILURES, TESTABILITY, entry, review

    accepting_world(world, accepted_event(A, "m2", [TESTABILITY, FAILURES]))
    world.seed("p1", review(world, "2026-10-14T12:00:00Z", {A: entry(world, A, "NEEDS_REVISION", [TESTABILITY], "m3")}))
    err = refused(world, capsys)
    assert f"{A}: NEEDS_REVISION: testability:" in err
    assert "(the acceptance by alex@example.com was for other material: accepted on material m2 with findings " in err
    assert err.rstrip().endswith("Next: l4 yolo findings p1")


def test_status_shows_the_acceptance_under_the_item_and_in_json(world, capsys):
    import json

    from .yolo_review_events import FAILURES, TESTABILITY

    accepting_world(world, accepted_event(A, "m2", [TESTABILITY, FAILURES], reason="keep the thresholds"))
    capsys.readouterr()
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert f"{A}: accepted by alex@example.com (person): keep the thresholds" in out
    assert "review: current" in out and f"{A}: NEEDS_REVISION" not in out
    assert "l4 yolo activate p1" in out  # the acceptance cleared the item
    assert world.l4("status", "p1", "--json") == 0
    review = json.loads(capsys.readouterr().out)["plans"][0]["review"]
    assert review["problems"] == []
    assert review["accepted"] == [
        {"subject": A, "by": "alex@example.com", "actor": "person", "reason": "keep the thresholds", "holds": True}
    ]


def test_review_local_passes_a_sandbox_chooser_and_records_the_label(world, forge, monkeypatch, capsys):
    world.push_plan()
    monkeypatch.setattr("l4.yolo.judge_sandbox.resolve_tool", lambda *a, **k: None)  # no bwrap on PATH
    config = yaml.safe_load(world.app.config_path.read_text(encoding="utf-8"))
    config["sandbox"] = {"mode": "bwrap"}
    world.app.config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    seen = {}

    def review(app, cfg, plan, units, *, git, rev, sandbox_for=None, **kw):
        seen["sandbox"] = sandbox_for("claude-code", "main")
        digests = {uid: current_unit_digest(git, cfg, uid, info.folder, rev) for uid, info in units.items()}
        return ReviewResult({u: Verdict("READY", digest=d, material=f"k-{u}") for u, d in digests.items()}, {}), 0.1

    monkeypatch.setattr("l4.yolo.commands.review_plan_costed", review)
    assert world.l4("review", "p1", "--local") == 0
    out = capsys.readouterr().out
    assert "judge unsandboxed (bwrap was not found on PATH): it has no tools and runs in an empty folder" in out
    reviewed = next(e for e in world.events() if e.type == "plan.reviewed")
    assert (
        reviewed.data["source"] == "local" and reviewed.data["sandbox"] == "none" and reviewed.data["judge"] == "main"
    )
    assert reviewed.data["units"][A]["material"] == f"k-{A}"


# --- activate: a force acceptance (L4-YOLO-061; SCN-YOLO-163 to -165) --------------------------------------

FORCE_REASON = "the judge is down; build as written"
A_SPEC = "openspec/changes/add-greeting/specs/greeting/spec.md"
A_SPEC_EDITED = (
    "## Purpose\n\nThe greeting capability of the simulator fixture: a greeting names the person it greets.\n\n"
    "## ADDED Requirements\n\n### Requirement: Greet by name\nThe `greet(name)` function SHALL return "
    "`Hello, <name>!` for a non-blank name.\n\n#### Scenario: Named greeting\n"
    '- **WHEN** `greet("Ada")` is called\n- **THEN** it returns `"Hello, Ada!"`\n'
)


def force_accept(world, reason=FORCE_REASON):
    assert world.l4("accept", "p1", "--all", "--force", "--reason", reason) == 0


def test_a_force_accepted_plan_never_reviewed_activates(world, forge, person, capsys):
    """SCN-YOLO-163."""
    world.push_plan()
    force_accept(world)
    capsys.readouterr()
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    out = capsys.readouterr().out
    for subject in (A, B, "batch:b1"):
        assert f"{subject}: force-accepted without review by alex@example.com ({FORCE_REASON})" in out
    assert out.index("force-accepted without review") < out.index("activated on")
    activated = world.events()[-1]
    assert activated.type == "plan.activated" and activated.data["review"] == "force_accepted"
    item = {"findings": [], "reason": FORCE_REASON, "by": "alex@example.com", "actor": "person", "force": True}
    assert activated.data["accepted"] == {A: item, B: item, "batch:b1": item}


def test_a_later_blocked_review_does_not_undo_it(world, forge, person):
    """SCN-YOLO-164."""
    world.push_plan()
    force_accept(world)
    blocked = {"criterion": "schema", "severity": "blocking", "text": "schema_invalid: ok"}
    world.seed("p1", world.reviewed({A: "BLOCKED"}, findings={A: [blocked]}))
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    activated = world.events()[-1]
    assert activated.data["accepted"][A]["force"] is True and activated.data["review"] == "force_accepted"


def test_a_voided_force_acceptance_is_named_in_the_refusal(world, forge, person, capsys):
    """SCN-YOLO-165."""
    world.push_plan()
    force_accept(world)
    world.push({A_SPEC: A_SPEC_EDITED}, "A's spec changes")
    before = world.kinds()
    err = refused(world, capsys)
    assert "has not been reviewed: run l4 yolo review p1" in err
    assert (
        "the force acceptance by alex@example.com no longer holds for openspec:add-greeting, batch:b1: "
        "their spec or the plan file changed" in err
    )
    assert 'Fix: l4 yolo review p1, or a person runs l4 yolo accept p1 --all --force --reason "..." again' in err
    assert world.kinds() == before


def test_a_ready_subject_of_a_force_acceptance_is_not_cleared_later(world, forge, person, capsys):
    from .yolo_review_events import TESTABILITY

    reviewed_world(world)  # every subject is READY at the current inputs: the force acceptance overrides nothing
    force_accept(world)
    world.push({A_SPEC: A_SPEC_EDITED}, "A's spec changes")
    world.seed("p1", world.reviewed({B: "NEEDS_REVISION"}, findings={B: [TESTABILITY]}))
    err = refused(world, capsys)
    assert f"{B}: NEEDS_REVISION: testability:" in err
    assert "the force acceptance by alex@example.com no longer holds for openspec:add-greeting, batch:b1" in err


def test_activation_without_force_has_no_review_key(world, forge):
    reviewed_world(world)
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    assert "review" not in world.events()[-1].data


def test_status_names_the_force_acceptance_and_says_activate(world, forge, person, capsys):
    """SCN-YOLO-166, the status part."""
    import json

    world.push_plan()
    blocked = {"criterion": "schema", "severity": "blocking", "text": "schema_invalid: ok"}
    world.seed(
        "p1",
        ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]),
        world.reviewed({A: "BLOCKED"}, findings={A: [blocked]}),
    )
    force_accept(world)
    capsys.readouterr()
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert "  review: current (force-accepted: no review is needed to activate)" in out
    assert f"    {A}: force-accepted without review by alex@example.com ({FORCE_REASON})" in out
    assert f"{A}: BLOCKED" not in out and f"{B}: force-accepted" not in out  # B was READY: it overrode nothing
    assert out.rstrip().endswith("Next: l4 yolo activate p1 --reason TEXT")
    assert world.l4("status", "p1", "--json") == 0
    plan = json.loads(capsys.readouterr().out)["plans"][0]
    force = plan["review"]["force_accepted"]
    assert (force["by"], force["actor"], force["reason"], force["covered"]) == (
        "alex@example.com", "person", FORCE_REASON, True,
    )  # fmt: skip
    assert force["at"]
    by_subject = {s["subject"]: s for s in force["subjects"]}
    assert set(by_subject) == {A, B, "batch:b1"}
    assert by_subject[A] == {
        "subject": A, "holds": True, "skipped": ["blocked"], "review_at": "2026-10-14T10:00:00Z", "verdict": "BLOCKED",
    }  # fmt: skip
    assert by_subject[B]["skipped"] == [] and plan["activated_force"] == []
    # a spec change voids it for A and its batch
    world.push({A_SPEC: A_SPEC_EDITED}, "A's spec changes")
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert f"    {A}: force-accepted without review by alex@example.com ({FORCE_REASON}); no longer holds: " in out
    assert "Next: l4 yolo review p1" in out and "(force-accepted: no review is needed" not in out
    assert world.l4("status", "p1", "--json") == 0
    voided = json.loads(capsys.readouterr().out)["plans"][0]["review"]["force_accepted"]
    assert voided["covered"] is False
    assert {s["subject"]: s["holds"] for s in voided["subjects"]} == {A: False, B: True, "batch:b1": False}


def test_status_after_activation_lists_the_force_items(world, forge, person, capsys):
    import json

    world.push_plan()
    force_accept(world)
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    capsys.readouterr()
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    at = lines.index("  activated by alex@example.com")
    expected = [
        f"  {s}: force-accepted without review by alex@example.com ({FORCE_REASON})" for s in (A, B, "batch:b1")
    ]
    assert sorted(lines[at + 1 : at + 4]) == sorted(expected)  # the ledger sorts the subjects, not the plan order
    assert world.l4("status", "p1", "--json") == 0
    plan = json.loads(capsys.readouterr().out)["plans"][0]
    assert sorted(plan["activated_force"], key=lambda x: x["subject"]) == sorted(
        ({"subject": s, "by": "alex@example.com", "reason": FORCE_REASON} for s in (A, B, "batch:b1")),
        key=lambda x: x["subject"],
    )
