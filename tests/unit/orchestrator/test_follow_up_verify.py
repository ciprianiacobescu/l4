# ruff: noqa: F811
"""human-feedback 5.2 (L4-FBK-010, L4-FBK-007): the follow-up's own rounds judge the parent's items. With the real
verifier on, a follow-up of a merged Kiro unit is verified, the judge is asked about FB-001 (found through the
follow-up's marker, in the parent's `feedback.md` on the follow-up's branch), and the item reads `addressed` there."""

import pytest

from l4.agents.fake import Step
from l4.specs.criteria import kiro_criteria

from ..archive.conftest import forge_env, gitlab, use_fake_gitlab  # noqa: F401
from ..verifier.conftest import judge_reply
from .test_follow_up import BRANCH, CHORE, FOLLOW, FOLLOW_DIR, SPEC, events, merged_kiro  # noqa: F401


@pytest.fixture(autouse=True)
def no_verifier() -> None:
    """The real verifier is on: this file is about the rounds it runs (overrides the orchestrator suite's)."""


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """The fix loop is on, as in the suite's other end-to-end files."""


def test_the_follow_up_judges_the_parents_items(merged_kiro, run_l4, raw):
    parents = [c.id for c in kiro_criteria(merged_kiro.repo / SPEC)]  # a refactor must leave them true
    assert len(parents) == 1
    answer = {"id": "FB-001", "addressed": True, "evidence": "pricing.py:3"}
    judge = Step(structured=judge_reply(parents, feedback=[answer]))
    run = run_l4([CHORE, judge], unit=False)

    assert run.code == 0, run.adapter.requests[-1].prompt[-800:] if run.adapter.requests else run.outcome
    ledger = events(merged_kiro, raw, BRANCH, FOLLOW_DIR)
    [addressed] = [e for e in ledger if e["type"] == "feedback.addressed"]
    assert (addressed["id"], addressed["round"], addressed["evidence"]) == ("FB-001", 1, "pricing.py:3")
    judged = raw(merged_kiro.origin, "show", f"{BRANCH}:{SPEC}/feedback.md")
    assert "**Status:** addressed" in judged and "Addressed in round 1 at" in judged
    assert [e["verdict"] for e in ledger if e["type"] == "verify.verdict"] == ["PASS"]
    assert "FB-001" in "".join(r.prompt for r in run.adapter.requests)  # the judge's block named the item
    assert f"kiro:{FOLLOW}" in {u["unit"] for u in run.outcome["units"]}
