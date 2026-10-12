"""human-feedback 2.7 (L4-FBK-011; D12): the *Your feedback* section of the sticky note and the `To ask for changes:`
line of every note of a unit in review."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from l4.archive import NOTHING_WAITING, compose_sticky
from l4.redact import Redactor
from l4.specs.feedback import (
    FeedbackFile,
    FeedbackKind,
    FeedbackStatus,
    NewFeedback,
    Place,
    append_item,
    content_sha256,
)
from l4.state.fold import fold
from l4.state.ledger import LedgerEvent
from l4.state.lifecycle import Trigger
from l4.verifier.notes import FEEDBACK_HINT, feedback_section

from .conftest import BRANCH, UNIT_DIR, green_step, red_step

T0 = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
RUN = "r-20261012T1200Z-aaaa"
BY = "CiprianSpot, 2026-10-12T15:04:00Z"
REDACTOR = Redactor({})
HINT = (
    'To ask for changes: l4 feedback add --kind refactor|duplication|tests|config|behaviour --at FILE:LINE '
    '--text "…", then commit and push (docs/feedback.md).'
)


def add(unit: Path, kind: str = "refactor", text: str = "Move the rounding into a helper.", **kw) -> str:
    if kind in ("refactor", "duplication", "config"):
        kw.setdefault("places", (Place("src/inventory/reorder.py", 7, 9),))
    if kind == "config":
        kw.setdefault("env", "PACK_ROUNDING")
    if kind == "behaviour":
        kw.setdefault("when", "PACK_ROUNDING is `down`")
        kw.setdefault("then", "reorder_quantity rounds down")
    new = NewFeedback(FeedbackKind(kind), title="A title", text=text, by=BY, **kw)
    return append_item(unit, "add-reorder", new, redactor=REDACTOR, validate=False)


def status(unit: Path, fid: str, value: FeedbackStatus) -> None:
    file = FeedbackFile.load(unit)
    assert file is not None
    file.set_status(fid, value).save()


def state(*rows: tuple[str, dict]):
    events = [
        LedgerEvent(T0 + timedelta(seconds=n), RUN, "openspec:add-reorder", n, kind, data)
        for n, (kind, data) in enumerate(rows)
    ]
    return fold(events, "openspec:add-reorder")


def lines_of(unit: Path, folded) -> list[str]:
    section = feedback_section(FeedbackFile.load(unit), folded)
    assert section is not None
    head, blank, *body = section.splitlines()
    assert head == "### Your feedback" and blank == ""
    return body


def taken(fid: str = "FB-001", sha: str = "a" * 64, round_: int = 1, fix_unit: str = "add-reorder-fix-1"):
    return "feedback.taken", {"id": fid, "kind": "refactor", "sha256": sha, "round": round_, "fix_unit": fix_unit}


def test_no_item_no_section(tmp_path):
    assert feedback_section(None, state()) is None
    add(tmp_path)
    (tmp_path / "feedback.md").unlink()
    assert feedback_section(FeedbackFile.load(tmp_path), state()) is None


def test_a_draft_a_submitted_and_a_withdrawn_item_read_from_the_file(tmp_path):
    """L4-FBK-011: the file alone says draft, submitted and withdrawn."""
    add(tmp_path, draft=True)
    add(tmp_path, "tests", text="Cover the empty pack.")
    add(tmp_path, "duplication")
    status(tmp_path, "FB-002", FeedbackStatus.SUBMITTED)
    status(tmp_path, "FB-003", FeedbackStatus.WITHDRAWN)
    assert lines_of(tmp_path, state()) == [
        "- FB-001 refactor src/inventory/reorder.py:7-9 \N{EM DASH} draft (not sent)",
        "- FB-002 tests \N{EM DASH} submitted (waiting for the next round)",
        "- FB-003 duplication src/inventory/reorder.py:7-9 \N{EM DASH} withdrawn",
    ]


def test_an_invalid_submitted_item_names_the_problem(tmp_path):
    add(tmp_path, "tests", text="")
    status(tmp_path, "FB-001", FeedbackStatus.SUBMITTED)
    assert lines_of(tmp_path, state()) == ["- FB-001 tests \N{EM DASH} invalid: needs Feedback text"]


def test_SCN_FBK_26_the_note_follows_an_item_through_its_life(tmp_path):
    """SCN-FBK-26: submitted, taken into the fix unit, then addressed in round 3 at a sha."""
    add(tmp_path)
    status(tmp_path, "FB-001", FeedbackStatus.SUBMITTED)
    file = FeedbackFile.load(tmp_path)
    assert file is not None
    sha = content_sha256(file.items[0])
    place = "src/inventory/reorder.py:7-9"
    assert lines_of(tmp_path, state()) == [
        f"- FB-001 refactor {place} \N{EM DASH} submitted (waiting for the next round)"
    ]
    assert lines_of(tmp_path, state(taken(sha=sha, round_=2))) == [
        f"- FB-001 refactor {place} \N{EM DASH} taken into add-reorder-fix-1"
    ]
    addressed = ("feedback.addressed", {"id": "FB-001", "round": 3, "sha": "0123456789abcdef", "evidence": "ok"})
    assert lines_of(tmp_path, state(taken(sha=sha, round_=2), addressed)) == [
        f"- FB-001 refactor {place} \N{EM DASH} addressed in round 3 at 0123456789"
    ]


def test_not_addressed_waiting_and_invalid_come_from_the_fold(tmp_path):
    for _ in range(3):
        add(tmp_path)
    add(tmp_path, places=())  # a refactor without Where
    for n in range(1, 5):
        status(tmp_path, f"FB-00{n}", FeedbackStatus.SUBMITTED)
    file = FeedbackFile.load(tmp_path)
    assert file is not None
    folded = state(
        taken("FB-001", sha=content_sha256(file.items[0])),
        ("feedback.not_addressed", {"id": "FB-001", "round": 2, "evidence": "the helper is still\ninline"}),
        ("feedback.waiting", {"ids": ["FB-002"], "reason": "fix_unit_full"}),
        ("feedback.waiting", {"ids": ["FB-003"], "reason": "follow_up_open"}),
        ("feedback.invalid", {"id": "FB-004", "problem": "refactor needs Where"}),
    )
    place = "src/inventory/reorder.py:7-9"
    d = "\N{EM DASH}"
    assert lines_of(tmp_path, folded) == [
        f"- FB-001 refactor {place} {d} not addressed in round 2: the helper is still inline",
        f"- FB-002 refactor {place} {d} waiting for the next round (fix unit full)",
        f"- FB-003 refactor {place} {d} waiting for the next round (follow-up open)",
        f"- FB-004 refactor {d} invalid: refactor needs Where",
    ]


def test_an_item_changed_after_its_take_is_submitted_again(tmp_path):
    add(tmp_path)
    status(tmp_path, "FB-001", FeedbackStatus.SUBMITTED)
    assert lines_of(tmp_path, state(taken(sha="not-the-current-hash", round_=2))) == [
        "- FB-001 refactor src/inventory/reorder.py:7-9 \N{EM DASH} "
        "submitted (changed after round 2; waiting for the next round)"
    ]


def test_repository_text_is_one_line_without_markup_and_redacted(tmp_path):
    add(tmp_path)
    status(tmp_path, "FB-001", FeedbackStatus.SUBMITTED)
    file = FeedbackFile.load(tmp_path)
    assert file is not None
    folded = state(
        taken(sha=content_sha256(file.items[0])),
        ("feedback.not_addressed", {"id": "FB-001", "round": 1, "evidence": "see [x](http://e) @team `s3cr3t-token`"}),
    )
    section = feedback_section(FeedbackFile.load(tmp_path), folded, redact=lambda t: t.replace("s3cr3t-token", "[R]"))
    assert section is not None
    assert "s3cr3t" not in section and "[x](" not in section and " @team" not in section and "`" not in section


def test_the_hint_is_the_literal_line():
    assert FEEDBACK_HINT == HINT


def test_SCN_FBK_25_an_in_review_note_ends_with_the_hint():
    """SCN-FBK-25: also when nothing else is waiting, the hint closes the note."""
    assert compose_sticky((), "in_review", None) == f"{NOTHING_WAITING}\n\n{HINT}"
    body = compose_sticky(("### Re-verifying after the hand-off\n\nx",), "in_review", "### Your feedback\n\n- FB-001 a")
    assert body == f"### Re-verifying after the hand-off\n\nx\n\n### Your feedback\n\n- FB-001 a\n\n{HINT}"


@pytest.mark.parametrize("phase", ["implementing", "verifying", "awaiting_human", "verified", "fixing", "archived"])
def test_other_phases_have_no_hint(phase):
    assert compose_sticky((), phase, None) == NOTHING_WAITING
    assert HINT not in compose_sticky(("### Waiting",), phase, "### Your feedback\n\n- FB-001 a")


def test_the_feedback_section_without_other_notes_follows_the_nothing_waiting_line():
    body = compose_sticky((), "implementing", "### Your feedback\n\n- FB-001 a")
    assert body == f"{NOTHING_WAITING}\n\n### Your feedback\n\n- FB-001 a"


# --- the note as a unit in review writes it -----------------------------------------------------------------------


def final_note(gitlab) -> str:
    (note,) = gitlab.notes[1]
    return note["body"]


def test_SCN_FBK_25_a_unit_that_just_handed_off_ends_its_note_with_the_hint(
    run_l4, install_hooks, forge_env, use_fake_gitlab
):
    """SCN-FBK-25: the real hand-off; nothing else waits, so the note says so and then how to ask for changes."""
    install_hooks(verify=lambda ctx: Trigger.VERIFY_PASS)
    run = run_l4([red_step(), green_step()])
    assert run.outcome["units"][0]["phase_after"] == "in_review"
    body = final_note(use_fake_gitlab)
    assert body.endswith(f"{NOTHING_WAITING}\n\n{HINT}") and body.count(HINT) == 1
    assert "Your feedback" not in body


def test_an_item_a_person_pushes_shows_in_the_note_when_the_unit_is_handed_off_again(
    run_l4, install_hooks, forge_env, use_fake_gitlab, tdd_repo, raw
):
    """The person adds the item on the unit branch after the hand-off; the next hand-off writes it into the note."""
    install_hooks(verify=lambda ctx: Trigger.VERIFY_PASS)
    assert run_l4([red_step(), green_step()]).code == 0
    clone = tdd_repo.repo.parent / "person"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
    add(clone / UNIT_DIR, "tests", text="Cover the empty basket.")
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", "ask for a test")
    raw(clone, "push", "-q", "origin", BRANCH)
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    assert run_l4([]).code == 0
    body = final_note(use_fake_gitlab)
    assert "### Your feedback\n\n- FB-001 tests \N{EM DASH} submitted (waiting for the next round)\n" in body
    assert body.endswith(HINT)
