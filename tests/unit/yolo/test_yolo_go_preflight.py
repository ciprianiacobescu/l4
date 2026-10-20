# ruff: noqa: F811
"""`l4 yolo go` preflight (L4-YOLO-081; SCN-YOLO-202 to -204): the checks of the skill's `yolo_preflight.py`, with one
implementation in the harness and a parity test against the script."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from l4.yolo.preflight import problems

from .yolo_cmd_world import world  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "plugins" / "l4" / "skills" / "l4" / "scripts" / "yolo_preflight.py"
BASE = "refs/remotes/origin/main"
PLAN_FILE = ".l4/plans/p1.json"
UNIT_FILE = "openspec/changes/add-b/notes.md"


def committed(world) -> None:
    """Plan `p1` pushed and the checkout up to date: the starting point of every fixture."""
    world.push_plan()
    world.pull()


def found(world) -> list[tuple[str, str]]:
    return [(p.code, p.fix) for p in problems(world.app.repo, world.clone, "p1", base_ref=BASE)]


def codes(world) -> list[str]:
    return [code for code, _ in found(world)]


def test_a_clean_tree_has_no_problem(world):
    committed(world)
    assert found(world) == []
    (world.app.repo / "scratch").mkdir()
    (world.app.repo / "scratch" / "notes.md").write_text("mine\n", encoding="utf-8")  # untracked, elsewhere
    assert found(world) == []


def test_a_tracked_change_is_dirty(world):
    committed(world)
    tracked = world.app.repo / "openspec" / "changes" / "add-b" / "proposal.md"
    tracked.write_text("# B changed\n", encoding="utf-8")
    assert found(world) == [("dirty", "git status")]  # unstaged
    world.clone.run("add", "openspec/changes/add-b/proposal.md")
    assert found(world) == [("dirty", "git status")]  # staged
    dirty = problems(world.app.repo, world.clone, "p1", base_ref=BASE)[0]
    assert "openspec/changes/add-b/proposal.md" in dirty.text


def test_a_plan_on_neither_side_is_missing(world):
    assert found(world) == [("plan_missing", "l4 yolo draft p1")]
    world.push_plan()  # on origin, not in this working tree: the script's rule, a pull is the fix
    world.clone.run("fetch", "--quiet", "origin")
    assert found(world) == [("plan_missing", "git pull --ff-only origin main")]


def test_a_plan_file_that_is_not_json_is_a_problem(world):
    committed(world)
    path = world.app.repo / PLAN_FILE
    path.write_text("{not json", encoding="utf-8")
    world.clone.run("commit", "-qam", "break the plan")
    assert codes(world) == ["plan_not_json"]


def test_an_untracked_plan_file_is_uncommitted(world):
    path = world.app.repo / PLAN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "l4/delivery-plan@1", "plan_id": "p1", "batches": []}), encoding="utf-8")
    assert found(world) == [("plan_uncommitted", f"git add {PLAN_FILE} && git commit")]


def test_an_untracked_file_in_a_unit_folder_is_a_problem_and_one_elsewhere_is_not(world):
    """SCN-YOLO-203, function level."""
    committed(world)
    (world.app.repo / UNIT_FILE).write_text("notes\n", encoding="utf-8")
    assert found(world) == [("unit_uncommitted", "git add openspec/changes/add-b && git commit")]
    (world.app.repo / UNIT_FILE).rename(world.app.repo / "notes.md")
    assert found(world) == []


# --- SCN-YOLO-204: the script is the arbiter -------------------------------------------------------------------------


def script_says(world) -> dict[str, str]:
    """The result of the script's two local checks, run as its usage says, in the checkout."""
    done = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "p1", "--no-fetch", "--json", "--l4", "true"],
        cwd=world.app.repo, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert done.returncode in (0, 1), done.stderr
    checks = {c["name"]: c["result"] for c in json.loads(done.stdout)["checks"]}
    return {"plan-file": checks["plan-file"], "clean-tree": checks["clean-tree"]}


# the script's check that catches each code of the function
SCRIPT_CHECK = {
    "dirty": "clean-tree", "plan_uncommitted": "clean-tree", "unit_uncommitted": "clean-tree",
    "plan_missing": "plan-file", "plan_not_json": "plan-file",
}  # fmt: skip


def setup_clean(world):
    committed(world)


def setup_unstaged(world):
    committed(world)
    (world.app.repo / "openspec/changes/add-b/proposal.md").write_text("# B changed\n", encoding="utf-8")


def setup_staged(world):
    setup_unstaged(world)
    world.clone.run("add", "openspec/changes/add-b/proposal.md")


def setup_none(world):
    pass


def setup_origin_only(world):
    world.push_plan()


def setup_untracked_plan(world):
    path = world.app.repo / PLAN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"plan_id": "p1"}), encoding="utf-8")


def setup_not_json(world):
    committed(world)
    (world.app.repo / PLAN_FILE).write_text("{not json", encoding="utf-8")
    world.clone.run("commit", "-qam", "break the plan")


def setup_unit_file(world):
    committed(world)
    (world.app.repo / UNIT_FILE).write_text("notes\n", encoding="utf-8")


def setup_elsewhere(world):
    committed(world)
    (world.app.repo / "notes.md").write_text("notes\n", encoding="utf-8")


def setup_untracked_in_dot_l4(world):
    committed(world)
    (world.app.repo / ".l4" / "scratch.txt").write_text("notes\n", encoding="utf-8")


@pytest.mark.parametrize(
    "setup, wanted",
    [
        (setup_clean, []),
        (setup_elsewhere, []),
        (setup_unstaged, ["dirty"]),
        (setup_staged, ["dirty"]),
        (setup_none, ["plan_missing"]),
        (setup_origin_only, ["plan_missing"]),
        (setup_untracked_plan, ["plan_uncommitted"]),
        (setup_untracked_in_dot_l4, ["plan_uncommitted"]),
        (setup_not_json, ["plan_not_json"]),
        (setup_unit_file, ["unit_uncommitted"]),
    ],
)
def test_the_harness_and_the_skill_script_agree(world, setup, wanted):
    setup(world)
    ours = codes(world)
    assert ours == wanted
    said = script_says(world)
    for code in ours:  # the script prints a check, not a code: the check that catches this code fails
        assert said[SCRIPT_CHECK[code]] == "FAIL", (code, said)
    if not ours:
        assert set(said.values()) == {"ok"}, said
    else:
        assert "FAIL" in said.values(), said
        failing = {name for name, result in said.items() if result == "FAIL"}
        assert failing == {SCRIPT_CHECK[c] for c in ours}, (failing, ours)
