"""A batch is reviewed with the prerequisites of its units (design D5): every unit-level prerequisite that is not a
unit of the batch, shown the way a unit's own review shows it, and the ordering of a plan stated in plain words."""

import pytest

from l4.agents.fake import FakeAdapter, Step
from l4.yolo.model import UnitInfo
from l4.yolo.readiness import review_plan

from .test_yolo_readiness_material import outside_blocks
from .yolo_review_world import SPEC_A, SPEC_B, World, make_cfg, plan_of

A, B, C = "openspec:a", "openspec:b", "openspec:c"
FOLDER_A, FOLDER_B, FOLDER_C = "openspec/changes/a", "openspec/changes/b", "openspec/changes/c"
MARK = "A-SPEC-MARKER-7731"
ORDER = "is delivered and merged into the target before any unit that depends on it starts"


def answer():
    return {"verdict": "READY", "findings": [], "assumptions": [], "missing": []}


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    w.rev = w.commit(
        {f"{FOLDER_A}/spec.md": SPEC_A + MARK + "\n", f"{FOLDER_B}/spec.md": SPEC_B, f"{FOLDER_C}/spec.md": SPEC_B}
    )
    w.units = {A: UnitInfo(A, FOLDER_A), B: UnitInfo(B, FOLDER_B), C: UnitInfo(C, FOLDER_C)}
    return w


def review(world, plan, steps=4, cfg=None):
    fake = FakeAdapter([Step(structured=answer()) for _ in range(steps)])
    result = review_plan(
        world.app, cfg or make_cfg(), plan, world.units, git=world.git, rev=world.rev, adapters={"fake": fake}
    )
    return result, fake


def batch_prompt(fake):
    return fake.requests[-1].prompt


def test_a_prerequisite_of_two_units_from_an_earlier_batch_is_shown_once_to_the_batch(world):
    plan = plan_of({A: [], B: [A], C: [A]}, batches=[("b1", [A]), ("b2", [B, C])])
    _, fake = review(world, plan)
    prompt = batch_prompt(fake)
    assert "# Review of batch" in prompt
    assert prompt.count(MARK) == 1
    assert '<l4:data source="prerequisite">' in prompt and FOLDER_A in prompt.split("## Specification folders")[0]


def prerequisites_of(prompt):
    return prompt.split("## Prerequisites")[1].split("## Specification folders")[0]


def test_a_prerequisite_that_is_a_unit_of_the_batch_is_not_shown_as_one(world):
    plan = plan_of({A: [], B: [A], C: []}, batches=[("b1", [A, B]), ("b2", [C])])
    _, fake = review(world, plan, steps=4)
    prompt = next(r.prompt for r in fake.requests if "# Review of batch" in r.prompt)
    assert "(none: the batch depends on nothing)" in prerequisites_of(prompt)
    assert 'source="prerequisite"' not in prompt and ORDER not in prompt


def test_the_batch_level_prerequisites_still_follow_the_unit_prerequisites(world):
    plan = plan_of({A: [], B: [A], C: [A]}, batches=[("b1", [A]), ("b2", [B, C])])
    plan.batches[1].depends_on.append("b1")
    _, fake = review(world, plan)
    section = prerequisites_of(batch_prompt(fake))
    assert section.index('source="prerequisite"') < section.index("batch prerequisites") and "- batch b1" in section


def test_the_cut_lines_of_a_shown_prerequisite_reach_the_batch_in_missing(world):
    world.rev = world.commit({f"{FOLDER_A}/big.md": "x" * 500 + "\n"})
    plan = plan_of({A: [], B: [A], C: [A]}, batches=[("b1", [A]), ("b2", [B, C])])
    result, _ = review(world, plan, cfg=make_cfg(yolo={"review": {"max_dependency_chars": 300}}))
    assert result.batches["b2"].verdict == "READY" and result.batches["b2"].findings == ()
    assert any(FOLDER_A in m and "big.md" in m and "not shown in full" in m for m in result.batches["b2"].missing)


def test_a_prerequisite_without_a_folder_is_shown_as_not_known_to_the_batch(world):
    plan = plan_of({A: [], B: [A], C: [A]}, batches=[("b1", [A]), ("b2", [B, C])])
    del world.units[A]
    _, fake = review(world, plan, steps=3)
    prompt = batch_prompt(fake)
    assert "# Review of batch" in prompt and prompt.count("(its folder is not known)") == 1


def test_the_ordering_sentence_is_in_the_unit_and_the_batch_material(world):
    plan = plan_of({A: [], B: [A], C: [A]}, batches=[("b1", [A]), ("b2", [B, C])])
    _, fake = review(world, plan)
    unit_b = next(r.prompt for r in fake.requests if f'source="subject">\n{B}\n' in r.prompt)
    for prompt in (unit_b, batch_prompt(fake)):
        assert ORDER in outside_blocks(prompt)
    unit_a = next(r.prompt for r in fake.requests if f'source="subject">\n{A}\n' in r.prompt)
    assert ORDER not in unit_a
