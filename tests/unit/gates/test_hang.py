"""W-D1: reading the hung tests out of a gate run."""

from pathlib import Path

from l4.gates import hang
from l4.gates.hang import HungTest, hung_tests, junit_id
from l4.gates.junit import TestCase, TestReport
from l4.gates.trace import plugin_dir


def test_the_markers_are_the_plugins():
    source = (plugin_dir() / "l4_trace.py").read_text()
    assert f'HANG_MARKER = "{hang.HANG_MARKER}"' in source and f'TIMEOUT_MARKER = "{hang.TIMEOUT_MARKER}"' in source


def test_a_node_id_becomes_the_reports_id():
    assert junit_id("tests/test_x.py::test_a") == "tests.test_x::test_a"
    assert junit_id("tests/test_x.py::TestC::test_m[a-b]") == "tests.test_x.TestC::test_m[a-b]"
    assert junit_id("test_x.py::test_a") == "test_x::test_a"


def test_a_soft_timeout_in_the_report_is_a_hung_test_with_its_frame():
    report = TestReport(
        {
            "t::ok": TestCase("t::ok", "passed"),
            "t::slow": TestCase(
                "t::slow",
                "failed",
                "Failed: l4-test-timeout: the test ran longer than 600s",
                (),
                "assertion",
                "a.recv(1)",
            ),
            "t::bad": TestCase("t::bad", "failed", "assert 1 == 2"),
        }
    )
    assert hung_tests(report) == [HungTest("t::slow", "a.recv(1)")]


def test_a_hang_line_in_the_log_names_the_test_and_keeps_the_frames_after_it():
    log = (
        "collected 3 items\n\nL4_TEST_HANG: tests/test_x.py::TestC::test_slow\n"
        "Thread 0x1 (most recent call first):\n  File x.py, line 3\n"
    )
    [found] = hung_tests(None, log)
    assert found.id == "tests.test_x.TestC::test_slow" and "File x.py, line 3" in found.frame


def test_a_test_in_both_places_is_listed_once_with_the_reports_frame():
    report = TestReport({"t::slow": TestCase("t::slow", "failed", "Failed: l4-test-timeout: x", (), None, "FRAME")})
    found = hung_tests(report, "L4_TEST_HANG: t.py::slow\n")
    assert [h.id for h in found] == ["t::slow"] and found[0].frame == "FRAME"


def test_an_ordinary_run_has_no_hung_test(tmp_path: Path):
    assert hung_tests(TestReport({"t::a": TestCase("t::a", "passed")}), "all fine\n") == []
