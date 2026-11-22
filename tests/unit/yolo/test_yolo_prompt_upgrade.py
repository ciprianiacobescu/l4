# ruff: noqa: F811
"""L4-YOLO-101, the upgrade to readiness prompt version 5 (design D2): a review of version 4 is stale before the
activation and for a stopped plan, it is judged again with nothing reused, an acceptance bound to it no longer holds,
a force acceptance and an active plan are not touched, and a plan CI never reviews is told to review here.
SCN-YOLO-285 to -288 and -307."""

import json

import pytest

from l4.config.schema import YoloReviewCfg
from l4.yolo import accept as accepting
from l4.yolo import findings as fnd
from l4.yolo.digest import plan_digest
from l4.yolo.findings import findings_sha
from l4.yolo.model import Verdict
from l4.yolo.readiness import PROMPT_VERSION
from l4.yolo.state import fold_plan

from .test_yolo_commands_activate import fake_judge
from .yolo_actor import person  # noqa: F401
from .yolo_cmd_world import A, B, forge, world  # noqa: F401
from .yolo_cmd_world import ev as cmd_ev
from .yolo_cycle_world import PLAN, READY, CycleWorld, ev, unit_id
from .yolo_review_world import SPEC_B

OLD = PROMPT_VERSION - 1  # the prompt version of 0.4.59
GAP = {"criterion": "testability", "severity": "major", "text": "no inputs"}
NEEDS = {"verdict": "NEEDS_REVISION", "findings": [GAP], "assumptions": [], "missing": []}


def old_review(world, *, digests=None, batch="NEEDS_REVISION"):
    """The plan admitted and reviewed under the old prompt: A and B READY, `batch:b1` judged `batch`."""
    text = (world.repo / ".l4" / "plans" / f"{PLAN}.json").read_text(encoding="utf-8")
    now = world.digests()
    units = {u: {"verdict": "READY", "digest": d, "material": f"m-{u}", "findings": []} for u, d in now.items()}
    entry = {"verdict": batch, "digest": None, "digests": digests or now, "material": "m-b1-old",
             "findings": [GAP] if batch != "READY" else []}  # fmt: skip
    world.seed(
        ev("plan.admitted", plan_digest=plan_digest(text), order=[unit_id("a"), unit_id("b")], merge="auto"),
        ev("plan.reviewed", plan_digest=plan_digest(text), prompt_version=OLD, units=units, batches={"b1": entry}),
    )
    return text


@pytest.fixture
def cycle(tmp_path):
    return CycleWorld(tmp_path)


# --- SCN-YOLO-285 ------------------------------------------------------------------------------------------------


def test_scn_yolo_285_the_step_judges_every_subject_again_and_the_acceptance_no_longer_holds(cycle):
    cycle.plan()
    text = old_review(cycle)
    cycle.seed(
        ev(
            "plan.accepted", subject="batch:b1", material="m-b1-old", findings=[GAP], findings_sha=findings_sha([GAP]),
            reason="r", by="alice", actor="person", marker=None, rounds=2, verdict="NEEDS_REVISION",
            prompt_version=OLD, digests=cycle.digests(),
        )
    )  # fmt: skip
    cycle.judge.requests.clear()
    from l4.agents.fake import FakeAdapter, Step

    cycle.judge = FakeAdapter([Step(structured=READY), Step(structured=READY), Step(structured=NEEDS)])
    cycle.step()
    assert len(cycle.judge.requests) == 3  # a, b and the batch: nothing of version 4 is reused
    reviewed = [e for e in cycle.events() if e.type == "plan.reviewed"]
    assert len(reviewed) == 2 and reviewed[-1].data["prompt_version"] == PROMPT_VERSION
    rows = [*reviewed[-1].data["units"].values(), *reviewed[-1].data["batches"].values()]
    assert rows and not any("reused_from" in r for r in rows)
    state = fold_plan(PLAN, cycle.events())
    assert "batch:b1" in state.accepted  # the acceptance is kept in the fold
    latest = reviewed[-1].data
    assert accepting.holds(state, latest) == {"batch:b1": False}
    why = accepting.whys(state, latest, reviewed[-1].at)["batch:b1"]
    assert why.startswith("other material:") and "the review prompt changed" in why
    # the rounds of the old review stay: a new acceptance is not refused for rounds
    assert text and fnd.rounds_not_ready(cycle.events(), "batch:b1") >= 1
    entry = latest["batches"]["b1"]
    twice = [
        *cycle.events(),
        ev("plan.reviewed", plan_digest=plan_digest(text), prompt_version=OLD,
           units={}, batches={"b1": {**entry, "digests": {unit_id("a"): "d-earlier", unit_id("b"): "d-earlier"}}}),
    ]  # fmt: skip
    assert fnd.rounds_not_ready(twice, "batch:b1") >= 2
    assert accepting.check(state, twice, "batch:b1", entry, YoloReviewCfg(), "person") is None


def test_scn_yolo_285_status_and_activation_say_the_prompt_changed(world, forge, capsys):
    world.push_plan()
    old = world.reviewed()
    old.data["prompt_version"] = OLD
    world.seed("p1", cmd_ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), old)
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert "review: stale (the review prompt changed)" in out
    line = f"review prompt {OLD} at the review, {PROMPT_VERSION} in this harness: every subject is judged again"
    assert line in out
    assert world.l4("status", "p1", "--json") == 0
    assert json.loads(capsys.readouterr().out)["plans"][0]["review"]["prompt_changed"] is True
    before = world.kinds()
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 2
    err = capsys.readouterr().err
    assert line in err and err.rstrip().endswith("Fix: l4 yolo review p1")
    assert world.kinds() == before


# --- SCN-YOLO-286 ------------------------------------------------------------------------------------------------


def test_scn_yolo_286_a_force_acceptance_holds_across_the_upgrade(world, forge, person):
    world.push_plan()
    old = world.reviewed()
    old.data["prompt_version"] = OLD
    world.seed("p1", cmd_ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), old)
    assert world.l4("accept", "p1", "--all", "--force", "--reason", "the judge is down") == 0
    requested = len(forge.called("start_run"))
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    assert world.kinds()[-1] == "plan.activated" and len(forge.called("start_run")) == requested


# --- SCN-YOLO-287 ------------------------------------------------------------------------------------------------


def test_scn_yolo_287_an_active_plan_is_neither_stopped_nor_reviewed_again(cycle):
    from l4.agents.fake import FakeAdapter, Step

    cycle.plan()
    text = old_review(cycle, batch="READY")
    cycle.seed(
        ev("plan.activated", plan_digest=plan_digest(text), digests=cycle.digests(), limits={}, by="alice", reason="go")
    )
    cycle.judge = FakeAdapter([Step(structured=READY) for _ in range(10)])
    before = cycle.kinds()
    cycle.step()
    assert cycle.judge.requests == []
    new = cycle.kinds()[len(before) :]
    assert not {"plan.reviewed", "plan.stopped", "plan.review_incomplete"} & set(new)
    assert fold_plan(PLAN, cycle.events()).status in ("active", "waiting")
    # a spec change of a pending unit stops the plan with inputs_changed, and its review judges every subject
    cycle.commit({"openspec/changes/b/specs/x/spec.md": SPEC_B + "- WHEN y THEN z\n"})
    cycle.push_main()
    cycle.step()
    assert fold_plan(PLAN, cycle.events()).stop_reason == "inputs_changed"
    cycle.step()
    last = [e for e in cycle.events() if e.type == "plan.reviewed"][-1]
    assert last.data["prompt_version"] == PROMPT_VERSION and len(cycle.judge.requests) == 3


def test_scn_yolo_287_the_status_of_an_active_plan_shows_no_prompt_change(world, forge, capsys):
    world.push_plan()
    old = world.reviewed()
    old.data["prompt_version"] = OLD
    activated = cmd_ev(
        "plan.activated", plan_digest=plan_digest(world.plan_text), digests={u: world.digest(u) for u in (A, B)},
        limits={}, by="alice", reason="go", attempt_base={}, accepted={},
    )  # fmt: skip
    world.seed("p1", cmd_ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), old, activated)
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert "prompt changed" not in out and "review prompt" not in out


# --- SCN-YOLO-288 ------------------------------------------------------------------------------------------------


def test_scn_yolo_288_kept_answers_of_the_old_prompt_are_not_reused(cycle):
    from l4.agents.fake import FakeAdapter, Step

    cycle.plan()
    text = (cycle.repo / ".l4" / "plans" / f"{PLAN}.json").read_text(encoding="utf-8")
    now = cycle.digests()
    cycle.seed(
        ev("plan.admitted", plan_digest=plan_digest(text), order=[unit_id("a"), unit_id("b")], merge="auto"),
        ev(
            "plan.review_incomplete", plan_digest=plan_digest(text), prompt_version=OLD, source="ci",
            reason="no_judge", answered={unit_id("a"): {"verdict": "READY", "digest": now[unit_id("a")],
                                                        "material": "m-a-old", "findings": [], "judge": "j2"}},
            left=[unit_id("b"), "batch:b1"],
            failures=[{"profile": "j1", "subject": unit_id("b"), "kind": "error", "detail": "boom", "material": "m-b"}],
        ),
    )  # fmt: skip
    events = cycle.events()
    assert fnd.kept_keys(events, PROMPT_VERSION) == set() and fnd.failed_before(events, PROMPT_VERSION) == {}
    assert fnd.latest_incomplete(events, PROMPT_VERSION) is None and fnd.prior_entries(events, PROMPT_VERSION) == {}
    cycle.judge = FakeAdapter([Step(structured=READY) for _ in range(10)])
    cycle.step()
    assert len(cycle.judge.requests) == 3  # A is judged again, with B and the batch


def test_scn_yolo_288_a_dry_run_reuses_no_cached_line_of_the_old_prompt(world, forge, monkeypatch, capsys):
    from .test_yolo_review_worktree import answer, cache_lines, judge, ready_world

    ready_world(world)
    first = judge(monkeypatch, *[answer() for _ in range(3)])
    assert world.l4("review", "p1", "--worktree") == 0
    assert len(first.requests) == 3
    path = next(world.root.glob("**/yolo/p1/review/verdicts.jsonl"))
    lines = cache_lines(world)
    assert {line["prompt_version"] for line in lines} == {PROMPT_VERSION}
    path.write_text(
        "".join(json.dumps({**line, "prompt_version": OLD}, sort_keys=True) + "\n" for line in lines),
        encoding="utf-8",
    )
    second = judge(monkeypatch, *[answer() for _ in range(3)])
    capsys.readouterr()
    assert world.l4("review", "p1", "--worktree") == 0
    assert len(second.requests) == 3  # every line of version 4 is ignored


# --- SCN-YOLO-307 ------------------------------------------------------------------------------------------------


def stopped_unit_rejected(world):
    """Activated on a review of version 4, stopped with unit_rejected for A, whose spec did not change."""
    world.push_plan()
    old = world.reviewed()
    old.data["prompt_version"] = OLD
    digests = {u: world.digest(u) for u in (A, B)}
    world.seed(
        "p1",
        cmd_ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]),
        old,
        cmd_ev(
            "plan.activated", plan_digest=plan_digest(world.plan_text), digests=digests, limits={}, by="alice",
            reason="go", attempt_base={}, accepted={},
        ),
        cmd_ev("plan.stopped", reason="unit_rejected", unit=A, digest=digests[A]),
    )  # fmt: skip


def test_scn_yolo_307_the_activation_the_review_and_the_status_name_the_local_review(world, forge, capsys, monkeypatch):
    stopped_unit_rejected(world)
    capsys.readouterr()
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 2
    err = capsys.readouterr().err
    assert f"review prompt {OLD} at the review, {PROMPT_VERSION} in this harness" in err
    assert err.rstrip().endswith("Fix: l4 yolo review p1 --local")
    assert world.l4("review", "p1") == 0
    out = capsys.readouterr().out
    assert "l4 yolo review p1 --local" in out
    assert world.l4("status", "p1") == 0
    status = capsys.readouterr().out
    assert "Next: " in status and "l4 yolo review p1 --local" in status
    fake_judge(monkeypatch, {}, batches={"b1": Verdict("READY")})
    assert world.l4("review", "p1", "--local") == 0
    capsys.readouterr()
    assert world.l4("activate", "p1", "--reason", "go", "--no-run") == 0
    assert world.kinds()[-1] == "plan.activated"
