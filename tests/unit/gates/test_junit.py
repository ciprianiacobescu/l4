from pathlib import Path

import pytest

from l4.gates.junit import ReportError, TestCase, failure_kind, parse_junit

RECORDED = Path(__file__).resolve().parents[2] / "fixtures" / "recorded" / "pytest"


def write(tmp_path: Path, text: str | bytes, name: str = "junit.xml") -> Path:
    path = tmp_path / name
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return path


@pytest.mark.parametrize("family", ["xunit1", "xunit2"])
def test_collection_error_has_no_individual_cases(family: str):
    report = parse_junit(RECORDED / f"collection-error-{family}.xml")
    assert report.tests == {}
    assert report.collection_errors == ["tests.test_broken"]
    assert report.total == 0


@pytest.mark.parametrize("family", ["xunit1", "xunit2"])
def test_every_case_is_reported_individually_with_a_status(family: str):
    report = parse_junit(RECORDED / f"mixed-{family}.xml")
    assert {i: c.status for i, c in report.tests.items()} == {
        "tests.test_mix::test_pass": "passed",
        "tests.test_mix::test_fail": "failed",
        "tests.test_mix::test_param[1]": "passed",
        "tests.test_mix::test_param[2]": "failed",
        "tests.test_mix::test_skipped": "skipped",
        "tests.test_mix::test_error": "error",
    }
    assert report.collection_errors == []
    assert report.total == 6 and report.executed == 5
    assert report.tests["tests.test_mix::test_fail"].message == "assert 1 == 2"
    assert report.tests["tests.test_mix::test_pass"] == TestCase("tests.test_mix::test_pass", "passed", "")


def test_a_bare_testsuite_root_and_a_case_without_classname(tmp_path: Path):
    path = write(tmp_path, '<testsuite><testcase name="test_a"/><testcase classname="m" name="test_b"/></testsuite>')
    assert sorted(parse_junit(path).tests) == ["m::test_b", "test_a"]


def test_report_with_entity_is_rejected(tmp_path: Path):
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><testsuite><testcase name="&a;"/></testsuite>'
    with pytest.raises(ReportError, match="DTD"):
        parse_junit(write(tmp_path, bomb))


def test_a_doctype_hidden_in_another_encoding_is_rejected_too(tmp_path: Path):
    text = '<?xml version="1.0" encoding="utf-16"?><!DOCTYPE x [<!ENTITY a "b">]><testsuite/>'
    with pytest.raises(ReportError, match="DTD"):
        parse_junit(write(tmp_path, text.encode("utf-16")))


def test_oversize_report_is_rejected_without_reading_it(tmp_path: Path):
    path = write(tmp_path, "<testsuite>" + " " * 200 + "</testsuite>")
    with pytest.raises(ReportError, match="larger than"):
        parse_junit(path, max_bytes=100)


@pytest.mark.parametrize("text", ["", "<testsuite><testcase", "<other/>"])
def test_unreadable_reports_are_errors(tmp_path: Path, text: str):
    with pytest.raises(ReportError):
        parse_junit(write(tmp_path, text))


def test_a_symlinked_report_is_refused(tmp_path: Path):
    target = write(tmp_path, "<testsuite/>", "real.xml")
    link = tmp_path / "link.xml"
    link.symlink_to(target)
    with pytest.raises(ReportError, match="symlink"):
        parse_junit(link)


def test_the_failure_body_is_kept_bounded(tmp_path: Path):
    body = "start\n" + "x" * 6000 + "\nE   FileNotFoundError: gone"
    xml = (
        '<testsuite><testcase classname="m" name="test_a"><failure message="boom">'
        + body
        + "</failure></testcase></testsuite>"
    )
    case = parse_junit(write(tmp_path, xml)).tests["m::test_a"]
    assert len(case.detail) == 4000
    assert case.detail.endswith("E   FileNotFoundError: gone")  # the end is kept
    assert case.message == "boom"


def test_a_passing_case_has_no_detail(tmp_path: Path):
    path = write(tmp_path, '<testsuite><testcase classname="m" name="test_a"/></testsuite>')
    assert parse_junit(path).tests["m::test_a"].detail == ""


@pytest.mark.parametrize("family", ["xunit1", "xunit2"])
def test_a_setup_error_records_its_phase(family: str):
    report = parse_junit(RECORDED / f"mixed-{family}.xml")
    assert report.tests["tests.test_mix::test_error"].when == "setup"
    assert {c.when for i, c in report.tests.items() if i != "tests.test_mix::test_error"} == {""}


def test_a_setup_assertion_is_an_assertion_in_setup(tmp_path: Path):
    path = write(
        tmp_path,
        '<testsuites><testsuite><testcase classname="tests.test_spans" name="test_one">'
        '<error message="failed on setup with &quot;assert False is True&quot;">'
        "@pytest.fixture\ndef exporter():\n>       assert telemetry.init(out) is True\n"
        "E       assert False is True\n\ntests/test_spans.py:9: AssertionError"
        "</error></testcase></testsuite></testsuites>",
    )
    case = parse_junit(path).tests["tests.test_spans::test_one"]
    assert (case.status, case.failure_kind, case.when) == ("error", "assertion", "setup")
    assert case.detail.endswith("tests/test_spans.py:9: AssertionError")


def test_collection_errors_keep_their_traceback():
    report = parse_junit(RECORDED / "collection-error-xunit2.xml")
    assert report.collection_details["tests.test_broken"].endswith("E   SyntaxError: invalid syntax")
    from l4.gates.junit import TestReport, merge_reports

    merged = merge_reports([report, TestReport()])
    assert merged.collection_details["tests.test_broken"].endswith("E   SyntaxError: invalid syntax")


@pytest.mark.parametrize(
    ("message", "type_name", "kind"),
    [
        ("expected: 2\nbut was : 3", "expected", "assertion"),
        ("expected to contain: 2\nbut was            : [1]", "expected to contain", "assertion"),
        ("some other text", "expected", None),  # the type is not the message's start
        ("expected 2", "expected", None),  # no ':' in the first line: not a fact
        ("expectedly: 2", "expected", None),  # the type must be the whole text before the colon
        ("a.b: 2", "a.b", None),  # a dotted type is a class name, not a fact
        ("expected: 2", "Expected", "other"),  # a capitalised type is a class name, not the message's start
        ("boom: 2", "boom", "assertion"),  # exactly the rule: the type is the first line's head
        ("x: 1", "org.opentest4j.AssertionFailedError", "assertion"),
        ("x: 1", "org.junit.ComparisonFailure", "assertion"),
        ("x: 1", "ComparisonFailure", "assertion"),
        ("x: 1", "org.example.MyComparisonFailure", "other"),
        ("", "java.lang.UnsupportedOperationException", "not_implemented"),
        ("x: 1", "kotlin.UnsupportedOperationException", "not_implemented"),
        ("x: 1", "java.lang.NullPointerException", "other"),
        ("Expectation failed: 1 + 2 == 2 (error)", "", "assertion"),
        ("Caught error: MyError() (error)", "", "other"),
        ("Expectation failed: false", "java.lang.NullPointerException", "assertion"),  # the message wins
        ("Caught error: x", "org.opentest4j.AssertionFailedError", "other"),
        ("Expectation: x", "", "other"),  # only the full prefix `Expectation failed:` is an assertion
        ("failure", "", None),  # SwiftPM's XCTest
    ],
)
def test_jvm_and_swift_failure_kinds(message: str, type_name: str, kind: str | None):
    """SCN-IMP-415 to SCN-IMP-417 and the limits of the Truth rule (design D2): the type rules apply only when the
    message gave no kind."""
    assert failure_kind("failed", message, type_name) == kind  # type: ignore[arg-type]
