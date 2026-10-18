"""The pure scans of step 1 (verifier 2.4, 2.6, 2.10)."""

from l4.verifier import scan


def test_makereport_hook_and_exitstatus_assignment_are_hits():
    assert scan.result_hooks("def pytest_runtest_makereport(item, call):\n    pass\n")
    assert scan.result_hooks("def pytest_sessionfinish(session):\n    session.exitstatus = 0\n")


def test_hookwrapper_only_counts_when_it_wraps_the_test_call():
    wrapped = "import pytest\n\n\n@pytest.hookimpl(hookwrapper=True)\ndef pytest_runtest_call(item):\n    yield\n"
    plain = "def pytest_runtest_call(item):\n    pass\n"
    other = "import pytest\n\n\n@pytest.hookimpl(hookwrapper=True)\ndef pytest_sessionstart(session):\n    yield\n"
    assert scan.result_hooks(wrapped) and not scan.result_hooks(other)
    # L4-VER-039: a plain pytest_runtest_call is no longer harmless; its hit has its own text
    assert scan.result_hooks(plain) == ["pytest_runtest_call: code around every test call"]
    assert scan.result_hooks(wrapped) == ["pytest_runtest_call: a hook wrapper around the test call"]


def test_a_source_that_does_not_parse_has_no_hits():
    assert scan.result_hooks("def (:") == [] and scan.skip_markers("def (:") == {}


def test_addopts_added_reads_ini_continuations_and_toml_lists():
    ini_before = "[pytest]\naddopts =\n    -ra\n"
    ini_after = "[pytest]\naddopts =\n    -ra\n    -p no:l4_trace\n    --deselect=tests/test_a.py::test_x\n"
    assert scan.addopts_added(ini_before, ini_after) == ["--deselect=tests/test_a.py::test_x", "-p"]
    toml = '[tool.pytest.ini_options]\naddopts = ["-ra", "-k", "not slow", "--ignore-glob=x*"]\n'
    assert scan.addopts_added("", toml) == ["--ignore-glob=x*", "-k"]
    assert scan.addopts_added(toml, toml) == []
    assert scan.addopts_added("", '[tool.pytest.ini_options]\naddopts = "-ra --strict-markers"\n') == []


def test_skip_markers_per_test_and_module():
    source = (
        "import pytest\n\npytestmark = pytest.mark.skipif(True, reason='x')\n\n\n"
        "@pytest.mark.skip\ndef test_a():\n    pass\n\n\n"
        "class TestB:\n    def test_c(self):\n        pytest.skip('later')\n\n    def test_d(self):\n        pass\n"
    )
    assert scan.skip_markers(source) == {"<module>": 1, "test_a": 1, "TestB.test_c": 1}
    assert scan.defined_tests(source) == {"test_a", "TestB.test_c", "TestB.test_d"}


def test_suppressions_in_a_line():
    kinds = [s.kind for s in scan.suppressions_in("x = 1  # noqa: E501  # type: ignore[arg-type]")]
    assert kinds == ["noqa", "type-ignore"]
    assert [s.kind for s in scan.suppressions_in("run()  # nosec B603")] == ["nosec"]
    assert [s.kind for s in scan.suppressions_in("KEY = 'x'  # gitleaks:allow")] == ["gitleaks"]
    assert scan.suppressions_in("text = 'no suppression here'") == []


def test_added_lines_carry_their_line_numbers():
    diff = "+++ b/src/a.py\n@@ -1,0 +5,2 @@\n+one\n+two\n@@ -9 +12 @@\n+three\n+++ /dev/null\n"
    assert [(a.path, a.number, a.text) for a in scan.added_lines(diff)] == [
        ("src/a.py", 5, "one"), ("src/a.py", 6, "two"), ("src/a.py", 12, "three"),
    ]  # fmt: skip


def test_task_tags():
    assert scan.task_tags("Update the docs [Docs] and [test-infra]") == {"docs", "test-infra"}
    assert scan.task_tags("plain [ ] title") == frozenset()


def test_hooks_that_replace_a_tests_call_are_hits():  # SCN-VER-129
    assert scan.result_hooks("def pytest_pyfunc_call(pyfuncitem):\n    return True\n") == [
        "pytest_pyfunc_call: runs or replaces the test function"
    ]
    assert scan.result_hooks("def pytest_runtest_setup(item):\n    pass\n") == [
        "pytest_runtest_setup: code around every test call"
    ]
    modify = "def pytest_collection_modifyitems(items):\n    for item in items:\n        item.obj = lambda: None\n"
    assert scan.result_hooks(modify) == ["assignment to .obj: replaces a collected test"]
    assert scan.result_hooks("def f(item):\n    item.runtest = print\n") == [
        "assignment to .runtest: replaces a collected test"
    ]
    wrapped = "import pytest\n\n\n@pytest.hookimpl(hookwrapper=True)\ndef pytest_runtest_setup(item):\n    yield\n"
    assert scan.result_hooks(wrapped) == []  # a wrapper of setup is not code around the call


def test_an_attribute_that_is_not_obj_or_runtest_is_no_hit():  # SCN-VER-129 control
    assert scan.result_hooks("def f(item):\n    item.name = 'x'\n    item.obj_count = 1\n") == []


# --- third review, item 2: hooks that can rewrite the report after pytest wrote it ------


def test_atexit_os_exit_and_session_end_hooks_that_write_files_are_hits():
    assert scan.result_hooks("import atexit\natexit.register(print)\n") == [
        "atexit.register: runs code after the test run, when the report is already written"
    ]
    assert scan.result_hooks("import atexit as _a\n_a.register(print)\n") != []
    assert scan.result_hooks("import os\nos._exit(0)\n") == [
        "os._exit: ends the process without the report being judged"
    ]
    assert scan.result_hooks("import os as _o\n_o._exit(0)\n") != []
    for hook in ("pytest_sessionfinish", "pytest_unconfigure", "pytest_terminal_summary"):
        writes = f"def {hook}(*a):\n    open('x.xml', 'w').write('')\n"
        assert scan.result_hooks(writes) == [f"{hook}: writes a file when the run ends"]
        assert scan.result_hooks(f"def {hook}(*a):\n    print('done')\n") == []
    assert scan.result_hooks("from pathlib import Path\ndef pytest_unconfigure(c):\n    Path('a').write_text('b')\n")


def test_other_register_calls_are_no_hit():
    assert scan.result_hooks("registry.register(print)\nclass A:\n    def _exit(self):\n        pass\n") == []
