"""SCN-IMP-380, third case (B-test): `_default_copy_problem` runs for real, on a repository with a bare origin whose
default branch `main` holds an older copy of the workflow than the base `staging`. The status tests patch it out."""

from pathlib import Path
from types import SimpleNamespace

from l4.ci.github import WORKFLOW_RELPATH, ActionPin, render_github_action_ci
from l4.config.schema import L4Config
from l4.vcs.git import Git
from l4.yolo import commands as cmd

OLD = "a" * 40
NEW = "b" * 40


def _workflow(pin: str) -> str:
    return render_github_action_ci(L4Config(), ActionPin("o/harness", pin))


def _world(tmp_path: Path, raw, git_environ: dict[str, str], main_copy: str | None):
    origin = tmp_path / "origin.git"
    raw(tmp_path, "init", "-q", "--bare", str(origin))
    main = tmp_path / "main-clone"
    main.mkdir()
    raw(main, "init", "-q")
    raw(main, "checkout", "-q", "-b", "main")
    raw(main, "remote", "add", "origin", str(origin))
    (main / "README").write_text("x\n")
    if main_copy is not None:
        (main / WORKFLOW_RELPATH).parent.mkdir(parents=True)
        (main / WORKFLOW_RELPATH).write_text(main_copy)
    raw(main, "add", "-A")
    raw(main, "commit", "-q", "-m", "main")
    raw(main, "push", "-q", "origin", "main")
    repo = tmp_path / "repo"
    repo.mkdir()
    raw(repo, "init", "-q")
    raw(repo, "remote", "add", "origin", str(origin))
    raw(repo, "fetch", "-q", "origin")
    raw(repo, "remote", "set-head", "origin", "main")
    raw(repo, "checkout", "-q", "-b", "staging", "origin/main")
    (repo / WORKFLOW_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    (repo / WORKFLOW_RELPATH).write_text(_workflow(NEW))
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "--allow-empty", "-m", "staging")
    env = {**git_environ, "GITHUB_ACTIONS": "true"}
    cfg = L4Config.model_validate({"harness": {"delivery": "action"}, "forge": {"base_branch": "staging"}})
    return SimpleNamespace(
        cfg=cfg, app=SimpleNamespace(repo=repo, environ=env), git=Git(repo, environ=env), target="staging",
        target_ref="staging",
    )  # fmt: skip


def test_the_default_branch_copy_that_pins_another_harness_is_named(tmp_path, raw, git_environ):
    ctx = _world(tmp_path, raw, git_environ, _workflow(OLD))
    assert cmd._default_copy_problem(ctx) == f"main's copy of {WORKFLOW_RELPATH} pins {OLD[:7]}, not {NEW[:7]}"


def test_a_default_branch_without_the_workflow_is_named(tmp_path, raw, git_environ):
    ctx = _world(tmp_path, raw, git_environ, None)
    assert cmd._default_copy_problem(ctx) == f"main has no {WORKFLOW_RELPATH}"


def test_the_same_pin_is_no_problem(tmp_path, raw, git_environ):
    ctx = _world(tmp_path, raw, git_environ, _workflow(NEW))
    assert cmd._default_copy_problem(ctx) is None
