"""human-feedback 2.2 (L4-FBK-004, L4-FBK-007; SCN-FBK-10): what step 0 takes from `feedback.md`. The scan is pure: the
file and the folded ledger in, the takeable items, their blocking findings and the events to record out."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from l4.redact import Redactor
from l4.specs.feedback import (
    FeedbackFile,
    FeedbackKind,
    FeedbackStatus,
    NewFeedback,
    Place,
    Quote,
    append_item,
    content_sha256,
)
from l4.state.fold import fold
from l4.state.ledger import LedgerEvent
from l4.verifier.feedback import feedback_findings, pending_feedback, scan_feedback
from l4.verifier.types import Severity

REDACTOR = Redactor({})
T0 = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
PLACE = Place("src/inventory/reorder.py", 7, 9)


def add(unit: Path, kind: str = "refactor", **kw) -> str:
    kw.setdefault("title", "Extract the rounding")
    kw.setdefault("text", "Move the rounding into a helper.")
    if kind in ("refactor", "duplication", "config"):
        kw.setdefault("places", (PLACE,))
    if kind == "config":
        kw.setdefault("env", "PACK_ROUNDING")
    if kind == "behaviour":
        kw.setdefault("when", "PACK_ROUNDING is `down`")
        kw.setdefault("then", "reorder_quantity rounds down")
    new = NewFeedback(FeedbackKind(kind), by="Ana, 2026-10-12T15:04:00Z", **kw)
    return append_item(unit, "add-reorder", new, redactor=REDACTOR, validate=False)


def state(*rows: tuple[str, dict]):
    events = [LedgerEvent(T0 + timedelta(seconds=n), "r-1", "openspec:p", n, k, d) for n, (k, d) in enumerate(rows)]
    return fold(events, "openspec:p")


def taken(file: FeedbackFile, fid: str = "FB-001", round_: int = 1) -> tuple[str, dict]:
    item = file.get(fid)
    return "feedback.taken", {
        "id": fid, "kind": item.kind.value, "sha256": content_sha256(item), "round": round_, "fix_unit": "p-fix-1",
    }  # fmt: skip


def load(unit: Path) -> FeedbackFile:
    file = FeedbackFile.load(unit)
    assert file is not None
    return file


def test_a_submitted_valid_item_is_takeable_and_becomes_a_blocking_feedback_finding(tmp_path: Path):
    """SCN-FBK-08: one deterministic major finding with source feedback; the structured item travels with it."""
    add(tmp_path, "config", code=(Quote("src/inventory/reorder.py:7-9", "python", "packs = ceil(x)"),))
    scan = scan_feedback(load(tmp_path), state())
    [item] = scan.takeable
    [finding] = feedback_findings(scan)
    assert (finding.source, finding.severity, finding.blocking) == ("feedback", Severity.MAJOR, True)
    assert finding.title == "Feedback FB-001 (config): Extract the rounding"
    assert finding.detail == "Move the rounding into a helper."
    ref = finding.feedback
    assert ref is not None
    assert (ref.id, ref.kind, ref.title, ref.by, ref.env) == (
        "FB-001", "config", "Extract the rounding", "Ana, 2026-10-12T15:04:00Z", "PACK_ROUNDING"
    )  # fmt: skip
    assert ref.places == ("src/inventory/reorder.py:7-9",) and "packs = ceil(x)" in ref.code
    assert ref.sha256 == content_sha256(item) and scan.events == ()


def test_the_detail_keeps_the_text_whole_up_to_1200_characters(tmp_path: Path):
    add(tmp_path, text="word " * 400)
    [finding] = feedback_findings(scan_feedback(load(tmp_path), state()))
    assert len(finding.detail) == 1200 and finding.detail.endswith("...")
    assert finding.feedback.text.startswith("word word")


def test_drafts_withdrawn_and_unknown_items_are_not_taken(tmp_path: Path):
    add(tmp_path, draft=True)
    add(tmp_path)
    file = load(tmp_path).set_status("FB-002", FeedbackStatus.WITHDRAWN)
    scan = scan_feedback(file, state())
    assert scan.takeable == () and scan.events == () and feedback_findings(scan) == []


def test_no_file_means_nothing_to_take():
    scan = scan_feedback(None, state())
    assert scan.takeable == () and scan.events == ()


def test_addressed_and_withdrawn_items_with_unchanged_content_add_no_finding(tmp_path: Path):
    """SCN-FBK-10 (-): nothing to take, nothing changes."""
    add(tmp_path)
    add(tmp_path, title="Other")
    file = load(tmp_path).set_status("FB-001", FeedbackStatus.ADDRESSED).set_status("FB-002", FeedbackStatus.WITHDRAWN)
    after = state(taken(file, "FB-001"), ("feedback.addressed", {"id": "FB-001", "round": 2, "sha": "abc"}))
    scan = scan_feedback(file, after)
    assert scan.takeable == () and scan.events == ()


def test_a_taken_item_is_not_taken_again_while_its_content_is_the_one_taken(tmp_path: Path):
    add(tmp_path)
    file = load(tmp_path).set_status("FB-001", FeedbackStatus.TAKEN)
    assert scan_feedback(file, state(taken(file))).takeable == ()


def test_an_edit_after_the_take_reopens_the_item_and_records_one_changed_event(tmp_path: Path):
    """L4-FBK-007: the content hash decides, whatever the Status says (SCN-FBK-19)."""
    add(tmp_path)
    old = load(tmp_path).set_status("FB-001", FeedbackStatus.ADDRESSED)
    old.save()
    before = state(taken(old))
    path = tmp_path / "feedback.md"
    path.write_text(path.read_text().replace("Move the rounding into a helper.", "Move it and name it `round_up`."))
    file = load(tmp_path)
    assert file.get("FB-001").status is FeedbackStatus.ADDRESSED
    scan = scan_feedback(file, before)
    [item] = scan.takeable
    assert scan.events == (
        ("feedback.changed", {"id": "FB-001", "previous_sha256": content_sha256(old.get("FB-001")),
                              "sha256": content_sha256(item)}),
    )  # fmt: skip
    again = state(taken(old), scan.events[0])  # the round recorded it: a second round says nothing new
    rescan = scan_feedback(file, again)
    assert [i.id for i in rescan.takeable] == ["FB-001"] and rescan.events == ()


def test_a_taken_item_whose_ledger_has_no_take_is_left_alone(tmp_path: Path):
    """Nothing to compare the hash with (a Status written by hand, or a follow-up's take): not taken here."""
    add(tmp_path)
    file = load(tmp_path).set_status("FB-001", FeedbackStatus.TAKEN)
    assert scan_feedback(file, state()).takeable == ()


def test_withdrawing_a_taken_item_records_feedback_withdrawn_once(tmp_path: Path):
    """D7: after a take the item is no longer judged; tasks already written still run."""
    add(tmp_path)
    taken_file = load(tmp_path).set_status("FB-001", FeedbackStatus.TAKEN)
    file = taken_file.set_status("FB-001", FeedbackStatus.WITHDRAWN)
    scan = scan_feedback(file, state(taken(taken_file)))
    assert scan.takeable == () and scan.events == (("feedback.withdrawn", {"id": "FB-001"}),)
    assert scan_feedback(file, state(taken(taken_file), scan.events[0])).events == ()


def test_an_invalid_item_is_reported_once_per_problem_and_never_taken(tmp_path: Path):
    add(tmp_path, "config", env=None)
    file = load(tmp_path)
    scan = scan_feedback(file, state())
    assert scan.takeable == ()
    assert scan.events == (("feedback.invalid", {"id": "FB-001", "problem": "config needs Env"}),)
    again = state(("feedback.invalid", {"id": "FB-001", "problem": "config needs Env"}))
    assert scan_feedback(file, again).events == ()
    other = state(("feedback.invalid", {"id": "FB-001", "problem": "something else"}))
    assert len(scan_feedback(file, other).events) == 1


def test_a_draft_that_is_invalid_is_not_reported(tmp_path: Path):
    add(tmp_path, "config", env=None, draft=True)
    assert scan_feedback(load(tmp_path), state()).events == ()


def test_pending_feedback_is_the_items_taken_and_not_yet_judged(tmp_path: Path):
    """The hand-off to the judge check (2.6): taken items, with their data from the file."""
    for title in ("One", "Two", "Three"):
        add(tmp_path, title=title)
    file = load(tmp_path)
    after = state(
        taken(file, "FB-001"),
        taken(file, "FB-002"),
        ("feedback.addressed", {"id": "FB-002", "round": 3, "sha": "abc", "evidence": "ok"}),
    )
    assert [i.id for i in pending_feedback(after, file)] == ["FB-001"]
    assert pending_feedback(after, None) == []


# --- review #6: a duplicate id is reported, never taken ----------------------------------------------------------


def test_a_duplicate_heading_is_recorded_once_as_invalid_and_never_taken(tmp_path: Path):
    """L4-FBK-004, review #6: the copy is not taken (the first section is the item); the problem is recorded once,
    without making the item itself invalid."""
    add(tmp_path)
    data = (tmp_path / "feedback.md").read_bytes()
    copy = data[data.index(b"## FB-001") :].replace(b"Move the rounding", b"Also rename it")
    (tmp_path / "feedback.md").write_bytes(data + b"\n---\n\n" + copy)
    file = load(tmp_path)
    scan = scan_feedback(file, state())
    assert [(i.id, i.text) for i in scan.takeable] == [("FB-001", "Move the rounding into a helper.")]
    assert scan.events == (
        ("feedback.invalid", {"id": "FB-001", "problem": "duplicate id FB-001", "duplicate": True}),
    )  # fmt: skip
    seen = state(("feedback.invalid", dict(scan.events[0][1])))
    assert scan_feedback(file, seen).events == ()  # once
    assert [i.id for i in scan_feedback(file, seen).takeable] == ["FB-001"]
    taken_state = state(taken(file), ("feedback.invalid", dict(scan.events[0][1])))
    assert taken_state.feedback["FB-001"].status == "taken"  # the copy does not stop the item being judged
    assert [i.id for i in pending_feedback(taken_state, file)] == ["FB-001"]


# --- review #2: an item judged not addressed is never dropped ----------------------------------------------------


def taken_file(tmp_path: Path) -> tuple[FeedbackFile, tuple[str, dict]]:
    """FB-001 as the fix-unit commit leaves it: Status `taken` in the file and `feedback.taken` in the ledger."""
    add(tmp_path)
    file = load(tmp_path).set_status("FB-001", FeedbackStatus.TAKEN)
    return file, taken(file)


def test_a_not_addressed_item_is_takeable_again_at_step_0(tmp_path: Path):
    """L4-FBK-007, review #2 (i) and (iii): the judge said no (`feedback.not_addressed`) and the round ended at the
    feedback limit, or the run died before `fix.spawned`. The file still says `taken`; step 0 takes it again."""
    file, take = taken_file(tmp_path)
    not_addressed = ("feedback.not_addressed", {"id": "FB-001", "round": 2, "evidence": "still nested"})
    after = state(take, not_addressed)
    assert after.feedback["FB-001"].status == "not_addressed"
    assert pending_feedback(after, file) == []  # the judge is not asked until it is taken again
    assert [i.id for i in scan_feedback(file, after).takeable] == ["FB-001"]


def test_a_waiting_item_that_was_taken_is_takeable_again_at_step_0(tmp_path: Path):
    """L4-FBK-005, review #2 (ii): a not-addressed item past `MAX_FIX_TASKS` waits; the next round takes it."""
    file, take = taken_file(tmp_path)
    rows = (take, ("feedback.not_addressed", {"id": "FB-001", "round": 2, "evidence": "x"}),
            ("feedback.waiting", {"ids": ["FB-001"], "reason": "fix_unit_full"}))  # fmt: skip
    waiting = state(*rows)
    assert waiting.feedback["FB-001"].status == "waiting" and waiting.feedback["FB-001"].sha256
    assert [i.id for i in scan_feedback(file, waiting).takeable] == ["FB-001"]
    # the take records it again, and then it is the judge's again, not step 0's
    again = state(*rows, ("feedback.taken", {**take[1], "round": 3, "fix_unit": "p-fix-3"}))
    assert scan_feedback(file, again).takeable == ()
    assert [i.id for i in pending_feedback(again, file)] == ["FB-001"]


def test_every_ledger_state_of_a_taken_item_is_takeable_or_pending(tmp_path: Path):
    """review #2: no item sits in a state that is neither takeable (step 0) nor pending (the judge)."""
    file, take = taken_file(tmp_path)
    after = {
        "taken": (),
        "not_addressed": (("feedback.not_addressed", {"id": "FB-001", "round": 2, "evidence": "x"}),),
        "waiting": (("feedback.waiting", {"ids": ["FB-001"], "reason": "fix_unit_full"}),),
    }
    for status, rows in after.items():
        folded = state(take, *rows)
        assert folded.feedback["FB-001"].status == status
        takeable = [i.id for i in scan_feedback(file, folded).takeable]
        pending = [i.id for i in pending_feedback(folded, file)]
        assert (takeable, pending) == (([], ["FB-001"]) if status == "taken" else (["FB-001"], [])), status


def test_a_not_addressed_item_past_the_fix_unit_is_taken_in_a_later_round(tmp_path: Path):
    """review #2 (ii), whole path: 5 blockers and a not-addressed item fill the unit; the item waits; the round after
    takes it."""
    from l4.verifier.feedback import decide_feedback, feedback_ref, not_addressed_findings
    from l4.verifier.fixunit import plan_fix_unit
    from l4.verifier.types import Finding, Verdict, VerifyResult

    file, take = taken_file(tmp_path)
    asked = [feedback_ref(file.get("FB-001"))]
    found = not_addressed_findings(decide_feedback(asked, [[]], lambda n: True), asked)
    blockers = [Finding(Severity.BLOCKER, f"gate {i} failed", "x", "deterministic") for i in range(5)]
    result = VerifyResult("openspec:p", 2, Verdict.FAIL, "h", "b", findings=[*blockers, *found])
    plan = plan_fix_unit([], result, (), ordinal=2, fix_minor=False)
    assert plan.waiting == ["FB-001"] and plan.taken == []
    waiting = state(take, ("feedback.not_addressed", {"id": "FB-001", "round": 2, "evidence": "not answered"}),
                    ("feedback.waiting", {"ids": plan.waiting, "reason": "fix_unit_full"}))  # fmt: skip
    [item] = scan_feedback(file, waiting).takeable
    third = plan_fix_unit([], VerifyResult("openspec:p", 3, Verdict.FAIL, "h", "b", findings=feedback_findings(
        scan_feedback(file, waiting))), (), ordinal=3, fix_minor=False)  # fmt: skip
    assert [r.id for r in third.taken] == [item.id]
