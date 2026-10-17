"""detect-test-tamper 1.1 (L4-IMP-045, L4-IMP-046, L4-IMP-047): the pure comparison of a pre-existing test, per test on
the AST, by file and qualified name."""

from pathlib import Path

import pytest

from l4.implementer import tamper
from l4.implementer.tamper import compare, facts_of, moved, names_test_id

PATH = "tests/test_pricing.py"
BASE = (Path(__file__).parents[2] / "fixtures/py_tdd/tests/test_pricing.py").read_text()
WEAKENED = (
    "from pytdd import total\n\n\ndef test_total_adds_prices():\n    assert True\n\n\n"
    "def test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"
)
REBOUND_SUFFIX = "\n\ndef test_total_adds_prices():\n    pass\n"
BODY_WHY = "its body, decorators or parametrisation changed"


def kinds(before, after, path=PATH):
    return {(t.name, t.kind): t.why for t in compare(path, before, after)}


def test_the_fixture_base_is_what_the_reproduction_weakens():
    assert "assert total([1.25, 2.5]) == 3.75" in BASE


def test_a_weakened_assertion_is_a_changed_test():  # SCN-IMP-260
    assert kinds(BASE, WEAKENED) == {("test_total_adds_prices", "changed"): BODY_WHY}


def test_a_second_definition_is_a_rebinding_that_names_its_line():  # SCN-IMP-261
    after = BASE + REBOUND_SUFFIX
    line = after.splitlines().index("def test_total_adds_prices():", 8) + 1
    assert kinds(BASE, after) == {
        ("test_total_adds_prices", "rebound"): f"its name is bound again at line {line}, which replaces it"
    }


@pytest.mark.parametrize(
    "suffix",
    [
        "\ntest_total_adds_prices = lambda: None\n",
        "\nfrom helpers import test_total_adds_prices\n",
        "\ndel test_total_adds_prices\n",
    ],
)
def test_an_assignment_an_import_or_a_del_that_binds_the_name_is_a_rebinding(suffix):  # SCN-IMP-262
    found = {t.name: t.kind for t in compare(PATH, BASE, BASE + suffix)}
    assert found["test_total_adds_prices"] == "rebound"  # a `del` is also a statement that reaches every test (D12)


PARAM = (
    "import pytest\n\n\n@pytest.mark.parametrize('n', [1, 2, 3])\ndef test_n(n):\n    assert n\n\n\n"
    "def test_plain(tmp_path):\n    assert tmp_path\n\n\ndef test_marked():\n    assert 1\n"
)


def test_a_dropped_case_a_new_decorator_and_a_renamed_fixture_are_changes():  # SCN-IMP-263
    after = (
        "import pytest\n\n\n@pytest.mark.parametrize('n', [1, 2])\ndef test_n(n):\n    assert n\n\n\n"
        "def test_plain(tmp_dir):\n    assert tmp_dir\n\n\n@pytest.mark.slow\ndef test_marked():\n    assert 1\n"
    )
    assert kinds(PARAM, after) == {
        ("test_n", "changed"): BODY_WHY,
        ("test_plain", "changed"): BODY_WHY,
        ("test_marked", "changed"): BODY_WHY,
    }


HELPERS = (
    "EXPECTED = 3\n\n\ndef _check(value):\n    assert value == EXPECTED\n\n\n"
    "def test_uses_both():\n    _check(3)\n\n\ndef test_alone():\n    assert 1\n"
)


def test_a_helper_and_a_constant_the_test_uses_are_part_of_it():  # SCN-IMP-264
    weak_helper = HELPERS.replace("    assert value == EXPECTED\n", "    return\n")
    assert kinds(HELPERS, weak_helper) == {("test_uses_both", "changed"): "what it uses in this file changed: _check"}
    other = HELPERS.replace("EXPECTED = 3", "EXPECTED = 4")
    assert kinds(HELPERS, other) == {("test_uses_both", "changed"): "what it uses in this file changed: EXPECTED"}


def test_an_autouse_fixture_and_a_module_mark_reach_every_test_of_the_file():  # SCN-IMP-265
    fixture = "\n\n@pytest.fixture(autouse=True)\ndef _everywhere():\n    yield\n"
    before = "import pytest\n\n\ndef test_a():\n    assert 1\n\n\ndef test_b():\n    assert 1\n"
    got = kinds(before, before + fixture)
    assert got == {
        ("test_a", "changed"): "what it uses in this file changed: _everywhere",
        ("test_b", "changed"): "what it uses in this file changed: _everywhere",
    }
    marked = kinds(before, before + "\npytestmark = pytest.mark.usefixtures('x')\n")
    assert marked == {
        ("test_a", "changed"): "what it uses in this file changed: pytestmark",
        ("test_b", "changed"): "what it uses in this file changed: pytestmark",
    }


def test_a_fixture_only_a_new_test_requests_changes_nothing():  # SCN-IMP-265
    before = "import pytest\n\n\ndef test_a():\n    assert 1\n"
    extra = "\n\n@pytest.fixture\ndef fresh():\n    return 1\n\n\ndef test_new(fresh):\n    assert fresh\n"
    assert compare(PATH, before, before + extra) == []
    explicit_false = "\n\n@pytest.fixture(autouse=False)\ndef fresh():\n    return 1\n"
    assert compare(PATH, before, before + explicit_false) == []


def test_a_fixture_override_of_a_requested_fixture_is_a_change():
    before = "import pytest\n\n\n@pytest.fixture\ndef rows():\n    return [1]\n\n\ndef test_a(rows):\n    assert rows\n"
    after = before.replace("return [1]", "return []")
    assert kinds(before, after) == {("test_a", "changed"): "what it uses in this file changed: rows"}


def test_all_the_allowed_edits_together_change_nothing():  # SCN-IMP-266
    after = (
        "import pytest\n\n# a comment\nimport pytest\nfrom pytdd import apply_discount, total\n\n\n"
        "def test_total_adds_prices():\n    assert total([1.25, 2.5]) == 3.75  # note\n\n\n"
        "def test_total_of_nothing_is_zero():\n    assert total([]) == 0\n\n\n"
        "def test_new_one():\n    assert apply_discount(10.0, 'X') == 9.0\n\n\n"
        "class TestNew:\n    def test_two(self):\n        assert 2\n\n"
    )
    assert compare(PATH, BASE, after) == []


def test_a_trailing_newline_is_no_tamper():  # SCN-IMP-266 and SCN-IMP-46
    old = "def test_slug():\n    assert 1\n"
    assert compare(PATH, old, old + "\n\n") == []
    assert compare(PATH, old.rstrip("\n"), old) == []


CART = (
    "import pytest\n\n\nclass TestCart:\n    def setup_method(self):\n        self.items = []\n\n"
    "    def test_empty(self):\n        assert self.items == []\n\n\ndef test_outside():\n    assert 1\n"
)


def test_a_methods_class_is_part_of_it():  # SCN-IMP-267
    setup = CART.replace("self.items = []", "self.items = [1]")
    assert kinds(CART, setup) == {
        ("TestCart.test_empty", "changed"): "what it uses in this file changed: TestCart.setup_method"
    }
    decorated = CART.replace("class TestCart:", "@pytest.mark.skip\nclass TestCart:")
    assert [t.name for t in compare(PATH, CART, decorated)] == ["TestCart.test_empty"]
    assert (
        compare(
            PATH,
            CART,
            CART.replace("\n\ndef test_outside", "\n    def test_added(self):\n        assert 2\n\n\ndef test_outside"),
        )
        == []
    )


def test_a_syntax_error_makes_every_old_test_unparsable():  # SCN-IMP-268
    got = kinds(BASE, "def test_total_adds_prices(:\n")
    assert got == {
        ("test_total_adds_prices", "unparsable"): "the file does not parse",
        ("test_total_of_nothing_is_zero", "unparsable"): "the file does not parse",
    }


def test_a_before_that_does_not_parse_has_no_test_to_protect():  # SCN-IMP-268
    assert compare(PATH, "def test_x(:\n", BASE) == []
    assert compare(PATH, "", BASE) == []


def test_a_deleted_file_deletes_every_test():
    assert kinds(BASE, None) == {
        ("test_total_adds_prices", "deleted"): "it was deleted",
        ("test_total_of_nothing_is_zero", "deleted"): "it was deleted",
    }


def test_a_deleted_test_is_deleted_in_a_file_that_remains():
    after = BASE.split("\n\n\ndef test_total_of_nothing_is_zero")[0] + "\n"
    assert kinds(BASE, after) == {("test_total_of_nothing_is_zero", "deleted"): "it was deleted"}


def test_the_same_name_in_another_file_is_not_this_test():
    # identity is the file and the qualified name, never the bare name
    assert [
        t.kind for t in compare("tests/test_a.py", "def test_x():\n    assert 1\n", "def test_y():\n    assert 1\n")
    ] == ["deleted"]


def digests(path, source):
    return {(path, n): f.definition for n, f in tamper.facts_of(source).items()}


def test_a_test_moved_unchanged_to_another_file_is_moved():  # SCN-IMP-269
    one = "@pytest.mark.slow\ndef test_one():\n    assert 1\n"
    old, new = digests("tests/test_a.py", one), digests("tests/test_b.py", one)
    assert moved(old, new) == {("tests/test_a.py", "test_one")}


def test_a_same_named_test_with_another_body_is_no_move():  # SCN-IMP-270
    old = digests("tests/test_cart.py", "def test_empty():\n    assert compute([]) == 0\n")
    new = digests("tests/test_orders.py", "def test_empty():\n    assert True\n")
    assert moved(old, new) == set()


def test_one_added_test_stands_for_one_deleted_test_only():  # SCN-IMP-270
    same = "def test_dup():\n    assert 1\n"
    old = {**digests("tests/test_a.py", same), **digests("tests/test_b.py", same)}
    new = digests("tests/test_c.py", same)
    assert moved(old, new) == {("tests/test_a.py", "test_dup")}


def test_a_test_moved_into_a_class_is_not_moved():  # SCN-IMP-269 as amended: the class is part of a method's definition
    old = digests("tests/test_a.py", "def test_one(self):\n    assert 1\n")
    new = digests("tests/test_a.py", "class TestOne:\n    def test_one(self):\n        assert 1\n")
    assert moved({("tests/test_a.py", "test_one"): old[("tests/test_a.py", "test_one")]}, new) == set()


@pytest.mark.parametrize(
    ("test_id", "path", "name", "expected"),
    [
        ("tests.test_long::test_long", "tests/test_long.py", "test_long", True),
        ("tests.test_long::test_long[case-1]", "tests/test_long.py", "test_long", True),
        ("tests.test_long.TestLong::test_long", "tests/test_long.py", "TestLong.test_long", True),
        ("tests.test_long::test_long", "tests/test_other.py", "test_long", False),
        ("tests.test_long::test_long", "tests/test_long.py", "test_short", False),
    ],
)
def test_names_test_id(test_id, path, name, expected):
    assert names_test_id(test_id, path, name) is expected


def test_no_public_name_of_the_module_starts_with_test():
    assert not [n for n in vars(tamper) if not n.startswith("_") and n.lower().startswith("test")]


# --- the review's false positives and a weak move (8.1, design D12) -------------------------------------------------

GEN = (
    "import pytest\n\nfrom shop import cart_total\n\n\ndef test_sum_of_lines():\n    lines = [(2, 1.5), (1, 3.0)]\n"
    "    assert cart_total(lines) == sum(q * p for q, p in lines)\n"
)
HOOK = (
    "from shop import apply\n\n\ndef test_apply_calls_hook():\n    seen = []\n"
    "    apply(hook=lambda code: seen.append(code))\n    assert seen\n"
)


def test_a_comprehension_variable_and_a_lambda_parameter_are_not_module_reads():  # SCN-IMP-266
    new_p = (
        GEN
        + "\n\np = pytest.param\n\n\n@pytest.mark.parametrize('code', ['A'])\ndef test_new(code):\n    assert code\n"
    )
    assert compare("tests/test_cart.py", GEN, new_p) == []
    new_code = (
        HOOK
        + "\n\nimport pytest\n\n\n@pytest.fixture\ndef code():\n    return 'SAVE10'\n\n\n"
        + "def test_new(code):\n    assert apply(code=code)\n"
    )
    assert compare("tests/test_cart.py", HOOK, new_code) == []


def test_a_name_a_test_really_reads_is_still_a_read():  # SCN-IMP-266 control
    reads = "LIMIT = 1\n\n\ndef test_a():\n    assert LIMIT\n"
    assert [t.name for t in compare("t.py", reads, reads.replace("LIMIT = 1", "LIMIT = 0"))] == ["test_a"]


def test_a_re_indented_docstring_is_no_change_and_a_new_word_is():  # SCN-IMP-266
    root = Path(__file__).parents[2] / "fixtures" / "py_tdd" / "tests"
    before = "\n".join(
        [
            "from pytdd import total",
            "",
            "",
            "def test_total_adds_prices():",
            "    '''   Adds the prices.   ",
            "    ",
            "\tIt rounds to cents.    '''",
            "    assert total([1.25, 2.5]) == 3.75",
            "",
        ]
    )
    after = (
        'from pytdd import total\n\n\ndef test_total_adds_prices():\n    """Adds the prices.\n\n'
        '    It rounds to cents."""\n    assert total([1.25, 2.5]) == 3.75\n'
    )
    assert compare("tests/test_pricing.py", before, after) == []
    assert [t.kind for t in compare("tests/test_pricing.py", before, after.replace("rounds", "floors"))] == ["changed"]
    assert root.is_dir()


def test_a_class_wrapper_around_the_same_body_stays_a_deletion():  # SCN-IMP-266 (the probe's refactor)
    found = compare(
        "t.py", "def test_one():\n    assert 1\n", "class TestOne:\n    def test_one(self):\n        assert 1\n"
    )
    assert [(t.name, t.kind) for t in found] == [("test_one", "deleted")]


def test_a_test_moved_next_to_a_weakened_helper_is_not_moved():  # SCN-IMP-270
    a = "def _check(v):\n    assert v == 3\n\n\ndef test_one():\n    _check(1 + 2)\n"
    b = "def _check(v):\n    return None\n\n\ndef test_one():\n    _check(1 + 2)\n"
    gone = {
        ("tests/test_a.py", t.name): (facts_of(a)[t.name].definition, facts_of(a)[t.name].closure)
        for t in compare("tests/test_a.py", a, None)
    }
    added = {("tests/test_b.py", n): (f.definition, f.closure) for n, f in facts_of(b).items() if f.test}
    assert moved(gone, added) == set()
    same = {("tests/test_b.py", n): (f.definition, f.closure) for n, f in facts_of(a).items() if f.test}
    assert moved(gone, same) == {("tests/test_a.py", "test_one")}
