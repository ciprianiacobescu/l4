"""Incremental review (L4-YOLO-022, review-resolution design D2): the same material is not judged twice. A subject's
material key covers the text the judge would get without the delivered block; a recorded entry with that key is reused
at no call and no cost, except one that is no review (`schema`, `unit_missing`, `completeness`)."""

import pytest

from l4.agents.fake import FakeAdapter, Step
from l4.availability.errors import RoleUnavailable
from l4.sandbox.none import NoSandbox
from l4.yolo.digest import unit_digest
from l4.yolo.model import UnitInfo
from l4.yolo.readiness import PROMPT_VERSION, material_key, review_plan_costed

from .yolo_review_world import SPEC_A, SPEC_B, World, make_cfg, plan_of

A, B = "openspec:a", "openspec:b"
FOLDER_A, FOLDER_B = "openspec/changes/a", "openspec/changes/b"
GAP = {"criterion": "testability", "severity": "major", "text": "no inputs"}


def answer(verdict="NEEDS_REVISION", findings=(GAP,)):
    return {"verdict": verdict, "findings": list(findings), "assumptions": [], "missing": []}


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    w.rev = w.commit({f"{FOLDER_A}/specs/x/spec.md": SPEC_A, f"{FOLDER_B}/specs/x/spec.md": SPEC_B})
    w.units = {A: UnitInfo(A, FOLDER_A), B: UnitInfo(B, FOLDER_B)}
    return w


def review(world, plan, n, *, cost=0.25, cfg=None, **kw):
    fake = FakeAdapter([Step(structured=answer(), cost_usd=cost) for _ in range(n)])
    kw.setdefault("rev", world.rev)
    result, spent = review_plan_costed(
        world.app, cfg or make_cfg(), plan, world.units, git=world.git, adapters={"fake": fake}, **kw
    )
    return result, spent, fake


def recorded(result, at="t1"):
    """material key -> the entry the ledger would hold (`plan.reviewed`)."""
    out = {}
    for verdict in [*result.units.values(), *result.batches.values()]:
        if verdict.material:
            out[verdict.material] = {
                "verdict": verdict.verdict,
                "findings": list(verdict.findings),
                "assumptions": list(verdict.assumptions),
                "missing": list(verdict.missing),
                "digest": verdict.digest,
                "material": verdict.material,
                "at": at,
            }
    return out


def prompts(fake):
    return [r.prompt for r in fake.requests]


def judged(fake, unit):
    return [p for p in prompts(fake) if f'source="subject">\n{unit}\n' in p]


def test_a_judged_verdict_carries_a_stable_material_key(world):
    result, _, _ = review(world, plan_of({A: []}), 1)
    again, _, _ = review(world, plan_of({A: []}), 1)
    key = result.units[A].material
    assert key and len(key) == 16 and result.units[A].reused_from is None and again.units[A].material == key


def test_an_unchanged_unit_is_not_judged_again(world):  # SCN-YOLO-47
    plan = plan_of({A: [], B: []})
    first, _, _ = review(world, plan, 3)
    prior = recorded(first)
    world.rev = world.commit({f"{FOLDER_B}/specs/x/spec.md": SPEC_B + "\nMore.\n"})
    second, spent, fake = review(world, plan, 2, prior=prior)
    assert len(fake.requests) == 2 and judged(fake, A) == [] and len(judged(fake, B)) == 1
    assert "# Review of batch" in fake.requests[1].prompt
    reused = second.units[A]
    assert reused.reused_from == "t1" and reused.material == first.units[A].material
    assert reused.verdict == first.units[A].verdict and reused.findings == first.units[A].findings
    assert reused.digest == unit_digest(world.git, world.rev, FOLDER_A)
    assert second.units[B].reused_from is None and second.units[B].material != first.units[B].material
    assert spent == pytest.approx(0.5)  # the calls made, not the reused ones


def test_a_changed_prerequisite_makes_its_dependents_judged_again(world):  # SCN-YOLO-48
    plan = plan_of({A: [], B: [A]}, batches=[("b1", [A]), ("b2", [B])])
    first, _, _ = review(world, plan, 2)
    prior = recorded(first)
    world.rev = world.commit({f"{FOLDER_A}/specs/x/spec.md": SPEC_A + "\nMore.\n"})
    second, _, fake = review(world, plan, 2, prior=prior)
    assert len(judged(fake, A)) == 1 and len(judged(fake, B)) == 1
    assert second.units[A].reused_from is None and second.units[B].reused_from is None


def test_a_review_that_did_not_happen_is_not_reused(world):  # SCN-YOLO-49
    plan = plan_of({A: [], B: []})
    broken = FakeAdapter([Step(final_text="not json"), Step(final_text="not json")])
    first, _ = review_plan_costed(
        world.app, make_cfg(), plan_of({A: []}), world.units, git=world.git, rev=world.rev, adapters={"fake": broken}
    )
    assert first.units[A].verdict == "BLOCKED" and first.units[A].findings[0]["criterion"] == "schema"
    prior = recorded(first)
    assert prior  # the entry carries its key; the rule is the review's
    world.rev = world.commit({f"{FOLDER_B}/specs/x/spec.md": SPEC_B + "\nMore.\n"})
    second, _, fake = review(world, plan, 3, prior=prior)
    assert len(judged(fake, A)) == 1 and second.units[A].reused_from is None


@pytest.mark.parametrize("criterion", ["unit_missing", "completeness"])
def test_the_other_harness_findings_are_not_reused_either(world, criterion):
    first, _, _ = review(world, plan_of({A: []}), 1)
    prior = recorded(first)
    (entry,) = prior.values()
    entry.update(verdict="BLOCKED", findings=[{"criterion": criterion, "severity": "blocking", "text": "x"}])
    _, _, fake = review(world, plan_of({A: []}), 1, prior=prior)
    assert len(fake.requests) == 1


def test_a_change_of_the_delivered_list_alone_keeps_the_key(world):
    plan = plan_of({A: []})
    first, _, _ = review(world, plan, 1)
    second, _, fake = review(world, plan, 1, delivered={"openspec:old": "archived"})
    assert len(fake.requests) == 1  # judged: no prior given
    assert "openspec:old" in fake.requests[0].prompt
    assert second.units[A].material == first.units[A].material
    third, _, fake = review(world, plan, 0, prior=recorded(first), delivered={"openspec:old": "archived"})
    assert fake.requests == [] and third.units[A].reused_from == "t1"


def test_a_tick_change_changes_the_key(world):
    plan = plan_of({A: []})
    world.rev = world.commit({f"{FOLDER_A}/tasks.md": "- [ ] 1.1 One\n- [ ] 1.2 Two\n"})
    first, _, _ = review(world, plan, 1)
    world.rev = world.commit({f"{FOLDER_A}/tasks.md": "- [x] 1.1 One\n- [ ] 1.2 Two\n"})
    second, _, fake = review(world, plan, 1, prior=recorded(first))
    assert second.units[A].material != first.units[A].material and len(fake.requests) == 1


def test_a_changed_plan_entry_changes_the_key(world):
    first, _, _ = review(world, plan_of({A: [], B: []}), 3)
    second, _, fake = review(world, plan_of({A: [], B: [A]}), 3, prior=recorded(first))
    assert second.units[A].reused_from == "t1"  # A's own material is the same
    assert second.units[B].reused_from is None  # B now depends on A


def test_fresh_asks_the_judge_again(world):
    plan = plan_of({A: [], B: []})
    first, _, _ = review(world, plan, 3)
    prior = recorded(first)
    second, _, fake = review(world, plan, 1, prior=prior, fresh=(A,))
    assert len(judged(fake, A)) == 1 and len(fake.requests) == 1
    assert second.units[A].reused_from is None and second.units[B].reused_from == "t1"
    assert second.batches["b1"].reused_from == "t1"
    third, _, fake = review(world, plan, 1, prior=prior, fresh=("batch:b1",))
    assert len(fake.requests) == 1 and "# Review of batch" in fake.requests[0].prompt
    assert third.units[A].reused_from == "t1" and third.batches["b1"].reused_from is None


def test_revs_reads_a_snapshot_commit(world):
    snapshot = world.commit({f"{FOLDER_A}/specs/x/spec.md": SPEC_A + "SNAPSHOT-ONLY\n"})
    world.git.run("update-ref", "refs/heads/snap", snapshot)
    world.git.run("reset", "--hard", "-q", world.rev)
    result, _, fake = review(world, plan_of({A: [], B: [A]}), 3, revs={A: snapshot, B: snapshot})
    assert "SNAPSHOT-ONLY" in fake.requests[0].prompt and "SNAPSHOT-ONLY" in fake.requests[1].prompt
    assert result.units[A].digest == unit_digest(world.git, snapshot, FOLDER_A)
    plain, _, fake = review(world, plan_of({A: []}), 1)
    assert "SNAPSHOT-ONLY" not in fake.requests[0].prompt


def test_nothing_is_created_when_every_subject_is_reused(world):
    plan = plan_of({A: [], B: []})
    first, _, _ = review(world, plan, 3)
    no_judges = make_cfg(roles={"implementer": ["impl"], "judges": []})

    def refuse(adapter, profile):
        raise AssertionError("no subject is judged")

    result, spent, fake = review(world, plan, 0, cfg=no_judges, prior=recorded(first), sandbox_for=refuse)
    assert spent == 0.0 and fake.requests == []
    assert {v.reused_from for v in [*result.units.values(), *result.batches.values()]} == {"t1"}
    with pytest.raises(RoleUnavailable):  # and with something to judge, the missing judge shows
        review(world, plan, 0, cfg=no_judges)


def test_sandbox_for_is_called_once_after_the_judge_is_chosen(world):
    calls = []

    def sandbox_for(adapter, profile):
        calls.append((adapter, profile))
        return NoSandbox(allow_none=True)

    _, _, fake = review(world, plan_of({A: [], B: []}), 3, sandbox_for=sandbox_for)
    assert calls == [("fake", "judge")] and len(fake.requests) == 3


def test_the_key_depends_on_the_prompt_version_and_the_kind():
    assert material_key("unit", "x") != material_key("batch", "x") != material_key("unit", "y")
    assert PROMPT_VERSION == 4
