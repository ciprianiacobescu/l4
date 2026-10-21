from pathlib import Path

from l4.evidence.testsran import check_tests_ran, file_of_test
from l4.gates.junit import TestCase, TestReport, parse_junit
from l4.verifier.types import Severity

RECORDED = Path(__file__).resolve().parents[2] / "fixtures" / "recorded" / "pytest"


def test_skipped_new_test_is_a_blocker():
    rep = TestReport({
        "tests.test_a::test_new": TestCase("tests.test_a::test_new", "skipped"),
        "tests.test_a::test_ok": TestCase("tests.test_a::test_ok", "passed"),
    })  # fmt: skip
    out = check_tests_ran(
        rep, {"tests.test_a::test_new", "tests.test_a::test_ok"}, {"tests/test_a.py"}, gate_passed=True
    )
    assert [(f.severity, f.source) for f in out.findings] == [(Severity.BLOCKER, "deterministic")]
    assert "tests.test_a::test_new" in out.findings[0].detail and out.label is False
    assert out.summary.skipped == 1 and out.summary.new == 2 and out.summary.new_passed == 1


def test_missing_and_errored_new_tests_are_blockers():
    rep = TestReport({"tests.test_a::test_e": TestCase("tests.test_a::test_e", "error")})
    out = check_tests_ran(rep, {"tests.test_a::test_e", "tests.test_a::test_gone"}, set(), gate_passed=True)
    assert len(out.findings) == 2 and all(f.severity is Severity.BLOCKER for f in out.findings)
    assert out.label is False


def test_label_true_only_when_every_new_test_passed():
    ok = TestReport({
        "tests.test_a::test_new": TestCase("tests.test_a::test_new", "passed"),
        "tests.test_b::test_old": TestCase("tests.test_b::test_old", "passed"),
    })  # fmt: skip
    clean = check_tests_ran(ok, {"tests.test_a::test_new"}, {"tests/test_a.py"}, gate_passed=True)
    assert clean.label is True and clean.findings == []
    assert check_tests_ran(ok, {"tests.test_a::test_new"}, set(), gate_passed=False).label is False
    failing = TestReport({**ok.tests, "tests.test_b::test_old": TestCase("tests.test_b::test_old", "failed")})
    out = check_tests_ran(failing, {"tests.test_a::test_new"}, set(), gate_passed=True)
    assert out.label is False and out.findings == []  # the failing test is the gate's finding, not this check's
    collected = TestReport(ok.tests, collection_errors=["tests/test_c.py"])
    assert check_tests_ran(collected, {"tests.test_a::test_new"}, set(), gate_passed=True).label is False


def test_unchanged_skipped_test_is_listed_only():
    rep = TestReport({
        "tests.test_a::test_new": TestCase("tests.test_a::test_new", "passed"),
        "tests.test_b::test_old": TestCase("tests.test_b::test_old", "skipped"),
        "tests.test_c::test_old": TestCase("tests.test_c::test_old", "skipped"),
    })  # fmt: skip
    out = check_tests_ran(rep, {"tests.test_a::test_new"}, {"tests/test_a.py", "tests/test_c.py"}, gate_passed=True)
    assert [(f.severity, "tests.test_c::test_old" in f.detail) for f in out.findings] == [(Severity.MAJOR, True)]
    assert out.summary.skipped_unchanged == ("tests.test_b::test_old",)
    assert out.label is True
    assert out.all_passed is False  # the question is literal: a skipped test of the run is not a pass (B-M1)


def test_added_files_make_their_testcases_new():
    rep = TestReport({
        "tests.test_a::test_x": TestCase("tests.test_a::test_x", "skipped"),
        "tests.test_a.TestK::test_y[1]": TestCase("tests.test_a.TestK::test_y[1]", "passed"),
    })  # fmt: skip
    out = check_tests_ran(rep, set(), {"tests/test_a.py"}, added_test_files={"tests/test_a.py"}, gate_passed=True)
    assert out.summary.new == 2 and len(out.findings) == 1 and out.findings[0].severity is Severity.BLOCKER


def test_classname_to_file_on_recorded_xunit2():
    rep = parse_junit(RECORDED / "mixed-xunit2.xml")
    files = {"tests/test_mix.py", "tests/other.py"}
    assert {file_of_test(i, files) for i in rep.tests} == {"tests/test_mix.py"}
    assert file_of_test("tests.test_a.TestK::test_y", {"tests/test_a.py"}) == "tests/test_a.py"
    assert file_of_test("tests.test_a::test_y", {"tests/other.py"}) is None
    out = check_tests_ran(rep, {"tests.test_mix::test_skipped", "tests.test_mix::test_pass"}, files, gate_passed=True)
    assert [f.severity for f in out.findings] == [Severity.BLOCKER]  # the skipped new test
    assert out.summary.total == 6 and out.summary.failed == 2 and out.summary.errored == 1 and out.label is False


def test_failed_new_test_is_a_blocker():
    rep = TestReport({"tests.test_a::test_new": TestCase("tests.test_a::test_new", "failed")})
    out = check_tests_ran(rep, {"tests.test_a::test_new"}, {"tests/test_a.py"}, gate_passed=True)
    assert [f.title for f in out.findings] == ["new tests failed"] and out.label is False


def test_added_test_file_that_collected_nothing_is_a_blocker():
    rep = TestReport({"tests.test_ok::test_a": TestCase("tests.test_ok::test_a", "passed")})
    out = check_tests_ran(
        rep, set(), {"tests/check_refunds.py"}, added_test_files={"tests/check_refunds.py"}, gate_passed=True
    )
    assert [(f.title, f.severity) for f in out.findings] == [("new test file ran no test", Severity.BLOCKER)]
    assert "tests/check_refunds.py" in out.findings[0].detail and out.label is False


def test_defines_tests():
    from l4.evidence.collect import defines_tests

    assert defines_tests("def test_a():\n    pass\n") and defines_tests("class TestK:\n    def test_m(self): ...\n")
    assert not defines_tests("def helper():\n    pass\n") and defines_tests("def (:\n")


def test_classname_resolves_under_a_pytest_rootdir_that_is_a_subdirectory():
    """`cd backend && pytest`: the JUnit classname starts at `backend/`, the git path does not."""
    files = {"backend/tests/test_a.py"}
    assert file_of_test("tests.test_a.TestK::test_y", files) == "backend/tests/test_a.py"
    assert file_of_test("tests.test_a::test_y", {"backend/tests/test_a.py", "tests/test_a.py"}) == "tests/test_a.py"
    assert file_of_test("tests.test_a::test_y", {"backend/tests/test_a.py", "worker/tests/test_a.py"}) is None
    assert file_of_test("tests.test_b::test_y", files) is None
    assert file_of_test("test_a::test_y", {"backend/tests/test_a.py"}) == "backend/tests/test_a.py"  # rootdir tests/
    rep = TestReport({"tests.test_a::test_new": TestCase("tests.test_a::test_new", "passed")})
    out = check_tests_ran(
        rep, set(), {"backend/tests/test_a.py"}, added_test_files={"backend/tests/test_a.py"}, gate_passed=True
    )
    assert out.findings == [] and out.label is True and out.summary.new == 1
    skipped = TestReport({
        "tests.test_a::test_new": TestCase("tests.test_a::test_new", "passed"),
        "tests.test_b::test_old": TestCase("tests.test_b::test_old", "skipped"),
    })  # fmt: skip
    out = check_tests_ran(skipped, {"tests.test_a::test_new"}, {"backend/tests/test_b.py"}, gate_passed=True)
    assert [f.title for f in out.findings] == ["existing tests are skipped in a changed test file"]


def test_scenario_h_unchanged_root_test_is_not_attributed_to_an_added_package_test():
    """A-M1: an old skipped `tests/test_util.py` and a new `pkg/tests/test_util.py` that collected nothing."""
    tree = {"tests/test_util.py", "pkg/tests/test_util.py"}
    added = {"pkg/tests/test_util.py"}
    assert file_of_test("tests.test_util::test_old", added, tree) is None
    assert file_of_test("tests.test_util::test_old", {"tests/test_util.py"}, tree) == "tests/test_util.py"
    rep = TestReport({"tests.test_util::test_old": TestCase("tests.test_util::test_old", "skipped")})
    out = check_tests_ran(rep, set(), added, added_test_files=added, tree=tree, gate_passed=True)
    assert [f.title for f in out.findings] == ["new test file ran no test"]
    assert out.label is False and out.summary.new == 0
    assert out.summary.skipped_unchanged == ("tests.test_util::test_old",)


def test_added_file_that_collected_nothing_is_never_tests_ok():
    rep = TestReport({"tests.test_a::test_x": TestCase("tests.test_a::test_x", "passed")})
    added = {"pkg/tests/test_empty.py"}
    tree = {"tests/test_a.py", *added}
    out = check_tests_ran(rep, set(), added, added_test_files=added, tree=tree, gate_passed=True)
    assert out.label is False and [f.title for f in out.findings] == ["new test file ran no test"]
    out = check_tests_ran(TestReport({}), set(), added, added_test_files=added, tree=tree, gate_passed=True)
    assert out.label is False


def test_only_class_names_may_be_dropped_and_ambiguity_resolves_to_nothing():
    assert file_of_test("tests.test_x::t", {"foo/tests/tests.py"}) is None
    assert file_of_test("tests.test_x::t", {"foo/tests/tests.py"}, {"tests.py", "foo/tests/tests.py"}) is None
    assert file_of_test("tests.test_a.TestK.Inner::t", {"b/tests/test_a.py"}) == "b/tests/test_a.py"
    both = {"a/tests/test_a.py", "b/tests/test_a.py"}
    assert file_of_test("tests.test_a::t", {"a/tests/test_a.py"}, both) is None  # ambiguous in the whole tree
    assert file_of_test("tests.test_a::t", {"a/tests/test_a.py"}) == "a/tests/test_a.py"  # no tree: candidates only


def test_all_passed_is_the_literal_question_any_non_passing_test_makes_it_false():
    passing = {"tests.test_a::test_new": TestCase("tests.test_a::test_new", "passed")}
    clean = check_tests_ran(TestReport(passing), {"tests.test_a::test_new"}, set(), gate_passed=True)
    assert clean.label is True and clean.all_passed is True
    for status in ("skipped", "failed", "error"):
        old = {**passing, "tests.test_b::test_old": TestCase("tests.test_b::test_old", status)}
        out = check_tests_ran(TestReport(old), {"tests.test_a::test_new"}, set(), gate_passed=True)
        assert out.all_passed is False, status
    assert (
        check_tests_ran(TestReport(passing), {"tests.test_a::test_new"}, set(), gate_passed=False).all_passed is False
    )
