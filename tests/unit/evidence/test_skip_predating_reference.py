"""The base report as a second necessary condition, and the hardened AST rule (skipped-test-hold D1, rework 7):
one test per case of the adversarial review (F1-F7), at the level of the pure rule `skip_predates`, whose last
argument is what the base report says about the test (`skipped_at_base`)."""

import pytest

from l4.config.schema import L4Config
from l4.evidence.skippred import skip_predates

CFG = L4Config.model_validate({})
PT = "import pytest\n\n\n"
T = "def test_x():\n    assert 1\n"
CHANGED = ("tests/test_a.py",)


def predates(base: str, head: str, q: str = "test_x", *, at_base: bool = True, changed=CHANGED) -> bool:
    return skip_predates(base, head, q, list(changed), CFG, skipped_at_base=at_base)


# --- (a): the base report -----------------------------------------------------------------------------------------


def test_an_unchanged_skip_that_the_base_report_holds_as_skipped_predates():
    skip = "@pytest.mark.skipif(not HAS, reason='r')\n"
    base = f"{PT}HAS = False\n\n\n{skip}{T}"
    assert predates(base, base.replace("assert 1", "assert 2"))


def test_a_test_the_base_report_did_not_hold_as_skipped_never_predates():
    skip = "@pytest.mark.skipif(not HAS, reason='r')\n"
    base = f"{PT}HAS = False\n\n\n{skip}{T}"
    assert not predates(base, base.replace("assert 1", "assert 2"), at_base=False)


# --- F1: a marker imported from another module -------------------------------------------------------------------


def test_f1_a_marker_imported_from_another_module_is_not_a_predating_skip():
    head = f"{PT}from tests.markers import requires_stack\n\n\n@requires_stack\n{T}"
    assert not predates(f"{PT}{T}", head, at_base=False)  # it ran at the base: the base report says passed


# --- F2: a fixture whose name starts with `test` ------------------------------------------------------------------


@pytest.mark.parametrize("name", ["test_env", "tester", "stack"])
@pytest.mark.parametrize(
    "decorator", ["@pytest.fixture", "@pytest.fixture()", "@pytest.fixture(scope='module')", "@fixture", "@pt.fixture"]
)
def test_f2_a_fixture_that_gained_a_skip_touches_every_test_whatever_its_name(name, decorator):
    imports = "import pytest\nimport pytest as pt\nfrom pytest import fixture\n\n\n"
    skipif = "@pytest.mark.skipif(not HAS, reason='r')\n"
    fixture = f"{decorator}\ndef {name}():\n    return 1\n"
    base = f"{imports}HAS = False\n\n\n{fixture}\n\n{skipif}def test_x({name}):\n    assert 1\n"
    head = base.replace("    return 1\n", "    pytest.skip('no stack')\n")
    assert not predates(base, head)
    assert predates(base, base.replace("assert 1", "assert 2"))  # the control: a fixture left alone


def test_f2_a_fixture_is_not_a_test_even_when_its_name_starts_with_test():
    source = f"{PT}@pytest.fixture\ndef test_env():\n    return 1\n"
    assert not predates(source, source.replace("return 1", "return 2"), "test_env")


# --- F3: a mark nested in a module or class level block -----------------------------------------------------------

MODULE_BLOCKS = [
    pytest.param("import os\nif os.getenv('CI'):\n    pytestmark = pytest.mark.skip\n", id="if"),
    pytest.param("try:\n    import docker\nexcept ImportError:\n    pytestmark = pytest.mark.skip\n", id="try"),
    pytest.param(
        "import contextlib\nwith contextlib.suppress(Exception):\n    pytestmark = pytest.mark.skip\n", id="with"
    ),
    pytest.param("for _ in range(1):\n    pytestmark = pytest.mark.skip\n", id="for"),
    pytest.param("import os\nif os.name:\n    if os.sep:\n        STACK = pytest.mark.skip\n", id="nested"),
]


@pytest.mark.parametrize("block", MODULE_BLOCKS)
def test_f3_a_mark_in_a_module_level_block_is_a_new_construct(block):
    base = f"{PT}@pytest.mark.skipif(True, reason='r')\n{T}"
    head = f"{PT}{block}\n\n@pytest.mark.skipif(True, reason='r')\n{T}"
    assert not predates(base, head)


def test_f3_a_mark_in_a_class_level_block_is_a_new_construct():
    base = f"{PT}import os\n\n\nclass TestK:\n    def test_x(self):\n        assert 1\n"
    head = base.replace("class TestK:\n", "class TestK:\n    if os.name:\n        pytestmark = pytest.mark.skip\n\n")
    assert not predates(base, head, "TestK.test_x")


def test_f3_an_alias_assigned_in_a_block_and_applied_is_seen():
    block = "import os\nif os.name:\n    requires_stack = pytest.mark.skipif(True, reason='r')\n"
    base = f"{PT}{block}\n\n{T}"
    head = base.replace("def test_x", "@requires_stack\ndef test_x")
    assert not predates(base, head)


# --- F4: a skip added at run time ---------------------------------------------------------------------------------


def test_f4_add_marker_in_the_test_body_is_a_construct():
    base = f"{PT}{T}"
    head = f"{PT}def test_x(request):\n    request.node.add_marker(pytest.mark.skip(reason='x'))\n    assert 1\n"
    assert not predates(base, head)


@pytest.mark.parametrize("call", ["i.add_marker(marker)", "i.applymarker(marker)", "i.add_marker('skip')"])
def test_f4_a_collection_hook_that_adds_a_marker_is_a_construct(call):
    hook = f"def pytest_collection_modifyitems(items, marker=None):\n    for i in items:\n        {call}\n"
    assert not predates(f"{PT}{T}", f"{PT}{hook}\n\n{T}")


def test_f4_a_marker_appended_to_pytestmark_is_a_construct():
    base = f"{PT}pytestmark = []\n\n\n{T}"
    head = base.replace("\n\n\n" + T, "\npytestmark.append(pytest.mark.skip)\n\n\n" + T)
    assert not predates(base, head)


def test_f4_any_call_with_a_skip_mark_argument_is_a_construct():
    head = f"{PT}def test_x(request):\n    register(pytest.mark.xfail)\n    assert 1\n"
    assert not predates(f"{PT}{T}", head)


# --- F5: an alias of pytest or unittest ---------------------------------------------------------------------------


F5 = [
    ("import pytest as pt\n", "def test_x():\n    assert 1\n", "def test_x():\n    pt.skip('x')\n", "test_x"),
    ("import pytest as pt\n", T, "@pt.mark.skip\n" + T, "test_x"),
    ("from pytest import mark as m\n", T, "@m.skip\n" + T, "test_x"),
    ("from pytest import mark as m\n", T, "@m.skipif(True, reason='r')\n" + T, "test_x"),
    ("from pytest import skip as s\n", T, "def test_x():\n    s('x')\n", "test_x"),
    ("from pytest import importorskip as imp\n", T, "def test_x():\n    imp('docker')\n", "test_x"),
    (
        "import unittest as ut\n",
        "class TestK(ut.TestCase):\n    def test_x(self):\n        assert 1\n",
        "class TestK(ut.TestCase):\n    @ut.skip('x')\n    def test_x(self):\n        assert 1\n",
        "TestK.test_x",
    ),
    (
        "from unittest import skip as s\n",
        "class TestK:\n    def test_x(self):\n        assert 1\n",
        "class TestK:\n    @s('x')\n    def test_x(self):\n        assert 1\n",
        "TestK.test_x",
    ),
    ("import pytest\n", T, "skip = pytest.skip\n\n\ndef test_x():\n    skip('x')\n", "test_x"),
    ("import pytest\n", T, "mark = pytest.mark\n\n\n@mark.skip\n" + T, "test_x"),
]


@pytest.mark.parametrize(("header", "before", "after", "qualname"), F5)
def test_f5_an_alias_of_a_skip_is_a_skip(header, before, after, qualname):
    assert not predates(f"{header}\n\n{before}", f"{header}\n\n{after}", qualname)


def test_f5_the_same_alias_at_the_base_and_the_head_is_not_new():
    source = "import pytest as pt\n\n\n@pt.mark.skip\ndef test_x():\n    assert {}\n"
    assert predates(source.format(1), source.format(2))


# --- F6: the reason of a skip that stays, and a class that inherits one ---------------------------------------------


def test_f6_a_condition_variable_that_changed_does_not_predate_when_the_test_ran_at_the_base():
    skip = "@pytest.mark.skipif(not HAS, reason='r')\n"
    base = f"{PT}HAS = True\n\n\n{skip}{T}"
    assert not predates(base, base.replace("HAS = True", "HAS = False"), at_base=False)


def test_f6_a_class_that_newly_inherits_a_skipped_base_does_not_predate_when_the_test_ran_at_the_base():
    base = f"{PT}@pytest.mark.skip\nclass Base:\n    pass\n\n\nclass TestK:\n    def test_x(self):\n        assert 1\n"
    head = base.replace("class TestK:", "class TestK(Base):")
    assert not predates(base, head, "TestK.test_x", at_base=False)


# --- F7: support and runner configuration files ---------------------------------------------------------------------


@pytest.mark.parametrize("support", ["tests/conftest.py", "conftest.py", "pytest.ini", "pyproject.toml"])
def test_f7_a_changed_support_or_runner_file_stops_a_skip_from_predating_even_with_a_construct_in_the_file(support):
    base = f"{PT}@pytest.mark.skipif(True, reason='r')\n{T}"
    assert predates(base, base.replace("assert 1", "assert 2"))
    assert not predates(base, base.replace("assert 1", "assert 2"), changed=(*CHANGED, support))


def test_a_code_file_is_neither_support_nor_runner_configuration():
    base = f"{PT}@pytest.mark.skipif(True, reason='r')\n{T}"
    assert predates(base, base.replace("assert 1", "assert 2"), changed=(*CHANGED, "src/shop/pricing.py"))
