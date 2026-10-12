"""human-feedback 2.7 (L4-FBK-011; D12): `l4 status` shows the feedback items per state for a unit that has some."""

import json
from pathlib import Path

from l4.redact import Redactor
from l4.specs.feedback import FeedbackKind, NewFeedback, Place, append_item

from .test_status_branch import IMPLEMENTING, run_cli, snapshot

UNIT = "openspec/changes/add-x"
BY = "CiprianSpot, 2026-10-12T15:04:00Z"


def two_items(repo: Path) -> None:
    for text, draft in (("Move the rounding into a helper.", False), ("Cover the empty pack.", True)):
        new = NewFeedback(FeedbackKind.REFACTOR, "A title", text, BY, places=(Place("src/a.py", 3, 4),), draft=draft)
        append_item(repo / UNIT, "add-x", new, redactor=Redactor({}))


def test_a_unit_without_items_shows_nothing_of_it(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    _, out, _ = run_cli(unit_repo, capsys, "status", "--json")
    assert "feedback_counts" not in json.loads(out)["units"][0]
    _, out, _ = run_cli(unit_repo, capsys, "status")
    assert "FEEDBACK" not in out


def test_json_carries_the_counts_for_a_unit_with_items(unit_repo, trailers, capsys):
    def work(repo: Path) -> None:
        unit_repo.write_ledger(repo, *IMPLEMENTING)
        two_items(repo)

    unit_repo.push_unit_branch(work, trailers)
    code, out, _ = run_cli(unit_repo, capsys, "status", "--json")
    assert code == 0
    assert json.loads(out)["units"][0]["feedback_counts"] == {"draft": 1, "submitted": 1}


def test_the_table_has_a_feedback_column_when_a_unit_has_items(unit_repo, trailers, capsys):
    def work(repo: Path) -> None:
        unit_repo.write_ledger(repo, *IMPLEMENTING)
        two_items(repo)

    unit_repo.push_unit_branch(work, trailers)
    _, out, _ = run_cli(unit_repo, capsys, "status")
    header, row = out.splitlines()[:2]
    assert "FEEDBACK" in header and "draft 1, submitted 1" in row


def test_a_worktree_unit_reads_the_file_from_disk(unit_repo):
    two_items(unit_repo.repo)
    snap = snapshot(unit_repo)
    assert snap.source == "worktree" and snap.feedback is not None and len(snap.feedback.items) == 2
