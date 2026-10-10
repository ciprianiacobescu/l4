"""Pre-satisfied criteria (L4-IMP-002, M13-G3): tests of behaviour that already exists must prove they discriminate."""

import pytest

from l4.implementer.discrimination import confirm_pre_satisfied, imported_modules
from l4.implementer.tdd import run_setup

from .conftest import Bench

C1, C2 = "C-aaaaaaaa", "C-bbbbbbbb"


@pytest.fixture
def staged(make_bench) -> Bench:
    bench = make_bench([])
    wb = bench.wb
    (wb.worktree / "tests/test_existing.py").write_text(
        "from pytdd import total\n\n\n"
        "def test_total_adds():\n    assert total([1.0, 2.0]) == 3.0\n\n\n"
        "def test_tautology():\n    assert total([]) == total([])\n\n\n"
        "def test_nothing():\n    assert True\n"
    )
    run_setup(wb)
    return bench


def test_existing_behaviour_is_pre_satisfied_and_a_tautology_is_not(staged: Bench):
    wb = staged.wb
    pricing = wb.worktree / "src/pytdd/pricing.py"
    before = pricing.read_bytes()
    result = confirm_pre_satisfied(
        wb,
        {
            C1: ["tests.test_existing::test_total_adds"],
            C2: ["tests.test_existing::test_nothing", "tests.test_existing::test_tautology"],
        },
    )
    assert set(result.confirmed) == {C1} and set(result.unconfirmed) == {C2}
    assert result.message == (
        f"not discriminating: {C2} (its tests still pass, or fail by an error rather than an assertion, "
        "when the functions they use answer the zero value)"
    )
    assert pricing.read_bytes() == before


def test_no_candidates_runs_nothing(staged: Bench):
    result = confirm_pre_satisfied(staged.wb, {})
    assert result.message == "" and not result.confirmed and not result.unconfirmed


def test_tests_that_import_no_project_module_cannot_be_confirmed(make_bench):
    bench = make_bench([])
    (bench.wb.worktree / "tests/test_lonely.py").write_text("def test_x():\n    assert True\n")
    run_setup(bench.wb)
    result = confirm_pre_satisfied(bench.wb, {C1: ["tests.test_lonely::test_x"]})
    assert set(result.unconfirmed) == {C1} and "no project source module" in result.message


def test_imports_are_followed_through_a_reexporting_package(staged: Bench):
    modules = imported_modules(staged.wb, ["tests.test_existing::test_total_adds"])
    assert modules == {"src/pytdd/__init__.py", "src/pytdd/pricing.py"}
