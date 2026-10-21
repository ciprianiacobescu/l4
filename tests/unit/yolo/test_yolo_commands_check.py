# ruff: noqa: F811
"""`l4 yolo check` (L4-YOLO-001, L4-YOLO-002; SCN-YOLO-01, -02, -04, -05): admit at the target head, print the findings
and the order, exit 0 or 2, write nothing."""

import json

from .yolo_cmd_world import A, B, plan_doc, world  # noqa: F401


def test_an_unknown_field_refuses_the_plan_and_records_nothing(world, capsys):
    """SCN-YOLO-01."""
    world.push_plan(plan_doc(parallel=3))
    assert world.l4("check", "p1") == 2
    assert "p1: unknown field parallel" in capsys.readouterr().out
    assert world.store().read().head is None


def test_external_dependencies_are_refused(world, capsys):
    """SCN-YOLO-02."""
    world.push_plan(plan_doc(external_dependencies=[{"repo": "x"}]))
    assert world.l4("check", "p1") == 2
    assert "external dependencies are not supported in this version" in capsys.readouterr().out


def test_a_valid_plan_prints_its_order_even_when_the_checkout_is_behind_the_target(world, capsys):
    """SCN-YOLO-04. The clone has not pulled the plan: the units are read from a temporary worktree of origin/main."""
    world.push_plan()
    assert world.l4("check", "p1") == 0
    out = capsys.readouterr().out
    assert "p1: admitted" in out and f"order: {A}, {B}" in out
    assert world.store().read().head is None
    listed = world.clone.run("worktree", "list").stdout.strip().splitlines()
    assert len(listed) == 1  # the temporary worktree is gone


def test_the_checkout_at_the_target_head_is_read_in_place(world, capsys):
    world.push_plan()
    world.pull()
    assert world.l4("check", "p1") == 0
    assert f"order: {A}, {B}" in capsys.readouterr().out
    assert len(world.clone.run("worktree", "list").stdout.strip().splitlines()) == 1


def test_a_plan_for_another_branch_is_a_finding(world, capsys):
    """SCN-YOLO-05: the base branch here is main."""
    world.push_plan(plan_doc(target="release"))
    assert world.l4("check", "p1") == 2
    assert "target_mismatch: the plan targets release, the base branch is main" in capsys.readouterr().out


def test_findings_are_printed_with_their_code_and_subject(world, capsys):
    world.push_plan(plan_doc({A: [], "openspec:nope": [A]}))
    assert world.l4("check", "p1") == 2
    out = capsys.readouterr().out
    assert "not admitted" in out and "unknown_unit: unit openspec:nope" in out


def test_a_cycle_is_named(world, capsys):
    world.push_plan(plan_doc({A: [B], B: [A]}))
    assert world.l4("check", "p1") == 2
    assert "cycle: dependency cycle:" in capsys.readouterr().out


def test_a_missing_plan_file_is_a_usage_error(world, capsys):
    assert world.l4("check", "p1") == 2
    assert "no plan file .l4/plans/p1.json on origin/main" in capsys.readouterr().err


def test_a_bad_plan_id_is_refused(world, capsys):
    assert world.l4("check", "P_1") == 2
    assert "not a plan id" in capsys.readouterr().err


def test_a_merge_auto_plan_needs_the_merge_policy(world, capsys):
    world.push_plan(plan_doc(merge="auto"))
    assert world.l4("check", "p1") == 2
    assert "merge_policy: merge: auto needs forge.merge_policy: auto" in capsys.readouterr().out


def test_status_json_is_valid_for_a_plan_that_is_only_a_file(world, capsys):
    world.push_plan()
    assert world.l4("status", "p1", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["plans"][0]["plan_id"] == "p1" and data["plans"][0]["status"] == "new"


# --- review budgets (L4-ADO-010; SCN-ADO-32) -----------------------------------------------------------------


def big_tasks(chars: int) -> str:
    head = "## 1. A\n\n- [ ] 1.1 Add the greeting\n\n"
    return head + ("background that does not belong in a unit folder\n" * (chars // 48 + 1))[: chars - len(head)]


def test_a_dependency_over_its_budget_is_printed_and_the_exit_stays_0(world, capsys):
    """SCN-ADO-32: B depends on A, whose tasks.md is read last and cut."""
    world.push({"openspec/changes/add-greeting/tasks.md": big_tasks(27_148)}, "a big tasks.md")
    world.push_plan()
    assert world.l4("check", "p1") == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].startswith("p1: admitted") and lines[1].startswith("order:")
    (line,) = [x for x in lines if x.startswith("warning: material_over_budget")]
    assert line.startswith(f"warning: material_over_budget: {A}: openspec/changes/add-greeting/tasks.md: ")
    assert line.endswith(f" characters cut (as a dependency of {B})")
    assert world.store().read().head is None


def test_a_planned_unit_over_its_folder_budget_is_printed_without_the_warning_prefix(world, capsys):
    world.push({"openspec/changes/add-b/design.md": "x" * 26_000}, "a big design.md")
    world.push_plan()
    assert world.l4("check", "p1") == 0
    out = capsys.readouterr().out
    assert f"material_over_budget: {B}: openspec/changes/add-b/design.md: 6000 characters cut" in out
    assert "warning: material_over_budget: " + B not in out


def test_a_plan_within_its_budgets_prints_no_budget_line(world, capsys):
    world.push_plan()
    assert world.l4("check", "p1") == 0
    assert "material_over_budget" not in capsys.readouterr().out
