"""Digest rules after the review (R3, R4; review #3, #4, #15, #17): the providers' task markers, a missing revision
that raises, the unit branch when it exists, and exclusions at any depth."""

import re

import pytest

from l4.specs import tasks_merge
from l4.vcs.names import unit_branch
from l4.yolo.digest import RevisionMissing, current_unit_digest, unit_digest

from .yolo_review_world import World, make_cfg

FOLDER = "openspec/changes/a"
UNIT = "openspec:a"

TICKS = [
    ("star bullet", "* [ ] 1. Task\n", "* [x] 1. Task\n"),
    ("plus bullet", "+ [ ] 1. Task\n", "+ [x] 1. Task\n"),
    ("numbered", "1. [ ] 1.1 Task\n", "1. [x] 1.1 Task\n"),
    ("numbered paren", "1) [ ] 1.1 Task\n", "1) [X] 1.1 Task\n"),
    ("no space", "-[ ] 1.1 Task\n", "-[x] 1.1 Task\n"),
    ("bom", "﻿- [ ] 1.1 Task\n", "﻿- [x] 1.1 Task\n"),
    ("nbsp indent", " - [ ] 1.1 Task\n", " - [x] 1.1 Task\n"),
    ("kiro started", "* [ ] 1. Task\n", "* [-] 1. Task\n"),
    ("kiro queued", "- [ ] 1. Task\n", "- [~] 1. Task\n"),
    ("nested", "- [ ] 1. T\n  - [ ] 1.1 U\n", "- [x] 1. T\n  - [x] 1.1 U\n"),
]


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


@pytest.mark.parametrize(("name", "before", "after"), TICKS, ids=[t[0] for t in TICKS])
def test_a_tick_of_any_task_form_the_harness_accepts_is_not_a_change(world, name, before, after):
    first = world.commit({f"{FOLDER}/tasks.md": before, f"{FOLDER}/proposal.md": "p\n"})
    second = world.commit({f"{FOLDER}/tasks.md": after})
    assert unit_digest(world.git, first, FOLDER) == unit_digest(world.git, second, FOLDER)


def test_a_change_to_the_task_text_still_changes_the_digest(world):
    first = world.commit({f"{FOLDER}/tasks.md": "* [ ] 1. Task\n"})
    second = world.commit({f"{FOLDER}/tasks.md": "* [x] 1. Another task\n"})
    assert unit_digest(world.git, first, FOLDER) != unit_digest(world.git, second, FOLDER)


def test_a_checkbox_in_another_file_is_content(world):
    first = world.commit({f"{FOLDER}/design.md": "- [ ] open\n"})
    second = world.commit({f"{FOLDER}/design.md": "- [x] open\n"})
    assert unit_digest(world.git, first, FOLDER) != unit_digest(world.git, second, FOLDER)


@pytest.mark.parametrize("line", [t[1] for t in TICKS] + [t[2] for t in TICKS])
def test_the_normalised_forms_are_the_ones_tasks_merge_reads(line):
    """The digest and the harness's own tick writer agree on what a marker is (`tasks_merge` Kiro and OpenSpec)."""
    raw = line.encode()
    assert tasks_merge._KIRO.match(raw) or tasks_merge._OPENSPEC.match(raw)
    from l4.yolo.digest import _normalise

    assert re.search(rb"\[[ xX~-]\]", _normalise("tasks.md", raw)).group(0) == b"[ ]"


def test_a_missing_revision_raises_never_the_empty_set_digest(world):
    world.commit({f"{FOLDER}/proposal.md": "p\n"})
    for rev in ("refs/remotes/origin/l4/openspec/a", "0123456789abcdef0123456789abcdef01234567"):
        with pytest.raises(RevisionMissing, match="does not exist"):
            unit_digest(world.git, rev, FOLDER)


def test_a_folder_that_is_not_in_an_existing_revision_is_still_the_empty_set(world):
    rev = world.commit({"other/x.md": "x\n"})
    assert unit_digest(world.git, rev, FOLDER) == unit_digest(world.git, rev, "also/not/there")


def test_the_current_digest_is_taken_on_the_unit_branch_when_it_exists(world):
    cfg = make_cfg()
    base = world.commit({f"{FOLDER}/proposal.md": "target version\n"})
    assert current_unit_digest(world.git, cfg, UNIT, FOLDER, base) == unit_digest(world.git, base, FOLDER)
    branch = world.commit({f"{FOLDER}/proposal.md": "branch version\n"})
    world.git.run("update-ref", f"refs/remotes/origin/{unit_branch(UNIT, cfg.forge.branch_prefix)}", branch)
    assert current_unit_digest(world.git, cfg, UNIT, FOLDER, base) == unit_digest(world.git, branch, FOLDER)
    assert unit_digest(world.git, branch, FOLDER) != unit_digest(world.git, base, FOLDER)


def test_the_current_digest_of_a_missing_target_raises(world):
    world.commit({f"{FOLDER}/proposal.md": "p\n"})
    with pytest.raises(RevisionMissing):
        current_unit_digest(world.git, make_cfg(), UNIT, FOLDER, "refs/remotes/origin/nope")


def test_exclusions_apply_at_any_depth(world):
    first = world.commit({f"{FOLDER}/proposal.md": "p\n"})
    second = world.commit(
        {
            f"{FOLDER}/specs/x/verification.md": "report\n",
            f"{FOLDER}/specs/x/questions.md": "q\n",
            f"{FOLDER}/deep/er/feedback.md": "f\n",
            f"{FOLDER}/specs/.l4/ledger.jsonl": "{}\n",
        }
    )
    assert unit_digest(world.git, first, FOLDER) == unit_digest(world.git, second, FOLDER)
