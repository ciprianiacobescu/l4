"""Which tests pytest collects, which report ids are a task's, and when the e2e command cannot judge them."""

from l4.implementer.browser_tests import (
    collectable_tests,
    is_pytest_file,
    match_task_tests,
    module_files,
    selecting_option,
    shared_with_unit_gate,
)

FILES = {"e2e/test_layout.py", "e2e/pytest.ini", "tests/test_unit.py", "e2e/other/test_layout.py"}


def test_pytest_default_file_patterns():
    assert is_pytest_file("e2e/test_a.py") and is_pytest_file("e2e/a_test.py")
    assert not is_pytest_file("e2e/helpers.py") and not is_pytest_file("e2e/conftest.py")
    assert not is_pytest_file("e2e/test_a.ts") and not is_pytest_file("e2e/a_test.txt")


def test_collectable_tests_follow_pytests_rules():
    source = (
        "import pytest\n\n"
        "@pytest.fixture\ndef test_user():\n    pass\n\n"
        "@pytest_asyncio.fixture(scope='session')\nasync def test_loop():\n    pass\n\n"
        "def test_plain():\n    pass\n\nasync def test_async():\n    pass\n\ndef helper():\n    pass\n\n"
        "class Helper:\n    def test_helper(self):\n        pass\n\n"
        "class TestA:\n    def test_x(self):\n        pass\n\n"
        "    @pytest.fixture\n    def test_data(self):\n        pass\n\n"
        "class TestB(TestA):\n    def test_y(self):\n        pass\n\n"
        "class TestInit:\n    def __init__(self):\n        pass\n\n    def test_z(self):\n        pass\n\n"
        "class TestInherits(TestInit):\n    def test_w(self):\n        pass\n"
    )
    assert collectable_tests(source) == {"test_plain", "test_async", "TestA.test_x", "TestB.test_x", "TestB.test_y"}


def test_an_unparsable_source_has_no_tests():
    assert collectable_tests("def test_x(:\n") == frozenset()


def test_a_selecting_command_is_seen_after_the_pytest_word_only():
    assert selecting_option("pytest e2e -m browser") == "-m"
    assert selecting_option('python -m pytest e2e -k "not slow"') == "-k"
    assert selecting_option("pytest e2e -mbrowser") == "-m"
    assert selecting_option("python -m pytest e2e -q -p no:cacheprovider --maxfail 1") is None
    assert selecting_option("npx playwright test -m x") is None  # not pytest: nothing is parsed
    assert selecting_option("pytest 'unbalanced") is None


def test_both_id_shapes_name_the_same_test():
    tests = [("e2e/test_layout.py", "test_width")]
    only = {"e2e/test_layout.py", "tests/test_unit.py"}
    for shape in ("e2e.test_layout::test_width[chromium]", "test_layout::test_width[chromium]"):
        assert match_task_tests([shape], tests, only).found == {tests[0]: [shape]}


def test_two_files_that_fit_the_suffix_are_ambiguous_and_never_guessed():
    tests = [("e2e/test_layout.py", "test_width")]
    got = match_task_tests(["test_layout::test_width"], tests, FILES)
    assert got.found == {} and got.ambiguous == ["test_layout::test_width"]
    exact = match_task_tests(["e2e.test_layout::test_width"], tests, FILES)  # the exact path wins
    assert exact.found == {tests[0]: ["e2e.test_layout::test_width"]} and exact.ambiguous == []


def test_a_class_is_matched_exactly():
    tests = [("e2e/test_layout.py", "TestA.test_x"), ("e2e/test_layout.py", "TestB.test_x")]
    ids = ["e2e.test_layout.TestA::test_x[chromium]", "e2e.test_layout::test_x"]
    got = match_task_tests(ids, tests, FILES)
    assert got.found == {tests[0]: [ids[0]]}
    plain = match_task_tests(ids, [("e2e/test_layout.py", "test_x")], FILES)
    assert plain.found == {("e2e/test_layout.py", "test_x"): [ids[1]]}


def test_collection_errors_resolve_to_a_file_or_none():
    got = module_files(["e2e.test_layout", "test_layout", "nope"], FILES)
    assert got == {"e2e.test_layout": "e2e/test_layout.py", "test_layout": None, "nope": None}


def test_unit_ids_in_the_e2e_directory_are_shared():
    files = {"tests/test_a.py", "tests/browser/test_b.py", "e2e/test_c.py"}
    ids = ["tests.test_a::test_1", "tests.browser.test_b::test_2[x]"]
    assert shared_with_unit_gate("tests", ids, files) == sorted(ids)
    assert shared_with_unit_gate("e2e", ids, files) == []
    assert shared_with_unit_gate("tests/browser", ids, files) == ["tests.browser.test_b::test_2[x]"]
