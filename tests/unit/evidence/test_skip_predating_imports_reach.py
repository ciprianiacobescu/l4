# ruff: noqa: E501  # the sources of the cases are strings that are kept on one line each
"""Rule (e) of the skip rule, rework 10 (skipped-test-hold D1 (e), L4-VER-092): the gaps a review of rework 9 found.

G1 an added import is allowed only from the standard library and takes no name a runner reads by convention, no
parameter name, no fixture name and no word that a string of the base spells; G2 the tests that a skip reaches are
reached transitively; G3 the decorators of any collected test differ between the sides only by a `pytest.mark.<name>`
that is not `skip`, `skipif`, `xfail`, `usefixtures` or `parametrize`; G4 a test that mentions `getfixturevalue`
anywhere has no free line; G5 a `raise` or a skip exception form ends the free body as a skip does."""

import pytest

from l4.config.schema import L4Config
from l4.evidence.skippred import SkipRule

CFG = L4Config.model_validate({})


def holds(base: str, head: str, q: str = "test_t") -> bool:
    return SkipRule(base, head, [], CFG).no_skip_added(q)


BASE = (
    "import os\nimport pytest\n\n\n"
    '@pytest.mark.skipif(os.environ.get("X") is None, reason="r")\ndef test_t():\n    assert 1\n'
)


def with_import(line: str, base: str = BASE) -> str:
    return base.replace("import os\n", f"import os\n{line}\n", 1)


# --- G1: an added import ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "from skipmod import pytestmark",  # review rows: a module outside the standard library
        "from helpers import autouse_net",
        "from m import setup_module",
        "from helpers import pytest_generate_tests",
        "from helpers import setup_function",
        "from helpers import load_tests",
        "from helpers import db",
        "import env_setter",
        "import numpy",
        "import numpy.linalg",
        "from . import helpers",  # a relative import is never allowed
        "from .helpers import thing",
        "from .. import thing",
    ],
)
def test_an_added_import_that_is_not_from_the_standard_library_is_not_a_hold(line):
    assert not holds(BASE, with_import(line))


@pytest.mark.parametrize(
    "name",
    [
        "pytestmark",
        "setup_module",
        "teardown_module",
        "setup_function",
        "teardown_function",
        "setUpModule",
        "tearDownModule",
        "load_tests",
        "pytest_generate_tests",
        "pytest_plugins",
        "test_helper",
        "testing",
        "TestHelper",
        "Testbed",
    ],
)
def test_a_name_that_a_runner_reads_off_a_module_is_not_free_even_from_the_standard_library(name):
    assert not holds(BASE, with_import(f"from json import load as {name}"))


def test_a_fresh_standard_library_import_is_a_hold():
    """The real-world control: `import json` and a few more."""
    for line in ("import json", "import json as j", "from json import loads", "from os import path as p2"):
        assert holds(BASE, with_import(line)), line
    assert holds(BASE, with_import("import json\nimport re"))


def test_a_standard_library_import_that_binds_the_name_of_a_parameter_is_not_a_hold():
    base = "import pytest\n\n\ndef test_t(db):\n    assert db\n"
    head = base.replace("import pytest\n", "import pytest\nfrom json import load as db\n")
    assert not holds(base, head)


def test_a_standard_library_import_that_binds_the_name_of_a_fixture_is_not_a_hold():
    base = (
        "import pytest\n\n\n@pytest.fixture(name='res')\ndef make():\n    pytest.skip('r')\n\n\n"
        "def test_t(res):\n    assert res\n"
    )
    head = base.replace("import pytest\n", "import pytest\nfrom json import load as res\n")
    assert not holds(base, head)


@pytest.mark.parametrize(
    "decorator, body",
    [
        ('@pytest.mark.usefixtures("db")', "pass"),
        ("", 'request.getfixturevalue("db")'),
        ('@pytest.mark.dependency(depends=["db"])', "pass"),
    ],
)
def test_a_standard_library_import_that_binds_a_word_a_string_of_the_base_spells_is_not_a_hold(decorator, body):
    """`usefixtures("db")`, `getfixturevalue("db")`, `depends=["db"]`: the word names a fixture or a test."""
    base = f"import pytest\n\n\n{decorator}\ndef test_t(request):\n    {body}\n"
    head = base.replace("import pytest\n", "import pytest\nfrom json import load as db\n")
    assert not holds(base, head)


def test_a_standard_library_import_of_a_name_a_string_condition_spells_is_not_a_hold():
    base = (
        'import sys\nimport pytest\n\n\n@pytest.mark.skipif("json" not in sys.modules, reason="r")\n'
        "def test_t():\n    assert 1\n"
    )
    assert not holds(base, base.replace("import sys\n", "import sys\nimport json\n"))


# --- G2: the tests that a skip reaches are reached transitively ----------------------------------------------------

TWO_HOPS = """\
import pytest


class TestK:
    def test_inner(self):
        return {inner}

    def test_mid(self):
        return self.test_inner()

    def test_t(self):
        if self.test_mid():
            pytest.skip("x")
        assert 1
"""


def test_a_test_two_calls_away_from_the_skip_is_not_free():
    assert not holds(TWO_HOPS.format(inner="True"), TWO_HOPS.format(inner="False"), "TestK.test_t")


def test_a_test_two_calls_away_through_a_helper_is_not_free():
    helper = (
        "import pytest\n\n\nclass TestK:\n    def helper(self):\n        return self.test_mid()\n\n"
        "    def test_inner(self):\n        return {inner}\n\n    def test_mid(self):\n        return self.test_inner()\n\n"
        "    def test_t(self):\n        if self.helper():\n            pytest.skip('x')\n        assert 1\n"
    )
    assert not holds(helper.format(inner="True"), helper.format(inner="False"), "TestK.test_t")


def test_a_test_three_calls_away_is_not_free():
    source = (
        "import pytest\n\n\ndef test_c():\n    return {value}\n\n\ndef test_b():\n    return test_c()\n\n\n"
        "def test_a():\n    return test_b()\n\n\n@pytest.mark.skipif(test_a(), reason='r')\ndef test_t():\n    assert 1\n"
    )
    assert not holds(source.format(value="True"), source.format(value="False"))


def test_a_test_that_nothing_reaches_is_still_free():
    source = TWO_HOPS.format(inner="True") + "\n    def test_free(self):\n        assert {n}\n"
    assert holds(source.format(n=1), source.format(n=2), "TestK.test_t")


# --- G3: the decorators of a collected test -----------------------------------------------------------------------

SPLIT = (
    "import pytest\n\n\n@pytest.mark.skipif(True, reason='r')\ndef test_t():\n    assert 1\n\n\n{decorators}def test_o():\n"
    "    assert 1\n"
)


def one(decorators: str) -> str:
    return SPLIT.format(decorators=decorators)


@pytest.mark.parametrize(
    "decorator",
    [
        "@pytest.mark.slow",
        "@pytest.mark.slow()",
        '@pytest.mark.slow(reason="x")',
        "@pytest.mark.timeout(30)",
    ],
)
def test_a_mark_that_is_not_a_skip_form_may_be_added_to_or_removed_from_a_test(decorator):
    assert holds(one(""), one(decorator + "\n"))
    assert holds(one(decorator + "\n"), one(""))
    assert holds(one(decorator + "\n"), one("@pytest.mark.other\n"))


@pytest.mark.parametrize(
    "decorator",
    [
        "@pytest.mark.skip",
        '@pytest.mark.skip(reason="x")',
        "@pytest.mark.skipif(True, reason='x')",
        "@pytest.mark.xfail",
        "@pytest.mark.usefixtures('a')",
        "@pytest.mark.parametrize('a', [1])",
        "@retry",
        "@mock.patch('x')",
        "@functools.wraps(f)",
        "@pytest.fixture",
        "@fx(name='res')",
        "@slow",
    ],
)
def test_any_other_decorator_difference_of_another_test_is_not_a_hold(decorator):
    assert not holds(one(""), one(decorator + "\n"))
    assert not holds(one(decorator + "\n"), one(""))


def test_a_decorator_replaced_by_another_one_is_not_a_hold():
    assert not holds(one("@retry\n"), one("@retry2\n"))
    assert not holds(one("@pytest.mark.slow\n@retry\n"), one("@pytest.mark.slow\n"))


def test_a_new_test_takes_only_marks_that_are_not_a_skip_form():
    fixture = (
        "import pytest\n\nfx = pytest.fixture\n\n\n@pytest.fixture\ndef res():\n    return 1\n\n\n"
        "@pytest.mark.skipif(True, reason='r')\ndef test_t(res):\n    assert 1\n"
    )
    assert not holds(fixture, fixture + "\n\n@fx(name='res')\ndef test_new():\n    pytest.skip('x')\n")
    partial = fixture.replace("fx = pytest.fixture", "import functools\n\nfx = functools.partial(pytest.fixture)")
    assert not holds(partial, partial + "\n\n@fx(name='res')\ndef test_new():\n    pytest.skip('x')\n")
    assert not holds(fixture, fixture + "\n\n@pytest.fixture(name='res')\ndef test_new():\n    pytest.skip('x')\n")
    assert holds(fixture, fixture + "\n\n@pytest.mark.slow\ndef test_new():\n    assert 1\n")
    assert holds(fixture, fixture + "\n\ndef test_new():\n    assert 1\n")


def test_a_deleted_test_with_another_decorator_is_not_a_hold():
    head = one("").split("\n\n\ndef test_o")[0] + "\n"  # the head has no test_o
    assert holds(one("@pytest.mark.slow\n"), head)
    assert not holds(one("@retry\n"), head)


def test_the_decorators_of_a_method_of_a_class_are_compared_the_same_way():
    source = (
        "import pytest\n\n\nclass TestK:\n    @pytest.mark.skipif(True, reason='r')\n    def test_t(self):\n        assert 1\n\n"
        "{decorators}    def test_o(self):\n        assert 1\n"
    )
    assert holds(source.format(decorators=""), source.format(decorators="    @pytest.mark.slow\n"), "TestK.test_t")
    assert not holds(source.format(decorators=""), source.format(decorators="    @retry\n"), "TestK.test_t")


# --- G4: a test that mentions getfixturevalue has no free line ------------------------------------------------------

FIXTURE = (
    "import pytest\n\n\n@pytest.fixture\ndef a():\n    pytest.skip('r')\n\n\n@pytest.fixture\ndef b():\n    pass\n\n\n"
    "def test_t(request):\n{body}\n"
)


@pytest.mark.parametrize(
    "first, second",
    [
        (
            "    get = request.getfixturevalue\n    get('a')\n    assert 1",
            "    get = request.getfixturevalue\n    get('b')\n    assert 1",
        ),
        (
            "    get = request.getfixturevalue\n    get('a')\n    assert 1",
            "    get = request.getfixturevalue\n    get('a')\n    assert 2",
        ),
        ("    request.getfixturevalue('a')\n    assert 1", "    request.getfixturevalue('a')\n    assert 2"),
        (
            "    run = getattr(request, 'getfixturevalue')\n    run('a')\n    assert 1",
            "    run = getattr(request, 'getfixturevalue')\n    run('b')\n    assert 1",
        ),
        ("    request.getfuncargvalue('a')\n    assert 1", "    request.getfuncargvalue('a')\n    assert 2"),
    ],
)
def test_a_test_that_mentions_getfixturevalue_has_no_free_line(first, second):
    assert not holds(FIXTURE.format(body=first), FIXTURE.format(body=second))


def test_a_comment_in_a_test_that_mentions_getfixturevalue_is_still_free():
    body = "    request.getfixturevalue('a')\n    assert 1"
    assert holds(FIXTURE.format(body=body), FIXTURE.format(body=body.replace("assert 1", "# note\n    assert 1")))


# --- G5: a raise or a skip exception form ends the free body --------------------------------------------------------


@pytest.mark.parametrize(
    "form",
    [
        "raise Skipped('old')",
        "raise pytest.skip.Exception('old')",
        "raise unittest.SkipTest('old')",
        "raise SkipTest('old')",
        "raise SomethingElse('old')",
        "raise",
    ],
)
def test_a_raise_in_the_body_ends_the_free_part(form):
    source = "import pytest\n\n\ndef test_t():\n    x = 1\n    if {cond}:\n        {form}\n    assert 1\n"
    assert not holds(source.format(cond="x", form=form), source.format(cond="not x", form=form))
    # the statements after the last raise stay free
    assert holds(source.format(cond="x", form=form), source.format(cond="x", form=form).replace("assert 1", "assert 2"))


def test_a_skip_exception_name_or_call_ends_the_free_part_without_a_raise():
    source = "import pytest\n\n\ndef test_t():\n    x = 1\n    err = {name}\n    if x:\n        raise err('old')\n    assert 1\n"
    for name in ("Skipped", "SkipTest", "pytest.skip.Exception"):
        body = source.format(name=name)
        assert not holds(body, body.replace("err = " + name, "err = " + name + "\n    x = 0")), name
    skipped = "import pytest\n\n\ndef test_t():\n    x = 1\n    y = pytest.skip.Exception\n    z = x\n    assert 1\n"
    assert not holds(skipped, skipped.replace("x = 1", "x = 0"))
    assert holds(skipped, skipped.replace("z = x", "z = 0"))  # after the last form: free
    assert holds(skipped, skipped.replace("assert 1", "assert 2"))


# --- positive controls: these stay a hold ---------------------------------------------------------------------------

REAL = """\
import os

import pytest

INTEGRATION = pytest.mark.skipif(os.getenv("X_INTEGRATION_TEST") != "true", reason="integration test")


@INTEGRATION
def test_alpha():
    value = compute(1)
    assert value == 1


@INTEGRATION
def test_beta():
    value = compute(2)
    assert value == 2


@INTEGRATION
def test_gamma():
    value = compute(3)
    assert value == 3
"""


def test_the_real_world_shape_is_a_hold():
    head = (
        REAL.replace("import os\n", "import json\nimport os\n", 1)
        .replace("assert value == 1", "assert value == 11")
        .replace("    value = compute(2)\n", "    value = compute(2)\n    # the second value\n")
        .replace("    value = compute(3)\n", "    value = compute(3)\n    # the third value\n")
        + "\n\ndef test_delta():\n    assert json.loads('1') == 1\n"
    )
    for q in ("test_alpha", "test_beta", "test_gamma"):
        assert holds(REAL, head, q), q


def test_a_comment_a_blank_line_and_a_new_marked_test_are_a_hold():
    beta = "\n\n\n@INTEGRATION\ndef test_beta"
    assert holds(REAL, REAL + "\n# a note at the end\n", "test_alpha")
    assert holds(REAL, REAL.replace(beta, "\n" + beta), "test_alpha")
    assert holds(REAL, REAL + "\n\n@pytest.mark.slow\ndef test_slow():\n    assert 1\n", "test_alpha")


def test_a_new_marked_test_method_of_an_existing_class_is_a_hold():
    source = "import pytest\n\n\nclass TestK:\n    @pytest.mark.skipif(True, reason='r')\n    def test_t(self):\n        assert 1\n"
    assert holds(
        source, source + "\n    @pytest.mark.slow\n    def test_new(self):\n        assert 1\n", "TestK.test_t"
    )
