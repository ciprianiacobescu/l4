"""A retaken feedback item (L4-FBK-005, review #8 follow-up): an item that had a `feedback.taken` before this fix unit
is flagged `retake` from step 0 or the judge check through the planner into the fix unit's marker (`retakes`), so that
its chore may complete when there is nothing left to change."""

import json
from pathlib import Path

from l4.specs.fixmark import FixMarker, chore_retakes, read_fix_marker, write_fix_marker
from l4.verifier.feedback import decide_feedback, feedback_findings, feedback_ref, not_addressed_findings, scan_feedback
from l4.verifier.fixunit import plan_fix_unit
from l4.verifier.types import Verdict, VerifyResult

from .test_feedback_step0 import add, load, state, taken_file


def retake_flags(file, folded) -> list[bool]:
    return [f.feedback.retake for f in feedback_findings(scan_feedback(file, folded))]


def test_a_first_take_is_not_a_retake(tmp_path: Path):
    add(tmp_path)
    assert retake_flags(load(tmp_path), state()) == [False]


def test_an_item_the_judge_did_not_accept_or_that_waited_is_a_retake(tmp_path: Path):
    file, take = taken_file(tmp_path)
    no = ("feedback.not_addressed", {"id": "FB-001", "round": 2, "evidence": "not answered"})
    assert retake_flags(file, state(take, no)) == [True]
    waiting = ("feedback.waiting", {"ids": ["FB-001"], "reason": "fix_unit_full"})
    assert retake_flags(file, state(take, no, waiting)) == [True]


def test_an_item_edited_after_its_take_is_a_new_request_not_a_retake(tmp_path: Path):
    file, take = taken_file(tmp_path)
    path = tmp_path / "feedback.md"
    path.write_text(path.read_text().replace("Move the rounding into a helper.", "Name the helper round_packs."))
    edited = load(tmp_path)
    scan = scan_feedback(edited, state(take))
    assert [i.id for i in scan.takeable] == ["FB-001"] and [e[0] for e in scan.events] == ["feedback.changed"]
    assert retake_flags(edited, state(take)) == [False]


def test_the_judge_check_flags_what_it_did_not_accept_as_a_retake(tmp_path: Path):
    file, _ = taken_file(tmp_path)
    asked = [feedback_ref(file.get("FB-001"))]
    assert asked[0].retake is False
    [finding] = not_addressed_findings(decide_feedback(asked, [[]], lambda n: True), asked)
    assert finding.feedback is not None and finding.feedback.retake is True


def test_the_planner_hands_the_retake_to_the_group_and_the_marker_lists_it(tmp_path: Path):
    file, take = taken_file(tmp_path)
    folded = state(take, ("feedback.not_addressed", {"id": "FB-001", "round": 2, "evidence": "x"}))
    findings = feedback_findings(scan_feedback(file, folded))
    plan = plan_fix_unit([], VerifyResult("openspec:p", 3, Verdict.FAIL, "h", "b", findings=findings), (), ordinal=2,
                         fix_minor=False)  # fmt: skip
    [group] = plan.groups
    assert group.retake is True and group.refactor is True
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    add(fresh)
    first = plan_fix_unit([], VerifyResult("openspec:p", 1, Verdict.FAIL, "h", "b", findings=feedback_findings(
        scan_feedback(load(fresh), state()))), (), ordinal=1, fix_minor=False)  # fmt: skip
    assert [g.retake for g in first.groups] == [False]


def test_the_marker_round_trips_retakes_and_an_older_marker_has_none(tmp_path: Path):
    marker = FixMarker("openspec:p", 2, ("F-1", "F-2"), ("F-1", "F-2"), (), ("F-1",), ("F-1",))
    write_fix_marker(tmp_path, marker)
    assert read_fix_marker(tmp_path) == marker
    assert json.loads((tmp_path / ".l4" / "fix.json").read_text())["retakes"] == ["F-1"]
    assert chore_retakes(tmp_path, "1.1 task of F-1") is True
    assert chore_retakes(tmp_path, "1.2 task of F-2") is False  # a first take
    assert chore_retakes(tmp_path, "1.3 no chore") is False
    body = json.loads((tmp_path / ".l4" / "fix.json").read_text())
    del body["retakes"]
    (tmp_path / ".l4" / "fix.json").write_text(json.dumps(body))
    assert chore_retakes(tmp_path, "1.1 task of F-1") is False
