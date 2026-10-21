"""`.serena/project.yml` seeded by `l4 init` and `l4 upgrade` (SPEC L4-INS-002, L4-MEM-004), in the form Serena 1.7.0
itself writes, so that Serena leaves the committed file alone and no agent step sees a changed `.serena/project.yml`.

Found by the M1.7 live run: on a repository without the file every agent step logged `guard violation:
.serena/project.yml ... removed`, whatever `settle_serena_project` was told Serena wrote at the check."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from l4.init.init import apply_plan, plan_init
from l4.init.upgrade import plan_upgrade
from l4.memory.serena import INITIAL_PROMPT, SEED_PROJECT_RELPATH, render_seed_project_yml

from .test_upgrade import adopt, run


def test_the_seed_carries_the_harness_keys_and_the_project_name():
    text = render_seed_project_yml("dummy-agentic")
    data = yaml.safe_load(text)
    assert data["project_name"] == "dummy-agentic" and data["language_servers"] == ["python"]
    assert data["read_only_memory_patterns"] == ["(?!inbox/).*"]
    assert data["ignored_memory_patterns"] == ["harness/_archive/.*"]
    assert data["initial_prompt"] == INITIAL_PROMPT
    assert text.count("project_name:") == 1 and text.count("dummy-agentic") == 1


@pytest.mark.parametrize("name", ["my repo", "a:b", "123", "true", "", "ünï", "x\nproject_name: evil"])
def test_a_directory_name_cannot_change_the_shape_of_the_seed(name):
    data = yaml.safe_load(render_seed_project_yml(name))
    assert isinstance(data["project_name"], str) and "\n" not in data["project_name"]
    assert re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]*", data["project_name"])
    assert data["language_servers"] == ["python"] and "evil" not in data


def test_init_plans_the_seed_and_apply_writes_it(target: Path, harness_repo: Path, git_environ):
    plan = plan_init(target, git_environ, force=False, harness=harness_repo)
    seeds = [f for f in plan.files if f.path == SEED_PROJECT_RELPATH]
    assert len(seeds) == 1 and seeds[0].mode == 0o644
    assert seeds[0].data.decode() == render_seed_project_yml(target.name)
    assert plan.overwrites == ()
    apply_plan(target, plan)
    assert (target / SEED_PROJECT_RELPATH).read_text() == render_seed_project_yml(target.name)


def test_init_keeps_a_project_yml_that_is_already_there(target: Path, harness_repo: Path, git_environ):
    (target / ".serena").mkdir()
    (target / SEED_PROJECT_RELPATH).write_text("project_name: mine\n")
    plan = plan_init(target, git_environ, force=False, harness=harness_repo)
    assert SEED_PROJECT_RELPATH not in [f.path for f in plan.files] and plan.overwrites == ()
    apply_plan(target, plan)
    assert (target / SEED_PROJECT_RELPATH).read_text() == "project_name: mine\n"


def test_upgrade_seeds_a_repository_that_has_none_and_never_overwrites(target, harness_repo, git_environ, capsys):
    adopt(target, harness_repo, git_environ)
    (target / SEED_PROJECT_RELPATH).unlink()
    assert run(target, harness_repo, git_environ, "--dry-run") == 0
    assert "would create .serena/project.yml" in capsys.readouterr().out
    assert not (target / SEED_PROJECT_RELPATH).exists()
    assert run(target, harness_repo, git_environ) == 0
    assert "created .serena/project.yml" in capsys.readouterr().out
    assert (target / SEED_PROJECT_RELPATH).read_text() == render_seed_project_yml(target.name)
    (target / SEED_PROJECT_RELPATH).write_text("project_name: edited by a human\n")
    assert run(target, harness_repo, git_environ) == 0
    assert (target / SEED_PROJECT_RELPATH).read_text() == "project_name: edited by a human\n"
    assert plan_upgrade(target, git_environ, harness_repo).seeded == ()


def test_memory_off_seeds_nothing(target, harness_repo, git_environ):
    adopt(target, harness_repo, git_environ)
    (target / SEED_PROJECT_RELPATH).unlink()
    config = target / ".l4/config.yaml"
    config.write_text(config.read_text() + "memory:\n  enabled: false\n")
    assert plan_upgrade(target, git_environ, harness_repo).seeded == ()


@pytest.mark.skipif(not os.environ.get("L4_SERENA_BIN"), reason="set L4_SERENA_BIN to a Serena 1.7.0 executable")
def test_serena_1_7_0_leaves_the_seed_byte_identical(tmp_path: Path):
    """The point of the seed: Serena's own start, twice, rewrites nothing. Real Serena, no network needed."""
    import json
    import time

    repo = tmp_path / "some-worktree"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "a.py").write_text("x = 1\n")
    (repo / ".serena").mkdir()
    seed = render_seed_project_yml("dummy-agentic").encode()  # another name than the directory's: still untouched
    (repo / SEED_PROJECT_RELPATH).write_bytes(seed)
    home = tmp_path / "serena-home"
    home.mkdir()
    (home / "serena_config.yml").write_text("base_modes: [editing]\nprojects: []\n")
    env = {**os.environ, "SERENA_HOME": str(home), "CI": "true"}
    argv = [
        os.environ["L4_SERENA_BIN"], "start-mcp-server", "--context", "codex", "--project", str(repo),
        "--enable-web-dashboard", "false", "--open-web-dashboard", "false", "--mode", "one-shot",
        "--mode", "no-onboarding",
    ]  # fmt: skip
    for _ in range(2):
        proc = subprocess.Popen(argv, cwd=repo, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)  # fmt: skip
        assert proc.stdin and proc.stdout
        params = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params}
        proc.stdin.write((json.dumps(init) + "\n").encode())
        proc.stdin.flush()
        while json.loads(proc.stdout.readline() or b"{}").get("id") != 1:
            pass
        time.sleep(1.5)
        proc.kill()
        proc.wait()
        assert (repo / SEED_PROJECT_RELPATH).read_bytes() == seed
    shutil.rmtree(repo)


def test_ignored_serena_dir_writes_no_seed_and_turns_memory_off(target: Path, harness_repo: Path, git_environ):
    """A5 (M1.8): a repository that ignores `.serena/` would never commit the seed (or the lessons); init writes no
    seed, switches memory off and says how to carve the harness paths out of the ignore rule."""
    (target / ".gitignore").write_text(".serena/\n")
    plan = plan_init(target, git_environ, force=False, harness=harness_repo)
    assert SEED_PROJECT_RELPATH not in [f.path for f in plan.files]
    config = next(f for f in plan.files if f.path == ".l4/config.yaml")
    assert yaml.safe_load(config.data)["memory"] == {"enabled": False}
    [note] = [n for n in plan.notes if n.startswith("memory is off")]
    assert "!.serena/project.yml" in note and ".gitignore:1" in note and ".serena/memories/harness/lessons.md" in note
    apply_plan(target, plan)
    assert not (target / ".serena").exists()


def test_the_printed_carve_out_makes_git_stop_ignoring_both_paths(target: Path, harness_repo: Path, git_environ, raw):
    """Proved with real git, not assumed: git cannot re-include a file under an ignored directory."""
    from l4.memory.ignore import apply_carve_out, ignored_harness_paths

    (target / ".gitignore").write_text("node_modules/\n.serena/\n__pycache__/\n")
    ignored = ignored_harness_paths(target, git_environ)
    assert {i.path for i in ignored} == {".serena/project.yml", ".serena/memories/harness/lessons.md"}
    (target / ".gitignore").write_text(apply_carve_out((target / ".gitignore").read_text(), ignored))
    assert ignored_harness_paths(target, git_environ) == []
    for path in (".serena/project.yml", ".serena/memories/harness/lessons.md"):
        (target / path).parent.mkdir(parents=True, exist_ok=True)
        (target / path).write_text("x\n")
    (target / ".serena/cache").mkdir()
    (target / ".serena/cache/junk").write_text("x\n")
    listed = raw(target, "status", "--porcelain", "--untracked-files=all").splitlines()
    assert "?? .serena/project.yml" in listed and "?? .serena/memories/harness/lessons.md" in listed
    assert not any("cache" in row for row in listed)  # Serena's own cache stays ignored
    assert "node_modules/" in (target / ".gitignore").read_text()  # the rest of the file is untouched


def test_a_repository_that_ignores_nothing_gets_the_seed(target: Path, harness_repo: Path, git_environ):
    plan = plan_init(target, git_environ, force=False, harness=harness_repo)
    assert SEED_PROJECT_RELPATH in [f.path for f in plan.files]
    assert not [n for n in plan.notes if "memory" in n]
    config = next(f for f in plan.files if f.path == ".l4/config.yaml")
    assert "memory" not in yaml.safe_load(config.data)
