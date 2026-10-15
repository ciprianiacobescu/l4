"""A real `l4 run` against worktrees an earlier layout, or another repository key, left in this clone (L4-WTR-001).

Each one still has the unit branch checked out, so `git worktree add -B` would fail on every run."""

import subprocess

from ..implementer.conftest import green_step, red_step
from .conftest import BRANCH


def sh(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def test_an_old_layout_worktree_holding_the_branch_is_replaced(run_l4, tdd_repo):
    old = tdd_repo.cache / "worktrees" / "openspec" / "add-discount-codes"
    old.parent.mkdir(parents=True, exist_ok=True)
    sh(tdd_repo.repo, "fetch", "-q", "origin")
    sh(tdd_repo.repo, "worktree", "add", "-q", "-B", BRANCH, str(old), "origin/main")
    (old / "OLD_MARKER").write_text("x")
    run = run_l4([red_step(), green_step()])
    assert run.code == 0
    assert not old.exists()
    assert str(old.resolve()) not in sh(tdd_repo.repo, "worktree", "list", "--porcelain")


def test_a_second_run_after_the_worktree_moved_to_the_old_layout(run_l4, tdd_repo):
    names_path = tdd_repo.cache / "worktrees" / tdd_repo.key / "openspec" / "add-discount-codes"
    first = run_l4([red_step()])
    assert names_path.exists()  # one red step: the run ends early with the branch pushed
    old = tdd_repo.cache / "worktrees" / "openspec" / "add-discount-codes"
    old.parent.mkdir(parents=True, exist_ok=True)
    sh(tdd_repo.repo, "worktree", "move", str(names_path), str(old))
    second = run_l4([green_step()])
    assert second.code == 0 and second.outcome["units"][0]["phase_after"] == "implemented"
    assert not old.exists()


def test_a_renamed_project_replaces_the_worktree_of_its_old_key(run_l4, tdd_repo):
    first = run_l4([red_step()])
    old_key = tdd_repo.key
    old = tdd_repo.cache / "worktrees" / old_key / "openspec" / "add-discount-codes"
    assert old.exists()
    renamed = tdd_repo.origin.parent / "renamed-origin.git"
    tdd_repo.origin.rename(renamed)
    sh(tdd_repo.repo, "remote", "set-url", "origin", str(renamed))
    assert tdd_repo.key != old_key
    second = run_l4([green_step()])
    assert second.code == 0 and second.outcome["units"][0]["phase_after"] == "implemented"
    assert not old.exists()


def test_a_persons_own_worktree_holding_the_branch_is_refused(run_l4, tdd_repo, tmp_path):
    mine = tmp_path / "my-checkout"
    sh(tdd_repo.repo, "fetch", "-q", "origin")
    sh(tdd_repo.repo, "worktree", "add", "-q", "-B", BRANCH, str(mine), "origin/main")
    (mine / "MINE.txt").write_text("uncommitted\n")
    run = run_l4([red_step(), green_step()])
    assert run.code == 2
    assert (mine / "MINE.txt").exists()
    assert str(mine.resolve()) in run.outcome["units"][0]["exit_reason"]
