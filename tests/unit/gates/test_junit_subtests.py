"""junit-subtests (L4-GAT-006): a unittest subtest is read as part of its test. unittest-xml-reporting writes a
testcase for each failing subtest only (`<method> (params)`, `<method> [msg] (params)`) and, when every subtest
passes, one testcase for the method, so a red id taken from a subtest would never be found again after green."""

from pathlib import Path

import pytest

from l4.gates.junit import fold_subtest_id, parse_junit
from l4.gates.runner import GateResult
from l4.implementer import variant
from l4.implementer.tdd import green_failures
from l4.state.ledger import LedgerEvent
from l4.verifier.ladder import _red_green
from l4.verifier.traceability import red_notes

RECORDED = Path(__file__).resolve().parents[2] / "fixtures" / "recorded" / "xmlrunner"
CLS = "test_forms.FormTests"
REJECTS = f"{CLS}::test_rejects_bad_values_C-1a2b3c4d"
LABELLED = f"{CLS}::test_labelled_subtests"
ACCEPTS = f"{CLS}::test_accepts_a_name"


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(f'<?xml version="1.0"?>\n<testsuites><testsuite name="s">{body}</testsuite></testsuites>')
    return path


def test_failing_subtests_are_one_failed_test_with_the_first_subtest_named():
    report = parse_junit(RECORDED / "subtests-red.xml")
    assert {i: c.status for i, c in report.tests.items()} == {
        ACCEPTS: "passed", LABELLED: "failed", REJECTS: "failed",
    }  # fmt: skip
    rejects = report.tests[REJECTS]
    assert rejects.message == "(value=''): True is not False"
    assert rejects.failure_kind == "assertion"
    assert report.tests[LABELLED].message.startswith("[too long or empty] (value=''): ")
    assert report.total == 3


def test_the_same_tests_pass_when_every_subtest_passes():
    report = parse_junit(RECORDED / "subtests-green.xml")
    assert {i: c.status for i, c in report.tests.items()} == {ACCEPTS: "passed", LABELLED: "passed", REJECTS: "passed"}


def test_red_ids_from_subtests_pass_the_green_check(tmp_path: Path):
    red = parse_junit(RECORDED / "subtests-red.xml")
    red_ids = sorted(i for i, c in red.tests.items() if c.status == "failed")
    green = parse_junit(RECORDED / "subtests-green.xml")
    gate = GateResult("test", "pass", "", 0, tmp_path / "test.log", green)
    assert green_failures(red, red_ids, gate) == ("", [])


def test_an_erroring_subtest_is_worse_than_a_failing_one(tmp_path: Path):
    report = parse_junit(write(tmp_path, (
        '<testcase classname="pkg.test_a.T" name="test_x (n=1)"><failure message="1 != 2" type="AssertionError"/>'
        "</testcase>"
        '<testcase classname="pkg.test_a.T" name="test_x (n=2)"><error message="boom" type="AttributeError"/>'
        "</testcase>"
    )))  # fmt: skip
    case = report.tests["pkg.test_a.T::test_x"]
    assert (case.status, case.message, case.failure_kind) == ("error", "(n=2): boom", "other")
    assert list(report.tests) == ["pkg.test_a.T::test_x"]


def test_a_failing_subtest_keeps_a_passing_parent_entry_failed(tmp_path: Path):
    report = parse_junit(write(tmp_path, (
        '<testcase classname="pkg.test_a.T" name="test_x (n=1)"><failure message="no" type="AssertionError"/>'
        "</testcase>"
        '<testcase classname="pkg.test_a.T" name="test_x"/>'
    )))  # fmt: skip
    assert report.tests["pkg.test_a.T::test_x"].status == "failed"


def test_names_that_are_not_python_subtests_stay_as_they_are(tmp_path: Path):
    report = parse_junit(write(tmp_path, (
        '<testcase classname="tests.test_mix" name="test_param[a (1)]"/>'  # a pytest parameter id
        '<testcase classname="src/list.test.ts" name="renders the list (empty)"/>'  # a JavaScript title
        '<testcase classname="ListTests" name="works when empty (case 1)"/>'  # words before the brackets
        '<testcase classname="com.example.CalcTest" name="sum (positive)"/>'  # a display name, not a test… method
        '<testcase name="test_y (n=1)"/>'  # no classname
    )))  # fmt: skip
    assert sorted(report.tests) == [
        "ListTests::works when empty (case 1)",
        "com.example.CalcTest::sum (positive)",
        "src/list.test.ts::renders the list (empty)",
        "test_y (n=1)",
        "tests.test_mix::test_param[a (1)]",
    ]


def test_a_duplicate_id_that_is_no_subtest_keeps_the_last_entry(tmp_path: Path):
    report = parse_junit(write(tmp_path, (
        '<testcase classname="pkg.T" name="test_z"><failure message="first" type="AssertionError"/></testcase>'
        '<testcase classname="pkg.T" name="test_z"/>'
    )))  # fmt: skip
    assert report.tests["pkg.T::test_z"].status == "passed"  # as before this change


@pytest.mark.parametrize(
    ("stored", "test"),
    [
        (f"{REJECTS} (value='')", REJECTS),
        (f"{LABELLED} [too long or empty] (value='')", LABELLED),
        ("pkg.T::test_x (v='a::b')", "pkg.T::test_x"),
        (REJECTS, REJECTS),
        ("tests.test_mix::test_param[a (1)]", "tests.test_mix::test_param[a (1)]"),
        ("src/list.test.ts::renders the list (empty)", "src/list.test.ts::renders the list (empty)"),
        ("test_y (n=1)", "test_y (n=1)"),
    ],
)
def test_a_stored_subtest_id_names_its_test(stored: str, test: str):
    assert fold_subtest_id(stored) == test


def test_red_ids_written_before_the_rule_pass_the_green_check(tmp_path: Path):
    """A unit whose red step ran before L4-GAT-006 resumes at green with the subtest ids of its `task.red_ok`."""
    stored = [f"{REJECTS} (value='')", f"{REJECTS} (value=' ')", f"{LABELLED} [too long or empty] (value='')"]
    green = parse_junit(RECORDED / "subtests-green.xml")
    gate = GateResult("test", "pass", "", 0, tmp_path / "test.log", green)
    assert green_failures(parse_junit(RECORDED / "subtests-red.xml"), stored, gate) == ("", [])


def test_the_verifier_expects_the_test_of_a_stored_subtest_id():
    events = [LedgerEvent(None, "run-a", "openspec:x", 1, "task.red_ok", {"task": "1.2", "tests": [  # type: ignore[arg-type]
        f"{REJECTS} (value='')", f"{REJECTS} (value=' ')", ACCEPTS,
    ]})]  # fmt: skip
    assert _red_green(events) == {REJECTS: "1.2", ACCEPTS: "1.2"}


NI = '<error message="not yet" type="NotImplementedError"/>'
TYPE = '<error message="f() takes 1 positional argument but 2 were given" type="TypeError"/>'


@pytest.mark.parametrize("order", [(NI, TYPE), (TYPE, NI)])
def test_of_two_equal_results_the_worse_kind_is_the_test(tmp_path: Path, order: tuple[str, str]):
    """A subtest that stops on a wrong call is not hidden by one that reaches the stub, in either order."""
    first, second = order
    report = parse_junit(write(tmp_path, (
        f'<testcase classname="pkg.test_a.T" name="test_x (n=1)">{first}</testcase>'
        f'<testcase classname="pkg.test_a.T" name="test_x (n=2)">{second}</testcase>'
    )))  # fmt: skip
    case = report.tests["pkg.test_a.T::test_x"]
    assert (case.status, case.failure_kind) == ("error", "other")
    assert "takes 1 positional argument" in case.message


def test_a_subtest_that_failed_by_assertion_proves_the_test_in_a_variant_run(tmp_path: Path):
    """Under the zero values one subtest fails by assertion and another errors: the test discriminates."""
    report = parse_junit(write(tmp_path, (
        '<testcase classname="pkg.test_a.T" name="test_x (n=1)"><failure message="0 != 3" type="AssertionError"/>'
        "</testcase>"
        '<testcase classname="pkg.test_a.T" name="test_x (n=2)"><error message="len() of None" type="TypeError"/>'
        "</testcase>"
    )))  # fmt: skip
    case = report.tests["pkg.test_a.T::test_x"]
    assert (case.status, case.assertion_failed) == ("error", True)
    run = variant.VariantRun("zero-value", report)
    assert variant.test_outcome(run, "pkg.test_a.T::test_x", None, ()) == ("proof", "")


def test_a_very_long_name_is_not_read_as_a_subtest(tmp_path: Path):
    name = "test_x [" + "] (" * 1000 + ")"
    report = parse_junit(write(tmp_path, f'<testcase classname="pkg.T" name="{name}"/>'))
    assert list(report.tests) == [f"pkg.T::{name}"]


def test_a_module_with_a_non_ascii_name_folds_too(tmp_path: Path):
    report = parse_junit(write(tmp_path, (
        '<testcase classname="pkg.test_ünï.T" name="test_x (v=1)"><failure message="no" type="AssertionError"/>'
        "</testcase>"
    )))  # fmt: skip
    assert list(report.tests) == ["pkg.test_ünï.T::test_x"]


def test_the_label_of_an_unproven_red_record_names_the_test_of_a_stored_subtest_id():
    info = {"proof": "zero_value", "via": "not_applicable", "tests": [f"{REJECTS} (value='')"], "discriminating": ["x"]}
    events = [LedgerEvent(None, "run-a", "openspec:x", 1, "task.red_ok", {"task": "1.2", "criteria": {  # type: ignore[arg-type]
        "C-1a2b3c4d": info,
    }})]  # fmt: skip
    assert set(red_notes(events)) == {("C-1a2b3c4d", REJECTS)}
