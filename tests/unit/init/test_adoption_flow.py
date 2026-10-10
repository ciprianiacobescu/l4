"""The sample-consumer shape, offline (M1.8 A2/A3): `l4 init`, then `l4 doctor --adoption`.

A project with extras `dev`, `otel`, `index` and `embed`, ruff in `dev`, and a test that needs a module of the `index`
extra. Init proposes `uv sync --frozen --extra dev`; the dry run of the gates fails on that test and the fix column
names the extra it needs, never the heavy one."""

import json
import sys
import textwrap
from pathlib import Path

import yaml

from l4.cli import main

from ..conftest import MKVENV

PYPROJECT = """\
[project]
name = "sample-consumer"
version = "0.1.0"
dependencies = ["click"]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff", "pytest-cov"]
otel = ["opentelemetry-sdk"]
index = ["no_such_index_module_xyz"]
embed = ["torch", "sentence-transformers"]
"""
TEST = "import no_such_index_module_xyz\n\n\ndef test_index():\n    assert no_such_index_module_xyz\n"


def test_extras_project_init_then_doctor_adoption_suggests_the_missing_extra(
    target: Path, harness_repo: Path, git_environ, raw, tmp_path, capsys
):
    environ = {**git_environ, "L4_CACHE": str(tmp_path / "cache"), "L4_HOME": str(tmp_path / "l4home")}
    (target / "pyproject.toml").write_text(PYPROJECT)
    (target / "uv.lock").write_text("version = 1\n")
    (target / "tests").mkdir()
    (target / "tests" / "test_index.py").write_text(TEST)
    raw(target, "add", "-A")
    raw(target, "commit", "-q", "-m", "the project")
    assert (
        main(
            ["init", "--repo", str(target), "--harness", str(harness_repo), "--ci", "gitlab", "--vendor"],
            environ=environ,
        )
        == 0
    )
    capsys.readouterr()
    config_path = target / ".l4" / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    assert config["gates"]["setup"] == ["uv sync --frozen --extra dev"]  # init's proposal: dev only, never embed
    assert config["gates"]["lint"] == [".venv/bin/ruff check --extend-exclude .l4 ."]

    # offline: `uv sync` and ruff are replaced by a launcher that makes `.venv/bin/python` (as the fixtures do)
    script = tmp_path / "mkvenv.py"
    script.write_text(MKVENV)
    config["gates"]["setup"] = [f"{sys.executable} {script} {sys.executable}"]
    config["gates"]["lint"] = []
    config["gates"]["test"]["command"] = textwrap.dedent(
        ".venv/bin/python -m pytest -p no:cacheprovider -o junit_family=xunit1 --junitxml=.l4-out/junit.xml"
    )
    config["sandbox"] = {"mode": "none", "allow_none": True}
    config_path.write_text(yaml.safe_dump(config))

    code = main(["doctor", "--adoption", "--json", "--repo", str(target)], environ=environ)
    doc = json.loads(capsys.readouterr().out)
    assert code == 3
    gate = next(c for c in doc["checks"] if c["id"] == "GATE-001")
    assert gate["status"] == "fail" and "test_index" in gate["message"]
    assert "--extra index" in gate["fix"] and "embed" not in gate["fix"] and "--all-extras" not in gate["fix"]
    ids = {c["id"] for c in doc["checks"]}
    assert not {i for i in ids if i.startswith(("ENV-", "PRV-", "SANDBOX-"))}  # a laptop with no agent CLI
