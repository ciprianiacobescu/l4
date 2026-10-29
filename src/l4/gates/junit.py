"""JUnit XML reports (SPEC L4-GAT-002): one `TestCase` per test, ids stable across runs so that two reports compare.

A test id is `classname::name` (just `name` without a classname), the form both pytest families write; `file::name`
would need `junit_family=xunit1`.
M1: implementer-tdd-loop's other formats (playwright-json, pytest-json, tap) come with gates beyond Python.
"""

import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from l4.security.hardening import XmlRejected, safe_parse_xml

MAX_REPORT_BYTES = 8_000_000
MAX_MESSAGE_CHARS = 500
MAX_DETAIL_CHARS = 4000
Status = Literal["passed", "failed", "error", "skipped"]
FailureKind = Literal["assertion", "not_implemented", "other"]
CRITERION_ID = re.compile(r"C-[0-9a-f]{8}")
_SETUP_WRAPPER = re.compile(r'failed on (setup|teardown) with "(.*)"', re.DOTALL)
_EXCEPTION = re.compile(r"([A-Za-z_][\w.]*)(?::|$)")


class ReportError(ValueError):
    """The report cannot be trusted or read: refused (DTD, size, symlink) or not a JUnit document."""


@dataclass(frozen=True)
class TestCase:
    __test__ = False  # not a pytest class

    id: str
    status: Status
    message: str = ""
    criteria: tuple[str, ...] = ()  # the `l4` properties of the testcase (the l4_trace plugin)
    failure_kind: FailureKind | None = None  # None: not a failure, or a message of no known shape
    detail: str = ""  # the end of the <failure>/<error> body (pytest's traceback text), bounded; "" when none
    when: Literal["", "setup", "teardown"] = ""  # the phase an <error> reports ("failed on setup with ..."); "" else


@dataclass(frozen=True)
class TestReport:
    __test__ = False

    tests: dict[str, TestCase] = field(default_factory=dict)
    collection_errors: list[str] = field(default_factory=list)  # pytest: a module that failed to import
    collection_details: dict[str, str] = field(default_factory=dict)  # a collection error's traceback end, same keys

    @property
    def total(self) -> int:
        return len(self.tests)

    @property
    def executed(self) -> int:
        return sum(case.status != "skipped" for case in self.tests.values())

    def ids_with(self, status: Status) -> set[str]:
        return {i for i, case in self.tests.items() if case.status == status}


_TAGS: tuple[tuple[str, Status], ...] = (("error", "error"), ("failure", "failed"), ("skipped", "skipped"))


_NOT_IMPLEMENTED_TEXT = re.compile(r"\bnot[ _-]?implemented(?:error|exception)?\b", re.IGNORECASE)
_ASSERTION_SUFFIXES = ("AssertionError", "AssertionException", "AssertFailedException", "AssertionFailedError")
_COMPARISON_FAILURE = "ComparisonFailure"  # JUnit 4's assertEquals of two strings (org.junit.ComparisonFailure)
_STUB_ERROR = "UnsupportedOperationException"  # the Java/Kotlin stub form red's prompt names (L4-IMP-002)
_PRESENCE_ASSERTION = "TestingLibraryElementError"  # getBy*/findBy* throw it when absent: Testing Library's assertion
_ASSERTION_NAMESPACES = ("Xunit.Sdk.", "Shouldly.", "FluentAssertions.")


def _type_kind(message: str, type_name: str) -> FailureKind | None:
    """The kind a failure's `type` attribute gives (Vitest writes `AssertionError`, `TypeError`; a .NET converter
    writes the full class name; JUnit 5 writes `org.opentest4j.AssertionFailedError`), used only when the message gave
    none. Matched on the full name, then its last part. Truth prints its facts without a class name, so Surefire takes
    the message's start as the type (`expected` for `expected: 2`): a type equal to the text before the first line's
    `:`, with no `.` and a lower-case first letter, is an assertion (no Java class name meets all three)."""
    name = type_name.strip()
    last = name.rsplit(".", 1)[-1]
    first = message.lstrip().split("\n", 1)[0]
    if name and "." not in name and name[0].islower() and ":" in first and first.split(":", 1)[0] == name:
        return "assertion"
    if not last or not last[0].isupper():
        return None
    if last.endswith(_ASSERTION_SUFFIXES) or last in (_COMPARISON_FAILURE, _PRESENCE_ASSERTION):
        return "assertion"
    if name.startswith(_ASSERTION_NAMESPACES):
        return "assertion"
    if last == "NotImplementedError" or last.endswith("NotImplementedException") or last == _STUB_ERROR:
        return "not_implemented"
    if last == "Error" and _NOT_IMPLEMENTED_TEXT.search(message.lstrip().split("\n", 1)[0]):
        return "not_implemented"
    return "other"


def failure_kind(status: Status, message: str, type_name: str = "") -> FailureKind | None:
    """What a failure message says about how the test failed, from the shapes pytest 9 writes in both families
    (tests/fixtures/recorded/pytest/failure-kinds-*.xml): `assert ...`, `AssertionError[: ...]`, `Failed: ...`
    (`DID NOT RAISE`, `pytest.fail`) are assertions; `NotImplementedError` is the red stub; any other `Name: text`
    is some other exception. The message always wins; only when it gives no kind does `type_name` (the `type`
    attribute of Vitest's and .NET converters' <failure>) decide, by `_type_kind`."""
    if status not in ("failed", "error"):
        return None
    return _message_kind(status, message) or _type_kind(message, type_name)


def _message_kind(status: Status, message: str) -> FailureKind | None:
    wrapped = _SETUP_WRAPPER.fullmatch(message.strip()) if status == "error" else None
    first = (wrapped.group(2) if wrapped else message).lstrip().split("\n", 1)[0]
    if first == "assert" or first.startswith("assert ") or first.startswith("Expectation failed:"):
        return "assertion"  # `Expectation failed:` is Swift Testing's #expect/#require
    if first.startswith("Caught error:"):
        return "other"  # Swift Testing: an error thrown in the test
    named = _EXCEPTION.match(first)
    if named is None or (status == "error" and wrapped is None):
        return None
    name = named.group(1).rsplit(".", 1)[-1]
    if name in ("AssertionError", "Failed", _PRESENCE_ASSERTION):
        return "assertion"
    if name == "NotImplementedError":
        return "not_implemented"
    return "other" if name[0].isupper() else None


def _criteria(case: ET.Element) -> tuple[str, ...]:
    found = (p.get("value") or "" for p in case.findall("properties/property") if p.get("name") == "l4")
    return tuple(dict.fromkeys(v for v in found if CRITERION_ID.fullmatch(v)))


def _status(case: ET.Element) -> tuple[Status, str, str, str]:
    for tag, status in _TAGS:
        child = case.find(tag)
        if child is not None:
            detail = (child.text or "") if status in ("failed", "error") else ""
            message = (child.get("message") or "")[:MAX_MESSAGE_CHARS]
            kind_type = (child.get("type") or "") if status in ("failed", "error") else ""
            return status, message, detail[-MAX_DETAIL_CHARS:], kind_type
    return "passed", "", "", ""


_WORSE = {"error": 3, "failed": 2, "passed": 1, "skipped": 0}


def merge_reports(reports: Sequence[TestReport]) -> TestReport:
    """One report of several (L4-GAT-005: a test gate that runs several suites lists one report each). A test id that
    two reports hold keeps the worse result (error, failed, passed, skipped), so a failure is never hidden by a
    second run of the same test; the collection errors of every report are kept, each once."""
    if len(reports) == 1:
        return reports[0]
    tests: dict[str, TestCase] = {}
    errors: list[str] = []
    details: dict[str, str] = {}
    for report in reports:
        for test_id, case in report.tests.items():
            held = tests.get(test_id)
            if held is None or _WORSE[case.status] > _WORSE[held.status]:
                tests[test_id] = case
        errors += [e for e in report.collection_errors if e not in errors]
        for name, detail in report.collection_details.items():
            details.setdefault(name, detail)
    return TestReport(tests, errors, details)


def parse_junit(path: Path, max_bytes: int = MAX_REPORT_BYTES) -> TestReport:
    try:
        root = safe_parse_xml(path, max_bytes=max_bytes)
    except XmlRejected as exc:
        raise ReportError(str(exc)) from None
    if root.tag not in ("testsuites", "testsuite"):
        raise ReportError(f"{path.name} is not a JUnit report (root element {root.tag!r})")
    tests: dict[str, TestCase] = {}
    collection_errors: list[str] = []
    collection_details: dict[str, str] = {}
    for case in root.iter("testcase"):
        name, classname = case.get("name") or "", case.get("classname") or ""
        status, message, detail, type_name = _status(case)
        error = case.find("error")
        if not classname and error is not None and error.get("message") == "collection failure":
            collection_errors.append(name)  # no individual test ran: the module did not import
            collection_details.setdefault(name, (error.text or "")[-MAX_DETAIL_CHARS:])
            continue
        test_id = f"{classname}::{name}" if classname else name
        kind = failure_kind(status, message, type_name)
        wrapped = _SETUP_WRAPPER.match(message.strip()) if status == "error" else None
        when = "" if wrapped is None else "setup" if wrapped.group(1) == "setup" else "teardown"
        tests[test_id] = TestCase(test_id, status, message, _criteria(case), kind, detail, when)
    return TestReport(tests, collection_errors, collection_details)
