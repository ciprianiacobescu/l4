"""Run (b): the zero-value variants of the red stubs, in place, restored byte-exact (L4-IMP-002, D7)."""

import hashlib
from pathlib import Path

import pytest

from l4.implementer.discrimination import (
    Vacuity,
    imported_modules,
    vacuity_check,
    zero_values_in_place,
    zeroed_run,
)
from l4.implementer.tdd import run_setup

from .conftest import Bench

STUB = "def apply_discount(amount: float, code: str) -> float:\n    raise NotImplementedError\n"
UNTYPED_STUB = "def apply_discount(amount, code):\n    raise NotImplementedError\n"  # zero value: None
C1, C2 = "C-aaaaaaaa", "C-bbbbbbbb"
TESTS = f"""import pytest
from pytdd.pricing import apply_discount


@pytest.mark.l4("{C1}")
def test_call_only():
    apply_discount(50.0, "SAVE10")


@pytest.mark.l4("{C2}")
def test_zero_is_the_answer():
    assert apply_discount(0.0, "SAVE10") == 0.0


@pytest.mark.l4("{C2}")
def test_real_answer():
    assert apply_discount(50.0, "SAVE10") == 45.0
"""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def staged(make_bench) -> tuple[Bench, Path]:
    bench = make_bench([])
    wb = bench.wb
    pricing = wb.worktree / "src/pytdd/pricing.py"
    pricing.write_text(pricing.read_text() + "\n\n" + STUB)
    (wb.worktree / "tests/test_red.py").write_text(TESTS)
    run_setup(wb)
    return bench, pricing


def test_call_only_test_is_vacuous_and_zero_edge_case_next_to_sibling_is_fine(staged: tuple[Bench, Path]):
    bench, pricing = staged
    before = sha(pricing)
    tracing = {
        C1: ["tests.test_red::test_call_only"],
        C2: ["tests.test_red::test_zero_is_the_answer", "tests.test_red::test_real_answer"],
    }
    result = vacuity_check(bench.wb, ["src/pytdd/pricing.py"], tracing)
    assert set(result.vacuous) == {C1} and result.vacuous[C1] == ("tests.test_red::test_call_only",)
    assert result.proofs == {
        C2: ("tests.test_red::test_real_answer",)
    }  # the zero-answer test passes, and is not flagged
    assert result.message.startswith("vacuous: C-aaaaaaaa") and "test_call_only" in result.message
    assert sha(pricing) == before  # restored byte for byte


def test_a_criterion_whose_only_test_has_the_zero_answer_is_vacuous(staged: tuple[Bench, Path]):
    bench, _ = staged
    result = vacuity_check(bench.wb, ["src/pytdd/pricing.py"], {C2: ["tests.test_red::test_zero_is_the_answer"]})
    assert set(result.vacuous) == {C2}


def test_the_variant_really_answers_the_zero_value_inside_the_block_only(staged: tuple[Bench, Path]):
    bench, pricing = staged
    original = pricing.read_text()
    with zero_values_in_place(bench.wb, ["src/pytdd/pricing.py", "src/missing.py"], public=False) as varied:
        assert varied == ["src/pytdd/pricing.py"] and "return 0.0" in pricing.read_text()
    assert pricing.read_text() == original


def test_an_error_inside_the_block_still_restores_the_file(staged: tuple[Bench, Path]):
    bench, pricing = staged
    original = pricing.read_bytes()
    with pytest.raises(KeyError), zero_values_in_place(bench.wb, ["src/pytdd/pricing.py"], public=True):
        raise KeyError("boom")
    assert pricing.read_bytes() == original


def test_nothing_to_vary_runs_no_gate(staged: tuple[Bench, Path]):
    bench, _ = staged
    assert zeroed_run(bench.wb, "test-zero", [], public=False) is None
    assert vacuity_check(bench.wb, [], {}).message == ""


def test_stale_bytecode_of_the_original_is_not_served_to_the_variant(staged: tuple[Bench, Path]):
    bench, pricing = staged
    cache = pricing.parent / "__pycache__"
    cache.mkdir(exist_ok=True)
    (cache / "pricing.cpython-312.pyc").write_bytes(b"stale")
    with zero_values_in_place(bench.wb, ["src/pytdd/pricing.py"], public=False):
        assert not list(cache.glob("pricing.*.pyc"))


def test_an_error_raised_by_the_zero_value_is_not_an_assertion(make_bench):
    """`round(None, 2)` and `1 / 0.0` blow up on the zero value without the test ever checking the answer."""
    bench = make_bench([])
    wb = bench.wb
    pricing = wb.worktree / "src/pytdd/pricing.py"
    pricing.write_text(pricing.read_text() + "\n\n" + UNTYPED_STUB)
    (wb.worktree / "tests/test_red.py").write_text(
        f'import pytest\nfrom pytdd.pricing import apply_discount\n\n\n@pytest.mark.l4("{C1}")\n'
        'def test_round_only():\n    round(apply_discount(50.0, "SAVE10"), 2)\n\n\n'
        f'@pytest.mark.l4("{C2}")\ndef test_assertion():\n    assert apply_discount(50.0, "SAVE10") == 45.0\n'
    )
    run_setup(wb)
    result = vacuity_check(
        wb,
        ["src/pytdd/pricing.py"],
        {C1: ["tests.test_red::test_round_only"], C2: ["tests.test_red::test_assertion"]},
    )
    assert set(result.vacuous) == {C1} and set(result.proofs) == {C2}
    assert "fail by assertion" in result.message


def test_a_symlinked_directory_never_lets_the_gate_rewrite_a_file_outside_the_worktree(staged, tmp_path: Path):
    bench, _ = staged
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "mod.py"
    target.write_text("def answer() -> int:\n    return 42\n")
    (bench.wb.worktree / "src/linked").symlink_to(outside, target_is_directory=True)
    with zero_values_in_place(bench.wb, ["src/linked/mod.py"], public=True) as varied:
        assert varied == [] and "42" in target.read_text()
    (bench.wb.worktree / "tests/test_link.py").write_text("from linked.mod import answer\n")
    assert imported_modules(bench.wb, ["tests.test_link::test_x"]) == set()


def test_the_vacuous_message_names_the_remedy_for_a_zero_answer_scenario():
    """Live M1.7 step 3 (job 5498): `Cart().item_count() == 0` is the zero value itself, so its criterion's only test
    passes on the stub. Codex read "a sibling that asserts on a real one" three times as a test of another criterion.
    The message names the criterion, a test that did fail on the zero values, and the two-id marker that fixes it."""
    proved, edge = (
        "tests.test_cart::test_item_count_sums_line_item_quantities",
        "tests.test_cart::test_new_cart_is_zero",
    )
    message = Vacuity(proofs={C2: (proved,)}, vacuous={C1: (edge,)}).message
    assert message.startswith(f"vacuous: {C1} (its tests pass or error against the zero-value stubs: {edge})")
    assert "the zero value itself" in message and "assert a real answer in the same test" in message
    assert f'{proved}: @pytest.mark.l4("{C2}", "{C1}")' in message
    assert "sibling" not in message


def test_with_no_proved_test_the_message_still_says_how_to_prove_a_zero_answer():
    message = Vacuity(vacuous={C1: ("tests.test_red::test_zero_is_the_answer",)}).message
    assert "the zero value itself" in message and "assert a real answer in the same test" in message
    assert "@pytest.mark.l4(" not in message
