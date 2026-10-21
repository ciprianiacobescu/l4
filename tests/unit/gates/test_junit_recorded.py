"""M13-G1: the JUnit XML of real pytest, both families, as the red rules need it (recorded by
scripts/record_pytest_junit.sh with the pytest version in PYTEST_VERSION)."""

from pathlib import Path

import pytest

from l4.gates.junit import failure_kind, parse_junit

RECORDED = Path(__file__).resolve().parents[2] / "fixtures" / "recorded" / "pytest"
FAMILIES = ["xunit1", "xunit2"]


@pytest.mark.parametrize("family", FAMILIES)
def test_trace_and_failure_kinds_both_families(family: str):
    traced = parse_junit(RECORDED / f"trace-{family}.xml").tests
    assert {i.split("::")[-1]: c.criteria for i, c in traced.items()} == {
        "test_two_ids": ("C-aaaaaaaa", "C-bbbbbbbb"),
        "test_failing_with_id": ("C-aaaaaaaa",),
        "test_param[1]": ("C-cccccccc",),
        "test_param[2]": ("C-cccccccc",),
        "test_untagged": (),
        "test_in_class": ("C-dddddddd",),
    }
    assert traced["tests.test_trace.TestGroup::test_in_class"].criteria == ("C-dddddddd",)
    failures = parse_junit(RECORDED / f"failure-kinds-{family}.xml").tests
    kinds = {i.split("::")[-1]: c.failure_kind for i, c in failures.items()}
    assert kinds == {
        "test_assert": "assertion",
        "test_assert_message": "assertion",
        "test_raises_did_not_raise": "assertion",
        "test_not_implemented": "not_implemented",
        "test_not_implemented_with_text": "not_implemented",
        "test_type_error": "other",
        "test_attribute_error": "other",
        "test_value_error": "other",
        "test_explicit_fail": "assertion",
    }


def test_a_passing_case_has_no_failure_kind():
    case = parse_junit(RECORDED / "trace-xunit2.xml").tests["tests.test_trace::test_two_ids"]
    assert case.status == "passed" and case.failure_kind is None


@pytest.mark.parametrize(
    ("status", "message", "kind"),
    [
        ("failed", "assert 1 == 2", "assertion"),
        ("failed", "assert", "assertion"),
        ("failed", "assertionerror", None),
        ("failed", "AssertionError", "assertion"),
        ("failed", "Failed: DID NOT RAISE <class 'ValueError'>", "assertion"),
        ("failed", "NotImplementedError", "not_implemented"),
        ("failed", "builtins.NotImplementedError: x", "not_implemented"),
        ("failed", "pkg.errors.Boom: x", "other"),
        ("failed", "KeyError: 'a'", "other"),
        ("failed", "", None),
        ("failed", "something odd happened", None),
        ("error", 'failed on setup with "NotImplementedError"', "not_implemented"),
        ("error", 'failed on setup with "RuntimeError: fixture exploded"', "other"),
        ("failed", "TestingLibraryElementError: Unable to find an element with the text: x", "assertion"),
        ("failed", "testing_library.TestingLibraryElementError: Unable to find role", "assertion"),
        ("error", "collection failure", None),
        ("passed", "", None),
        ("skipped", "later", None),
    ],
)
def test_failure_kind_of_a_message(status: str, message: str, kind: str | None):
    assert failure_kind(status, message) == kind  # type: ignore[arg-type]


def test_vitest_failures_are_classified_from_the_type_attribute():
    """SCN-IMP-70, SCN-IMP-78. Vitest 4.1.2 (`--reporter=junit`) writes a plain message and the class in `type`."""
    cases = parse_junit(RECORDED.parent / "vitest" / "failure-kinds.xml").tests
    assert [c.failure_kind for c in cases.values()] == [
        "assertion", "assertion", "not_implemented", "not_implemented", "other", "assertion", "assertion",
    ]  # fmt: skip
    assert [c.criteria for c in cases.values()] == [()] * 7  # the ids are in the names, which trace_ids reads


@pytest.mark.parametrize(
    ("message", "type_name", "kind"),
    [
        ("expected 1 to be 2", "AssertionError", "assertion"),
        ("x", "chai.AssertionError", "assertion"),
        ("x", "NotImplementedError", "not_implemented"),
        ("Not Implemented", "Error", "not_implemented"),
        ("NotImplementedError: later\nmore", "Error", "not_implemented"),
        ("not implemented yet", "Error", "not_implemented"),
        ("boom", "Error", "other"),
        ("boom", "TypeError", "other"),
        ("boom", "", None),
        ("boom", "pytest.skip", None),
        ("assert 1 == 2", "TypeError", "assertion"),  # a message that gives a kind wins over the type
        ("AssertionError: Assert.Equal() Failure", "Xunit.Sdk.EqualException", "assertion"),
        ("NotImplementedError: later", "System.NotImplementedException", "not_implemented"),
        ("NotImplementedError: later", "Xunit.Sdk.EqualException", "not_implemented"),
        ("TypeError: x", "NUnit.Framework.AssertionException", "other"),
        ("Assert.Equal() Failure", "Xunit.Sdk.EqualException", "assertion"),
        ("Expected 1 but was 2", "NUnit.Framework.AssertionException", "assertion"),
        ("Assert.AreEqual failed", "Microsoft.VisualStudio.TestTools.UnitTesting.AssertFailedException", "assertion"),
        ("should be 1", "Shouldly.ShouldAssertException", "assertion"),
        ("Expected x to be 1", "FluentAssertions.Execution.AssertionFailedException", "assertion"),
        ("The method is not implemented.", "System.NotImplementedException", "not_implemented"),
        ("Object reference not set", "System.NullReferenceException", "other"),
        ("boom", "System.InvalidOperationException", "other"),
        ("boom", "MyXunit.Sdk.Thing", "other"),
        ("Unable to find an element with the text: Rendering Error", "TestingLibraryElementError", "assertion"),
        ("Unable to find role", "TestingLibraryElementError", "assertion"),  # getBy*/findBy* absent
        ("Unable to find", "MyTestingLibraryElementError", "other"),
    ],
)
def test_the_type_attribute_is_the_fallback_when_the_message_gives_no_kind(message, type_name, kind):
    assert failure_kind("failed", message, type_name) == kind
