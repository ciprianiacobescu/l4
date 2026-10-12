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
