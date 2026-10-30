# ruff: noqa: F811
"""`l4 yolo check PLAN --worktree` (L4-YOLO-034; SCN-YOLO-86 to -89): the admission of `l4 yolo check` on the plan files
and the units of the working tree, plus the coverage checks across all plan files; and the package's coverage rules
against `scripts/validate_plan.py` on the same trees."""

import json
import subprocess
import sys

import pytest
import yaml

from l4.config.schema import L4Config
from l4.specs.detect import collect_units
from l4.specs.providers import providers_for
from l4.yolo.coverage import coverage_findings
from l4.yolo.plans import plan_files

from .test_yolo_validate_plan import SCRIPT, change, config, plan, put, spec, touch, units
from .yolo_cmd_world import SPEC_B, A, B, plan_doc, world  # noqa: F401

C, D = "openspec:add-c", "openspec:add-d"


def new_change(world, name: str) -> None:
    """A change in the clone's working tree only (a new capability needs a Purpose at intake)."""
    for rel, text in {
        "proposal.md": f"# {name}\n",
        "tasks.md": "## 1. T\n\n- [ ] 1.1 Do it\n",
        f"specs/{name}/spec.md": SPEC_B,
    }.items():
        touch(world.app.repo, f"openspec/changes/{name}/{rel}", text)


def local_plan(world, doc, plan_id="p1") -> None:
    touch(world.app.repo, f".l4/plans/{plan_id}.json", json.dumps(doc, indent=2))


MIGRATION = "app/migrations/0001_initial.py"


def forbidden_change(world, name: str, task: str, *, extra: dict[str, str] | None = None) -> None:
    """A change in the clone's working tree whose first task is `task` (a capability new to `openspec/specs` needs a
    Purpose at intake)."""
    files = {
        "proposal.md": f"# {name}\n",
        "tasks.md": f"## 1. T\n\n- [ ] 1.2 {task}\n",
        f"specs/{name}/spec.md": SPEC_B,
    }
    for rel, text in files.items():
        touch(world.app.repo, f"openspec/changes/{name}/{rel}", text)
    for rel, text in (extra or {}).items():
        touch(world.app.repo, rel, text)


def set_forbidden(world, globs) -> None:
    path = world.app.config_path
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["odd"] = {"forbidden_paths": list(globs)}
    path.write_text(yaml.safe_dump(config), encoding="utf-8")


def remote_state(world) -> str:
    return world.remote.run("for-each-ref").stdout + world.remote.run("rev-parse", "main").stdout


def local_state(world) -> str:
    return world.clone.run("rev-parse", "HEAD").stdout + world.clone.run("diff", "--cached").stdout


def test_scn_yolo_86_a_plan_on_a_feature_branch_is_checked_before_the_push(world, capsys):
    world.pull()
    new_change(world, "add-c")
    local_plan(world, plan_doc({A: [], B: [A], C: [B]}))
    before = (remote_state(world), local_state(world))
    assert world.l4("check", "p1", "--worktree") == 0
    out = capsys.readouterr().out
    assert "p1: admitted (working tree)" in out and f"order: {A}, {B}, {C}" in out
    assert (remote_state(world), local_state(world)) == before  # nothing pushed, committed or staged
    assert world.store().read().head is None
    assert len(world.clone.run("worktree", "list").stdout.strip().splitlines()) == 1


def test_scn_yolo_87_a_spec_no_plan_lists_is_uncovered(world, capsys):
    world.pull()
    new_change(world, "add-c")
    new_change(world, "add-d")
    local_plan(world, plan_doc({A: [], B: [A], C: [B]}))
    assert world.l4("check", "p1", "--worktree") == 2
    out = capsys.readouterr().out
    assert f"uncovered: {D}" in out and "admitted" not in out.replace("not admitted", "")
    # the standalone validator says the same about the same tree
    done = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--repo", str(world.app.repo)], capture_output=True, text=True
    )
    assert f"error: uncovered: {D}" in done.stdout.splitlines()[0]


def test_an_excluded_spec_is_covered(world, capsys):
    world.pull()
    new_change(world, "add-d")
    local_plan(world, plan_doc(exclude=[{"id": D, "reason": "held"}]))
    assert world.l4("check", "p1", "--worktree") == 0
    assert "uncovered" not in capsys.readouterr().out


def test_a_unit_two_plan_files_list_is_covered_twice(world, capsys):
    world.pull()
    local_plan(world, plan_doc())
    local_plan(world, plan_doc({A: []}, plan_id="p2"), "p2")
    assert world.l4("check", "p1", "--worktree") == 2
    assert f"covered_twice: {A} (listed in plans p1, p2)" in capsys.readouterr().out


def test_scn_yolo_88_a_cycle_and_an_unknown_unit_are_refused_before_the_push(world, capsys):
    world.pull()
    local_plan(world, plan_doc({A: [B], B: [A], "openspec:nope": []}))
    before = (remote_state(world), local_state(world))
    assert world.l4("check", "p1", "--worktree") == 2
    out = capsys.readouterr().out
    assert "cycle" in out and "unknown_unit: unit openspec:nope" in out
    assert (remote_state(world), local_state(world)) == before


def test_a_plan_file_not_in_the_working_tree_is_refused_naming_the_path(world, capsys):
    world.push_plan()  # on origin, but this clone has not pulled it
    assert world.l4("check", "p1", "--worktree") == 2
    err = capsys.readouterr().err
    assert ".l4/plans/p1.json" in err and "working tree" in err


def test_an_invalid_plan_file_prints_its_errors(world, capsys):
    world.pull()
    local_plan(world, plan_doc(parallel=3))
    assert world.l4("check", "p1", "--worktree") == 2
    assert "p1: unknown field parallel" in capsys.readouterr().out


def test_check_without_the_flag_still_reads_the_target(world, capsys):
    world.pull()
    local_plan(world, plan_doc())
    assert world.l4("check", "p1") == 2  # not pushed: the target has no p1
    assert ".l4/plans/p1.json on origin/main" in capsys.readouterr().err


def test_the_worktree_review_points_at_the_worktree_check(world, capsys):
    world.pull()
    local_plan(world, plan_doc({A: [B], B: [A]}))
    assert world.l4("review", "p1", "--worktree") == 2
    assert "l4 yolo check p1 --worktree" in capsys.readouterr().out


# --- the package's coverage rules equal scripts/validate_plan.py -----------------------------------------------------


def script_findings(repo) -> list[str]:
    done = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--repo", str(repo)], capture_output=True, text=True, timeout=60
    )
    return [
        line.removeprefix("error: ")
        for line in done.stdout.splitlines()
        if line.startswith(("error: uncovered:", "error: covered_twice:"))
    ]


def package_findings(repo, hold=()) -> list[str]:
    cfg = L4Config.model_validate({})
    known = [u.id for u in collect_units(providers_for(cfg, repo, {}))]
    return coverage_findings(plan_files(repo), known, list(hold))


def fixture_plain(repo):
    for name in ("a", "b", "c"):
        change(repo, name)
    put(repo, plan("p1", [units("openspec:a")]))


def fixture_derived(repo):
    for name in ("a", "b", "a-fix-1", "a-followup-2", "b-fix-1", "a-fix-1-followup-1", "x-fix-1"):
        change(repo, name)
    spec(repo, "k-followup-1")
    put(repo, plan("p1", [units("openspec:a")], exclude=[{"id": "openspec:b", "reason": "in review"}]))


def fixture_twice(repo):
    for name in ("a", "b"):
        change(repo, name)
    put(repo, plan("p1", [units("openspec:a", "openspec:b")]))
    put(repo, plan("p2", [units("openspec:a")]), "p2")


def fixture_excluded_elsewhere(repo):
    change(repo, "a")
    put(repo, plan("p1", [units("openspec:a")]))
    put(repo, plan("p2", [{"id": "b1", "units": []}], exclude=[{"id": "openspec:a", "reason": "p1"}]), "p2")


def fixture_invalid_file_still_lists(repo):
    for name in ("a", "b"):
        change(repo, name)
    put(repo, plan("p1", [units("openspec:a")], parallel=3))  # invalid schema, ids are still read
    put(repo, "not json", "p2")  # lists nothing


def fixture_kiro_and_openspec(repo):
    change(repo, "a")
    spec(repo, "k1")
    spec(repo, "k1-fix-2")
    put(repo, plan("p1", [units("kiro:k1")]))


@pytest.mark.parametrize(
    "fixture",
    [
        fixture_plain,
        fixture_derived,
        fixture_twice,
        fixture_excluded_elsewhere,
        fixture_invalid_file_still_lists,
        fixture_kiro_and_openspec,
    ],
)
def test_the_package_coverage_equals_the_standalone_validator(repo, fixture):
    fixture(repo)
    expected = script_findings(repo)
    assert package_findings(repo) == expected


@pytest.mark.parametrize("patterns", [["openspec:a"], ["openspec:b*"], ["*"], ["openspec:a", "openspec:c"]])
def test_the_package_hold_equals_the_validators(repo, patterns):
    fixture_derived(repo)
    config(repo, "yolo:\n  hold:\n" + "".join(f'    - "{p}"\n' for p in patterns))
    assert package_findings(repo, patterns) == script_findings(repo)


def test_the_parity_fixtures_find_something(repo):
    fixture_derived(repo)
    found = package_findings(repo)
    assert any(line.startswith("uncovered: kiro:k-followup-1") for line in found)
    assert any(line.startswith("uncovered: openspec:x-fix-1") for line in found)
    assert not any("a-fix-1" in line and "x-fix" not in line for line in found)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "openspec" / "changes").mkdir(parents=True)
    touch(root, "openspec/config.yaml", "schema: spec-driven\n")
    return root


def test_scn_yolo_246_a_task_that_creates_a_forbidden_migration_is_refused_before_the_push(world, capsys):
    world.pull()
    forbidden_change(world, "add-c", f"Create `{MIGRATION}` for the new table")
    local_plan(world, plan_doc({A: [], B: [A], C: [B]}))
    assert world.l4("check", "p1", "--worktree") == 2
    out = capsys.readouterr().out
    assert "p1: not admitted" in out
    assert f"intake: unit {C} fails the intake checks: forbidden_path: task 1.2 names {MIGRATION}," in out
    assert "odd.forbidden_paths rule **/migrations/** forbids" in out
    assert "set odd.forbidden_paths to an explicit list without **/migrations/**" in out
    assert f"have a person commit {MIGRATION} on the base branch first" in out


def test_scn_yolo_247_a_narrowed_list_admits_it(world, capsys):
    world.pull()
    forbidden_change(world, "add-c", f"Create `{MIGRATION}` for the new table")
    local_plan(world, plan_doc({A: [], B: [A], C: [B]}))
    set_forbidden(world, ["infra/**"])
    assert world.l4("check", "p1", "--worktree") == 0
    assert "p1: admitted (working tree)" in capsys.readouterr().out


def test_scn_yolo_248_an_existing_file_is_a_warning_with_exit_0(world, capsys):
    world.pull()
    forbidden_change(world, "add-c", f"Edit `{MIGRATION}` to add a column", extra={MIGRATION: "# migration\n"})
    world.clone.run("add", MIGRATION)  # a file the checkout tracks (the index counts for a working-tree check)
    local_plan(world, plan_doc({A: [], B: [A], C: [B]}))
    assert world.l4("check", "p1", "--worktree") == 0
    out = capsys.readouterr().out
    assert "p1: admitted (working tree)" in out
    assert f"warning: forbidden_path: {C}: task 1.2 names {MIGRATION}," in out and "already exists" in out


def test_scn_yolo_249_a_directory_token_is_a_warning(world, capsys):
    world.pull()
    forbidden_change(world, "add-c", "Move the files into `infra/`")
    local_plan(world, plan_doc({A: [], B: [A], C: [B]}))
    assert world.l4("check", "p1", "--worktree") == 0
    out = capsys.readouterr().out
    assert f"warning: forbidden_path: {C}: task 1.2 names infra/," in out and "a directory" in out


def test_a_negated_line_is_neither_a_blocker_nor_a_warning(world, capsys):
    world.pull()
    forbidden_change(world, "add-c", f"Add the column; do not touch `{MIGRATION}`")
    local_plan(world, plan_doc({A: [], B: [A], C: [B]}))
    assert world.l4("check", "p1", "--worktree") == 0
    assert "forbidden_path" not in capsys.readouterr().out


def test_an_untracked_local_file_does_not_turn_the_blocker_into_a_warning(world, capsys):
    world.pull()
    forbidden_change(world, "add-c", f"Edit `{MIGRATION}` to add a column", extra={MIGRATION: "# local only\n"})
    local_plan(world, plan_doc({A: [], B: [A], C: [B]}))
    assert world.l4("check", "p1", "--worktree") == 2
    assert f"forbidden_path: task 1.2 names {MIGRATION}," in capsys.readouterr().out


def test_scn_yolo_256_a_docs_fixture_task_is_a_warning_with_exit_0(world, capsys):
    world.pull()
    forbidden_change(world, "add-c", "Write the client fixtures `docs/client/fixtures/*.json`")
    local_plan(world, plan_doc({A: [], B: [A], C: [B]}))
    assert world.l4("check", "p1", "--worktree") == 0
    out = capsys.readouterr().out
    assert "p1: admitted (working tree)" in out
    assert f"warning: test_path: {C}: task 1.2 names docs/client/fixtures/, which the test glob **/fixtures/**" in out
