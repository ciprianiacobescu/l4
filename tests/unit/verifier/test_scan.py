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


# --- fourth review: references to the harness's own plugin and to the report option ------


def test_references_to_the_harness_plugin_the_record_and_the_report_option_are_hits():
    forms = {
        'import sys\nsys.modules.get("l4_trace")': "l4_trace",
        'x = "L4_OUTCOME_FILE"': "L4_OUTCOME_FILE",
        "import l4_trace\nl4_trace._OUTCOME_FD.clear()": "l4_trace",
        "def pytest_unconfigure(config):\n    path = config.option.xmlpath\n": "xmlpath",
        'def f(config):\n    return getattr(config.option, "xmlpath", None)\n': "xmlpath",
        'import sys\nm = sys.modules["l4.gates.outcomes"]\n': "sys.modules",
        "def pytest_sessionfinish(session):\n    session.exitstatus = 0\n": "exitstatus",
    }
    for source, word in forms.items():
        assert any(word in hit for hit in scan.harness_references(source)), source
    assert scan.harness_references("import os\nx = os.environ.get('HOME')\nORDER_OUTCOME = 1\n") == []
    assert scan.harness_references("import sys\nm = sys.modules.get('json')\n") == []


def test_honest_names_that_only_look_like_the_harness_references_are_not_hits():  # fifth review
    honest = {
        "_OUTCOMES = ['win', 'draw', 'loss']\n": "a constant that starts with _OUTCOME",
        "import pytest\n\n\n@pytest.fixture\ndef xmlpath(tmp_path):\n    return tmp_path / 'a.xml'\n": "a fixture",
        "def test_parse(xmlpath):\n    assert xmlpath.suffix == '.xml'\n": "a parameter",
        "class Doc:\n    xmlpath = 'a.xml'\n\n\ndef f(d):\n    return d.xmlpath\n": "an attribute read",
    }
    for source, why in honest.items():
        assert scan.harness_references(source) == [], why
    assert scan.harness_references("def f(config):\n    return config.option.xmlpath\n")
    assert scan.harness_references("_OUTCOME_FD = []\n")


# skip_constructs (skipped-test-hold D3): the constructs that can skip a test, keyed by (scope, unparsed text)
SKIPIF = "pytest.mark.skipif(os.getenv('X') != 'true', reason='stack')"


def _keys(source: str) -> set[tuple[str, str]]:
    found = scan.skip_constructs(source)
    assert found is not None
    return set(found)


def test_skip_constructs_of_a_source_that_does_not_parse_is_none():
    assert scan.skip_constructs("def (:") is None
    assert scan.skip_constructs("") == {}


def test_skip_constructs_decorators_are_scoped_to_what_they_decorate():
    source = (
        "import os\nimport pytest\nimport unittest\n\n\n"
        "@pytest.mark.skip\ndef test_a():\n    pass\n\n\n"
        "@pytest.mark.xfail(reason='x')\nclass TestB:\n"
        "    @pytest.mark.skipif(os.getenv('X') != 'true', reason='stack')\n    def test_c(self):\n        pass\n\n"
        "    @unittest.expectedFailure\n    def test_d(self):\n        pass\n\n\n"
        "@unittest.skipUnless(os.getenv('Y'), 'y')\ndef test_e():\n    pass\n"
    )
    assert _keys(source) == {
        ("test_a", "pytest.mark.skip"),
        ("TestB", "pytest.mark.xfail(reason='x')"),
        ("TestB.test_c", SKIPIF),
        ("TestB.test_d", "unittest.expectedFailure"),
        ("test_e", "unittest.skipUnless(os.getenv('Y'), 'y')"),
    }


def test_skip_constructs_an_unchanged_skipif_is_the_same_key_however_it_is_wrapped():
    one_line = f"import os, pytest\n\n\n@{SKIPIF}\ndef test_a():\n    pass\n"
    wrapped = (
        'import os, pytest\n\n\n@pytest.mark.skipif(\n    os.getenv("X") != "true",\n    reason="stack",\n)\n'
        "def test_a():\n    pass\n"
    )
    assert scan.skip_constructs(one_line) == scan.skip_constructs(wrapped)


def test_skip_constructs_a_changed_condition_on_a_continuation_line_is_a_different_key():
    before = "@pytest.mark.skipif(\n    os.getenv('A') != 'true',\n    reason='r',\n)\ndef test_a():\n    pass\n"
    after = before.replace("'A'", "'B'")
    assert scan.skip_markers(before) == scan.skip_markers(after)  # the old count cannot see it
    assert _keys(before) != _keys(after)


def test_skip_constructs_a_mark_inside_a_parametrize_makes_the_decorator_a_construct():
    source = (
        "import pytest\n\n\n@pytest.mark.parametrize('n', [1, pytest.param(2, marks=pytest.mark.skip)])\n"
        "def test_a(n):\n    pass\n\n\n@pytest.mark.parametrize('n', [1, 2])\ndef test_b(n):\n    pass\n"
    )
    assert {scope for scope, _ in _keys(source)} == {"test_a"}


def test_skip_constructs_module_and_class_marks_and_the_aliases_they_define():
    source = (
        f"import os, pytest\n\npytestmark = [pytest.mark.skip]\nrequires_stack = {SKIPIF}\n\n\n"
        "@requires_stack\ndef test_a():\n    pass\n\n\n"
        "class TestB:\n    pytestmark = pytest.mark.skipif(True, reason='r')\n    needs: int = pytest.mark.xfail\n\n"
        "    def test_c(self):\n        pass\n\n    @needs\n    def test_d(self):\n        pass\n"
    )
    assert _keys(source) == {
        ("<module>", "pytestmark = [pytest.mark.skip]"),
        ("<module>", f"requires_stack = {SKIPIF}"),
        ("test_a", "requires_stack"),
        ("TestB", "pytestmark = pytest.mark.skipif(True, reason='r')"),
        ("TestB", "needs: int = pytest.mark.xfail"),
        ("TestB.test_d", "needs"),
    }


def test_skip_constructs_an_alias_of_an_alias_and_a_dotted_use():
    source = (
        "import pytest\nfrom helpers import marks\n\nbase = pytest.mark.skip\nstack = base\n\n\n"
        "@stack\ndef test_a():\n    pass\n\n\n@marks.base\ndef test_b():\n    pass\n"
    )
    scopes = {scope for scope, _ in _keys(source)}
    assert scopes == {"<module>", "test_a", "test_b"}


def test_skip_constructs_runtime_calls_in_a_test_a_fixture_a_class_body_and_the_module():
    source = (
        "import pytest\nfrom unittest import SkipTest\n\ndocker = pytest.importorskip('docker')\n"
        "if not docker:\n    pytest.skip('no docker', allow_module_level=True)\n\n\n"
        "def test_a():\n    pytest.xfail('later')\n\n\n"
        "@pytest.fixture\ndef stack():\n    pytest.skip('no stack')\n\n\n"
        "class TestB:\n    other = pytest.importorskip('other')\n\n"
        "    def setUp(self):\n        self.skipTest('no')\n\n    def test_c(self):\n        raise SkipTest('x')\n"
    )
    assert _keys(source) == {
        ("<module>", "pytest.importorskip('docker')"),
        ("<module>", "pytest.skip('no docker', allow_module_level=True)"),
        ("test_a", "pytest.xfail('later')"),
        ("stack", "pytest.skip('no stack')"),
        ("TestB", "pytest.importorskip('other')"),
        ("TestB.setUp", "self.skipTest('no')"),
        ("TestB.test_c", "SkipTest('x')"),
    }


def test_skip_constructs_names_imported_from_pytest_and_unittest():
    source = (
        "from pytest import skip, importorskip\nfrom unittest import skipIf\n\nnp = importorskip('numpy')\n\n\n"
        "@skipIf(True, 'r')\ndef test_a():\n    skip('x')\n"
    )
    assert _keys(source) == {
        ("<module>", "importorskip('numpy')"),
        ("test_a", "skipIf(True, 'r')"),
        ("test_a", "skip('x')"),
    }


def test_skip_constructs_counts_repeats_and_ignores_what_is_not_a_skip():
    source = (
        "import pytest\n\n\ndef test_a():\n    pytest.skip('x')\n    if False:\n        pytest.skip('x')\n\n\n"
        "@pytest.mark.parametrize('n', [1])\n@pytest.fixture\ndef test_b(n):\n    assert n\n"
    )
    found = scan.skip_constructs(source)
    assert found == {("test_a", "pytest.skip('x')"): 2}
    more = scan.skip_constructs(source + "\n\ndef test_c():\n    pass\n")
    assert more == found
