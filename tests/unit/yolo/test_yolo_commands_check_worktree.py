# ruff: noqa: F811
"""`l4 yolo check --worktree` (L4-MCP-003, SCN-MCP-05): admit the plan file and the unit folders of the working tree,
before they are pushed; read only, no judge."""

import json

from .yolo_cmd_world import A, B, plan_doc, world  # noqa: F401


def write_plan(world, doc, plan_id="p1") -> None:
    path = world.app.repo / ".l4" / "plans" / f"{plan_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_an_unpushed_plan_is_admitted_from_the_working_tree(world, capsys):  # SCN-MCP-05
    world.pull()
    write_plan(world, plan_doc())
    assert world.l4("check", "p1", "--worktree") == 0
    out = capsys.readouterr().out
    assert "p1: admitted" in out and f"order: {A}, {B}" in out
    assert world.store().read().head is None  # nothing recorded


def test_without_worktree_the_same_plan_is_not_on_origin(world, capsys):
    world.pull()
    write_plan(world, plan_doc())
    assert world.l4("check", "p1") == 2
    assert "no plan file .l4/plans/p1.json on origin/main" in capsys.readouterr().err


def test_a_missing_file_in_the_working_tree_is_a_usage_error(world, capsys):
    assert world.l4("check", "p1", "--worktree") == 2
    assert "no plan file .l4/plans/p1.json in the working tree" in capsys.readouterr().err


def test_findings_of_the_working_tree_plan_are_printed(world, capsys):
    world.pull()
    write_plan(world, plan_doc({A: [], "openspec:nope": [A]}))
    assert world.l4("check", "p1", "--worktree") == 2
    out = capsys.readouterr().out
    assert "not admitted" in out and "unknown_unit: unit openspec:nope" in out


def test_an_invalid_working_tree_plan_is_refused(world, capsys):
    world.pull()
    write_plan(world, plan_doc(parallel=3))
    assert world.l4("check", "p1", "--worktree") == 2
    assert "unknown field parallel" in capsys.readouterr().out


def test_a_unit_folder_only_in_the_working_tree_counts(world, capsys):
    world.pull()
    folder = world.app.repo / "openspec" / "changes" / "add-local"
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text("## 1. L\n\n- [ ] 1.1 Add `local()`\n", encoding="utf-8")
    (folder / "proposal.md").write_text("# L\n", encoding="utf-8")
    write_plan(world, plan_doc({"openspec:add-local": []}))
    code = world.l4("check", "p1", "--worktree")
    out = capsys.readouterr().out
    assert code == 0, out
    assert "order: openspec:add-local" in out
