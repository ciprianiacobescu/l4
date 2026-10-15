"""Which units' archive pull requests the sweep may merge (L4-YOLO-009, D14): only those of an active `merge: auto` plan
on the base branch, read from the fetched plan ref."""

import pytest

from l4.yolo.cycle import auto_plan_units

from .yolo_cycle_world import CycleWorld, ev, unit_id

A, B = unit_id("a"), unit_id("b")


@pytest.fixture
def world(tmp_path):
    return CycleWorld(tmp_path)


def units(world) -> frozenset[str]:
    return auto_plan_units(world.app, world.cfg, world.git)


def test_no_plan_file_means_no_unit(world):
    assert units(world) == frozenset()


def test_the_units_of_an_active_auto_plan(world):
    world.plan(merge="auto")
    world.activate()
    assert units(world) == {A, B}


@pytest.mark.parametrize("merge", ["human"])
def test_a_human_merge_plan_has_none(world, merge):
    world.plan(merge=merge)
    world.activate()
    assert units(world) == frozenset()


def test_a_plan_that_is_not_active_has_none(world):
    world.plan(merge="auto")
    world.reviewed()
    assert units(world) == frozenset()
    world.activate()
    world.seed(ev("plan.stopped", reason="unit_halted", unit=A))
    assert units(world) == frozenset()


def test_an_unreadable_plan_state_means_no_unit(world, monkeypatch):
    world.plan(merge="auto")
    world.activate()

    def broken(self):
        raise ValueError("ledger.jsonl line 1 is not a plan event")

    monkeypatch.setattr("l4.yolo.store.PlanStore.read", broken)
    assert units(world) == frozenset()


# --- review-resolution 3.5: an accepted finding the verifier did not address blocks the merge (L4-YOLO-028) ---

from l4.yolo.digest import plan_digest  # noqa: E402
from l4.yolo.findings import finding_id  # noqa: E402
from l4.yolo.state import fold_plan  # noqa: E402

TEXT1, TEXT2 = "no example for the empty cart", "the order is unclear"
F1 = {"criterion": "testability", "severity": "major", "text": TEXT1}
F2 = {"criterion": "ordering", "severity": "major", "text": TEXT2}
ID1, ID2 = finding_id(A, F1), finding_id(A, F2)


def accepted_item(*findings):
    return {"findings": list(findings), "reason": "use a plain path", "by": "alice", "actor": "person"}


def in_review(world, *, accepted=None, merge="auto", **state):
    """An active plan whose unit a is in review with a PASS and an open PR; `accepted`: subject -> item, frozen at the
    activation. `state`: the unit fold's `accepted_addressed` / `accepted_evidence`."""
    world.plan(merge=merge)
    world.activate()
    if accepted is not None:
        text = (world.repo / ".l4" / "plans" / "p1.json").read_text(encoding="utf-8")
        world.seed(ev("plan.activated", plan_digest=plan_digest(text), digests=world.digests(), limits={},
                      by="alice", reason="go", accepted=accepted))  # fmt: skip
    world.seed(ev("unit.dispatched", unit=A, run="r0"))
    head = world.unit_branch("a")
    world.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    return head, {"a": world.in_review("a", head, **state)}


def waits(world):
    return [e for e in world.events() if e.type == "plan.waiting"]


def test_scn_yolo_69_two_open_findings_make_the_plan_wait_and_nothing_is_pushed(world):
    head, snaps = in_review(
        world, accepted={A: accepted_item(F1, F2)}, accepted_evidence={ID1: "src/cart.py:9 still sums inline"}
    )
    tip = world.tip()
    step = world.step(snaps)
    assert world.tip() == tip != head and step.start_next_run is False
    assert "unit.merge_requested" not in world.kinds() and "unit.merged" not in world.kinds()
    (waiting,) = waits(world)
    assert waiting.data["reason"] == "accepted_finding_open" and waiting.data["unit"] == A
    assert waiting.data["detail"] == (
        f"{A}: {ID1} not addressed: src/cart.py:9 still sums inline; {ID2} not addressed: no answer recorded"
    )
    assert fold_plan("p1", world.events()).wait_reason == "accepted_finding_open"
    n = len(world.events())
    world.step(snaps)
    assert len(world.events()) == n  # the same detail is recorded once


def test_after_a_persons_merge_the_next_step_integrates_the_unit(world):
    _, snaps = in_review(world, accepted={A: accepted_item(F1)})
    world.step(snaps)
    assert fold_plan("p1", world.events()).status == "waiting"
    world.step({"a": world.snapshot("a", "merged")})  # the person merged the PR
    assert A in fold_plan("p1", world.events()).integrated


def test_an_adopted_unit_with_a_pass_and_no_answer_waits(world):
    world.plan(merge="auto")
    world.activate()
    text = (world.repo / ".l4" / "plans" / "p1.json").read_text(encoding="utf-8")
    world.seed(ev("plan.activated", plan_digest=plan_digest(text), digests=world.digests(), limits={}, by="alice",
                  reason="go", accepted={A: accepted_item(F1)}))  # fmt: skip
    head = world.unit_branch("a")
    world.forge.create_pr("l4/openspec/a", "main", "[l4] a", "b", draft=False)
    tip = world.tip()
    world.step({"a": world.in_review("a", head)})  # not dispatched by the plan: adopted in review
    assert world.tip() == tip and "unit.merged" not in world.kinds()
    (waiting,) = waits(world)
    assert (
        waiting.data["reason"] == "accepted_finding_open"
        and f"{ID1} not addressed: no answer recorded" in waiting.data["detail"]
    )


def test_an_addressed_finding_merges_as_before(world):
    head, snaps = in_review(world, accepted={A: accepted_item(F1)}, accepted_addressed=frozenset({ID1}))
    world.step(snaps)
    assert world.tip() == head and "unit.merged" in world.kinds() and not waits(world)


def test_one_open_finding_of_two_still_blocks(world):
    _, snaps = in_review(world, accepted={A: accepted_item(F1, F2)}, accepted_addressed=frozenset({ID1}))
    world.step(snaps)
    (waiting,) = waits(world)
    assert ID2 in waiting.data["detail"] and ID1 not in waiting.data["detail"]


def test_a_unit_with_no_accepted_item_merges_as_before(world):
    head, snaps = in_review(world)
    world.step(snaps)
    assert world.tip() == head and "unit.merged" in world.kinds()


def test_an_item_of_another_unit_does_not_block(world):
    head, snaps = in_review(world, accepted={B: accepted_item(F1)})
    world.step(snaps)
    assert world.tip() == head and "unit.merged" in world.kinds()


def _batch_item_plan(world, name, *, integrated=(), **state):
    """An active two-unit batch with one batch-level accepted finding; `name` is in review with a PASS."""
    world.plan(merge="auto", deps={})
    world.activate()
    text = (world.repo / ".l4" / "plans" / "p1.json").read_text(encoding="utf-8")
    world.seed(ev("plan.activated", plan_digest=plan_digest(text), digests=world.digests(), limits={}, by="alice",
                  reason="go", accepted={"batch:b1": accepted_item(F1)}))  # fmt: skip
    for done in integrated:
        world.seed(ev("unit.integrated", unit=unit_id(done), revision="r"))
    world.seed(ev("unit.dispatched", unit=unit_id(name), run="r0"))
    head = world.unit_branch(name)
    world.forge.create_pr(f"l4/openspec/{name}", "main", f"[l4] {name}", "b", draft=False)
    return head, {name: world.in_review(name, head, **state)}


def test_a_batch_item_does_not_hold_a_unit_that_does_not_complete_the_batch(world):
    head, snaps = _batch_item_plan(world, "a")
    world.step(snaps)
    assert world.tip() == head and "unit.merged" in world.kinds() and not waits(world)


def test_the_unit_that_completes_the_batch_waits_for_the_batch_item(world):
    _, snaps = _batch_item_plan(world, "b", integrated=["a"])
    world.step(snaps)
    (waiting,) = waits(world)
    assert waiting.data["reason"] == "accepted_finding_open" and finding_id("batch:b1", F1) in waiting.data["detail"]


def test_the_unit_that_completes_the_batch_merges_once_the_batch_item_is_addressed(world):
    bid = finding_id("batch:b1", F1)
    head, snaps = _batch_item_plan(world, "b", integrated=["a"], accepted_addressed=frozenset({bid}))
    world.step(snaps)
    assert world.tip() == head and "unit.merged" in world.kinds() and not waits(world)


def test_a_human_merge_plan_is_unchanged(world):
    _, snaps = in_review(world, accepted={A: accepted_item(F1)}, merge="human")
    world.step(snaps)
    assert not waits(world) and "unit.merged" not in world.kinds()


def test_the_wait_ends_when_a_later_round_addresses_the_findings(world):
    head, snaps = in_review(world, accepted={A: accepted_item(F1)})
    world.step(snaps)
    assert fold_plan("p1", world.events()).wait_reason == "accepted_finding_open"
    again = {"a": world.in_review("a", head, accepted_addressed=frozenset({ID1}))}
    world.step(again)
    kinds = world.kinds()
    assert "plan.resumed" in kinds and world.tip() == head and "unit.merged" in kinds


def test_a_changed_evidence_is_recorded_as_a_new_wait(world):
    head, snaps = in_review(world, accepted={A: accepted_item(F1)}, accepted_evidence={ID1: "first"})
    world.step(snaps)
    world.step({"a": world.in_review("a", head, accepted_evidence={ID1: "second"})})
    assert [e.data["detail"].rsplit(": ", 1)[1] for e in waits(world)] == ["first", "second"]


# --- the report -------------------------------------------------------------------------------------------------------


def report_of(world, units):
    from l4.yolo.plans import plan_files
    from l4.yolo.report import render_report

    (file,) = plan_files(world.repo)
    events = world.events()
    return render_report(
        repository="r", plan=file.plan, state=fold_plan("p1", events), events=events, target_revision="abc",
        units=units, generated_at="t",
    )  # fmt: skip


def test_the_report_lists_the_accepted_findings_who_accepted_them_and_the_answers(world):
    from l4.state.fold import UnitState

    in_review(world, accepted={A: accepted_item(F1, F2)})
    unit = UnitState(unit=A, accepted_addressed=frozenset({ID1}), accepted_evidence={ID2: "still inline"})
    text = report_of(world, {A: unit})
    section = text.split(f"### {A}")[1].split("### ")[0]
    assert "Accepted review findings (accepted by alice (person): use a plain path):" in section
    assert f"{ID1} [testability/major] {TEXT1}: addressed by the verifier" in section
    assert f"{ID2} [ordering/major] {TEXT2}: not addressed: still inline" in section
    other = text.split("### openspec:b")[1]
    assert "Accepted review findings" not in other


def test_the_report_says_no_answer_recorded(world):
    in_review(world, accepted={A: accepted_item(F1)})
    assert f"{ID1} [testability/major] {TEXT1}: no answer recorded" in report_of(world, {})


def test_the_report_has_no_line_without_items(world):
    world.plan()
    world.activate()
    assert "Accepted review findings" not in report_of(world, {})
