"""Import roots (L4-IMP-025): the zero-value run finds the modules a test imports in a workspace layout too."""

from pathlib import Path

import pytest

from l4.implementer.discrimination import confirm_pre_satisfied, head_stub_modules, imported_modules
from l4.implementer.tdd import run_setup

from .conftest import Bench

C1 = "C-aaaaaaaa"
TEST_ID = "packages.calc.tests.test_ops::test_double"


def _write(root: Path, relative: str, text: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


@pytest.fixture
def workspace(tdd_repo, raw, make_bench) -> Bench:
    """A workspace member `packages/calc` with its own `pyproject.toml` and a `src` layout under a namespace package
    (`acme` has no `__init__.py`), and a flat member `packages/flat` whose package sits next to its project file. Both
    are on the base branch: the unit changed none of them, as when a test pins behaviour that already exists."""
    root = tdd_repo.repo
    _write(root, "packages/calc/pyproject.toml", '[project]\nname = "acme-calc"\nversion = "0.1.0"\n')
    _write(root, "packages/calc/src/acme/calc/__init__.py", "")
    _write(root, "packages/calc/src/acme/calc/ops.py", "def double(x: int) -> int:\n    return 2 * x\n")
    _write(
        root,
        "packages/calc/tests/test_ops.py",
        "from acme.calc.ops import double\n\n\ndef test_double():\n    assert double(2) == 4\n",
    )
    _write(root, "packages/flat/setup.cfg", "[metadata]\nname = flat\n")
    _write(root, "packages/flat/flatpkg/__init__.py", "")
    _write(root, "packages/flat/flatpkg/core.py", "def one() -> int:\n    return 1\n")
    _write(
        root,
        "packages/flat/tests/test_core.py",
        "from flatpkg.core import one\n\n\ndef test_one():\n    assert one() == 1\n",
    )
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text()
        .replace('testpaths = ["tests"]', 'testpaths = ["tests", "packages/calc/tests"]')
        .replace('pythonpath = ["src"]', 'pythonpath = ["src", "packages/calc/src"]')
    )
    raw(root, "add", "-A")
    raw(root, "commit", "-q", "-m", "workspace members")
    raw(root, "push", "-q", "origin", "main")
    raw(root, "fetch", "-q", "origin")
    bench = make_bench([])
    run_setup(bench.wb)
    return bench


def test_a_module_under_a_member_src_is_found(workspace: Bench):
    assert imported_modules(workspace.wb, [TEST_ID]) == {"packages/calc/src/acme/calc/ops.py"}


def test_a_flat_member_package_is_found(workspace: Bench):
    modules = imported_modules(workspace.wb, ["packages.flat.tests.test_core::test_one"])
    assert modules == {"packages/flat/flatpkg/core.py"}


def test_existing_behaviour_in_a_workspace_is_pre_satisfied(workspace: Bench):
    ops = workspace.wb.worktree / "packages/calc/src/acme/calc/ops.py"
    before = ops.read_bytes()
    result = confirm_pre_satisfied(workspace.wb, {C1: [TEST_ID]})
    assert set(result.confirmed) == {C1} and not result.unconfirmed, result.message
    assert ops.read_bytes() == before


def test_a_head_stub_in_a_member_is_found(workspace: Bench):
    ops = workspace.wb.worktree / "packages/calc/src/acme/calc/ops.py"
    ops.write_text("def double(x: int) -> int:\n    raise NotImplementedError\n")
    assert head_stub_modules(workspace.wb, [TEST_ID]) == ["packages/calc/src/acme/calc/ops.py"]


def test_a_directory_that_is_no_import_root_is_not_searched(workspace: Bench):
    """`scripts/` holds no project file and is not named `src`: a `json.py` there is not the `json` a test imports."""
    root = workspace.wb.worktree
    _write(root, "scripts/json.py", "def dumps(x: object) -> str:\n    return ''\n")
    _write(
        root, "packages/calc/tests/test_json.py", "import json\n\n\ndef test_dump():\n    assert json.dumps(1) == '1'\n"
    )
    assert imported_modules(workspace.wb, ["packages.calc.tests.test_json::test_dump"]) == set()


def test_an_ignored_directory_is_not_searched(workspace: Bench):
    """A virtual environment's copy of a package is not the project's source."""
    root = workspace.wb.worktree
    _write(root, ".gitignore", ".venv/\n")
    _write(root, ".venv/lib/site/pyproject.toml", "")
    _write(root, ".venv/lib/site/vendored/__init__.py", "")
    _write(root, "packages/calc/tests/test_vendored.py", "import vendored\n\n\ndef test_v():\n    assert vendored\n")
    assert imported_modules(workspace.wb, ["packages.calc.tests.test_vendored::test_v"]) == set()
