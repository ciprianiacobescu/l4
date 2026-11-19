"""L4-YOLO-098: a batch too large for one call is reviewed in parts, and the parts make one verdict under the batch's
material key. A subject that is not split keeps the prompt and the material key of 0.4.58."""

import hashlib
import re

import pytest

from l4.agents.fake import FakeAdapter, Step
from l4.yolo.model import UnitInfo, Verdict
from l4.yolo.readiness import (
    PROMPT_VERSION,
    ReviewIncomplete,
    Subject,
    _amend,
    material_key,
    merge_parts,
    review_plan_costed,
)

from .yolo_review_world import SPEC_A, SPEC_B, World, make_cfg, plan_of

A, B, C = "openspec:a", "openspec:b", "openspec:c"
ROOT = "openspec/changes"
PROFILES = {
    "impl": {"adapter": "fake", "vendor": "vendor-a"},
    "j1": {"adapter": "claude-code", "vendor": "anthropic"},
    "j2": {"adapter": "codex", "vendor": "openai"},
}


def ok(**kw):
    return Step(structured={"verdict": "READY", "findings": [], "assumptions": [], "missing": []}, **kw)


def said(verdict, findings=()):
    return Step(structured={"verdict": verdict, "findings": list(findings), "assumptions": [], "missing": []})


PARTS_FINDING = {
    "criterion": "parts",
    "severity": "minor",
    "text": (
        "this batch was reviewed in parts: no judge saw two units' full text together, so defects visible only across "
        "units may be missed"
    ),
}


def cfg_of(bound=None, judges=("j1", "j2")):
    review = {} if bound is None else {"max_batch_chars": bound}
    return make_cfg(profiles=PROFILES, roles={"implementer": ["impl"], "judges": list(judges)}, yolo={"review": review})


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    files = {}
    for name, spec in (("a", SPEC_A), ("b", SPEC_B), ("c", SPEC_B)):
        files[f"{ROOT}/{name}/proposal.md"] = f"Why: {name.upper()}-PROPOSAL.\n"
        files[f"{ROOT}/{name}/specs/x/spec.md"] = spec
    files[f"{ROOT}/a/design.md"] = "A-DESIGN-FULL\n"
    files[f"{ROOT}/b/design.md"] = "B-DESIGN-START\n" + "x" * 9000 + "\nB-DESIGN-TAIL\n"
    files[f"{ROOT}/c/design.md"] = "C-DESIGN-START\n" + "y" * 9000 + "\nC-DESIGN-TAIL\n"
    w.rev = w.commit(files)
    w.units = {A: UnitInfo(A, f"{ROOT}/a"), B: UnitInfo(B, f"{ROOT}/b"), C: UnitInfo(C, f"{ROOT}/c")}
    return w


def review(world, plan, j1, j2=None, cfg=None, **kw):
    adapters = {"claude-code": j1, "codex": j2 or FakeAdapter([])}
    return review_plan_costed(
        world.app, cfg or cfg_of(), plan, world.units, git=world.git, rev=world.rev, adapters=adapters, **kw
    )


THREE = plan_of({A: [], B: [], C: []})
TWO = plan_of({A: [], B: []})


def outside_data(prompt: str) -> str:
    return re.sub(r"<l4:data.*?</l4:data>", "", prompt, flags=re.S)


# --- SCN-YOLO-276 ----------------------------------------------------------------------------------------------------


def test_scn_yolo_276_a_unit_and_a_batch_that_fit_keep_the_prompt_and_the_keys_of_0458(tmp_path):
    """The expected values were taken by running this on the 0.4.58 code (commit f0bc8a3c)."""
    w = World(tmp_path)
    one, two = "openspec:data-contract", "openspec:service-api"
    w.rev = w.commit(
        {
            "openspec/changes/data-contract/proposal.md": "Why: data.\n",
            "openspec/changes/data-contract/specs/x/spec.md": SPEC_A,
            "openspec/changes/service-api/proposal.md": "Why: api.\n",
            "openspec/changes/service-api/specs/x/spec.md": SPEC_B,
        }
    )
    w.units = {one: UnitInfo(one, "openspec/changes/data-contract"), two: UnitInfo(two, "openspec/changes/service-api")}
    fake = FakeAdapter([ok(), ok(), ok()])
    result, _ = review_plan_costed(
        w.app, make_cfg(), plan_of({one: [], two: [one]}), w.units, git=w.git, rev=w.rev, adapters={"fake": fake}
    )
    assert PROMPT_VERSION == 4
    assert (result.units[one].material, result.units[two].material, result.batches["b1"].material) == (
        "f45e103a2f50207b", "10ccc51ad25a92c8", "9b3b2be18e927743",
    )  # fmt: skip
    assert [hashlib.sha256(r.prompt.encode()).hexdigest()[:16] for r in fake.requests] == [
        "bdd0fb29b01140c1", "637d60b3489df373", "de183686df9d117e",
    ]  # fmt: skip


def test_scn_yolo_276_a_batch_with_one_unit_left_and_a_bound_of_zero_are_asked_whole(world):
    fake = FakeAdapter([ok(), ok()])
    review(world, TWO, fake, cfg=cfg_of(1), done=[A])  # one unit left: nothing to read in part
    assert len(fake.requests) == 2 and "read in part" not in fake.requests[1].prompt
    fake = FakeAdapter([ok(), ok(), ok(), ok()])
    result, _ = review(world, THREE, fake, cfg=cfg_of(0))
    assert len(fake.requests) == 4 and "read in part" not in fake.requests[3].prompt
    assert result.batches["b1"].parts == ()


# --- SCN-YOLO-273 ----------------------------------------------------------------------------------------------------


def test_scn_yolo_273_a_large_batch_is_reviewed_in_parts_from_the_start(world):
    fake = FakeAdapter([ok() for _ in range(7)])
    result, _ = review(world, THREE, fake, cfg=cfg_of(1000))
    assert len(fake.requests) == 7  # A, B, C, the parts of A, B and C, the summary: never the whole batch
    prompts = [r.prompt for r in fake.requests]
    part_a, part_b, part_c, summary = prompts[3:]
    assert "A-DESIGN-FULL" in part_a and "B-DESIGN-START" in part_a and "C-DESIGN-START" in part_a
    assert "B-DESIGN-TAIL" not in part_a and "C-DESIGN-TAIL" not in part_a  # read within 6,000 characters
    assert "B-DESIGN-TAIL" in part_b and "A-DESIGN-FULL" in part_b and "B-DESIGN-TAIL" not in part_a
    assert "C-DESIGN-TAIL" in part_c and "C-DESIGN-TAIL" not in part_b
    assert "A-DESIGN-FULL" in summary and "B-DESIGN-TAIL" not in summary and "C-DESIGN-TAIL" not in summary
    assert all("<l4:data" in p and "read in part" in p for p in prompts[3:])
    for prompt in (part_a, part_b, part_c, summary):  # harness text names no unit and no batch
        text = outside_data(prompt)
        assert A not in text and B not in text and C not in text and "b1" not in text
        assert "This call reviews" in text
    verdict = result.batches["b1"]
    assert len(verdict.parts) == 4
    assert [name for name, _ in verdict.parts] == [
        f"batch:b1/{A}",
        f"batch:b1/{B}",
        f"batch:b1/{C}",
        "batch:b1/summary",
    ]
    assert verdict.missing[-1].startswith("judged in 4 parts")
    assert "yolo.review.max_batch_chars (1000)" in verdict.missing[-1]
    whole = _whole_key(world, THREE)
    assert verdict.material == whole and all(v.material and v.judge for _, v in verdict.parts)


def _whole_key(world, plan):
    """The material key the whole batch would have: asked whole with the bound off."""
    fake = FakeAdapter([ok() for _ in range(len(plan.units()) + 1)])
    result, _ = review(world, plan, fake, cfg=cfg_of(0))
    return result.batches["b1"].material


def test_the_default_bound_is_off_so_a_large_batch_is_asked_whole(tmp_path):
    """`yolo.review.max_batch_chars` defaults to 0: a batch over 160,000 characters is asked whole, and split only after
    its whole call stops at the limit or times out."""
    w = World(tmp_path)
    files = {}
    for name in "abc":
        files[f"{ROOT}/{name}/proposal.md"] = f"Why: {name}.\n"
        files[f"{ROOT}/{name}/specs/x/spec.md"] = SPEC_A
        files[f"{ROOT}/{name}/design.md"] = ("d" * 19_000 + "\n") * 1
        files[f"{ROOT}/{name}/notes-1.md"] = "n" * 19_000 + "\n"
        files[f"{ROOT}/{name}/notes-2.md"] = "m" * 19_000 + "\n"
        files[f"{ROOT}/{name}/notes-3.md"] = "o" * 19_000 + "\n"
    w.rev = w.commit(files)
    w.units = {A: UnitInfo(A, f"{ROOT}/a"), B: UnitInfo(B, f"{ROOT}/b"), C: UnitInfo(C, f"{ROOT}/c")}
    fake = FakeAdapter([ok() for _ in range(4)])
    result, _ = review(w, THREE, fake)  # no bound configured
    batch = fake.requests[-1].prompt
    assert len(batch) > 160_000 and "read in part" not in batch and len(fake.requests) == 4
    assert result.batches["b1"].parts == ()


# --- the note that a batch was reviewed in parts (L4-YOLO-098) -------------------------------------------------------


def parts_findings(verdict):
    return [f for f in verdict.findings if f["criterion"] == "parts"]


def test_a_batch_in_parts_carries_one_minor_finding_that_says_so_and_stays_ready(world):
    fake = FakeAdapter([ok() for _ in range(7)])
    result, _ = review(world, THREE, fake, cfg=cfg_of(1000))
    verdict = result.batches["b1"]
    assert verdict.verdict == "READY" and parts_findings(verdict) == [PARTS_FINDING]  # a note: it blocks nothing
    assert verdict.missing[-1].startswith("judged in 4 parts")  # the `missing` line stays
    assert all(not parts_findings(v) for _, v in verdict.parts)  # the recorded parts are what the judge said
    assert all(not parts_findings(v) for v in result.units.values())


def test_the_finding_is_added_once_to_a_verdict_that_already_has_findings(world):
    major = {"criterion": "contradiction", "severity": "major", "text": "a and b disagree"}
    fake = FakeAdapter([ok(), ok(), said("NEEDS_REVISION", [major]), ok(), ok()])
    result, _ = review(world, TWO, fake, cfg=cfg_of(1000))
    verdict = result.batches["b1"]
    assert verdict.verdict == "NEEDS_REVISION" and verdict.findings == (major, PARTS_FINDING)


def test_a_batch_asked_whole_carries_no_such_finding(world):
    fake = FakeAdapter([ok() for _ in range(4)])
    result, _ = review(world, THREE, fake, cfg=cfg_of(0))
    assert not parts_findings(result.batches["b1"]) and result.batches["b1"].parts == ()


def test_every_way_into_parts_carries_the_finding(world):
    limit = Step(status="error", length_stop=True, detail="stopped at the output limit")
    j1 = FakeAdapter([ok(), ok(), limit, ok(), ok(), ok()])
    by_limit, _ = review(world, TWO, j1)
    j1 = FakeAdapter([ok(), ok(), Step(status="timeout"), ok(), ok(), ok()])
    by_timeout, _ = review(world, TWO, j1)
    first = _first_review(world)
    prior = {v.material: _entry(v) for v in first.units.values()}
    kept = [v.material for _, v in first.batches["b1"].parts][:2]
    prior.update({v.material: _entry(v) for _, v in first.batches["b1"].parts})
    by_kept, _ = review(world, THREE, FakeAdapter([]), cfg=cfg_of(0), prior=prior, kept=kept)
    for result in (by_limit, by_timeout, by_kept):
        assert parts_findings(result.batches["b1"]) == [PARTS_FINDING]


# --- SCN-YOLO-274 ----------------------------------------------------------------------------------------------------


def test_scn_yolo_274_a_whole_batch_at_the_output_limit_is_split_for_the_same_judge(world):
    limit = Step(status="error", length_stop=True, detail="stopped at the output limit")
    j1 = FakeAdapter([ok(), ok(), limit, ok(), ok(), limit])  # A, B, the whole batch, parts A and B, the summary
    j2 = FakeAdapter([ok()])
    result, _ = review(world, TWO, j1, j2)
    assert len(j1.requests) == 6 and len(j2.requests) == 1
    assert "read in part" in j2.requests[0].prompt
    verdict = result.batches["b1"]
    assert "the whole batch stopped at the output limit of j1" in verdict.missing[-1]
    assert [(f.profile, f.subject, f.kind) for f in result.failures] == [("j1", "batch:b1/summary", "length")]
    assert verdict.judge == "j1, j2"


def test_scn_yolo_274_a_whole_batch_that_times_out_is_split_the_same_way(world):
    j1 = FakeAdapter([ok(), ok(), Step(status="timeout"), ok(), ok(), ok()])
    result, _ = review(world, TWO, j1)
    verdict = result.batches["b1"]
    assert "the whole batch timed out on j1" in verdict.missing[-1] and len(verdict.parts) == 3
    assert result.failures == ()  # a timeout that splits the batch is no failure


def test_scn_yolo_274_a_part_that_times_out_ends_the_review_for_the_run(world):
    j1 = FakeAdapter([ok(), ok(), ok(), Step(status="timeout")])
    with pytest.raises(ReviewIncomplete) as err:
        review(world, TWO, j1, cfg=cfg_of(1000))
    exc = err.value
    assert exc.reason == "timeout" and list(exc.answered) == [A, B, f"batch:b1/{A}"]
    assert exc.left == ("batch:b1", f"batch:b1/{B}", "batch:b1/summary")


# --- SCN-YOLO-275 ----------------------------------------------------------------------------------------------------

F = {"criterion": "contradiction", "severity": "major", "text": "a and b disagree"}
MINOR = {"criterion": "outcome", "severity": "minor", "text": "wording"}
GAP = {"criterion": "batch_acceptance", "severity": "major", "text": "no outcome"}


def test_scn_yolo_275_the_parts_make_one_verdict():
    parts = [
        Verdict("READY"),
        Verdict("NEEDS_REVISION", (F,), ("a1",), ("m1",)),
        Verdict("NEEDS_REVISION", (F,), ("a1",), ("m1",)),
        Verdict("READY", (MINOR,), ("a2",)),
    ]
    merged = merge_parts(parts, "its material has 9 characters, over yolo.review.max_batch_chars (1)")
    assert merged.verdict == "NEEDS_REVISION" and merged.findings == (F, MINOR)
    assert merged.assumptions == ("a1", "a2") and merged.missing[0] == "m1"
    assert merged.missing[-1] == (
        "judged in 4 parts (each unit in full with the other units read in part, and every unit read in part): no "
        "call saw two units of the batch in full together; why: its material has 9 characters, over "
        "yolo.review.max_batch_chars (1)"
    )
    blocked = Verdict("BLOCKED", ({"criterion": "schema", "severity": "blocking", "text": "schema_invalid: x"},))
    assert merge_parts([*parts[:3], blocked], "why").verdict == "BLOCKED"


def test_scn_yolo_275_a_batch_without_a_profile_whose_only_finding_is_batch_acceptance_is_ready():
    merged = merge_parts([Verdict("READY"), Verdict("NEEDS_REVISION", (GAP,))], "why")
    grouping = Subject("batch", "b1", "", groups_only=True)
    amended = _amend(merged, grouping)
    assert amended.verdict == "READY" and amended.findings == ()
    assert any("batch_acceptance does not apply" in a and "no outcome" in a for a in amended.assumptions)


def test_a_part_that_says_needs_revision_and_names_nothing_is_never_merged_into_ready():
    """The harness finding for a NEEDS_REVISION that names no finding is made per part, before the merge: another
    part's minor finding must not hide it (L4-YOLO-098)."""
    silent = Verdict("NEEDS_REVISION", missing=("m1",))
    merged = merge_parts([silent, Verdict("READY", (MINOR,))], "why")
    assert merged.verdict == "NEEDS_REVISION"
    verdicts = [f for f in merged.findings if f["criterion"] == "verdict"]
    assert len(verdicts) == 1 and verdicts[0]["severity"] == "major" and "m1" in verdicts[0]["text"]
    assert MINOR in merged.findings
    amended = _amend(merged, Subject("batch", "b1", ""))
    assert amended.verdict == "NEEDS_REVISION" and verdicts[0] in amended.findings


def test_a_silent_part_keeps_the_review_of_a_batch_from_being_ready(world):
    silent = said("NEEDS_REVISION")
    minor = said("READY", [MINOR])
    fake = FakeAdapter([ok(), ok(), silent, minor, ok()])  # A, B, part A, part B, the summary
    result, _ = review(world, TWO, fake, cfg=cfg_of(1000))
    verdict = result.batches["b1"]
    assert verdict.verdict == "NEEDS_REVISION"
    assert any(f["criterion"] == "verdict" for f in verdict.findings)
    raw = dict(verdict.parts)[f"batch:b1/{A}"]
    assert raw.verdict == "NEEDS_REVISION" and raw.findings == ()  # the recorded part is what the judge said


# --- SCN-YOLO-277 ----------------------------------------------------------------------------------------------------


def _entry(v):
    entry = {
        "verdict": v.verdict,
        "findings": list(v.findings),
        "assumptions": [],
        "missing": [],
        "material": v.material,
    }
    if v.parts:
        entry["parts"] = [{"part": name, **_entry(part)} for name, part in v.parts]
    return entry


def _first_review(world):
    fake = FakeAdapter([ok() for _ in range(7)])
    result, _ = review(world, THREE, fake, cfg=cfg_of(1000))
    return result


def test_scn_yolo_277_a_kept_part_is_reused_and_only_the_others_are_asked(world):
    first = _first_review(world)
    parts = dict(first.batches["b1"].parts)
    prior = {v.material: _entry(v) for v in first.units.values()}
    kept = [f"batch:b1/{A}", "batch:b1/summary"]
    prior.update({parts[name].material: _entry(parts[name]) for name in kept})
    fake = FakeAdapter([ok(), ok()])
    result, _ = review(world, THREE, fake, cfg=cfg_of(0), prior=prior, kept=[parts[n].material for n in kept])
    assert len(fake.requests) == 2  # the two other parts, and no whole-batch request
    assert all("read in part" in r.prompt for r in fake.requests)
    verdict = result.batches["b1"]
    assert "an earlier review run answered a part of it" in verdict.missing[-1] and len(verdict.parts) == 4
    reused = {name: v.reused_from for name, v in verdict.parts}
    assert reused[kept[0]] is None and reused[kept[1]] is None  # the entries had no `at`: reuse is marked by the key
    assert [n for n, v in verdict.parts if v.judge is None] == kept


def test_a_part_of_a_finished_review_does_not_split_the_batch_again(world):
    """Parts in `prior` that no incomplete review kept (they come from a `plan.reviewed`) are reused when the batch is
    split, but they do not split it: with the bound off the changed batch is asked whole."""
    first = _first_review(world)
    prior = {v.material: _entry(v) for v in first.units.values()}
    prior.update({v.material: _entry(v) for _, v in first.batches["b1"].parts})
    fake = FakeAdapter([ok()])
    result, _ = review(world, THREE, fake, cfg=cfg_of(0), prior=prior)
    assert len(fake.requests) == 1 and "read in part" not in fake.requests[0].prompt
    assert result.batches["b1"].parts == ()
    only_units = FakeAdapter([ok()])
    kept = [v.material for v in first.units.values()]  # a unit kept by an incomplete review is no part: still whole
    review(world, THREE, only_units, cfg=cfg_of(0), prior=prior, kept=kept)
    assert len(only_units.requests) == 1 and "read in part" not in only_units.requests[0].prompt


def test_a_batch_split_for_its_size_reuses_the_parts_of_a_finished_review(world):
    first = _first_review(world)
    prior = {v.material: _entry(v) for v in first.units.values()}
    prior.update({v.material: _entry(v) for _, v in first.batches["b1"].parts})
    fake = FakeAdapter([])
    result, _ = review(world, THREE, fake, cfg=cfg_of(1000), prior=prior)
    assert fake.requests == [] and len(result.batches["b1"].parts) == 4


def test_scn_yolo_277_fresh_asks_every_part_again_and_a_whole_key_in_prior_reuses_the_batch(world):
    first = _first_review(world)
    batch_key = first.batches["b1"].material
    prior = {v.material: _entry(v) for v in first.units.values()}
    prior.update({v.material: _entry(v) for _, v in first.batches["b1"].parts})
    prior[batch_key] = _entry(first.batches["b1"])
    nothing = FakeAdapter([])
    reused, cost = review(world, THREE, nothing, cfg=cfg_of(1000), prior=prior)
    assert nothing.requests == [] and cost == 0 and reused.batches["b1"].material == batch_key
    fake = FakeAdapter([ok() for _ in range(4)])
    review(world, THREE, fake, cfg=cfg_of(1000), prior=prior, fresh=("batch:b1",))
    assert len(fake.requests) == 4 and all("read in part" in r.prompt for r in fake.requests)


def test_a_part_key_is_the_key_of_its_own_text(world):
    first = _first_review(world)
    keys = [v.material for _, v in first.batches["b1"].parts]
    assert len(set(keys)) == 4 and material_key("batch", "x") not in keys


def test_fresh_on_a_batch_judged_in_parts_asks_every_part_again_even_under_the_bound(world):
    first = _first_review(world)
    prior = {v.material: _entry(v) for v in first.units.values()}
    prior.update({v.material: _entry(v) for _, v in first.batches["b1"].parts})
    prior[first.batches["b1"].material] = _entry(first.batches["b1"])
    fake = FakeAdapter([ok() for _ in range(4)])
    review(world, THREE, fake, prior=prior, fresh=("batch:b1",))  # the default bound: the batch itself is small enough
    assert len(fake.requests) == 4 and all("read in part" in r.prompt for r in fake.requests)


def test_the_summary_part_names_every_prerequisite_outside_the_batch_on_its_own_line(world):
    plan = plan_of({A: ["openspec:x"], B: ["openspec:y"]})
    world.units = {
        **world.units,
        "openspec:x": UnitInfo("openspec:x", f"{ROOT}/c"),
        "openspec:y": UnitInfo("openspec:y", f"{ROOT}/c"),
    }
    fake = FakeAdapter([ok() for _ in range(5)])
    review(world, plan, fake, cfg=cfg_of(1000))
    summary = fake.requests[-1].prompt
    assert '<l4:data source="batch prerequisites outside it">\n- openspec:x\n- openspec:y\n</l4:data>' in summary
