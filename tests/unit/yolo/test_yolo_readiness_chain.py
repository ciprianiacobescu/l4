"""L4-YOLO-095..097: the readiness review walks its judge chain per subject, keeps what was answered, bounds each call
by `yolo.review.timeout`, and a review that cannot finish raises `ReviewIncomplete`. The judges are scripted
`FakeAdapter`s, one per adapter name, so each profile of a chain has its own script."""

from datetime import UTC, datetime, timedelta

import pytest

from l4.agents.base import LimitSignal, ProbeResult
from l4.agents.fake import FakeAdapter, Step
from l4.availability.cooldown import AvailabilityStore, cooldown_key
from l4.availability.errors import RoleUnavailable
from l4.config.defaults import cache_root
from l4.config.schema import Profile
from l4.yolo.model import UnitInfo
from l4.yolo.readiness import (
    JudgeFailed,
    ReviewIncomplete,
    Subject,
    _Call,
    _Walk,
    material_key,
    review_chain,
    review_plan_costed,
)

from .yolo_review_world import SPEC_A, SPEC_B, World, make_cfg, plan_of

A, B = "openspec:data-contract", "openspec:service-api"
PROFILES = {
    "impl": {"adapter": "fake", "vendor": "vendor-a"},
    "j1": {"adapter": "claude-code", "vendor": "anthropic"},
    "j2": {"adapter": "codex", "vendor": "openai"},
}
PROFILES_OF = {name: Profile(**profile) for name, profile in PROFILES.items()}


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    w.rev = w.commit(
        {
            "openspec/changes/data-contract/proposal.md": "Why: data.\n",
            "openspec/changes/data-contract/specs/x/spec.md": SPEC_A,
            "openspec/changes/service-api/specs/x/spec.md": SPEC_B,
        }
    )
    w.units = {A: UnitInfo(A, "openspec/changes/data-contract"), B: UnitInfo(B, "openspec/changes/service-api")}
    return w


def ok(**kw):
    return Step(structured={"verdict": "READY", "findings": [], "assumptions": [], "missing": []}, **kw)


def bad():
    return Step(final_text="not json")


def cfg_of(judges=("j1", "j2"), **over):
    return make_cfg(profiles=PROFILES, roles={"implementer": ["impl"], "judges": list(judges)}, **over)


def chain_of(j1, j2):
    return {"claude-code": j1, "codex": j2}


def review(world, plan, j1, j2, cfg=None, **kw):
    return review_plan_costed(
        world.app, cfg or cfg_of(), plan, world.units, git=world.git, rev=world.rev, adapters=chain_of(j1, j2), **kw
    )


SINGLE = plan_of({A: []})
BATCH = plan_of({A: [], B: []})  # one batch b1 of two units: A, B, then batch:b1
SEPARATE = plan_of({A: [], B: []}, batches=[("b1", [A]), ("b2", [B])])


def test_scn_yolo_261_the_review_asks_plan_judges_and_not_judges(world):
    other = {
        **PROFILES,
        "j-unit": {"adapter": "claude-code", "vendor": "anthropic"},
        "j-plan": {"adapter": "codex", "vendor": "openai"},
    }
    cfg = make_cfg(profiles=other, roles={"implementer": ["impl"], "judges": ["j-unit"], "plan_judges": ["j-plan"]})
    unit, plan_judge = FakeAdapter([ok()]), FakeAdapter([ok()])
    result, _ = review(world, SINGLE, unit, plan_judge, cfg=cfg)
    assert unit.requests == [] and len(plan_judge.requests) == 1
    assert result.units[A].judge == "j-plan"


def test_review_chain_is_plan_judges_else_judges():
    assert review_chain(make_cfg(roles={"implementer": ["impl"], "judges": ["judge"]})) == ("judges", ["judge"])
    empty = make_cfg(roles={"implementer": ["impl"], "judges": ["judge"], "plan_judges": []})
    assert review_chain(empty) == ("judges", ["judge"])
    own = make_cfg(profiles={**PROFILES}, roles={"implementer": ["impl"], "judges": ["j1"], "plan_judges": ["j2"]})
    assert review_chain(own) == ("plan_judges", ["j2"])


def test_scn_yolo_263_a_judge_whose_hello_fails_is_skipped_and_named(world):
    j1 = FakeAdapter([], probes={"hello": ProbeResult("hello", False, reason="hello refused")})
    j2 = FakeAdapter([ok(), ok(), ok()])
    result, _ = review(world, BATCH, j1, j2)
    assert {v.judge for v in (*result.units.values(), *result.batches.values())} == {"j2"}
    (failure,) = result.failures
    assert (failure.profile, failure.subject, failure.kind) == ("j1", "", "unusable")
    assert "hello refused" in failure.detail and j1.requests == []


def test_scn_yolo_264_an_error_moves_the_subject_on_and_what_was_answered_is_kept(world):
    j1 = FakeAdapter([ok(cost_usd=0.1), Step(status="error", detail="boom", cost_usd=0.2)])
    j2 = FakeAdapter([ok(cost_usd=0.3), ok(cost_usd=0.4)])
    result, cost = review(world, BATCH, j1, j2)
    assert [result.units[A].judge, result.units[B].judge, result.batches["b1"].judge] == ["j1", "j2", "j2"]
    assert [(f.profile, f.subject, f.kind) for f in result.failures] == [("j1", B, "error")]
    assert "boom" in result.failures[0].detail
    assert len(j1.requests) == 2  # j1 is not asked the batch: an error discards it for the rest of the review
    assert cost == pytest.approx(1.0)


def test_scn_yolo_265_a_schema_break_moves_only_that_subject(world):
    j1 = FakeAdapter([bad(), bad(), ok(), ok()])
    j2 = FakeAdapter([ok()])
    result, _ = review(world, BATCH, j1, j2)
    assert (result.units[A].judge, result.units[B].judge) == ("j2", "j1")
    assert [(f.profile, f.subject, f.kind) for f in result.failures] == [("j1", A, "schema_invalid")]


def test_scn_yolo_266_a_schema_break_with_no_judge_left_is_blocked(world):
    only = cfg_of(judges=("j1",))
    result, _ = review(world, SEPARATE, FakeAdapter([bad(), bad(), ok()]), FakeAdapter([]), cfg=only)
    blocked = result.units[A]
    assert blocked.verdict == "BLOCKED" and blocked.findings[0]["text"].startswith("schema_invalid: ")
    assert result.units[B].verdict == "READY" and result.units[B].judge == "j1"
    # an error of the first judge, then a schema break of the second: still BLOCKED, the review finishes
    result, _ = review(world, SINGLE, FakeAdapter([Step(status="error")]), FakeAdapter([bad(), bad()]))
    assert result.units[A].verdict == "BLOCKED" and result.units[A].findings[0]["criterion"] == "schema"


def test_scn_yolo_266_an_error_with_no_judge_left_leaves_the_review_unfinished(world):
    with pytest.raises(ReviewIncomplete) as err:
        review(
            world, SEPARATE, FakeAdapter([Step(status="error", detail="boom")]), FakeAdapter([]), cfg=cfg_of(("j1",))
        )
    exc = err.value
    assert isinstance(exc, JudgeFailed) and isinstance(exc, RoleUnavailable)
    assert exc.reason == "no_judge" and A in exc.left and exc.answered == {}
    assert "judge_error: the review is incomplete (no_judge)" in str(exc)
    assert [(f.profile, f.subject, f.kind) for f in exc.failures] == [("j1", A, "error")]


def test_scn_yolo_267_a_usage_limit_cools_the_judge_and_the_next_judge_answers(world):
    resets = datetime.now(UTC) + timedelta(hours=2)
    limit = LimitSignal("claude-code", None, "usage_limit", resets, "test", "")
    j1 = FakeAdapter([Step(status="quota", limit=limit)])
    j2 = FakeAdapter([ok(), ok()])
    result, _ = review(world, SEPARATE, j1, j2)  # no RoleLimit leaves the review
    assert (result.units[A].judge, result.units[B].judge) == ("j2", "j2") and len(j1.requests) == 1
    assert [(f.profile, f.subject, f.kind) for f in result.failures] == [("j1", A, "limit")]
    store = AvailabilityStore(cache_root(world.app.environ, repo=world.app.repo))
    cooling = store.cooldowns.cooling(cooldown_key("j1", PROFILES_OF["j1"]), datetime.now(UTC))
    assert cooling is not None and abs(cooling.until - resets) < timedelta(seconds=2)


def test_scn_yolo_268_a_judge_that_failed_a_material_is_asked_it_last(world):
    first, _ = review(world, SEPARATE, FakeAdapter([ok(), ok()]), FakeAdapter([]))
    key_a = first.units[A].material
    j1, j2 = FakeAdapter([ok()]), FakeAdapter([ok()])
    result, _ = review(world, SEPARATE, j1, j2, failed_before={key_a: ["j1"]})
    assert (result.units[A].judge, result.units[B].judge) == ("j2", "j1")
    assert len(j1.requests) == 1 and len(j2.requests) == 1


def test_scn_yolo_270_every_request_carries_the_configured_time(world):
    j1 = FakeAdapter([ok()])
    review(world, SINGLE, j1, FakeAdapter([]), cfg=cfg_of(yolo={"review": {"timeout": "30m"}}))
    assert j1.requests[0].timeout_s == 1800
    j1 = FakeAdapter([ok()])
    review(world, SINGLE, j1, FakeAdapter([]))
    assert j1.requests[0].timeout_s == 900


def test_scn_yolo_271_a_timeout_ends_the_review_for_the_run(world):
    j1 = FakeAdapter([ok(), Step(status="timeout")])
    j2 = FakeAdapter([ok(), ok()])
    with pytest.raises(ReviewIncomplete) as err:
        review(world, BATCH, j1, j2)
    exc = err.value
    assert exc.reason == "timeout" and list(exc.answered) == [A] and exc.answered[A].judge == "j1"
    assert exc.left == (B, "batch:b1")
    assert [(f.profile, f.subject, f.kind) for f in exc.failures] == [("j1", B, "timeout")]
    assert exc.failures[0].material == material_key("unit", _key_text(world, B))
    assert j2.requests == []


def _key_text(world, unit):
    from l4.yolo.readiness import FolderText, _unit_subject, read_folder

    plan = BATCH
    batch = plan.batches[0]
    folder = read_folder(world.git, world.rev, world.units[unit].folder, budget=80_000, base="main")
    assert isinstance(folder, FolderText)
    pu = next(u for u in batch.units if u.id == unit)
    return _unit_subject(plan, pu, batch, folder, []).key_text


def test_scn_yolo_272_no_call_starts_that_the_job_has_no_time_for(world):
    j1 = FakeAdapter([ok()])
    with pytest.raises(ReviewIncomplete) as err:
        review(world, SINGLE, j1, FakeAdapter([]), time_left=lambda: 600.0)
    assert err.value.reason == "job_time" and err.value.left == (A,) and err.value.failures == ()
    assert j1.requests == []
    result, _ = review(world, SINGLE, FakeAdapter([ok()]), FakeAdapter([]), time_left=lambda: 901.0)
    assert result.units[A].verdict == "READY"


def test_scn_yolo_276_a_unit_that_stops_at_the_output_limit_goes_to_the_next_judge_unsplit(world):
    j1 = FakeAdapter([Step(status="error", length_stop=True, detail="stopped at the output limit")])
    j2 = FakeAdapter([ok()])
    result, _ = review(world, SINGLE, j1, j2)
    assert [(f.profile, f.subject, f.kind) for f in result.failures] == [("j1", A, "length")]
    assert result.units[A].judge == "j2" and j1.requests[0].prompt == j2.requests[0].prompt


def test_an_empty_chain_is_a_plain_role_unavailable(world):
    with pytest.raises(RoleUnavailable) as err:
        review(world, SINGLE, FakeAdapter([]), FakeAdapter([]), cfg=cfg_of(judges=()))
    assert not isinstance(err.value, ReviewIncomplete)


def test_every_judge_unusable_is_an_incomplete_review_with_no_answers(world):
    refuse = {"hello": ProbeResult("hello", False, reason="hello refused")}
    with pytest.raises(ReviewIncomplete) as err:
        review(world, SINGLE, FakeAdapter([], probes=refuse), FakeAdapter([], probes=refuse))
    assert err.value.reason == "no_judge" and err.value.answered == {} and err.value.left == (A,)
    assert [(f.profile, f.subject, f.kind) for f in err.value.failures] == [
        ("j1", "", "unusable"),
        ("j2", "", "unusable"),
    ]


def test_the_judge_that_split_a_batch_does_not_come_first_again_for_a_part_it_failed(world):
    """j1 stopped the whole batch at the limit, then timed out on a part: the next run asks that part of j2 first."""
    walk = _Walk(
        world.app, cfg_of(), world.git, BATCH, adapters=None, sandbox=None, sandbox_for=None, timeout_s=900,
        time_left=None, failed_before={"k": ["j1"]},
    )  # fmt: skip
    call = _Call("batch:b1/summary", Subject("batch", "b1", ""), None, "k")
    assert walk.order(call, first="j1") == ["j2", "j1"]
    assert walk.order(_Call("other", Subject("batch", "b1", ""), None, "k2"), first="j2") == ["j2", "j1"]


def test_the_repair_prompt_is_a_call_too_and_a_job_without_the_time_for_it_stops_the_review(world):
    """L4-YOLO-097: a judge call starts only with `yolo.review.timeout` left, the repair after a schema break too."""
    left = iter([901.0, 10.0])  # the first call has the time, the repair does not
    j1 = FakeAdapter([bad(), ok()])
    with pytest.raises(ReviewIncomplete) as err:
        review(world, SINGLE, j1, FakeAdapter([]), time_left=lambda: next(left))
    assert len(j1.requests) == 1  # no second call
    assert err.value.reason == "job_time" and err.value.left == (A,) and err.value.failures == ()
    again = FakeAdapter([bad(), ok()])
    result, _ = review(world, SINGLE, again, FakeAdapter([]), time_left=lambda: 901.0)
    assert len(again.requests) == 2 and result.units[A].verdict == "READY"  # with the time, the repair is asked


def test_a_call_starts_with_exactly_the_timeout_left_and_not_with_a_second_less(world):
    result, _ = review(world, SINGLE, FakeAdapter([ok()]), FakeAdapter([]), time_left=lambda: 900.0)
    assert result.units[A].verdict == "READY"
    j1 = FakeAdapter([ok()])
    with pytest.raises(ReviewIncomplete) as err:
        review(world, SINGLE, j1, FakeAdapter([]), time_left=lambda: 899.0)
    assert err.value.reason == "job_time" and j1.requests == []
