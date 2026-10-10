"""Kiro e2e H1 re-run (task 2.2): on a case-insensitive filesystem (macOS) the pre-satisfied confirmation zeroed
`src/pricing/cart.py` twice, once as `Cart.py` (from `from pricing import Cart`) and once as `cart.py`, and left it
zeroed; the production guard then blamed the agent's tests ("test code changed production files while a gate ran")."""

import os

from l4.implementer.discrimination import imported_modules, red_code_in_place, zero_values_in_place
from l4.implementer.tdd import run_setup

from .conftest import Bench

TEST = "from pytdd import Pricing, total\n\n\ndef test_total_adds():\n    assert total([1.0, 2.0]) == 3.0\n"


def test_a_class_name_is_not_resolved_to_a_module_whose_name_differs_only_in_case(make_bench):
    bench: Bench = make_bench([])
    (bench.wb.worktree / "tests/test_alias.py").write_text(TEST)
    modules = imported_modules(bench.wb, ["tests.test_alias::test_total_adds"])
    assert modules == {"src/pytdd/__init__.py", "src/pytdd/pricing.py"}  # `Pricing` is a name: no `Pricing.py`


def test_zero_values_in_place_restores_a_file_named_twice(make_bench):
    """Two names of one file (a hard link here; `Cart.py` and `cart.py` on a case-insensitive filesystem)."""
    bench: Bench = make_bench([])
    wb = bench.wb
    run_setup(wb)
    pricing = wb.worktree / "src/pytdd/pricing.py"
    alias = wb.worktree / "src/pytdd/pricing_alias.py"
    os.link(pricing, alias)
    before = pricing.read_bytes()
    with zero_values_in_place(wb, ["src/pytdd/pricing.py", "src/pytdd/pricing_alias.py"], public=True) as varied:
        assert len(varied) == 1  # one file, varied once
        assert pricing.read_bytes() != before
    assert pricing.read_bytes() == before and alias.read_bytes() == before


def test_red_code_in_place_restores_a_file_named_twice(make_bench):
    bench: Bench = make_bench([])
    wb = bench.wb
    pricing = wb.worktree / "src/pytdd/pricing.py"
    alias = wb.worktree / "src/pytdd/pricing_alias.py"
    red = wb.head()
    pricing.write_text(pricing.read_text() + "\n\ndef extra() -> int:\n    return 1\n")
    os.link(pricing, alias)
    changed = pricing.read_bytes()
    with red_code_in_place(wb, red, ["src/pytdd/pricing.py", "src/pytdd/pricing_alias.py"]):
        assert pricing.read_bytes() != changed
    assert pricing.read_bytes() == changed and alias.read_bytes() == changed
