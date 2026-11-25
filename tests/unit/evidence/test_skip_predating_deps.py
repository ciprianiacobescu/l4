"""Condition (d) of the skip rule (skipped-test-hold D1, rework 8, review G1): the dependency closure of what makes the
test skip is the same at the base and at the head. (b) compares the skip constructs; it cannot see that the unit changed
WHY an unchanged construct skips (a flag, a guard's condition, a helper). Pure rule: `skip_predates` with the base
report's answer given."""

import pytest

from l4.config.schema import L4Config
from l4.evidence.skippred import skip_predates
from l4.verifier.skipdeps import SkipFacts

CFG = L4Config.model_validate({})
CHANGED = ("tests/test_a.py",)
H = "import os\nimport pytest\n\n\n"


def predates(base: str, head: str, q: str = "test_x") -> bool:
    return skip_predates(base, head, q, list(CHANGED), CFG, skipped_at_base=True)


def closure_holds(base: str, head: str, q: str = "test_x") -> bool:
    """(d) alone: the closure of the test is the same at both sides. `predates` is (b) to (e) together, and (e) is
    stricter than (d) on purpose: it refuses a changed line of the module or of a class that is not in a test, whether
    or not the closure reads it (rework 9). The cases below that say what (d) does NOT trip on ask (d) directly."""
    closure = SkipFacts(base).closure(q)
    return closure is not None and closure == SkipFacts(head).closure(q)


# --- the cases of the review: (b) saw no change, the cause of the skip changed ----------------------------------------


def test_g1_a_module_flag_the_skipif_reads_was_changed():
    skipif = "@pytest.mark.skipif(FLAG, reason='r')\ndef test_x():\n    assert 1\n"
    base = f"{H}FLAG = True\n\n\n{skipif}"
    head = f"{H}FLAG = os.environ.get('Z') is None\n\n\n{skipif}"
    assert not predates(base, head)
    assert predates(base, base.replace("assert 1", "assert 2"))  # the control: the same flag, another assertion


def test_g1_the_condition_of_a_guard_in_the_body_was_changed():
    base = f"{H}def test_x():\n    if not os.environ.get('S'):\n        pytest.skip('no stack')\n    assert 1\n"
    head = base.replace("if not os.environ.get('S'):", "if True:")
    assert not predates(base, head)
    assert predates(base, base.replace("assert 1", "assert 2"))  # after the guard: not a part of what skips


def test_g1_the_body_of_a_helper_the_skipif_calls_was_changed():
    def source(body: str) -> str:
        skipif = "@pytest.mark.skipif(not has(), reason='r')\ndef test_x():\n    assert 1\n"
        return f"{H}def has():\n    return {body}\n\n\n{skipif}"

    assert not predates(source("False"), source("os.environ.get('Q') == '1'"))
    assert predates(source("False"), source("False").replace("assert 1", "assert 2"))


def test_g1_a_helper_that_skips_and_that_the_body_calls_was_changed():
    def source(cond: str) -> str:
        return (
            f"{H}def need():\n    if {cond}:\n        pytest.skip('no stack')\n\n\n"
            "def test_x():\n    need()\n    assert 1\n"
        )

    assert not predates(source("not os.environ.get('S')"), source("True"))
    assert predates(
        source("not os.environ.get('S')"), source("not os.environ.get('S')").replace("assert 1", "assert 2")
    )


def test_g1_the_dependencies_of_a_dependency_count_too():
    def source(value: str) -> str:
        skipif = "@pytest.mark.skipif(FLAG, reason='r')\ndef test_x():\n    assert 1\n"
        return f"{H}BASE = {value}\nFLAG = BASE is None\n\n\n{skipif}"

    assert not predates(source("None"), source("os.environ.get('Z')"))


def test_g1_the_setup_before_a_guard_is_part_of_the_guard():
    def source(setup: str) -> str:
        return f"{H}def test_x():\n    {setup}\n    if not value:\n        pytest.skip('r')\n    assert 1\n"

    assert not predates(source("value = os.environ.get('S')"), source("value = None"))


def test_g1_an_import_the_skipif_reads_now_comes_from_another_module():
    skipif = "@pytest.mark.skipif(not has(), reason='r')\ndef test_x():\n    assert 1\n"
    assert not predates(
        f"import pytest\nfrom helpers import has\n\n\n{skipif}", f"import pytest\nfrom other import has\n\n\n{skipif}"
    )


def test_g1_a_conditional_import_fallback_that_changed_is_a_change():
    def source(module: str) -> str:
        return (
            f"import pytest\ntry:\n    import {module} as docker\nexcept ImportError:\n    docker = None\n\n\n"
            "@pytest.mark.skipif(docker is None, reason='r')\ndef test_x():\n    assert 1\n"
        )

    assert not predates(source("docker"), source("podman"))


def test_g1_the_condition_of_a_block_that_picks_an_import_is_part_of_its_binding():
    def source(condition: str) -> str:
        return (
            f"import sys\nimport pytest\n\nif {condition}:\n    import json as codec\n"
            "else:\n    import pickle as codec\n\n\n"
            "@pytest.mark.skipif(codec is None, reason='r')\ndef test_x():\n    assert 1\n"
        )

    assert not predates(source("sys.platform == 'linux'"), source("sys.platform == 'win32'"))
    assert predates(
        source("sys.platform == 'linux'"), source("sys.platform == 'linux'").replace("assert 1", "assert 2")
    )


def test_g1_the_fixture_the_test_takes_and_an_autouse_fixture_count_whole():
    def source(fixture: str, autouse: str) -> str:
        return (
            f"{H}@pytest.fixture\ndef stack():\n    {fixture}\n\n\n"
            f"@pytest.fixture(autouse=True)\ndef guard():\n    {autouse}\n\n\n"
            "def test_x(stack):\n    assert stack\n"
        )

    base = source("return 1", "pass")
    assert not predates(base, source("pytest.skip('x')", "pass"))
    assert not predates(base, source("return 1", "pytest.skip('x')"))
    assert not predates(base, source("return 2", "pass"))  # a fixture the test takes: a changed definition is a change
    assert predates(base, base.replace("assert stack", "assert stack, 'x'"))


def test_g1_a_fixture_the_test_does_not_take_is_not_a_part_of_it():
    def source(value: str) -> str:
        return (
            f"{H}@pytest.fixture\ndef other():\n    return {value}\n\n\n"
            "@pytest.mark.skipif(True, reason='r')\ndef test_x():\n    assert 1\n"
        )

    assert closure_holds(source("1"), source("2"))
    assert not predates(source("1"), source("2"))  # (e): a fixture of the file is not a place the unit may change


def test_g1_the_class_and_the_module_parts_count():
    def source(flag: str, decorator: str = "", pytestmark: str = "") -> str:
        return (
            f"{H}FLAG = {flag}\n{pytestmark}\n\n{decorator}class TestA:\n"
            "    @pytest.mark.skipif(FLAG, reason='r')\n    def test_x(self):\n        assert 1\n"
        )

    assert not predates(source("True"), source("False"), "TestA.test_x")
    assert predates(source("True"), source("True").replace("assert 1", "assert 2"), "TestA.test_x")


def test_g1_a_class_level_flag_the_method_reads_was_changed():
    def source(flag: str) -> str:
        method = "    @pytest.mark.skipif(FLAG, reason='r')\n    def test_x(self):\n        assert 1\n"
        return f"{H}class TestA:\n    FLAG = {flag}\n\n{method}"

    assert not predates(source("True"), source("os.environ.get('Z') is None"), "TestA.test_x")


def test_g1_a_base_class_the_test_class_inherits_was_changed():
    def source(body: str) -> str:
        method = "    @pytest.mark.skip(reason='r')\n    def test_x(self):\n        assert 1\n"
        return f"{H}class Base:\n    {body}\n\n\nclass TestA(Base):\n{method}"

    assert not predates(source("x = 1"), source("x = 2"), "TestA.test_x")


def test_g1_a_setup_hook_of_the_class_counts_whole():
    def source(cond: str) -> str:
        return (
            f"{H}import unittest\n\n\nclass TestA(unittest.TestCase):\n    def setUp(self):\n        if {cond}:\n"
            "            self.skipTest('r')\n\n    def test_x(self):\n        assert 1\n"
        )

    assert not predates(source("not os.environ.get('S')"), source("True"), "TestA.test_x")


# --- what must NOT trip (d): the closure is the cause of the skip, not the file --------------------------------------


def test_g1_an_unrelated_import_and_an_unrelated_test_do_not_trip_it():
    base = f"{H}FLAG = True\n\n\n@pytest.mark.skipif(FLAG, reason='r')\ndef test_x():\n    assert 1\n"
    head = base.replace("import os\n", "import os\nimport json\n") + "\n\ndef test_new():\n    assert json\n"
    assert closure_holds(base, head)
    assert predates(base, head)  # and (e): a whole new import of a new name, and a whole new test


def test_g1_an_unrelated_name_added_to_an_import_line_the_test_reads_does_not_trip_it():
    test = "\n\n@pytest.mark.skipif({}, reason='r')\ndef test_x():\n    assert 1\n"
    base = "import os\nimport pytest\n" + test.format("os.name == 'x'")
    assert closure_holds(base, base.replace("import os\n", "import os, json\n"))
    from_import = "from os import path\nimport pytest\n" + test.format("path is None")
    assert closure_holds(from_import, from_import.replace("import path", "import path, sep"))
    # (e) wants a whole new import statement: a name added to a line the base has is a changed line outside a test
    assert not predates(base, base.replace("import os\n", "import os, json\n"))
    assert predates(base, base.replace("import os\n", "import os\nimport json\n"))


def test_g1_an_unrelated_flag_and_an_unrelated_helper_do_not_trip_it():
    test = "@pytest.mark.skipif(True, reason='r')\ndef test_x():\n    assert helper() == OTHER\n"
    base = f"{H}OTHER = 1\n\n\ndef helper():\n    return 1\n\n\n{test}"
    head = base.replace("OTHER = 1", "OTHER = 2").replace("return 1", "return 2")
    assert closure_holds(base, head)  # the body after the skip's parts reads them, the skip does not
    assert not predates(base, head)  # (e): a flag and a helper of the module are not a place the unit may change


INTEGRATION = (
    "import os\n\nimport pytest\n\nINTEGRATION = pytest.mark.skipif(\n"
    "    os.getenv('X_INTEGRATION_TEST') != 'true', reason='needs the stack'\n)\n\n\n"
)
LIVE_TESTS = (
    "@INTEGRATION\ndef test_a():\n    value = compute(1)\n    assert value == 1\n\n\n"
    "@INTEGRATION\ndef test_b():\n    value = compute(2)\n    assert value == 2\n\n\n"
    "@INTEGRATION\ndef test_c():\n    assert 1\n\n\ndef compute(n):\n    return n\n"
)


def test_g1_the_real_world_shape_still_gives_the_hold():
    """Several tests under one `INTEGRATION` mark; the unit changes an assertion and adds a comment inside two of the
    bodies, adds an import and a new test that is not skipped."""
    base = INTEGRATION + LIVE_TESTS
    head = (
        base.replace("import pytest\n", "import json\nimport pytest\n", 1)
        .replace("assert value == 1", "# the count is one\n    assert value == 1 and True")
        .replace("assert value == 2", "# the count is two\n    assert value == 2 and True")
        + "\n\ndef test_new():\n    assert json.dumps(1) == '1'\n"
    )
    for name in ("test_a", "test_b", "test_c"):
        assert predates(base, head, name), name
    changed_mark = head.replace("!= 'true'", "== 'true'")
    assert not predates(base, changed_mark, "test_a")  # control: the mark's own condition


def test_g1_a_removed_part_is_a_difference_too():
    """(d) is an equality of the closure: it is stricter than (b), where a removed skip never counts, and says so."""
    base = f"{H}@pytest.mark.skip(reason='a')\n@pytest.mark.skipif(True, reason='b')\ndef test_x():\n    assert 1\n"
    head = base.replace("@pytest.mark.skip(reason='a')\n", "")
    assert not predates(base, head)


def test_g1_a_test_that_is_not_in_the_head_is_never_predating():
    base = f"{H}@pytest.mark.skip(reason='a')\ndef test_x():\n    assert 1\n"
    assert not predates(base, f"{H}@pytest.mark.skip(reason='a')\ndef test_y():\n    assert 1\n")


DYNAMIC = [
    "globals()['FLAG'] = True",
    "global FLAG\n    FLAG = True",
    "setattr(sys.modules[__name__], 'FLAG', True)",
]


@pytest.mark.parametrize("body", DYNAMIC)
def test_g1_dynamic_forms_in_another_tests_body_are_a_documented_residual(body):
    """Not read, by design (the runbook's known limits): `getattr`, `importlib`, `globals()`, a name bound in a function
    and used through `global`, in a place the unit may change: the body of another test, run-time state that the order
    of the run decides. The base report of rule (a) is what stands in front of them."""
    base = (
        f"{H}import sys\n\nFLAG = False\n\n\n@pytest.mark.skipif(FLAG, reason='r')\ndef test_x():\n    assert 1\n\n\n"
        "def test_other():\n    assert 2\n"
    )
    assert predates(base, base.replace("    assert 2\n", f"    {body}\n"))


@pytest.mark.parametrize(
    "head",
    [
        "globals()['FLAG'] = True\n",
        "def _set():\n    global FLAG\n    FLAG = True\n\n\n_set()\n",
    ],
)
def test_g1_dynamic_forms_at_module_level_are_a_change_outside_a_test(head):
    """The same forms at module level are a changed line outside a collected test: (e) refuses them."""
    base = f"{H}FLAG = False\n\n\n@pytest.mark.skipif(FLAG, reason='r')\ndef test_x():\n    assert 1\n"
    assert not predates(base, base.replace("\n\n\n@", f"\n{head}\n\n@", 1))


def test_g1_a_pytestmark_assignment_counts_whatever_its_value():
    base = f"{H}@pytest.mark.skip(reason='r')\ndef test_x():\n    assert 1\n"
    head = f"{H}pytestmark = getattr(pytest.mark, 'sk' + 'ip')\n\n\n" + base[len(H) :]
    assert not predates(base, head)
