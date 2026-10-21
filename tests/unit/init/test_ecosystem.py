"""`l4 init` reads pyproject.toml and proposes the gates (forge-and-ci 1.19 reduced to uv/pytest/ruff, M1.8 A2)."""

from pathlib import Path

import pytest

from l4.init.ecosystem import M0_GATES, Proposal, detect_python, propose_gates


def project(tmp_path: Path, pyproject: str | None, *, lock: bool = True) -> Path:
    if pyproject is not None:
        (tmp_path / "pyproject.toml").write_text(pyproject)
    if lock:
        (tmp_path / "uv.lock").write_text("version = 1\n")
    return tmp_path


EXTRAS = """\
[project]
name = "sample-consumer"
dependencies = ["click"]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff", "pytest-cov"]
otel = ["opentelemetry-sdk"]
index = ["chromadb"]
embed = ["torch", "sentence-transformers"]
"""


def test_dev_extra_adds_extra_dev_to_setup(tmp_path):
    proposal = propose_gates(detect_python(project(tmp_path, EXTRAS)))
    assert proposal.gates["setup"] == ["uv sync --frozen --extra dev"]
    assert proposal.gates["lint"] == [".venv/bin/ruff check --extend-exclude .l4 ."]
    assert proposal.gates["test"]["command"] == ".venv/bin/python -m pytest --junitxml=.l4-out/junit.xml"
    assert "--extra dev" in " ".join(proposal.todos)  # the assumption is written down


def test_dev_group_keeps_plain_sync(tmp_path):
    text = '[project]\nname = "x"\n\n[dependency-groups]\ndev = ["pytest", "ruff"]\n'
    proposal = propose_gates(detect_python(project(tmp_path, text)))
    assert proposal.gates["setup"] == ["uv sync --frozen"]
    assert proposal.gates["lint"] == M0_GATES["lint"]


def test_other_extras_are_listed_never_all_extras(tmp_path):
    proposal = propose_gates(detect_python(project(tmp_path, EXTRAS)))
    assert proposal.extras_not_installed == ("embed", "index", "otel")
    assert "--all-extras" not in str(proposal.gates) and "embed" not in str(proposal.gates)
    assert any("embed" in note and "index" in note for note in proposal.notes)


def test_no_ruff_leaves_lint_empty_with_a_note(tmp_path):
    text = '[project]\nname = "x"\n\n[project.optional-dependencies]\ndev = ["pytest"]\n'
    proposal = propose_gates(detect_python(project(tmp_path, text)))
    assert proposal.gates["lint"] == []
    assert any("ruff" in todo for todo in proposal.todos)


def test_ruff_only_in_an_uninstalled_extra_leaves_lint_empty(tmp_path):
    text = '[project]\nname = "x"\n\n[project.optional-dependencies]\ndev = ["pytest"]\nlint = ["ruff"]\n'
    proposal = propose_gates(detect_python(project(tmp_path, text)))
    assert proposal.gates["lint"] == [] and any("lint" in todo and "--extra" in todo for todo in proposal.todos)


def test_no_lock_says_uv_lock(tmp_path):
    proposal = propose_gates(detect_python(project(tmp_path, EXTRAS, lock=False)))
    assert proposal.gates["setup"] == ["uv sync --frozen --extra dev"]  # still frozen: the harness never relocks
    assert any("uv lock" in todo for todo in proposal.todos)


def test_no_pytest_or_coverage_is_a_note(tmp_path):
    text = '[project]\nname = "x"\n\n[project.optional-dependencies]\ndev = ["ruff"]\n'
    proposal = propose_gates(detect_python(project(tmp_path, text)))
    assert any("pytest" in todo for todo in proposal.todos)
    other = tmp_path / "b"
    other.mkdir()
    with_pytest = propose_gates(detect_python(project(other, EXTRAS.replace(', "pytest-cov"', ""))))
    assert any("coverage" in n for n in with_pytest.notes)


def test_no_pyproject_keeps_the_m0_gates_with_a_todo(tmp_path):
    proposal = propose_gates(detect_python(project(tmp_path, None, lock=False)))
    assert proposal.gates == M0_GATES
    assert any("pyproject.toml" in todo for todo in proposal.todos)


# --- ci.toolchains proposals (L4-CI-005) ---------------------------------------------------------------------------

import json  # noqa: E402

import yaml  # noqa: E402

from l4.config.schema import L4Config  # noqa: E402
from l4.init.ecosystem import detect_toolchains, toolchain_todos  # noqa: E402
from l4.init.init import render_config  # noqa: E402


def write(root: Path, name: str, text: str) -> None:
    (root / name).write_text(text)


def test_go_work_wins_over_go_mod_and_both_are_version_files(tmp_path):
    write(tmp_path, "go.mod", "module x\n\ngo 1.26\n")
    assert detect_toolchains(tmp_path) == {"go": {"version_file": "go.mod"}}
    write(tmp_path, "go.work", "go 1.26\n")
    assert detect_toolchains(tmp_path)["go"] == {"version_file": "go.work"}


def test_node_from_nvmrc_or_engines_and_pnpm_from_package_manager(tmp_path):
    write(
        tmp_path,
        "package.json",
        json.dumps({"engines": {"node": ">=22 <23"}, "packageManager": "pnpm@11.0.9+sha512.ab"}),
    )
    assert detect_toolchains(tmp_path) == {"node": {"version": ">=22 <23"}, "pnpm": {"version": "11.0.9"}}
    write(tmp_path, ".nvmrc", "v22.1.0\n")
    assert detect_toolchains(tmp_path)["node"] == {"version_file": ".nvmrc"}


@pytest.mark.parametrize(
    "package",
    ["not json", "[]", json.dumps({"engines": "node"}), json.dumps({"packageManager": "yarn@4.1.0"}), "{}"],
)
def test_a_package_json_that_names_nothing_proposes_nothing(tmp_path, package):
    write(tmp_path, "package.json", package)
    assert detect_toolchains(tmp_path) == {}


def test_no_toolchain_files_no_proposal_and_no_todo(tmp_path):
    assert detect_toolchains(tmp_path) == {} and toolchain_todos({}) == ()


def test_the_proposal_is_written_to_ci_toolchains_and_loads(tmp_path):
    found = {"go": {"version_file": "go.work"}, "node": {"version": ">=22"}, "pnpm": {"version": "11.0.9"}}
    proposal = Proposal({}, toolchains=found)
    text = render_config("0" * 40, "github", proposal=proposal)
    assert yaml.safe_load(text)["ci"]["toolchains"] == found
    cfg = L4Config.model_validate(yaml.safe_load(text))
    assert cfg.ci.toolchains.go.version_file == "go.work" and cfg.ci.toolchains.node.version == ">=22"
    assert "ci.toolchains" not in render_config("0" * 40, "github")


def test_the_todo_names_the_toolchains_and_says_the_gates_are_the_python_ones():
    (todo,) = toolchain_todos({"go": {"version_file": "go.work"}, "pnpm": {"version": "11"}})
    assert "go, pnpm" in todo and "gates" in todo
