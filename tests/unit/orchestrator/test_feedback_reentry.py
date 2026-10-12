# ruff: noqa: F811
"""human-feedback 2.2 end to end (L4-FBK-004, L4-FBK-006, L4-FBK-007; SCN-FBK-08, SCN-FBK-09, SCN-FBK-15, SCN-FBK-16):
`l4 run` with a scripted fake agent, a fake GitLab and a bare origin. A person's commit of `feedback.md` after the
hand-off re-enters the unit; before it, the item waits for the unit's own verification."""

import json
from pathlib import Path

import pytest

from l4.agents.fake import Step
from l4.redact import Redactor
from l4.specs.criteria import openspec_criteria
from l4.specs.feedback import FeedbackKind, NewFeedback, Place, append_item

from ..archive.conftest import forge_env, gitlab, use_fake_gitlab  # noqa: F401  (a fake GitLab for the hand-off)
from ..conftest import FIXTURE
from ..implementer.conftest import IMPL, blocked_step, green_step, red_step, result
from ..verifier.conftest import judge_reply, openspec_stand_in, valid_spec  # noqa: F401
from .conftest import BRANCH, UNIT_DIR, edit_questions_on_origin
from .test_review_reentry import HANDOFF, human_commit

CRITERIA = [c.id for c in openspec_criteria(FIXTURE / "openspec" / "changes" / "add-discount-codes")]
JUDGE = Step(structured=judge_reply(CRITERIA))
FEEDBACK = f"{UNIT_DIR}/feedback.md"
FIX_UNIT = "add-discount-codes-fix-1"
CHORE = Step(
    writes={"src/pytdd/pricing.py": IMPL + "\n# the rounding is its own function\n"}, structured=result("single")
)


@pytest.fixture(autouse=True)
def no_verifier() -> None:
    """The real verifier is on: this file is about the rounds it runs (overrides the orchestrator suite's)."""


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """The fix loop is on: a FAIL at step 0 goes on into the fix tasks in the same run."""


def feedback_text(tmp: Path, *items: dict, status: str = "submitted") -> str:
    """The `feedback.md` a person would commit: the command's own writer, so the grammar is the real one."""
    folder = tmp / "fb"
    folder.mkdir(exist_ok=True)
    for body in items:
        spec = {
            "kind": FeedbackKind.REFACTOR, "title": "Extract the rounding", "text": "Move the rounding into a helper.",
            "by": "Ana, 2026-10-12T15:04:00Z", "places": (Place("src/pytdd/pricing.py", 5, 6),),
        }  # fmt: skip
        append_item(folder, "add-discount-codes", NewFeedback(**{**spec, **body}), redactor=Redactor({}))
    return (folder / "feedback.md").read_text().replace("**Status:** submitted", f"**Status:** {status}")


@pytest.fixture
def in_review(run_l4, valid_spec, forge_env, use_fake_gitlab):
    first = run_l4([red_step(), green_step(), JUDGE])
    assert first.code == 0 and first.outcome["units"][0]["phase_after"] == "in_review"
    return first


def test_feedback_after_the_handoff_reenters_and_the_round_fails_at_step_0(
    in_review, run_l4, tdd_repo, raw, use_fake_gitlab, tmp_path
):
    """SCN-FBK-08: in_review -> implementing -> verifying -> fixing; one feedback finding; no gate or judge ran."""
    human = human_commit(tdd_repo, raw, {FEEDBACK: feedback_text(tmp_path, {})}, "ask for a refactor")
    run = run_l4([CHORE, JUDGE])
    assert run.code == 0, run.adapter.requests[-1].prompt[-500:]
    assert run.triggers()[-7:] == [
        "spec_edit_after_handoff", "all_leaves_done", "verification_started", "verify_fail_fix", "fix_unit_done",
        "verify_pass", "hand_off_pushed",
    ]  # fmt: skip
    edge = [e for e in run.events("phase.changed") if e["trigger"] == "spec_edit_after_handoff"][0]
    assert edge["to"] == "implementing" and [c["sha"] for c in edge["commits"]] == [human]
    assert [v["verdict"] for v in run.events("verify.verdict")] == ["PASS", "FAIL", "PASS"]
    steps = {s["step"]: s["status"] for s in run.events("verify.step") if s["round"] == 2}
    assert steps == {"0": "failed", "10": "ok"}  # no gate, no judge
    assert len(run.events("verify.judge")) == 2  # the first PASS and the last: the failed round never reached it
    [spawned] = run.events("fix.spawned")
    assert spawned["fix_unit"] == FIX_UNIT and spawned["feedback_only"] is True and len(spawned["findings"]) == 1
    [taken] = run.events("feedback.taken")
    assert (taken["id"], taken["kind"], taken["round"], taken["fix_unit"]) == ("FB-001", "refactor", 2, FIX_UNIT)
    assert len(taken["sha256"]) == 64
    fix_dir = f"{BRANCH}:openspec/changes/{FIX_UNIT}"
    marker = json.loads(raw(tdd_repo.origin, "show", f"{fix_dir}/.l4/fix.json"))
    assert marker["refactors"] == marker["chores"] == spawned["findings"]
    proposal = raw(tdd_repo.origin, "show", f"{fix_dir}/proposal.md")
    assert (
        "Requested by Ana, 2026-10-12T15:04:00Z in FB-001 (refactor, src/pytdd/pricing.py:5-6): Move the rounding"
        in proposal
    )
    # the harness set Status and Outcome in the same commit as the fix unit
    fb = raw(tdd_repo.origin, "show", f"{BRANCH}:{FEEDBACK}")
    assert "**Status:** taken" in fb and f"Taken in round 2 into {FIX_UNIT}" in fb
    assert "| FB-001 | taken | refactor |" in fb
    commit = raw(tdd_repo.origin, "log", "--format=%H %s", BRANCH, "--", FEEDBACK).splitlines()[0]
    assert "fix unit 1 [skip ci]" in commit
    changed = raw(tdd_repo.origin, "show", "--name-only", "--format=", commit.split()[0]).split()
    assert FEEDBACK in changed and any(c.startswith(f"openspec/changes/{FIX_UNIT}/") for c in changed)
    assert raw(tdd_repo.origin, "log", "-1", "--format=%s", BRANCH).strip() == HANDOFF
    assert not use_fake_gitlab.mrs[1]["title"].lower().startswith("draft")
    # the next round has nothing to take: the item is `taken` and its content is the one taken
    assert run.events("feedback.taken") == [taken]


def test_feedback_pushed_before_the_handoff_waits_for_the_units_own_verification(
    run_l4, valid_spec, tdd_repo, raw, tmp_path
):
    """SCN-FBK-09: the task order does not change; the item is taken at the unit's verification."""
    assert run_l4([blocked_step()]).code == 11
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="Round half up.")
    human_commit(tdd_repo, raw, {FEEDBACK: feedback_text(tmp_path, {})}, "ask for a refactor")
    run = run_l4([red_step(), green_step(), CHORE, JUDGE])
    assert run.code == 0, run.adapter.requests[-1].prompt[-500:]
    assert run.triggers()[-5:] == [
        "all_leaves_done",
        "verification_started",
        "verify_fail_fix",
        "fix_unit_done",
        "verify_pass",
    ]
    kinds = [
        e["type"] for e in run.ledger() if e["type"] in ("task.red_ok", "task.done", "verify.verdict", "fix.spawned")
    ]
    assert kinds.index("task.done") < kinds.index("verify.verdict") < kinds.index("fix.spawned")
    assert [v["verdict"] for v in run.events("verify.verdict")] == ["FAIL", "PASS"]
    [taken] = run.events("feedback.taken")
    assert taken["id"] == "FB-001" and taken["round"] == 1
    assert "- [x] 1.1" in run.pushed(f"{UNIT_DIR}/tasks.md")
