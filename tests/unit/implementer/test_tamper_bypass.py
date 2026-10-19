"""detect-test-tamper 8.1 (L4-IMP-049, L4-IMP-045, design D12): statements that replace a test without binding its name,
and tests a subclass inherits. Ports the review's `probes/pure_bypass.py`, which printed `[]` for every form."""

import pytest

from l4.implementer.tamper import compare

PATH = "tests/test_pricing.py"
BASE = (
    "from pytdd import total\n\n\ndef test_total_adds_prices():\n    assert total([1.25, 2.5]) == 3.75\n\n\n"
    "def test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"
)
FORMS = {
    "__code__ swap": "\n\ntest_total_adds_prices.__code__ = (lambda: None).__code__\n",
    "globals()": '\n\nglobals()["test_total_adds_prices"] = lambda: None\n',
    "setattr on the module": '\n\nimport sys\nsetattr(sys.modules[__name__], "test_total_adds_prices", lambda: None)\n',
    "vars()": '\n\nvars()["test_total_adds_prices"] = lambda: None\n',
    "per-test pytestmark": "\n\nimport pytest\ntest_total_adds_prices.pytestmark = [pytest.mark.skip]\n",
}
CLS = "class TestCart:\n    def test_empty(self):\n        assert len([]) == 0\n"


@pytest.mark.parametrize("form", sorted(FORMS))
def test_a_statement_that_replaces_a_test_without_binding_its_name_changes_every_test(form):  # SCN-IMP-278
    found = {t.name: (t.kind, t.why) for t in compare(PATH, BASE, BASE + FORMS[form])}
    why = "what it uses in this file changed: <module>"
    assert found == {"test_total_adds_prices": ("changed", why), "test_total_of_nothing_is_zero": ("changed", why)}


def test_a_class_attribute_assigned_after_the_class_changes_its_tests():  # SCN-IMP-278
    found = compare("tests/test_cart.py", CLS, CLS + "\n\nTestCart.test_empty = lambda self: None\n")
    assert [(t.name, t.kind) for t in found] == [("TestCart.test_empty", "changed")]
    assert "<module>" in found[0].why


def test_a_statement_in_a_class_body_that_replaces_a_test_changes_it():  # SCN-IMP-278
    after = CLS + "    test_empty = staticmethod(lambda: None)\n"
    found = compare("tests/test_cart.py", CLS, after)
    assert [(t.name, t.kind) for t in found] == [("TestCart.test_empty", "rebound")]
    after = CLS.replace("def test_empty", "def test_other") + "    test_empty = 1\n"
    assert compare("tests/test_cart.py", CLS, after)[0].kind == "changed"
    after = CLS + "    helper = staticmethod(lambda: None)\n    test_empty.pytestmark = []\n"
    assert [(t.name, t.kind) for t in compare("tests/test_cart.py", CLS, after)] == [("TestCart.test_empty", "changed")]


def test_the_plain_second_def_stays_a_rebinding():  # SCN-IMP-278 control
    found = compare(PATH, BASE, BASE + "\n\ndef test_total_adds_prices():\n    pass\n")
    assert [(t.name, t.kind) for t in found] == [("test_total_adds_prices", "rebound")]


def test_a_new_plain_definition_and_a_new_fixture_change_nothing():  # SCN-IMP-278 control, SCN-IMP-265
    new = (
        "\n\nimport pytest\n\nLIMIT = 10\n\n\n@pytest.fixture(scope='module')\ndef extra():\n    return [1]\n\n\n"
        "def test_new(extra):\n    assert extra\n"
    )
    assert compare(PATH, BASE, BASE + new) == []


INH = (
    "class TestBase:\n    def test_x(self):\n        assert sum([1, 2]) == 3\n\n\n"
    "class TestChild(TestBase):\n    pass\n"
)
INH2 = INH.replace("    pass\n", "    def test_x(self):\n        pass\n")


def test_a_subclass_that_overrides_an_inherited_test_changes_it():  # SCN-IMP-279
    found = {t.name: t for t in compare("tests/test_inh.py", INH, INH2)}
    assert found["TestChild.test_x"].kind == "changed"
    assert found["TestChild.test_x"].why == "its body, decorators or parametrisation changed"


def test_a_subclass_that_keeps_inheriting_changes_nothing():  # SCN-IMP-279
    assert (
        compare("tests/test_inh.py", INH, INH + "\n\nclass TestOther:\n    def test_y(self):\n        assert 1\n") == []
    )


def test_a_removed_subclass_deletes_its_inherited_test():  # SCN-IMP-279
    found = {t.name: t.kind for t in compare("tests/test_inh.py", INH, INH.split("\n\n\nclass TestChild")[0] + "\n")}
    assert found == {"TestChild.test_x": "deleted"}


def test_a_changed_base_class_test_changes_the_inherited_one_too():  # SCN-IMP-279
    found = {t.name for t in compare("tests/test_inh.py", INH, INH.replace("== 3", "is not None"))}
    assert found == {"TestBase.test_x", "TestChild.test_x"}
