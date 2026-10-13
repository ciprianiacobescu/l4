"""The follow-up marker is repo content: a parent that does not validate makes the unit no follow-up (review #4,
L4-FBK-010). Every consumer goes through `parent_folder` / `feedback_home`, so one validation answers all of them."""

import json
from pathlib import Path

import pytest

from l4.specs.followup import (
    MARKER_SCHEMA,
    FollowUpMarker,
    feedback_home,
    follow_up_problem,
    parent_folder,
    read_follow_up_marker,
    write_follow_up_marker,
)


def tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    """`.kiro/specs/{add-x, add-x-followup-1, victim}`"""
    root = tmp_path / ".kiro" / "specs"
    for name in ("add-x", "add-x-followup-1", "victim"):
        (root / name).mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    return root / "add-x", root / "add-x-followup-1", root / "victim"


def marked(unit: Path, parent: str) -> FollowUpMarker:
    marker = FollowUpMarker(parent, (("FB-001", "0" * 64),))
    write_follow_up_marker(unit, marker)
    return marker


def test_a_sound_marker_resolves_to_the_parents_sibling_folder(tmp_path):
    parent, unit, _ = tree(tmp_path)
    marker = marked(unit, "kiro:add-x")
    assert follow_up_problem(unit) is None
    assert parent_folder(unit, marker) == parent
    assert feedback_home(unit) == parent


@pytest.mark.parametrize(
    "bad",
    [
        "kiro:victim",  # another unit's folder: the name does not agree with the folder name
        "kiro:../../elsewhere",
        "kiro:../add-x",
        "kiro:add-x/..",
        "kiro:",
        "kiro:a/b",
        "openspec:add-x",  # another framework than the unit's own
        "add-x",
        "kiro:.hidden",
    ],
)
def test_a_marker_that_does_not_validate_is_no_follow_up(tmp_path, bad):
    """review #4: no path is built from it, nothing is raised, and the unit answers for its own folder."""
    _, unit, _ = tree(tmp_path)
    marker = marked(unit, bad)
    assert follow_up_problem(unit) is not None
    assert parent_folder(unit, marker) is None
    assert feedback_home(unit) == unit


def test_the_folder_name_must_say_it_follows_the_parent(tmp_path):
    root = tmp_path / ".kiro" / "specs"
    (root / "plain").mkdir(parents=True)
    (root / "victim").mkdir()
    marker = marked(root / "plain", "kiro:victim")
    assert parent_folder(root / "plain", marker) is None


def test_an_openspec_follow_up_and_its_archived_parent_validate(tmp_path):
    changes = tmp_path / "openspec" / "changes"
    unit = changes / "add-x-followup-1"
    unit.mkdir(parents=True)
    (changes / "archive" / "2026-05-01-add-x").mkdir(parents=True)
    (changes / "archive" / "2026-05-01-other-add-x").mkdir()
    marker = marked(unit, "openspec:add-x")
    assert parent_folder(unit, marker) == changes / "archive" / "2026-05-01-add-x"
    assert marked(unit, "kiro:add-x") and follow_up_problem(unit) is not None  # a Kiro parent of an OpenSpec unit


def test_a_marker_without_the_schema_or_a_unit_without_one_has_no_problem(tmp_path):
    _, unit, _ = tree(tmp_path)
    assert follow_up_problem(unit) is None
    (unit / ".l4").mkdir()
    (unit / ".l4" / "followup.json").write_text(json.dumps({"schema": MARKER_SCHEMA + "x", "parent": "kiro:victim"}))
    assert read_follow_up_marker(unit) is None and follow_up_problem(unit) is None
