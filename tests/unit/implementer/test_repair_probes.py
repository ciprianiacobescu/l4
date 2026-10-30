"""own-test-repair, adversarial review: every probe that got past the first structural check is refused, and the two
consumer repairs stay accepted. Pure (`check_repair`, `encoding_problem`): text in, rules out."""

import pytest

from l4.implementer.repaircheck import check_repair, encoding_problem

BEFORE = """from playwright.sync_api import expect
from app.calc import compute

EXPECTED = 4


def helper(n):
    return compute(n)


def test_other():
    assert all([helper(2) == EXPECTED])
    assert len([1, 2]) == 2


def test_x(page):
    page.goto("/a")
    expect(page.locator("#t")).to_have_text("Hi")
    assert compute(2) == EXPECTED
"""
GOTO = '    page.goto("/a")\n'
EXPECT = 'expect(page.locator("#t")).to_have_text("Hi")\n'
ASSERT = "assert compute(2) == EXPECTED\n"


def rules(after: str, before: str = BEFORE, tests=("test_x",)) -> list[str]:
    return [b.rule for b in check_repair(before, after, tests)]


def edited(old: str, new: str, imports: str = "", text: str = BEFORE) -> str:
    assert old in text, old
    return imports + text.replace(old, new, 1)


PROBES = [
    ("P1 early return replaces setup", edited(GOTO, "    return\n"), "return-added"),
    ("P2 or 1 == 1", edited(ASSERT, "assert compute(2) == EXPECTED or 1 == 1\n"), "constant-operand"),
    ("P2b or -1", edited(ASSERT, "assert compute(2) == EXPECTED or -1\n"), "constant-operand"),
    ("P2c list literal", edited(ASSERT, "assert [compute(2) == EXPECTED]\n"), "assert-constant"),
    ("P2d not None", edited(ASSERT, "assert not None\n"), "assert-constant"),
    (
        "P3 == ANY",
        edited(ASSERT, "assert compute(2) == ANY\n", "from unittest.mock import ANY\n"),
        "import-banned",
    ),
    ("P4 expect without a matcher", edited(EXPECT, "expect(page)\n"), "check-dropped"),
    (
        "P4b short-circuit and",
        edited(EXPECT, 'False and expect(page.locator("#t")).to_have_text("Hi")\n'),
        "conditional-check",
    ),
    (
        "P5 assert inside a nested def never called",
        edited("    " + ASSERT, "    def _never():\n        assert compute(2) == EXPECTED\n"),
        "assert-removed",
    ),
    (
        "P6 check in an empty comprehension",
        edited(EXPECT, '[expect(page.locator("#t")).to_have_text("Hi") for _ in ()]\n'),
        "check-dropped",
    ),
    (
        "P6b check in an uncalled lambda",
        edited(EXPECT, '(lambda: expect(page.locator("#t")).to_have_text("Hi"))\n'),
        "check-dropped",
    ),
    (
        "P7 import shadows the builtins that a frozen test uses",
        edited(
            "EXPECTED = 4\n",
            "EXPECTED = 4\n",
            "from unittest.mock import MagicMock as all\nfrom unittest.mock import MagicMock as len\n",
        ),
        "import-shadows",
    ),
    (
        "P8 rebinding a module constant at runtime",
        edited(GOTO, "    globals().update(EXPECTED=compute(2))\n"),
        "side-effect",
    ),
    (
        "P9 monkeypatching the product at runtime",
        edited(GOTO, "    _calc.compute = lambda n: 4\n", "import app.calc as _calc\n"),
        "side-effect",
    ),
    (
        "P10 product call replaced by the expected value",
        edited(ASSERT, "assert EXPECTED == EXPECTED\n"),
        "assert-constant",
    ),
    (
        "P11 alias import that counts as a check",
        edited(EXPECT, "assert_nothing(page)\n", "from builtins import id as assert_nothing\n"),
        "import-banned",
    ),
    (
        "P12 skip spelled with getattr and __import__",
        edited(GOTO, '    getattr(__import__("pyt" "est"), "sk" "ip")("later")\n'),
        "side-effect",
    ),
    ("P13 raise SkipTest", edited(GOTO, "    raise SkipTest('x')\n", "from unittest import SkipTest\n"), "skip-added"),
]


@pytest.mark.parametrize(("label", "after", "rule"), PROBES, ids=[p[0] for p in PROBES])
def test_the_probe_is_refused(label, after, rule):
    assert rule in rules(after), (label, rules(after))


def test_the_utf7_probe_is_refused_by_the_encoding_rule_and_a_plain_file_is_not():
    hidden = b"# coding: utf-7\n" + BEFORE.encode()
    assert encoding_problem(hidden) is not None and "utf-7" in encoding_problem(hidden)
    for ok in (BEFORE.encode(), b"\xef\xbb\xbf" + BEFORE.encode(), b"# -*- coding: utf-8 -*-\n" + BEFORE.encode()):
        assert encoding_problem(ok) is None
    assert encoding_problem(b"# coding: latin-1\n" + BEFORE.encode()) is not None
    assert encoding_problem(b"# coding: no-such-codec\nx = 1\n") is not None
    assert encoding_problem(b"\xff\xfe\x00") is not None  # not utf-8 text at all


def test_a_duplicated_or_moved_existing_import_is_refused():  # P15
    before = (
        'from app.checks import strict_check\nstrict_check = __import__("functools").partial(strict_check, exact=True)'
        "\n\n\ndef test_x():\n    strict_check(1)\n"
    )
    assert "import-duplicated" in rules(before + "from app.checks import strict_check\n", before)
    moved = before.replace("from app.checks import strict_check\n", "", 1) + "from app.checks import strict_check\n"
    assert rules(moved, before)  # an import after the statement that overrides it: refused (moved or removed)
    assert rules("import os\n" + before, before) == []  # a new import in front is fine


def test_the_two_consumer_repairs_stay_accepted():
    page = (
        "from playwright.sync_api import expect\n\n\ndef test_x(page):\n    page.goto('/a')\n"
        "    expect(page).to_have_url(lambda url: url.endswith('/cart'))\n"
        "    assert page.get_by_role('button', name='Pay').is_visible()\n"
    )
    assert rules(page.replace("expect(page).to_have_url(", "page.wait_for_url("), page) == []
    assert rules(page.replace("name='Pay')", "name='Pay', exact=True)"), page) == []


def test_checks_are_compared_by_name_not_only_by_count():
    swapped = edited(EXPECT, 'expect(page.locator("#t")).to_be_visible()\n')
    assert "check-dropped" in rules(swapped)
    same_kind = edited(EXPECT, 'page.locator("#t").wait_for(state="visible")\n')
    assert "check-dropped" in rules(same_kind)


def test_a_new_import_binding_a_checkish_name_is_refused():
    for name in ("assert_ok", "assertEqual", "expect_it", "wait_for_it", "expectation"):
        after = edited(GOTO, GOTO, f"from os import getcwd as {name}\n")
        assert "import-banned" in rules(after), name


def test_state_changes_outside_the_tests_locals_are_refused_and_local_ones_are_not():
    for statement in (
        "    EXPECTED = 5\n    global EXPECTED\n",
        "    app.calc.compute = None\n",
        "    cache['k'] = 1\n",
        "    monkeypatch.setattr(app.calc, 'compute', None)\n",
        "    exec('x = 1')\n",
        "    importlib.import_module('os')\n",
        "    vars(app)['x'] = 1\n",
        "    nonlocal_thing = 1\n    def inner():\n        nonlocal nonlocal_thing\n        nonlocal_thing = 2\n",
    ):
        assert "side-effect" in rules(edited(GOTO, statement)), statement
    assert rules(edited(GOTO, "    local = {}\n    local['k'] = 1\n    page.timeout = 5\n")) != ["side-effect"]
    assert "side-effect" not in rules(edited(GOTO, "    local = {}\n    local['k'] = 1\n    page.timeout = 5\n"))


def test_a_return_yield_or_await_added_is_refused():
    assert "return-added" in rules(edited(GOTO, "    yield\n"))
    assert "return-added" in rules(edited(EXPECT, "return\n"))


def test_a_check_in_a_boolean_or_conditional_expression_is_refused():
    for text in (
        'page and expect(page.locator("#t")).to_have_text("Hi")\n',
        'expect(page.locator("#t")).to_have_text("Hi") if page else None\n',
        '(x := expect(page.locator("#t")).to_have_text("Hi"))\n',
    ):
        assert "conditional-check" in rules(edited(EXPECT, text)), text


def test_an_operand_with_no_name_call_or_attribute_is_refused():
    for operand in ("1 == 1", "-1", "True", "'x'", "None is None"):
        assert "constant-operand" in rules(edited(ASSERT, f"assert compute(2) == EXPECTED or {operand}\n")), operand
    assert rules(edited(ASSERT, "assert compute(2) == EXPECTED or compute(3) == EXPECTED\n")) == []


def test_the_builtins_cannot_be_shadowed_by_an_import():
    for builtin in ("any", "isinstance", "print", "range"):
        assert "import-shadows" in rules(edited(GOTO, GOTO, f"from os import getcwd as {builtin}\n")), builtin


def test_checks_in_a_nested_scope_do_not_count_for_the_function_and_may_not_go():
    nested = BEFORE.replace(GOTO, "    def inner():\n        assert page\n    inner()\n")
    dropped = nested.replace("        assert page\n", "        pass\n")
    assert "check-dropped" in rules(dropped, nested)
    assert rules(nested, nested) == []


def test_existing_imports_cannot_be_reordered():
    before = "import os\nimport re\n\n\ndef test_x():\n    assert os.sep and re.I\n"
    swapped = "import re\nimport os\n\n\ndef test_x():\n    assert os.sep and re.I\n"
    assert rules(swapped, before) != []
    assert rules("import sys\n" + before, before) == []
