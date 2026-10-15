"""The third review of yolo-mode, admission and activation (L4-YOLO-002, -013, -017): a plan that edits itself after its
first integration is admitted with its own ledger (H1), an excluded archived change is known (M4), a re-activation drops
a current unit that has a new prerequisite (H2), and a unit that left the plan stops nothing with its attempts (L1)."""

import json
from datetime import UTC, datetime

import pytest

from l4.config.schema import L4Config
from l4.exitcodes import ExitCode
from l4.yolo.admit import admit, done_units, next_eligible, unit_blocker
from l4.yolo.commands import Extend, resume_blocker
from l4.yolo.digest import plan_digest
from l4.yolo.limits import reached_at
from l4.yolo.model import Plan, PlanState, UnitInfo, load_plan
from l4.yolo.plans import archived_at, archived_changes
from l4.yolo.readiness import PROMPT_VERSION
from l4.yolo.state import fold_plan

from .yolo_cmd_world import A as CA
from .yolo_cmd_world import B as CB
from .yolo_cmd_world import ev as cev
from .yolo_cmd_world import forge, plan_doc  # noqa: F401
from .yolo_cmd_world import world as cmd_world  # noqa: F401
from .yolo_cycle_world import CycleWorld, ev, unit_id

A, B, C = unit_id("a"), unit_id("b"), unit_id("c")


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


@pytest.fixture
def abc(tmp_path):
    return CycleWorld(tmp_path, units=("a", "b", "c"))


def st(w, pid="p1"):
    return fold_plan(pid, w.events(pid))


# --- pure admission ------------------------------------------------------------------------------------------------


def make_plan(batches, **extra) -> Plan:
    raw = {"schema": "l4/delivery-plan@1", "plan_id": "p1", "target": "staging", "merge": "human", "batches": batches}
    plan = load_plan(json.dumps({**raw, **extra}))
    assert isinstance(plan, Plan), plan
    return plan


def cfg() -> L4Config:
    return L4Config.model_validate({"forge": {"base_branch": "staging", "merge_policy": "human"}})


def abc_plan(**extra) -> Plan:
    return make_plan(
        [{"id": "b1", "units": [{"id": "a"}, {"id": "b", "depends_on": ["a"]}, {"id": "c", "depends_on": ["b"]}]}],
        **extra,
    )


def info(unit, **over) -> UnitInfo:
    return UnitInfo(id=unit, folder=f"f/{unit}", **over)


def codes(result) -> list[tuple[str, str]]:
    return [(f.code, f.subject) for f in result.findings]


def test_a_unit_the_plan_integrated_is_not_finished_when_the_plan_is_admitted_again():
    state = PlanState(plan_id="p1", integrated={"a": "r1"})
    known = {"a": info("a", phase="merged"), "b": info("b"), "c": info("c")}
    result = admit(abc_plan(), known_units=known, cfg=cfg(), state=state)
    assert result.ok and result.order == ("a", "b", "c")


def test_a_unit_the_plan_merged_is_not_finished_either():
    state = PlanState(plan_id="p1", merged={"a": "h1"})
    known = {"a": info("a", phase="merged"), "b": info("b"), "c": info("c")}
    assert admit(abc_plan(), known_units=known, cfg=cfg(), state=state).ok


def test_an_integrated_unit_whose_change_was_archived_is_no_unknown_unit_and_still_a_dependency():
    state = PlanState(plan_id="p1", integrated={"a": "r1"})
    known = {"b": info("b"), "c": info("c")}  # no provider finds a: its folder moved to the archive
    result = admit(abc_plan(), known_units=known, cfg=cfg(), state=state)
    assert result.ok and result.order == ("a", "b", "c")  # b still waits for a in the graph


def test_a_done_unit_has_no_open_question_or_intake_finding():
    state = PlanState(plan_id="p1", integrated={"a": "r1"})
    known = {"a": info("a", open_questions=("q1",), intake_ok=False), "b": info("b"), "c": info("c")}
    assert admit(abc_plan(), known_units=known, cfg=cfg(), state=state).ok


def test_the_other_units_of_the_plan_are_still_checked():
    state = PlanState(plan_id="p1", integrated={"a": "r1"})
    known = {"b": info("b", phase="merged"), "c": info("c", open_questions=("q",))}
    result = admit(abc_plan(), known_units=known, cfg=cfg(), state=state)
    assert codes(result) == [("finished", "b"), ("open_questions", "c")]


def test_a_unit_that_depends_on_a_done_unit_the_plan_dropped_is_still_refused():
    plan = make_plan([{"id": "b1", "units": [{"id": "b", "depends_on": ["a"]}]}])
    state = PlanState(plan_id="p1", integrated={"a": "r1"})
    result = admit(plan, known_units={"b": info("b")}, cfg=cfg(), state=state)
    assert codes(result) == [("unknown_dependency", "b")]


@pytest.mark.parametrize("state", [None, PlanState(plan_id="p1"), PlanState(plan_id="p1", integrated={"z": "r"})])
def test_a_fresh_plan_that_lists_a_merged_unit_is_still_refused(state):
    known = {"a": info("a", phase="merged"), "b": info("b"), "c": info("c")}
    result = admit(abc_plan(), known_units=known, cfg=cfg(), state=state)
    assert codes(result) == [("finished", "a")]


@pytest.mark.parametrize("state", [None, PlanState(plan_id="p1")])
def test_a_fresh_plan_that_lists_an_archived_unit_is_still_unknown(state):
    result = admit(abc_plan(), known_units={"b": info("b"), "c": info("c")}, cfg=cfg(), state=state)
    assert codes(result) == [("unknown_unit", "a")]


def test_the_units_of_the_plan_that_the_ledger_marks_done():
    state = PlanState(plan_id="p1", integrated={"a": "r"}, merged={"b": "h", "gone": "h"})
    assert done_units(abc_plan(), state) == {"a", "b"} and done_units(abc_plan(), None) == frozenset()


def test_an_excluded_change_archived_at_the_target_is_known():
    plan = make_plan(
        [{"id": "b1", "units": [{"id": "a"}]}],
        exclude=[{"id": "openspec:old", "reason": "already merged"}, {"id": "openspec:ghost", "reason": "?"}],
    )
    result = admit(plan, known_units={"a": info("a")}, cfg=cfg(), archived={"openspec:old"})
    assert codes(result) == [("unknown_unit", "openspec:ghost")]
    assert admit(plan, known_units={"a": info("a")}, cfg=cfg()).findings[0].subject == "openspec:old"


# --- archived_changes: the rule of scripts/validate_plan.py --------------------------------------------------------


def test_the_archived_changes_of_a_revision_follow_the_rule_of_the_plan_validator(world):
    base = "openspec/changes/archive"
    world.commit(
        {
            f"{base}/2026-10-01-old-thing/proposal.md": "x\n",
            f"{base}/2026-10-02-two-words-here/proposal.md": "x\n",
            f"{base}/no-date-here/proposal.md": "x\n",
            f"{base}/2026-10-03-a-file": "not a folder\n",
            "elsewhere/changes/archive/2026-10-04-other-root/proposal.md": "x\n",
        },
        "archive",
    )
    world.push_main()
    got = archived_changes(world.git, "origin/main", "openspec")
    assert got == {"openspec:old-thing", "openspec:two-words-here"}
    assert archived_changes(world.git, "origin/main", "elsewhere") == {"openspec:other-root"}
    for root in ("", "/openspec", "../openspec", "missing"):
        assert archived_changes(world.git, "origin/main", root) == frozenset()
    assert archived_at(world.git, "origin/main", world.cfg) == got


# --- H1: the step and the commands admit the plan with its own ledger -----------------------------------------------


def x5(w, variant):
    """The update flow on a plan that integrated `a`: the person adds `c`; the step stops the plan; CI reviews it."""
    w.plan(batches=[{"id": "b1", "units": [{"id": A}, {"id": B, "depends_on": [A]}]}])
    w.activate(order=[A, B])
    w.seed(
        ev("unit.dispatched", unit=A, run="r0"),
        ev("unit.merged", unit=A, head="h", merge_commit=w.tip()),
        ev("unit.integrated", unit=A, revision=w.tip()),
    )
    snaps = {"b": w.snapshot("b", "implementing")}
    if variant == "merged":
        snaps["a"] = w.snapshot("a", "merged")
    else:
        w.units = ["b", "c"]  # a was archived: no provider finds it any more
    w.step(snaps)
    text = w.plan(batches=[{"id": "b1", "units": [{"id": A}, {"id": B, "depends_on": [A]}, {"id": C}]}])
    w.step(snaps)
    assert (st(w).status, st(w).stop_reason) == ("stopped", "inputs_changed")
    return text, snaps


@pytest.mark.parametrize("variant", ["merged", "archived"])
def test_a_plan_that_integrated_a_unit_is_reviewed_activated_again_and_dispatches_the_new_unit(abc, variant):
    world = abc
    text, snaps = x5(world, variant)
    world.step(snaps)  # CI reviews the edited plan
    got = st(world)
    assert got.findings == [] and got.review_plan_digest == plan_digest(text)
    assert {A, B, C} <= set(got.review) and set(got.review.values()) == {"READY"}  # the review covers a, b and c
    names = ["b", "c"] + (["a"] if variant == "merged" else [])
    world.seed(
        ev(
            "plan.activated",
            plan_digest=plan_digest(text),
            digests=world.digests(names),
            limits={},
            by="alice",
            reason="c added",
            current=B,
        )  # fmt: skip
    )
    assert st(world).status == "active" and set(st(world).integrated) == {A}
    # b finishes; the new unit c is what the plan dispatches next
    world.seed(
        ev("unit.merged", unit=B, head="hb", merge_commit=world.tip()),
        ev("unit.integrated", unit=B, revision=world.tip()),
    )
    snaps["b"] = world.snapshot("b", "merged")
    snaps["c"] = world.snapshot("c", None)
    step = world.step(snaps)
    assert step.allow == frozenset({C}) and st(world).current == C


def test_the_judge_is_not_asked_about_a_unit_the_plan_already_integrated(abc):
    world = abc
    asked = []
    original = world.judge.run

    def counting(request, *a, **kw):
        asked.append(request)
        return original(request, *a, **kw)

    world.judge.run = counting
    text, snaps = x5(world, "archived")
    before = len(asked)
    world.step(snaps)
    assert len(asked) - before == 3  # b, c and the batch: not a


def test_a_fresh_plan_that_lists_an_archived_unit_is_refused_by_the_step(world):
    world.units = ["b"]
    world.plan(batches=[{"id": "b1", "units": [{"id": A}, {"id": B}]}], deps={})
    world.step({"b": world.snapshot("b", None)})
    got = st(world)
    assert got.status == "refused" and [f["code"] for f in got.findings] == ["unknown_unit"]


# --- the commands: check, review and activate pass the ledger ---------------------------------------------------------


def push_archive_of_a(w):
    """The archive pull request of A: its folder moves to `changes/archive/<date>-add-greeting`."""
    w.clone.run("pull", "--quiet", "--ff-only", "origin", "main")
    root = w.app.repo
    (root / "openspec/changes/archive").mkdir(parents=True, exist_ok=True)
    w.clone.run("mv", "openspec/changes/add-greeting", "openspec/changes/archive/2026-10-01-add-greeting")
    w.clone.run("commit", "-q", "-m", "archive add-greeting")
    w.clone.run("push", "-q", "origin", "main")


def integrated_a_ledger(w):
    w.seed(
        "p1",
        cev("plan.admitted", plan_digest="old", order=[CA, CB], merge="human"),
        cev("plan.reviewed", plan_digest="old", units={}, batches={}),
        cev("plan.activated", plan_digest="old", digests={}, limits={}, by="a", reason="r"),
        cev("unit.dispatched", unit=CA, run="r0"),
        cev("unit.merged", unit=CA, head="h", merge_commit="m"),
        cev("unit.integrated", unit=CA, revision="m"),
        cev("plan.stopped", reason="inputs_changed", unit="plan"),
    )


def test_check_review_and_activate_accept_a_plan_that_integrated_an_archived_unit(cmd_world, forge, capsys):  # noqa: F811
    w = cmd_world
    w.push_plan(plan_doc({CA: [], CB: [CA]}, merge="human"))
    integrated_a_ledger(w)
    push_archive_of_a(w)
    w.pull()
    assert w.l4("check", "p1") == 0
    out = capsys.readouterr().out
    assert "admitted" in out and f"order: {CA}, {CB}" in out
    # a fresh plan file of another id that lists the archived unit is still refused
    w.push_plan(plan_doc({CA: [], CB: [CA]}, plan_id="p2"), plan_id="p2")
    assert w.l4("check", "p2") == 2
    assert "unknown_unit" in capsys.readouterr().out
    # the review is recorded as the step would: a is READY without a digest, b is READY
    w.push_plan(plan_doc({CA: [], CB: [CA]}, merge="human"))
    w.seed(
        "p1",
        cev("plan.admitted", plan_digest=plan_digest(w.plan_text), order=[CA, CB], merge="human"),
        cev(
            "plan.reviewed",
            plan_digest=plan_digest(w.plan_text),
            prompt_version=PROMPT_VERSION,
            units={CA: {"verdict": "READY"}, CB: {"verdict": "READY", "digest": w.digest(CB)}},
            batches={"b1": {"verdict": "READY"}},
        ),
    )
    assert w.l4("activate", "p1", "--reason", "again", "--no-run") == 0
    got = fold_plan("p1", w.events())
    assert got.status == "active" and got.integrated == {CA: "m"}


def test_check_of_a_plan_with_an_excluded_archived_change_exits_0(cmd_world, capsys):  # noqa: F811
    w = cmd_world
    push_archive_of_a(w)
    w.push_plan(plan_doc({CB: []}, exclude=[{"id": CA, "reason": "already merged"}]))
    w.pull()
    assert w.l4("check", "p1") == 0
    assert "admitted" in capsys.readouterr().out
    w.push_plan(plan_doc({CB: []}, exclude=[{"id": "openspec:nothing", "reason": "gone"}]))
    w.pull()
    assert w.l4("check", "p1") == 2


# --- H2: a dependency added to the current unit at the re-activation ----------------------------------------------


def test_the_activation_event_decides_the_current_unit_when_it_says_so():
    base = [
        ev("plan.admitted", plan_digest="d1", order=[A, C], merge="auto"),
        ev("plan.activated", plan_digest="d1", digests={}, limits={}),
        ev("unit.dispatched", unit=A, run="r0"),
        ev("plan.stopped", reason="inputs_changed", unit="plan"),
        ev("plan.admitted", plan_digest="d2", order=[C, A], merge="auto"),
    ]
    again = ev("plan.activated", plan_digest="d2", digests={}, limits={})
    assert fold_plan("p1", [*base, again]).current == A  # an older event keeps the rule: A is still in the order
    nulled = ev("plan.activated", plan_digest="d2", digests={}, limits={}, current=None)
    assert fold_plan("p1", [*base, nulled]).current is None
    kept = ev("plan.activated", plan_digest="d2", digests={}, limits={}, current=A)
    assert fold_plan("p1", [*base, kept]).current == A


def two_unit_plan(dep_on_c: bool) -> Plan:
    return make_plan([{"id": "b1", "units": [{"id": "a", "depends_on": ["c"] if dep_on_c else []}, {"id": "c"}]}])


def test_next_eligible_never_chooses_a_current_unit_that_has_a_blocker():
    plan = two_unit_plan(dep_on_c=True)
    state = PlanState(plan_id="p1", current="a", order=["c", "a"])
    got = next_eligible(plan, state, {})
    assert got.unit == "c" and got.waiting["a"] == "waits for c (not integrated)"
    done = PlanState(plan_id="p1", current="a", order=["c", "a"], integrated={"c": "r"})
    assert next_eligible(plan, done, {}).unit == "a"
    assert unit_blocker(plan, state, "a") == "waits for c (not integrated)" and unit_blocker(plan, done, "a") is None


def test_the_unit_blocker_names_a_prerequisite_batch_that_is_not_accepted():
    plan = make_plan(
        [
            {"id": "b1", "acceptance_profile": "all", "units": [{"id": "a"}]},
            {"id": "b2", "depends_on": ["b1"], "units": [{"id": "b"}]},
        ]
    )
    state = PlanState(plan_id="p1", integrated={"a": "r"})
    assert unit_blocker(plan, state, "b") == "waits for batch b1 (acceptance)"
    accepted = PlanState(plan_id="p1", integrated={"a": "r"}, accepted_batches={"b1": "r"})
    assert unit_blocker(plan, accepted, "b") is None


def reactivate_with_a_needing_c(w, *, current):
    w.plan(deps={}, batches=[{"id": "b1", "units": [{"id": A}, {"id": C}]}])
    w.units = ["a", "c"]
    w.activate(order=[A, C])
    w.step({"a": w.snapshot("a", None)})
    assert st(w).current == A
    text = w.plan(batches=[{"id": "b1", "units": [{"id": A, "depends_on": [C]}, {"id": C}]}])
    w.step({"a": w.snapshot("a", "implementing")})
    assert st(w).stop_reason == "inputs_changed"
    w.reviewed(text, order=[C, A])
    extra = {} if current == "absent" else {"current": current}
    w.seed(
        ev(
            "plan.activated",
            plan_digest=plan_digest(text),
            digests=w.digests(),
            limits={},
            by="alice",
            reason="x",
            **extra,
        )
    )


@pytest.fixture
def cworld(tmp_path):
    return CycleWorld(tmp_path, units=("a", "c"))


def test_an_old_activation_without_the_current_key_cannot_merge_a_unit_before_its_new_dependency(cworld):
    w = cworld
    reactivate_with_a_needing_c(w, current="absent")  # the fold keeps current = a; the step guards
    assert st(w).current == A
    head = w.unit_branch("a")
    w.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    before = w.tip()
    step = w.step({"a": w.in_review("a", head), "c": w.snapshot("c", None)})
    assert w.tip() == before and A not in st(w).merged and A not in st(w).integrated
    assert any("not merged" in x or "dispatched" in x for x in step.actions)
    assert st(w).current == C  # the plan went on with c, which a waits for


def test_a_unit_that_lost_current_is_not_merged_with_a_head_that_lacks_the_new_dependency(cworld, monkeypatch):
    w = cworld
    reactivate_with_a_needing_c(w, current=None)
    assert st(w).current is None
    head_a = w.unit_branch("a")  # a's work is finished and passes review, on the target before c
    w.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    before = w.tip()
    # a is held: c is dispatched, a is not adopted nor merged
    w.step({"a": w.in_review("a", head_a), "c": w.snapshot("c", None)})
    assert st(w).current == C and w.tip() == before and not st(w).merged
    # c lands in the target
    head_c = w.unit_branch("c")
    w.forge.create_pr("l4/openspec/c", "main", "[l4] c", "b", draft=False)
    w.step({"a": w.in_review("a", head_a), "c": w.in_review("c", head_c, pr="local://forge/pull/2")})
    assert C in st(w).integrated and w.tip() == head_c
    # a is eligible now: it is adopted, and the guarded merge refuses its head, which lacks the new target tip
    retried = []

    def retry(app, cfg, git, provider, ref, **kw):
        from l4.outcome import UnitOutcome
        from l4.state.retry import UnitRunResult

        retried.append(ref.id)
        return UnitRunResult(UnitOutcome(unit=ref.id, phase_before="in_review", phase_after="verifying"), ExitCode.OK)

    monkeypatch.setattr("l4.state.retry.retry_unit", retry)
    w.step({"a": w.in_review("a", head_a), "c": w.snapshot("c", "merged")})
    got = st(w)
    assert w.tip() == head_c and A not in got.integrated and A not in got.merged
    assert [e.data["reason"] for e in w.events() if e.type == "unit.merge_refused"] == ["stale"]
    assert retried == [A]  # the existing stale path asks for a retry


def test_activate_drops_the_current_unit_that_has_a_new_dependency_and_keeps_one_that_has_none(cmd_world, forge):  # noqa: F811
    w = cmd_world
    w.push_plan(plan_doc({CA: [], CB: []}))
    w.seed(
        "p1",
        cev("plan.admitted", plan_digest="old", order=[CA, CB], merge="human"),
        cev("plan.activated", plan_digest="old", digests={}, limits={}, by="a", reason="r"),
        cev("unit.dispatched", unit=CA, run="r0"),
        cev("plan.stopped", reason="inputs_changed", unit="plan"),
    )
    w.push_plan(plan_doc({CA: [CB], CB: []}))
    w.pull()
    w.seed("p1", w.reviewed())
    assert w.l4("activate", "p1", "--reason", "a needs b", "--no-run") == 0
    activated = w.events()[-1]
    assert activated.type == "plan.activated" and activated.data["current"] is None
    assert fold_plan("p1", w.events()).current is None


def test_activate_keeps_the_current_unit_when_nothing_new_blocks_it(cmd_world, forge):  # noqa: F811
    w = cmd_world
    w.push_plan(plan_doc({CA: [], CB: []}))
    w.seed(
        "p1",
        cev("plan.admitted", plan_digest="old", order=[CA, CB], merge="human"),
        cev("plan.activated", plan_digest="old", digests={}, limits={}, by="a", reason="r"),
        cev("unit.dispatched", unit=CA, run="r0"),
        cev("plan.stopped", reason="inputs_changed", unit="plan"),
    )
    w.push_plan(plan_doc({CA: [], CB: [CA]}))
    w.pull()
    w.seed("p1", w.reviewed())
    assert w.l4("activate", "p1", "--reason", "b needs a", "--no-run") == 0
    assert w.events()[-1].data["current"] == CA and fold_plan("p1", w.events()).current == CA


def test_activate_drops_a_current_unit_whose_new_prerequisite_batch_is_not_accepted(cmd_world, forge):  # noqa: F811
    w = cmd_world
    w.push_plan(plan_doc({CA: [], CB: []}))
    w.seed(
        "p1",
        cev("plan.admitted", plan_digest="old", order=[CA, CB], merge="human"),
        cev("plan.activated", plan_digest="old", digests={}, limits={}, by="a", reason="r"),
        cev("unit.dispatched", unit=CB, run="r0"),
        cev("plan.stopped", reason="inputs_changed", unit="plan"),
    )
    doc = plan_doc()
    doc["batches"] = [
        {"id": "b1", "units": [{"id": CA, "depends_on": []}]},
        {"id": "b2", "depends_on": ["b1"], "units": [{"id": CB, "depends_on": []}]},
    ]
    w.push_plan(doc)
    w.pull()
    w.seed("p1", w.reviewed())
    assert w.l4("activate", "p1", "--reason", "b after a", "--no-run") == 0
    assert w.events()[-1].data["current"] is None


# --- L1: a unit that left the plan does not stop it ---------------------------------------------------------------


def test_the_attempts_of_a_unit_that_left_the_plan_reach_no_limit():
    state = PlanState(plan_id="p1", order=["b"], limits={"max_unit_attempts": 2})
    state.used.attempts.update({"a": 3, "b": 1})
    now = datetime(2026, 10, 15, tzinfo=UTC)
    assert reached_at(state, now=now) is None
    assert reached_at(state, now=now, units=["a", "b"]) == ("limit_attempts", "a is on attempt 3 of 2", "a")
    old = PlanState(plan_id="p1", limits={"max_unit_attempts": 2})  # no order recorded: every unit counts
    old.used.attempts["a"] = 3
    assert reached_at(old, now=now) is not None


def test_a_plan_reactivated_without_a_unit_that_used_too_many_attempts_goes_on(world):
    w = world
    w.plan(deps={}, limits={"max_unit_attempts": 2})
    w.activate()
    w.step({"a": w.snapshot("a", None)})
    w.restarts("a", 2)  # attempt 3
    text = w.plan(deps={}, limits={"max_unit_attempts": 2}, batches=[{"id": "b1", "units": [{"id": B}]}])
    w.step({"a": w.snapshot("a", "intake")})
    assert st(w).stop_reason == "inputs_changed" and st(w).used.attempts == {A: 3}
    w.units = ["b"]
    w.reviewed(text, order=[B])
    w.seed(
        ev(
            "plan.activated",
            plan_digest=plan_digest(text),
            digests=w.digests(["b"]),
            limits={"max_unit_attempts": 2},
            by="alice",
            reason="without a",
        )  # fmt: skip
    )
    w.units = ["a", "b"]
    w.step({"a": w.snapshot("a", "intake"), "b": w.snapshot("b", None)})
    got = st(w)
    assert got.status == "active" and got.stop_reason is None
    blocker = resume_blocker("p1", got, w.events(), load_plan(text, file_name="p1.json"), {B: None}, Extend())
    assert blocker is None
