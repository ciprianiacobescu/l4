"""What the implementer's prompt carries of a unit (kiro-prompt-context): the sources read as they are, the task's
whole block, the criteria text, the budget filled in priority order, and every cut named."""

import os

from l4.implementer.prompt import collect_sources
from l4.implementer.unit_context import MAX_SOURCE_BYTES, read_sources, task_block
from l4.specs.base import Framework
from l4.specs.kiro import parse_kiro_tasks
from l4.specs.openspec import parse_openspec_tasks

from .._kiro_probe import UNIT_REL, probe_tree

# -- the readers (tasks 1.1) -------------------------------------------------------------------------------------


def test_the_task_block_of_the_probe_leaf_holds_the_checkbox_the_detail_bullets_and_the_requirements_line(tmp_path):
    """SCN-IMP-282, reader part."""
    data = (probe_tree(tmp_path) / UNIT_REL / "tasks.md").read_bytes()
    tasks = parse_kiro_tasks(data)
    block = task_block(data, tasks[0], tasks, Framework.KIRO)
    expected = [
        "- [ ] 1. Implement the tip function",
        "  - TASK-DETAIL-MARKER: reject a percent above 100 with ValueError as well",
        "  - Use Decimal throughout",
        "  - _Requirements: 1.1, 1.2_",
    ]
    positions = [block.index(line) for line in expected]
    assert positions == sorted(positions)
    assert block.endswith("\n".join(expected) + "\n")


def test_the_task_block_of_a_nested_kiro_leaf_starts_with_its_parent_task_line():
    data = b"# Plan\n\n- [ ] 1. Parent\n  - [ ] 1.1 Leaf\n    - detail\n    - _Requirements: 1.1_\n- [ ] 2. Other\n"
    tasks = parse_kiro_tasks(data)
    leaf = next(t for t in tasks if t.key == "1.1")
    assert task_block(data, leaf, tasks, Framework.KIRO) == (
        "# Plan\n- [ ] 1. Parent\n  - [ ] 1.1 Leaf\n    - detail\n    - _Requirements: 1.1_\n"
    )


def test_the_task_block_of_an_openspec_task_has_its_group_heading_and_no_parents():
    data = b"## 1. Group\n\n- [ ] 1.1 First\n  more words\n- [ ] 1.2 Second\n"
    tasks = parse_openspec_tasks(data)
    assert task_block(data, tasks[1], tasks, Framework.OPENSPEC) == "## 1. Group\n- [ ] 1.2 Second\n"
    assert task_block(data, tasks[0], tasks, Framework.OPENSPEC) == "## 1. Group\n- [ ] 1.1 First\n  more words\n"


def test_a_source_over_the_limit_is_read_up_to_it_and_a_link_or_a_fifo_is_named(tmp_path):
    """SCN-IMP-286, reader part."""
    unit = tmp_path / ".kiro" / "specs" / "big"
    unit.mkdir(parents=True)
    (unit / "design.md").write_bytes(b"line of the design\n" * 15_789 + b"x" * 9)
    assert (unit / "design.md").stat().st_size == 300_000
    (tmp_path / "elsewhere.md").write_text("# elsewhere\n")
    (unit / "requirements.md").symlink_to(tmp_path / "elsewhere.md")
    os.mkfifo(unit / "bugfix.md")
    (unit / "proposal.md").write_text("# Proposal\nwhole\n")
    found = {s.name: s for s in read_sources(unit, tmp_path)}
    design = found["design.md"]
    assert (design.reason, design.total_bytes, design.path) == ("oversize", 300_000, ".kiro/specs/big/design.md")
    assert len(design.text.encode()) == MAX_SOURCE_BYTES == 262_144
    assert (found["requirements.md"].reason, found["requirements.md"].text) == ("symlink", "")
    assert (found["bugfix.md"].reason, found["bugfix.md"].text) == ("not_regular", "")
    assert (found["proposal.md"].reason, found["proposal.md"].text) == ("", "# Proposal\nwhole\n")
    assert [s.name for s in read_sources(unit, tmp_path)] == [
        "proposal.md",
        "design.md",
        "requirements.md",
        "bugfix.md",
    ]
    assert [name for name, _ in collect_sources(unit)] == ["proposal.md"]  # the clarifier and the audit writer


def test_the_spec_deltas_are_read_in_name_order_and_a_linked_specs_directory_is_named(tmp_path):
    unit = tmp_path / "openspec" / "changes" / "add-x"
    for capability in ("zeta", "alpha"):
        (unit / "specs" / capability).mkdir(parents=True)
        (unit / "specs" / capability / "spec.md").write_text(f"## ADDED Requirements\n{capability}\n")
    assert [s.name for s in read_sources(unit, tmp_path)] == ["specs/alpha/spec.md", "specs/zeta/spec.md"]
    moved = tmp_path / "moved"
    unit.joinpath("specs").rename(moved)
    unit.joinpath("specs").symlink_to(moved)
    (only,) = read_sources(unit, tmp_path)
    assert (only.name, only.reason, only.text) == ("specs", "symlink", "")
