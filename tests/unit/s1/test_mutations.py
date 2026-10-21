import ast

from l4.s1 import mutations as m

TESTS = """import pytest
from shop.cart import cart_total


def test_a():
    assert cart_total([], None, 0) == 0


class TestK:
    @pytest.mark.parametrize("n", [1])
    def test_m(self, n):
        assert n == 1
        assert cart_total([(5, 2)], None, 0) == 10
"""


def test_pick_is_stable_and_bounded():
    assert m.pick(1, 5, "u", "x") == m.pick(1, 5, "u", "x")
    assert {m.pick(s, 3, "u") for s in range(40)} == {0, 1, 2}
    assert m.pick(1, 0, "u") == 0


def test_untested_function_and_template_edit_append_valid_code():
    text, name = m.add_untested_function("def f():\n    return 1", 2)
    assert ast.parse(text) and f"def {name}(" in text and "value + 3" not in text
    assert not m.LEAK.search(name) and name.isidentifier()
    edited = m.add_template_edit("X = 1\n", 0)
    assert ast.parse(edited) and not m.LEAK.search(edited)


def test_generated_names_come_from_the_files_vocabulary_and_never_collide():
    src = "def cart_total(items):\n    return 0\n\n\ndef add_tax(x):\n    return x\n"
    names = {m.add_untested_function(src, v)[1] for v in range(6)}
    words = {"cart", "total", "items", "add", "tax", "2", "3", "4", "5", "6", "7"}
    assert len(names) > 1 and all(set(n.split("_")) <= words for n in names)
    assert all(not m.LEAK.search(m.add_untested_function(src, v)[0].split("return 0")[-1]) for v in range(6))
    taken = "def cart_cart(): pass\n"
    for v in range(8):
        assert m.add_untested_function(taken, v)[1] != "cart_cart"


def test_remove_or_skip_tests_handles_classes_decorators_and_imports():
    deleted = m.remove_or_skip_tests(TESTS, [("TestK", "test_m")], skip=False)
    assert deleted is not None and "test_m" not in deleted and "parametrize" not in deleted and "def test_a" in deleted
    ast.parse(deleted)
    skipped = m.remove_or_skip_tests(TESTS, [(None, "test_a")], skip=True)
    assert skipped is not None and "    @pytest.mark.skip" not in skipped and "@pytest.mark.skip(reason=" in skipped
    assert not m.LEAK.search(skipped.split("def test_a")[0])
    ast.parse(skipped)
    nested = m.remove_or_skip_tests(TESTS, [("TestK", "test_m")], skip=True)
    assert nested is not None and "    @pytest.mark.skip(reason=" in nested and "    @pytest.mark.parametrize" in nested
    bare = m.remove_or_skip_tests("def test_a():\n    assert 1\n", [(None, "test_a")], skip=True)
    assert bare is not None and bare.startswith("import pytest\n")
    assert m.remove_or_skip_tests(TESTS, [(None, "test_zzz")], skip=True) is None
    assert m.remove_or_skip_tests("def (", [(None, "t")], skip=True) is None


def test_flip_expected_literal_changes_exactly_one_integer_equality():
    first = m.flip_expected_literal(TESTS, 0)
    second = m.flip_expected_literal(TESTS, 1)
    assert first is not None and second is not None and first != second != TESTS
    assert "== 1\n" in first and first.count("== 0") == 0  # the first assert's 0 became 1
    assert m.flip_expected_literal(TESTS, 0, only_in=["test_zzz"]) is None
    assert m.flip_expected_literal("def test_a():\n    assert x == 'a'\n", 0) is None


def test_top_level_block_renames_only_on_a_collision_and_refuses_what_is_not_a_definition():
    src = "import os\n\n@dec\ndef shipping(x):\n    return x\n\nVALUE = 3\n"
    assert m.top_level_block(src, (3, 5)) == "@dec\ndef shipping(x):\n    return x"
    block = m.top_level_block(src, (3, 5), "def shipping(): pass\n", 4)
    assert block == "@dec\ndef shipping_6(x):\n    return x"
    assert m.top_level_block(src, (7, 7), 0) is None
    assert m.top_level_block(src, (4, 4), 0) is None  # not parseable on its own


def test_a_test_with_no_integer_equality_can_still_be_made_to_error_or_skip():
    src = (
        "from shop.cart import cart_total\n\n\ndef test_a():\n    assert cart_total([]) is None\n\n\n"
        "class TestK:\n    def test_m(self):\n        assert True\n"
    )
    assert m.flip_expected_literal(src, 0) is None
    errored = m.add_missing_fixture(src, 0)
    assert errored is not None and ast.parse(errored) and "def test_a(" in errored and "test_a()" not in errored
    methods = m.add_missing_fixture(src, 1)
    assert methods is not None and "def test_m(self, " in methods
    assert not m.LEAK.search(errored)
    skipped = m.skip_a_test(src, 1)
    assert skipped is not None and ast.parse(skipped) and "    @pytest.mark.skip(reason=" in skipped
    assert m.add_missing_fixture("def helper():\n    pass\n", 0) is None and m.skip_a_test("x = 1", 0) is None


def test_add_passing_test_appends_a_test_that_parses_and_carries_no_marker():
    new = m.add_passing_test(TESTS, 0)
    assert new is not None and ast.parse(new) and new.startswith(TESTS.rstrip("\n"))
    added = [n.name for n in ast.parse(new).body if isinstance(n, ast.FunctionDef)]
    assert len(added) == 2 and added[0] == "test_a" and added[1].startswith("test_") and not m.LEAK.search(added[1])
    assert m.add_passing_test(TESTS, 1) != new  # another variant, another test
    assert m.add_passing_test("VALUE = 1\n", 0) is None  # a helper module, not a test file
    assert m.add_passing_test("def test_(:\n", 0) is None


def _generated(src: str, variants: range = range(12)) -> list[str]:
    """The appended `def` line and body of each variant."""
    out = []
    for v in variants:
        text, name = m.add_untested_function(src, v)
        tree = ast.parse(text)
        assert tree.body[-1].name == name  # type: ignore[union-attr]
        out.append(text[len(src) :])
    return out


def test_untested_function_signature_is_drawn_from_the_files_own_functions():
    src = (
        "def price(amount: Decimal, rate: float) -> Decimal:\n    return amount\n\n\n"
        "def tax(base: int) -> str:\n    return ''\n"
    )
    heads = {"def {}(amount: Decimal, rate: float) -> Decimal:", "def {}(base: int) -> str:"}
    seen = set()
    for v in range(12):
        text, name = m.add_untested_function(src, v)
        seen.add(next(h for h in heads if h.format(name) in text))
    assert seen == heads  # both signatures are drawn across variants, none is invented
    assert not any("value" in g or "-> int" in g for g in _generated(src))


def test_no_fixed_token_marks_the_untested_function_template():
    sources = [
        "def f():\n    return 1\n",
        "X = 1\n",
        "def cart_total(items, discount=None):\n    return 0\n\n\nclass Cart:\n    def add(self, sku, qty): ...\n",
        "def price(amount: float) -> float:\n    return amount\n",
    ]
    generated = [g for src in sources for g in _generated(src, range(16))]
    assert len({g.split("(", 1)[1].split(")")[0] for g in generated}) > 3
    for token in ("value", "int", "-> int", "value: int"):
        assert not all(token in g for g in generated), token  # no token is in every generated function
    for src in sources:
        heads = {g.split("\n")[2].split("(", 1)[1] for g in _generated(src, range(16))}
        assert len(heads) > 1 or src.startswith("def price"), src
    assert all(not m.LEAK.search(g) for g in generated)
    bare = _generated("X = 1\n", range(16))  # no functions of its own: names from its vocabulary, seeded types
    assert not all(" value" in g.split("\n")[2] or "(value" in g.split("\n")[2] for g in bare)
    assert len({g.split("\n")[2] for g in bare}) > 3
