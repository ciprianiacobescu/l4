"""What the project's tests already do about optional dependencies and how a test file starts (M1.9, P2/P3): read from
the base commit only, so that nothing the unit changed shapes what its tests are judged against."""

from l4.config.schema import L4Config
from l4.verifier.conventions import base_test_header, test_conventions

CONFTEST = """\
import importlib.util

import pytest

requires_fastapi = pytest.mark.skipif(importlib.util.find_spec("fastapi") is None, reason="fastapi missing")
yaml = pytest.importorskip("yaml")
slow = pytest.mark.slow


@pytest.fixture
def tmp():
    needs = pytest.mark.skipif(True, reason="indented: not a module-level helper")
    return needs
"""
PYPROJECT = """\
[project]
name = "demo"

[tool.pytest.ini_options]
markers = [
    "slow: marks tests as slow",
    "needs_db: needs a database",
]
"""
CFG = L4Config.model_validate({})


def commit(raw, repo, files: dict[str, str], message: str) -> str:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", message)
    return raw(repo, "rev-parse", "HEAD").strip()


def test_skip_helpers_and_markers_are_listed(make_repo, raw, git_for):
    repo = make_repo()
    base = commit(raw, repo, {"tests/conftest.py": CONFTEST, "pyproject.toml": PYPROJECT}, "base")
    text = test_conventions(git_for(repo), base, CFG)
    lines = text.splitlines()
    assert lines[0].startswith("tests/conftest.py:5: requires_fastapi = pytest.mark.skipif(")
    assert 'tests/conftest.py:6: yaml = pytest.importorskip("yaml")' in lines
    assert "tests/conftest.py:7: slow = pytest.mark.slow" in lines
    assert not any("indented" in line for line in lines)  # only module-level lines
    assert "pyproject.toml:6: slow: marks tests as slow" in lines
    assert "pyproject.toml:7: needs_db: needs a database" in lines
    # a pytest.ini wins the markers it declares, and is listed too
    pytest_ini = "[pytest]\nmarkers =\n    gpu: needs a gpu\n    net: needs the network\n"
    ini = commit(raw, repo, {"pytest.ini": pytest_ini}, "ini")
    listed = test_conventions(git_for(repo), ini, CFG).splitlines()
    assert "pytest.ini:3: gpu: needs a gpu" in listed and "pytest.ini:4: net: needs the network" in listed
    # at most 40 lines and 3000 characters
    many = "import pytest\n" + "".join(f"h{i} = pytest.mark.skipif(False, reason='r{i}')\n" for i in range(100))
    big = commit(raw, repo, {"tests/conftest.py": many}, "many")
    capped = test_conventions(git_for(repo), big, CFG)
    assert len(capped.splitlines()) <= 40 and len(capped) <= 3000


def test_a_project_without_helpers_gives_nothing(make_repo, raw, git_for):
    repo = make_repo()
    plain = "import pytest\n\n\n@pytest.fixture\ndef thing():\n    return 1\n"
    base = commit(raw, repo, {"tests/conftest.py": plain, "pyproject.toml": "[project]\nname = 'demo'\n"}, "base")
    assert test_conventions(git_for(repo), base, CFG) == ""
    assert test_conventions(git_for(repo), raw(repo, "rev-parse", "HEAD~1").strip(), CFG) == ""  # not even a conftest


def test_only_the_base_is_read(make_repo, raw, git_for):
    repo = make_repo()
    base = commit(raw, repo, {"tests/conftest.py": "import pytest\n\nslow = pytest.mark.slow\n"}, "base")
    head = commit(raw, repo, {"tests/conftest.py": CONFTEST, "pyproject.toml": PYPROJECT}, "the unit's change")
    (repo / "tests" / "conftest.py").write_text("import pytest\n\nplanted = pytest.mark.skip\n")  # not even committed
    git = git_for(repo)
    assert test_conventions(git, base, CFG).splitlines() == ["tests/conftest.py:3: slow = pytest.mark.slow"]
    assert "requires_fastapi" in test_conventions(git, head, CFG) and "planted" not in test_conventions(git, head, CFG)


def test_the_header_comes_from_a_base_file_the_unit_did_not_change(make_repo, raw, git_for):
    repo = make_repo()
    header = '"""Pricing tests."""\n\nimport pytest\n\nfrom pytdd import pricing\n\nrequires_x = pytest.mark.slow\n'
    body = "\n\ndef test_a():\n    assert pricing\n"
    base = commit(raw, repo, {
        "tests/test_a.py": header + body, "tests/unit/test_b.py": "import os\n" + body,
        "tests/test_l4_audit_c_00000001_r1.py": "# generated\n" + body, "src/mod.py": "x = 1\n",
    }, "base")  # fmt: skip
    git = git_for(repo)
    path, text = base_test_header(git, base, changed=["tests/test_a.py"], near="tests/test_l4_audit_c_00000002_r1.py")
    assert path != "tests/test_a.py" and path == "tests/unit/test_b.py" and text == "import os\n"  # the unit changed a
    path, text = base_test_header(git, base, changed=[], near="tests/test_l4_audit_c_00000002_r1.py")
    assert path == "tests/test_a.py" and text.endswith("requires_x = pytest.mark.slow\n") and "def test_a" not in text
    assert base_test_header(git, base, changed=["tests/test_a.py", "tests/unit/test_b.py"], near="tests/x.py") is None
    long = "".join(f"import mod{i}\n" for i in range(80)) + body
    big = commit(raw, repo, {"tests/test_c.py": long, "tests/test_a.py": "", "tests/unit/test_b.py": ""}, "long")
    _, cut = base_test_header(git_for(repo), big, changed=[], near="tests/test_x.py")
    assert len(cut.splitlines()) == 40
