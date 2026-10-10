"""`l4 init` reads pyproject.toml and proposes the gates (forge-and-ci 1.19 reduced to uv/pytest/ruff, M1.8 A2)."""

from pathlib import Path

from l4.init.ecosystem import M0_GATES, detect_python, propose_gates


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
