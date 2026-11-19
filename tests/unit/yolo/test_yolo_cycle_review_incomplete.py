"""L4-YOLO-099 at the CI step: a review that does not finish records `plan.review_incomplete` with what it answered
(and the admission, and the cost), the next run asks only the rest, a repeat adds nothing, and `l4 yolo status` shows
it. The judges are scripted `FakeAdapter`s, one per adapter name."""

import pytest

from l4.agents.base import ProbeResult
from l4.agents.fake import FakeAdapter, Step
from l4.yolo import findings as fnd
from l4.yolo.readiness import PROMPT_VERSION, JudgeFailed
from l4.yolo.state import fold_plan

from .yolo_cycle_world import PLAN, READY, CycleWorld, unit_id
from .yolo_review_world import make_cfg

A, B = unit_id("a"), unit_id("b")
PROFILES = {
    "impl": {"adapter": "fake", "vendor": "vendor-a"},
    "j1": {"adapter": "claude-code", "vendor": "anthropic"},
    "j2": {"adapter": "codex", "vendor": "openai"},
}
REFUSED = {"hello": ProbeResult("hello", False, reason="hello refused")}


def ok(**kw):
    return Step(structured=READY, **kw)


@pytest.fixture
def world(tmp_path):
    w = CycleWorld(tmp_path)
    w.cfg = make_cfg(
        forge={"type": "local", "base_branch": "main", "merge_policy": "auto"},
        profiles=PROFILES,
        roles={"implementer": ["impl"], "judges": ["j1", "j2"]},
    )
    return w


def judges(world, j1, j2):
    world.adapters = {"claude-code": j1, "codex": j2}


def last(world, kind):
    return [e for e in world.events() if e.type == kind][-1]


def first_failed_review(world, **plan):
    """SCN-YOLO-278: j1's hello fails, j2 answers A and B and ends `error` on the batch."""
    world.plan(**plan)
    j2 = FakeAdapter([ok(cost_usd=0.1), ok(cost_usd=0.1), Step(status="error", detail="boom", cost_usd=0.1)])
    judges(world, FakeAdapter([], probes=REFUSED), j2)
    return world.step()


def test_scn_yolo_278_every_judge_fails_and_the_reason_is_recorded(world):
    step = first_failed_review(world)
    assert world.kinds() == ["plan.admitted", "plan.review_incomplete", "plan.charged"]
    assert fold_plan(PLAN, world.events()).status == "admitted"
    event = last(world, "plan.review_incomplete").data
    assert (event["source"], event["reason"], event["prompt_version"]) == ("ci", "no_judge", PROMPT_VERSION)
    assert set(event["answered"]) == {A, B} and event["left"] == ["batch:b1"]
    digests = world.digests()
    for unit in (A, B):
        assert event["answered"][unit]["judge"] == "j2" and event["answered"][unit]["digest"] == digests[unit]
        assert event["answered"][unit]["material"] and event["answered"][unit]["verdict"] == "READY"
    assert [(f["profile"], f["subject"], f["kind"]) for f in event["failures"]] == [
        ("j1", "", "unusable"),
        ("j2", "batch:b1", "error"),
    ]
    assert "hello refused" in event["failures"][0]["detail"] and event["failures"][1]["material"]
    assert event["cost_usd"] == pytest.approx(0.3)
    charged = last(world, "plan.charged").data
    assert charged["unit"] == "plan:review" and charged["cost_usd"] == pytest.approx(0.3)
    lines = [a.removeprefix(f"plan {PLAN}: ") for a in step.actions]
    assert "j1: selection: unusable: " in "\n".join(lines) and any(
        "j2: batch:b1: error: boom" in line for line in lines
    )
    assert "the review is incomplete (no_judge): 2 answered and kept, 1 left; a later run asks the rest" in lines
    assert step.start_next_run is False


def test_scn_yolo_279_the_next_run_asks_only_what_is_left(world):
    first_failed_review(world)
    incomplete_at = last(world, "plan.review_incomplete").at
    j2 = FakeAdapter([ok()])
    judges(world, FakeAdapter([], probes=REFUSED), j2)
    world.step()
    assert len(j2.requests) == 1 and "read in part" not in j2.requests[0].prompt  # only the batch
    assert world.kinds() == ["plan.admitted", "plan.review_incomplete", "plan.charged", "plan.reviewed"]
    reviewed = last(world, "plan.reviewed").data
    assert reviewed["units"][A]["reused_from"] == incomplete_at == reviewed["units"][B]["reused_from"]
    assert reviewed["batches"]["b1"]["judge"] == "j2" and reviewed["batches"]["b1"]["material"]
    assert reviewed["judge"] == "j2" and reviewed["judges"] == ["j2"]
    assert [(f["profile"], f["subject"], f["kind"]) for f in reviewed["failures"]] == [("j1", "", "unusable")]
    hist = fnd.history(world.events(), A, PROMPT_VERSION)
    assert [h["at"] for h in hist][0] == incomplete_at and hist[0]["source"] == "ci"


def test_scn_yolo_280_a_repeat_adds_nothing_and_a_changed_unit_is_judged_again(world):
    first_failed_review(world, deps={})  # B does not depend on A: its material does not change with A's spec
    head = world.store().read().head
    j2 = FakeAdapter([Step(status="error", detail="boom")])  # A and B are reused: only the batch is asked
    judges(world, FakeAdapter([], probes=REFUSED), j2)
    step = world.step()
    assert world.store().read().head == head and len(j2.requests) == 1
    assert any("the review is incomplete (no_judge): 0 answered and kept, 1 left" in a for a in step.actions)
    spec = "\n".join(line for line in world.unit_files("a")["openspec/changes/a/specs/x/spec.md"].splitlines())
    world.commit({"openspec/changes/a/specs/x/spec.md": spec + "\nA SHALL also be fast.\n"}, "change a")
    world.push_main()
    j2 = FakeAdapter([ok(), Step(status="error", detail="boom")])
    judges(world, FakeAdapter([], probes=REFUSED), j2)
    world.step()
    assert len(j2.requests) == 2  # A again, the batch again; B reused
    again = last(world, "plan.review_incomplete").data
    assert list(again["answered"]) == [A] and again["left"] == ["batch:b1"]


def test_scn_yolo_271_a_timeout_stops_the_run_and_the_next_run_asks_the_other_judge_first(world):
    world.plan()
    j1 = FakeAdapter([ok(), Step(status="timeout")])
    j2 = FakeAdapter([])
    judges(world, j1, j2)
    world.step()
    event = last(world, "plan.review_incomplete").data
    assert event["reason"] == "timeout" and list(event["answered"]) == [A] and event["left"] == [B, "batch:b1"]
    assert [(f["profile"], f["subject"], f["kind"]) for f in event["failures"]] == [("j1", B, "timeout")]
    assert j2.requests == []
    j1, j2 = FakeAdapter([ok()]), FakeAdapter([ok()])
    judges(world, j1, j2)
    world.step()
    assert len(j2.requests) == 1 and len(j1.requests) == 1  # B went to j2 first, the batch to j1; A was not asked
    reviewed = last(world, "plan.reviewed").data
    assert reviewed["units"][B]["judge"] == "j2" and reviewed["batches"]["b1"]["judge"] == "j1"


def test_scn_yolo_272_no_call_starts_in_a_job_without_the_time(world):
    world.plan()
    j1 = FakeAdapter([ok()])
    judges(world, j1, FakeAdapter([]))
    step = world.step(budget=lambda: 600.0)  # the default timeout is 15 minutes
    assert j1.requests == []
    assert world.kinds() == ["plan.admitted", "plan.review_incomplete"]
    event = last(world, "plan.review_incomplete").data
    assert event["reason"] == "job_time" and event["answered"] == {} and event["left"] == [A, B, "batch:b1"]
    assert any("the review is incomplete (job_time): 0 answered and kept, 3 left" in a for a in step.actions)
    judges(world, FakeAdapter([ok(), ok(), ok()]), FakeAdapter([]))
    world.step(budget=lambda: 901.0)
    assert world.kinds()[-1] == "plan.reviewed"


def test_a_review_that_finishes_prints_one_line_per_failure(world):
    world.plan()
    j2 = FakeAdapter([ok(), ok(), ok()])
    judges(world, FakeAdapter([], probes=REFUSED), j2)
    step = world.step()
    assert any("j1: selection: unusable: " in a for a in step.actions)
    reviewed = last(world, "plan.reviewed").data
    assert reviewed["failures"][0]["profile"] == "j1" and "material" not in reviewed["failures"][0]


def test_a_plain_judge_failure_still_records_nothing(world, monkeypatch):
    world.plan()
    head = world.store().read().head

    def failing(*args, **kw):
        raise JudgeFailed("the judge timed out")

    monkeypatch.setattr("l4.yolo.cycle.review_plan_costed", failing)
    step = world.step()
    assert world.store().read().head == head and any("no judge could run" in a for a in step.actions)


def test_scn_yolo_280_a_timeout_on_an_edited_unit_is_recorded_again_and_the_next_run_asks_the_other_judge(world):
    """The repeat check compares the material too: j1 times out on A at no cost, a person edits A, and the same failure
    on the new text must be written, or `failed_before` never learns it and j2 is never asked."""
    world.plan(deps={})
    judges(world, FakeAdapter([Step(status="timeout")]), FakeAdapter([]))
    world.step()
    old = last(world, "plan.review_incomplete").data["failures"][0]["material"]
    spec = world.unit_files("a")["openspec/changes/a/specs/x/spec.md"]
    world.commit({"openspec/changes/a/specs/x/spec.md": spec + "\nA SHALL also be fast.\n"}, "change a")
    world.push_main()
    judges(world, FakeAdapter([Step(status="timeout")]), FakeAdapter([]))
    world.step()
    events = [e for e in world.events() if e.type == "plan.review_incomplete"]
    assert len(events) == 2  # a timeout of the same judge and subject, on another text, is no repeat
    new = events[-1].data["failures"][0]["material"]
    assert new != old
    j1, j2 = FakeAdapter([ok(), ok(), ok()]), FakeAdapter([ok()])
    judges(world, j1, j2)
    world.step()
    assert len(j2.requests) == 1  # A went to j2 first; B and the batch to j1
    assert last(world, "plan.reviewed").data["units"][A]["judge"] == "j2"


def big_design(tail: str) -> dict[str, str]:
    """A's design, longer than the 6,000 characters a part reads of a sibling: the tail is seen only by A's own part."""
    return {"openspec/changes/a/design.md": "A-DESIGN-START\n" + "x" * 9000 + f"\nA-DESIGN-{tail}\n"}


def test_a_batch_that_was_split_before_is_asked_whole_again_once_a_review_finished(world):
    """A part kept from an earlier `plan.reviewed` does not split the batch again: only a part an incomplete review
    kept after the latest `plan.reviewed` does (L4-YOLO-098). With `max_batch_chars: 0` the batch is asked whole."""
    world.cfg = make_cfg(
        forge={"type": "local", "base_branch": "main", "merge_policy": "auto"},
        profiles=PROFILES,
        roles={"implementer": ["impl"], "judges": ["j1", "j2"]},
        yolo={"review": {"max_batch_chars": 0}},
    )
    world.commit(big_design("TAIL"))
    world.push_main()
    world.plan(deps={})
    limit = Step(status="error", length_stop=True, detail="stopped at the output limit")
    judges(world, FakeAdapter([ok(), ok(), limit, ok(), ok(), ok()]), FakeAdapter([]))
    world.step()  # A, B, the whole batch (stops at the limit), the parts of A and B, the summary
    first = last(world, "plan.reviewed").data["batches"]["b1"]
    assert len(first["parts"]) == 3
    world.commit(big_design("TAIX"), "change the tail of a")  # no part but A's own part reads it
    world.push_main()
    j1 = FakeAdapter([ok(), ok()])
    judges(world, j1, FakeAdapter([]))
    world.step()
    assert len(j1.requests) == 2  # A, and the batch asked whole
    assert "read in part" not in j1.requests[1].prompt
    assert "parts" not in last(world, "plan.reviewed").data["batches"]["b1"]


def test_a_batch_reused_whole_keeps_its_part_rows_in_the_next_review(world):
    """A review that reuses a batch judged in parts records the entry with its `parts` rows again."""
    world.plan(deps={})
    limit = Step(status="error", length_stop=True, detail="stopped at the output limit")
    judges(world, FakeAdapter([ok(), ok(), limit, ok(), ok(), ok()]), FakeAdapter([]))
    world.step()
    first = last(world, "plan.reviewed").data["batches"]["b1"]
    assert len(first["parts"]) == 3
    world.plan(deps={}, limits={"max_cost_usd": 55})  # the plan file changes: a new review, with every subject reused
    nothing = FakeAdapter([])
    judges(world, nothing, FakeAdapter([]))
    world.step()
    assert nothing.requests == []
    again = last(world, "plan.reviewed").data["batches"]["b1"]
    assert again["reused_from"] and [r["material"] for r in again["parts"]] == [r["material"] for r in first["parts"]]


def test_a_lost_lease_drops_the_incomplete_record_when_another_run_recorded_one(world, monkeypatch):
    """The lease is lost while the record is written and the ref now holds another `plan.review_incomplete`: this
    run's record is stale and is dropped, not appended again (L4-YOLO-099)."""
    from l4.yolo.model import PlanMoved
    from l4.yolo.store import PlanStore

    world.plan(deps={})
    judges(world, FakeAdapter([Step(status="timeout")]), FakeAdapter([]))
    real, calls = PlanStore.append, []

    def moved(self, events, *, files=None, expect):
        calls.append(1)
        if len(calls) == 1:  # another run wins the race with its own incomplete record
            other = [e for e in events if e.type == "plan.review_incomplete"]
            real(self, other, files=files, expect=expect)
            raise PlanMoved("moved")
        return real(self, events, files=files, expect=expect)

    monkeypatch.setattr(PlanStore, "append", moved)
    world.step()  # the step ends its plan quietly on a stale write
    assert world.kinds().count("plan.review_incomplete") == 1 and len(calls) == 1


def test_the_ci_step_passes_the_kept_parts_so_the_next_run_asks_only_the_remaining_parts(world):
    """An incomplete review kept a part of a batch split by a size bound of 1. The next run, with the bound off,
    splits the batch for the kept part and asks the part of B and the summary: no whole-batch call (L4-YOLO-098)."""
    world.cfg = make_cfg(
        forge={"type": "local", "base_branch": "main", "merge_policy": "auto"},
        profiles=PROFILES,
        roles={"implementer": ["impl"], "judges": ["j1", "j2"]},
        yolo={"review": {"max_batch_chars": 1}},
    )
    world.plan()
    # A, B, the part of A (answered), the part of B (an error: no judge is left, so the summary is not asked)
    j2 = FakeAdapter([ok(), ok(), ok(), Step(status="error", detail="boom")])
    judges(world, FakeAdapter([], probes=REFUSED), j2)
    world.step()
    assert world.kinds()[:2] == ["plan.admitted", "plan.review_incomplete"]
    world.cfg = make_cfg(
        forge={"type": "local", "base_branch": "main", "merge_policy": "auto"},
        profiles=PROFILES,
        roles={"implementer": ["impl"], "judges": ["j1", "j2"]},
        yolo={"review": {"max_batch_chars": 0}},
    )
    again = FakeAdapter([ok(), ok()])
    judges(world, FakeAdapter([], probes=REFUSED), again)
    world.step()
    assert len(again.requests) == 2 and all("read in part" in r.prompt for r in again.requests)  # part of B, summary
    assert "plan.reviewed" in world.kinds()
