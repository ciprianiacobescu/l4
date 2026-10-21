"""A batch with no acceptance profile only groups units: the judge is told batch_acceptance does not apply, and a
batch_acceptance finding on it never decides the verdict (design D5, L4-YOLO-004)."""

import json

import pytest

from l4.agents.fake import FakeAdapter, Step
from l4.yolo.model import UnitInfo, load_plan
from l4.yolo.readiness import review_plan

from .yolo_review_world import SPEC_A, SPEC_B, World, make_cfg

A, B = "openspec:a", "openspec:b"
FOLDER_A, FOLDER_B = "openspec/changes/a", "openspec/changes/b"
SENTENCE = "only groups units, has no acceptance profile and states no outcome of its own"
GAP = {"criterion": "batch_acceptance", "severity": "major", "text": "acceptance_profile is none and no outcome"}
OTHER = {"criterion": "contradiction", "severity": "major", "text": "a and b disagree"}


def answer(verdict, findings=()):
    return {"verdict": verdict, "findings": list(findings), "assumptions": [], "missing": []}


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    w.rev = w.commit({f"{FOLDER_A}/spec.md": SPEC_A, f"{FOLDER_B}/spec.md": SPEC_B})
    w.units = {A: UnitInfo(A, FOLDER_A), B: UnitInfo(B, FOLDER_B)}
    return w


def run(world, profile, batch_answer):
    batch = {"id": "b1", "units": [{"id": A}, {"id": B}]}
    if profile:
        batch["acceptance_profile"] = profile
    plan = load_plan(json.dumps({"schema": "l4/delivery-plan@1", "plan_id": "p1", "target": "main", "merge": "human",
                                 "batches": [batch]}))  # fmt: skip
    fake = FakeAdapter(
        [Step(structured=answer("READY")), Step(structured=answer("READY")), Step(structured=batch_answer)]
    )
    result = review_plan(
        world.app, make_cfg(), plan, world.units, git=world.git, rev=world.rev, adapters={"fake": fake}
    )
    return result.batches["b1"], fake.requests[-1].prompt


def test_the_material_of_a_batch_without_a_profile_says_it_only_groups_units(world):
    _, prompt = run(world, None, answer("READY"))
    assert SENTENCE in prompt and "batch_acceptance does not apply" in prompt


def test_the_material_of_a_batch_with_a_profile_does_not(world):
    _, prompt = run(world, "fast", answer("READY"))
    assert SENTENCE not in prompt


def test_a_batch_acceptance_gap_alone_does_not_refuse_a_batch_without_a_profile(world):
    verdict, _ = run(world, None, answer("NEEDS_REVISION", [GAP]))
    assert verdict.verdict == "READY" and verdict.findings == ()
    assert any("batch_acceptance" in a and GAP["text"] in a for a in verdict.assumptions)


def test_the_same_answer_stays_needs_revision_for_a_batch_with_a_profile(world):
    verdict, _ = run(world, "fast", answer("NEEDS_REVISION", [GAP]))
    assert verdict.verdict == "NEEDS_REVISION" and verdict.findings == (GAP,)


def test_another_major_finding_keeps_the_batch_needs_revision(world):
    verdict, _ = run(world, None, answer("NEEDS_REVISION", [GAP, OTHER]))
    assert verdict.verdict == "NEEDS_REVISION" and verdict.findings == (OTHER,)


def test_blocked_stays_blocked_while_a_finding_is_left(world):
    verdict, _ = run(world, None, answer("BLOCKED", [GAP, OTHER]))
    assert verdict.verdict == "BLOCKED" and verdict.findings == (OTHER,)


def test_a_blocked_verdict_with_only_the_not_applicable_finding_is_ready_and_keeps_it_as_a_note(world):
    gap = {"criterion": "batch_acceptance", "severity": "blocking", "text": "the batch outcome cannot be judged"}
    other = {"criterion": "contradiction", "severity": "blocking", "text": "a and b disagree"}
    for extra in ({}, {"acceptance_profile": "none"}):
        verdict = _batch_verdict(world, extra, answer("BLOCKED", [gap]))
        assert verdict.verdict == "READY" and verdict.findings == ()
        assert any("batch_acceptance does not apply" in a for a in verdict.assumptions)
    kept = _batch_verdict(world, {}, answer("BLOCKED", [gap, other]))  # another finding is left: BLOCKED stays
    assert kept.verdict == "BLOCKED" and [f["criterion"] for f in kept.findings] == ["contradiction"]
    profiled = _batch_verdict(world, {"acceptance_profile": "all"}, answer("BLOCKED", [gap]))
    assert profiled.verdict == "BLOCKED" and len(profiled.findings) == 1


def _batch_verdict(world, batch_extra, batch_answer):
    import json

    from l4.agents.fake import FakeAdapter, Step
    from l4.yolo.model import load_plan
    from l4.yolo.readiness import review_plan

    from .yolo_review_world import make_cfg

    batch = {"id": "b1", "units": [{"id": A}, {"id": B}], **batch_extra}
    plan = load_plan(json.dumps({"schema": "l4/delivery-plan@1", "plan_id": "p1", "target": "main", "merge": "human",
                                 "batches": [batch]}))  # fmt: skip
    fake = FakeAdapter(
        [Step(structured=answer("READY")), Step(structured=answer("READY")), Step(structured=batch_answer)]
    )
    result = review_plan(
        world.app, make_cfg(), plan, world.units, git=world.git, rev=world.rev, adapters={"fake": fake}
    )
    return result.batches["b1"]
