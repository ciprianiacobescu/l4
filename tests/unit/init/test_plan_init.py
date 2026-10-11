from pathlib import Path

import yaml

from l4.config.loader import load_config
from l4.config.preflight import preflight_run_config
from l4.init.init import plan_init, render_config


def test_python_repo_gets_exact_file_set(target: Path, harness_repo: Path, git_environ, raw):
    plan = plan_init(target, git_environ, force=False, harness=harness_repo)
    assert [f.path for f in plan.files] == [
        ".l4/config.yaml",
        ".l4/bin/l4",
        ".l4/bin/l4-setup",
        ".l4/ci/l4.gitlab-ci.yml",
        ".gitlab-ci.yml",
        ".serena/project.yml",
    ]
    assert {f.path: f.mode for f in plan.files}[".l4/bin/l4"] == 0o755
    assert {f.path: f.mode for f in plan.files}[".l4/bin/l4-setup"] == 0o755
    assert plan.gitignore == b".l4-out/\n.l4/vendor/.venv/\n"
    assert not plan.vendor_exists and plan.overwrites == ()
    assert plan.vendor.commit == raw(harness_repo, "rev-parse", "HEAD").strip()
    assert sorted(p.name for p in target.iterdir()) == [".git", "README.md"]
    assert not (target / ".l4").exists()  # planning writes nothing


def test_the_config_loads_and_a_run_accepts_it(target: Path, harness_repo: Path, git_environ, app_for):
    commit = "a" * 40
    (target / ".l4").mkdir()
    (target / ".l4" / "config.yaml").write_text(render_config(commit))
    cfg = load_config(target)
    assert cfg.harness.commit == commit
    assert cfg.spec.frameworks == ["openspec"]
    assert cfg.gates.setup == ["uv sync --frozen"]
    assert cfg.gates.test.command == ".venv/bin/python -m pytest --junitxml=.l4-out/junit.xml"
    assert cfg.gates.lint == [".venv/bin/ruff check --extend-exclude .l4 ."]  # the vendored harness is not linted
    assert cfg.roles.implementer == ["codex"] and cfg.roles.judges == ["claude-code"]
    assert cfg.profiles["codex"].vendor == "openai" and cfg.profiles["claude-code"].vendor == "anthropic"
    assert cfg.profiles["codex"].adapter == "codex" and cfg.profiles["claude-code"].adapter == "claude-code"
    assert cfg.forge.type == "gitlab" and cfg.ci.platform == "gitlab"
    preflight_run_config(app_for(target), cfg)  # roles name defined profiles, caches are fine


def test_the_config_is_plain_yaml_with_only_the_keys_init_sets():
    assert set(yaml.safe_load(render_config("b" * 40))) == {
        "version", "harness", "spec", "gates", "profiles", "roles", "forge", "ci",
    }  # fmt: skip


def test_the_ci_file_and_shim_are_the_renderers_output(target: Path, harness_repo: Path, git_environ):
    from l4.ci.render import render_gitlab_ci, render_shim

    plan = plan_init(target, git_environ, force=False, harness=harness_repo)
    by_path = {f.path: f.data.decode() for f in plan.files}
    assert by_path[".l4/ci/l4.gitlab-ci.yml"] == render_gitlab_ci()
    assert by_path[".l4/bin/l4"] == render_shim()


def test_the_generated_lint_gate_does_not_walk_the_vendored_harness(tmp_path):
    import shlex
    import subprocess
    import sys

    from l4.init.init import GATES

    (tmp_path / ".l4" / "vendor" / "src").mkdir(parents=True)
    (tmp_path / ".l4" / "vendor" / "src" / "bad.py").write_text("import os\n")  # F401 in the harness, not the target
    (tmp_path / "ok.py").write_text("x = 1\n")
    [command] = GATES["lint"]
    tokens = shlex.split(command)
    assert tokens[0] == ".venv/bin/ruff"
    done = subprocess.run(
        [sys.executable, "-m", "ruff", *tokens[1:], "--no-cache"], cwd=tmp_path, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stdout
    assert not (tmp_path / ".l4" / "vendor" / ".ruff_cache").exists()


EXTRAS_PYPROJECT = """\
[project]
name = "sample-consumer"
dependencies = ["click"]

[project.optional-dependencies]
dev = ["pytest", "ruff"]
index = ["chromadb"]
embed = ["torch"]
"""


def test_gates_follow_pyproject_and_todos_name_the_assumptions(target: Path, harness_repo: Path, git_environ):
    (target / "pyproject.toml").write_text(EXTRAS_PYPROJECT)
    (target / "uv.lock").write_text("version = 1\n")
    plan = plan_init(target, git_environ, force=False, harness=harness_repo)
    text = next(f for f in plan.files if f.path == ".l4/config.yaml").data.decode()
    body = yaml.safe_load(text)
    assert body["gates"]["setup"] == ["uv sync --frozen --extra dev"]
    todos = [line for line in text.splitlines() if line.startswith("# TODO:")]
    assert todos and any("--extra dev" in line for line in todos)
    assert text.splitlines().index(todos[0]) < text.index("version") and text.startswith("# Written by")
    (target / ".l4").mkdir()
    (target / ".l4" / "config.yaml").write_text(text)
    assert load_config(target).gates.setup == ["uv sync --frozen --extra dev"]  # TODO lines are comments: it loads
    assert any("index" in note and "embed" in note for note in plan.notes)


def test_a_repository_without_pyproject_keeps_the_m0_gates_and_a_todo(target: Path, harness_repo: Path, git_environ):
    plan = plan_init(target, git_environ, force=False, harness=harness_repo)
    text = next(f for f in plan.files if f.path == ".l4/config.yaml").data.decode()
    assert yaml.safe_load(text)["gates"]["setup"] == ["uv sync --frozen"]
    assert "# TODO: no pyproject.toml" in text
