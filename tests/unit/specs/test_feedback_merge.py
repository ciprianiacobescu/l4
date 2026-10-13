"""human-feedback 1.3 (L4-FBK-012): `feedback.md` merged per item id when a base merge conflicts in it. The union of
items; each item's human content from the side that changed it since the merge base, else the unit branch; the
harness's spans (Status `taken`/`addressed`, Outcome, index) from the unit branch."""

from pathlib import Path

import pytest

from l4.redact import Redactor
from l4.specs.base import Framework
from l4.specs.feedback import (
    FEEDBACK_FILENAME,
    FeedbackFile,
    FeedbackKind,
    FeedbackStatus,
    NewFeedback,
    Place,
    append_item,
)
from l4.specs.feedback_merge import merge_feedback
from l4.specs.harness_merge import harness_resolvers
from l4.vcs.merge import Escalate, Sides, merge_base_into
from l4.vcs.trailers import CommitTrailers

R = Redactor({})
UNIT = "openspec/changes/add-reorder"


def build(tmp_path: Path, *texts: str, kind: str = "tests") -> bytes:
    """A file with one submitted item per text, FB-001 first."""
    for text in texts:
        item = NewFeedback(FeedbackKind(kind), text[:30], text, "someone, 2026-10-12T10:00:00Z")
        append_item(tmp_path, "add-reorder", item, redactor=R)
    return (tmp_path / FEEDBACK_FILENAME).read_bytes()


def with_text(data: bytes, old: str, new: str) -> bytes:
    assert old.encode() in data
    return data.replace(old.encode(), new.encode())


def harnessed(data: bytes, fid: str, outcome: str) -> bytes:
    file = FeedbackFile.parse(data).set_status(fid, "taken").set_outcome(fid, outcome, redactor=R)
    return file.data


def parsed(data: bytes) -> FeedbackFile:
    return FeedbackFile.parse(data)


def test_identical_sides_are_ours_byte_for_byte(tmp_path: Path):
    base = build(tmp_path, "one", "two")
    ours = harnessed(base, "FB-001", "taken into fix 1")
    assert merge_feedback(base, ours, base) == ours
    assert merge_feedback(base, ours, ours) == ours
    assert merge_feedback(None, ours, ours) == ours


def test_an_item_only_the_base_has_is_appended_with_its_row(tmp_path: Path):
    base = build(tmp_path, "one")
    theirs = build(tmp_path, "two")
    merged = parsed(merge_feedback(base, base, theirs))
    assert [i.id for i in merged.items] == ["FB-001", "FB-002"]
    assert b"| FB-002 | submitted | tests |  | two |" in merged.data
    assert merged.get("FB-002").text == "two"
    assert parsed(merged.data).refresh_index().data == merged.data  # the index is whole


def test_an_item_only_the_unit_branch_has_is_kept(tmp_path: Path):
    base = build(tmp_path, "one")
    ours = build(tmp_path, "two")
    assert merge_feedback(base, ours, base) == ours


def test_the_side_that_changed_the_human_content_wins_and_the_harness_spans_stay(tmp_path: Path):
    """L4-FBK-012: the person edited FB-001 on the base while the harness took it on the unit branch."""
    base = build(tmp_path, "round up", "other")
    ours = harnessed(base, "FB-001", "taken into add-reorder-fix-1")
    theirs = with_text(base, "round up", "round down  and more")
    merged = parsed(merge_feedback(base, ours, theirs))
    first = merged.get("FB-001")
    assert first.text == "round down  and more"  # the person's edit
    assert first.status is FeedbackStatus.TAKEN and first.outcome == "taken into add-reorder-fix-1"
    assert b"| FB-001 | taken |" in merged.data
    assert merged.get("FB-002").text == "other"


def test_the_unit_branch_wins_when_it_changed_the_item_or_both_did(tmp_path: Path):
    base = build(tmp_path, "round up")
    ours = with_text(base, "round up", "round to even")
    assert merge_feedback(base, ours, with_text(base, "round up", "round down")) == ours
    assert merge_feedback(base, ours, base) == ours


def test_a_human_status_edit_on_the_base_is_taken_over_a_harness_status(tmp_path: Path):
    base = build(tmp_path, "one")
    taken = harnessed(base, "FB-001", "taken")
    withdrawn = with_text(base, "- **Status:** submitted", "- **Status:** withdrawn")
    merged = parsed(merge_feedback(base, taken, withdrawn))
    assert merged.get("FB-001").status is FeedbackStatus.WITHDRAWN
    assert merged.get("FB-001").outcome == "taken"  # the Outcome is the harness's
    assert b"| FB-001 | withdrawn |" in merged.data
    # a draft on the unit branch that the person submitted on the base
    draft = with_text(base, "- **Status:** submitted", "- **Status:** draft")
    assert parsed(merge_feedback(draft, draft, base)).get("FB-001").status is FeedbackStatus.SUBMITTED


def test_a_status_the_person_did_not_change_keeps_the_harness_value(tmp_path: Path):
    base = build(tmp_path, "one")
    ours = parsed(harnessed(base, "FB-001", "taken")).set_status("FB-001", "addressed").data
    assert merge_feedback(base, ours, base) == ours


def test_the_outcome_is_added_when_the_base_side_lost_the_block(tmp_path: Path):
    base = build(tmp_path, "one")
    ours = harnessed(base, "FB-001", "taken into fix 1")
    theirs = with_text(base, "one\n", "one, changed\n").replace(b"### Outcome\n<!-- written by the harness -->\n", b"")
    merged = parsed(merge_feedback(base, ours, theirs))
    assert merged.get("FB-001").text == "one, changed" and merged.get("FB-001").outcome == "taken into fix 1"


def test_a_file_that_is_new_on_both_sides(tmp_path: Path):
    mine, other = tmp_path / "a", tmp_path / "b"
    mine.mkdir()
    other.mkdir()
    ours, theirs = build(mine, "one"), build(other, "one", "two")
    merged = parsed(merge_feedback(None, ours, theirs))
    assert [i.id for i in merged.items] == ["FB-001", "FB-002"] and merged.get("FB-001").text == "one"


def test_the_same_id_for_different_items_stays_a_conflict(tmp_path: Path):
    mine, other = tmp_path / "a", tmp_path / "b"
    mine.mkdir()
    other.mkdir()
    ours, theirs = build(mine, "one"), build(other, "something else")
    with pytest.raises(Escalate, match="FB-001"):
        merge_feedback(None, ours, theirs)


def test_the_base_resolver_is_registered_for_the_unit_and_its_fix_units():
    table = harness_resolvers(UNIT, Framework.OPENSPEC)
    paths = (f"{UNIT}/feedback.md", f"{UNIT}-fix-2/feedback.md", f"{UNIT}/proposal.md", "feedback.md")
    matching = {path for path in paths if any(matches(path) for matches, _ in table)}
    assert matching == {f"{UNIT}/feedback.md", f"{UNIT}-fix-2/feedback.md"}


def test_the_resolver_table_merges_the_file(tmp_path: Path):
    base = build(tmp_path, "round up")
    ours = harnessed(base, "FB-001", "taken")
    theirs = with_text(base, "round up", "round down")
    path = f"{UNIT}/feedback.md"
    resolve = next(fn for matches, fn in harness_resolvers(UNIT, Framework.OPENSPEC) if matches(path))
    merged = parsed(resolve(Sides(path, base, ours, theirs, 2000, 1000)))
    assert (merged.get("FB-001").text, merged.get("FB-001").status) == ("round down", FeedbackStatus.TAKEN)


def test_places_and_kinds_are_human_content(tmp_path: Path):
    item = NewFeedback(FeedbackKind.REFACTOR, "t", "x", "b, 2026-10-12T10:00:00Z", places=(Place("a.py", 1, 2),))
    append_item(tmp_path, "u", item, redactor=R)
    base = (tmp_path / FEEDBACK_FILENAME).read_bytes()
    theirs = with_text(base, "`a.py:1-2`", "`b.py:5`")
    merged = parsed(merge_feedback(base, harnessed(base, "FB-001", "t"), theirs))
    assert merged.get("FB-001").places == (Place("b.py", 5, 5),)
    assert merged.get("FB-001").status is FeedbackStatus.TAKEN


def test_a_git_base_merge_settles_the_file(make_repo, raw, git_for, tmp_path: Path):
    """The whole path: both sides edit feedback.md, git conflicts, the table settles it, the merge commits."""
    repo = make_repo(remote=True)
    path = repo / UNIT / "feedback.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(base := build(tmp_path, "round up", "other"))
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "feedback")
    raw(repo, "checkout", "-q", "-b", "l4/x")
    path.write_bytes(harnessed(base, "FB-001", "taken into fix 1"))
    raw(repo, "commit", "-q", "-am", "harness takes FB-001")
    raw(repo, "checkout", "-q", "main")
    path.write_bytes(with_text(base, "round up", "round down"))
    raw(repo, "commit", "-q", "-am", "person edits FB-001")
    main_sha = raw(repo, "rev-parse", "HEAD").strip()
    raw(repo, "checkout", "-q", "l4/x")
    trailers = CommitTrailers(unit="openspec:x", run_id="r-1", iteration=2, phase="verifying")
    result = merge_base_into(
        git_for(repo), main_sha, message="chore(x): merge main into the unit branch [skip ci]", trailers=trailers,
        resolvers=harness_resolvers(UNIT, Framework.OPENSPEC),
    )  # fmt: skip
    assert result.kind == "merged" and result.resolved == (f"{UNIT}/feedback.md",) and result.files == ()
    merged = parsed(path.read_bytes())
    assert merged.get("FB-001").text == "round down" and merged.get("FB-001").status is FeedbackStatus.TAKEN
    assert merged.get("FB-001").outcome == "taken into fix 1"


def _follow_up_repo(make_repo, raw, tmp_path: Path):
    """review #3: the follow-up's branch edits the PARENT's feedback.md; a person adds FB-002 on base."""
    from l4.specs.followup import FollowUpMarker, write_follow_up_marker

    repo = make_repo(remote=True)
    parent = repo / ".kiro/specs/add-x"
    parent.mkdir(parents=True)
    base = build(tmp_path, "round up")
    (parent / "feedback.md").write_bytes(base)
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "feedback")
    raw(repo, "checkout", "-q", "-b", "l4/kiro/add-x-followup-1")
    unit = repo / ".kiro/specs/add-x-followup-1"
    unit.mkdir()
    write_follow_up_marker(unit, FollowUpMarker("kiro:add-x", (("FB-001", "0" * 64),)))
    (parent / "feedback.md").write_bytes(harnessed(base, "FB-001", "Taken into add-x-followup-1"))
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "follow-up takes FB-001")
    raw(repo, "checkout", "-q", "main")
    (parent / "feedback.md").write_bytes(_two(base, tmp_path))
    raw(repo, "commit", "-q", "-am", "person adds FB-002 on base")
    return repo, parent, raw(repo, "rev-parse", "HEAD").strip()


def _two(base: bytes, tmp_path: Path) -> bytes:
    other = tmp_path / "two"
    other.mkdir()
    (other / "feedback.md").write_bytes(base)
    item = NewFeedback(FeedbackKind.TESTS, "More tests", "Add a test.", "me, 2026-10-12T10:00:00Z")
    append_item(other, "add-x", item, redactor=R)
    return (other / "feedback.md").read_bytes()


def test_a_follow_up_base_merge_settles_the_parents_feedback_file(make_repo, raw, git_for, tmp_path: Path):
    """review #3 (L4-FBK-010): without the resolver the merge stops at BaseMergeConflict on every run."""
    from l4.specs.harness_merge import follow_up_feedback_rel

    repo, parent, main_sha = _follow_up_repo(make_repo, raw, tmp_path)
    raw(repo, "checkout", "-q", "l4/kiro/add-x-followup-1")
    unit = repo / ".kiro/specs/add-x-followup-1"
    rel = follow_up_feedback_rel(unit, repo)
    assert rel == ".kiro/specs/add-x/feedback.md"
    trailers = CommitTrailers(unit="kiro:add-x-followup-1", run_id="r-1", iteration=2, phase="verifying")
    result = merge_base_into(
        git_for(repo), main_sha, message="chore: merge main into the unit branch [skip ci]", trailers=trailers,
        resolvers=harness_resolvers(".kiro/specs/add-x-followup-1", Framework.KIRO, follow_up_feedback=rel),
    )  # fmt: skip
    assert result.kind == "merged" and result.resolved == (rel,) and result.files == ()
    merged = parsed((parent / "feedback.md").read_bytes())
    assert merged.get("FB-002").text == "Add a test."
    assert merged.get("FB-001").status is FeedbackStatus.TAKEN
    assert merged.get("FB-001").outcome == "Taken into add-x-followup-1"


def test_only_a_follow_up_gets_the_parents_file_and_only_that_file(make_repo, raw, tmp_path: Path):
    from l4.specs.harness_merge import follow_up_feedback_rel

    repo = make_repo(remote=True)
    plain = repo / ".kiro/specs/add-x"
    plain.mkdir(parents=True)
    assert follow_up_feedback_rel(plain, repo) is None
    paths = [m for m, _ in harness_resolvers(".kiro/specs/add-x-followup-1", Framework.KIRO)]
    assert not any(m(".kiro/specs/add-x/feedback.md") for m in paths)
    own = harness_resolvers(
        ".kiro/specs/add-x-followup-1", Framework.KIRO, follow_up_feedback=".kiro/specs/add-x/feedback.md"
    )
    assert any(m(".kiro/specs/add-x/feedback.md") for m, _ in own)
    assert not any(m(".kiro/specs/add-x/tasks.md") for m, _ in own)
    assert not any(m(".kiro/specs/other/feedback.md") for m, _ in own)

# --- review #6: duplicate ids never make the merge raise -----------------------------------------------------------


def duplicated(data: bytes) -> bytes:
    return data + b"\n---\n\n" + data[data.index(b"## FB-001") :].replace(b"round up", b"round copy")


@pytest.mark.parametrize("where", ["ours", "theirs", "both"])
def test_duplicate_ids_never_raise_anything_but_escalate(tmp_path: Path, where: str):
    base = build(tmp_path, "round up", "other")
    ours, theirs = base.replace(b"round up", b"round down"), base.replace(b"other", b"another")
    if where in ("ours", "both"):
        ours = duplicated(ours)
    if where in ("theirs", "both"):
        theirs = duplicated(theirs)
    try:
        merged = merge_feedback(base, ours, theirs)
    except Escalate:
        return
    FeedbackFile.parse(merged)

