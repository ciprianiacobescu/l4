"""L4-IMP-105: which regressed pre-existing tests get a re-run (`recheck_candidates`), and the file rule they share with
step 3's repeat (`gate_repeat.untouched`). Pure: no workbench."""

from l4.gates.hang import TIMEOUT_MARKER
from l4.gates.junit import TestCase, TestReport
from l4.implementer.recheck import recheck_candidates
from l4.verifier.gate_repeat import MAX_REPEAT_FAILURES, short_of_time, untouched

TREE = ["tests/test_stack.py", "tests/test_cart.py", "e2e/auth/signin.spec.ts", "e2e/app.spec.ts", "src/app.py"]


def failed(*ids: str, message: str = "boom", status: str = "failed") -> TestReport:
    return TestReport({i: TestCase(i, status, message) for i in ids})  # type: ignore[arg-type]


def always(_id: str) -> bool:
    return True


def test_one_to_five_failed_ids_are_candidates_sorted():
    ids = [f"tests.test_stack::t{n}" for n in range(MAX_REPEAT_FAILURES, 0, -1)]
    assert recheck_candidates(failed(*ids), ids, always) == sorted(ids)
    assert recheck_candidates(failed(ids[0]), [ids[0]], always) == [ids[0]]


def test_six_ids_none_and_a_missing_report_get_no_rerun():
    ids = [f"tests.test_stack::t{n}" for n in range(MAX_REPEAT_FAILURES + 1)]
    assert recheck_candidates(failed(*ids), ids, always) is None
    assert recheck_candidates(failed("a::b"), [], always) is None
    assert recheck_candidates(None, ["a::b"], always) is None


def test_an_id_the_report_lacks_or_that_did_not_fail_is_no_candidate():
    report = TestReport({"a::x": TestCase("a::x", "passed"), "a::y": TestCase("a::y", "skipped")})
    assert recheck_candidates(report, ["a::gone"], always) is None  # gone, not flaky
    assert recheck_candidates(report, ["a::x"], always) is None
    assert recheck_candidates(report, ["a::y"], always) is None
    assert recheck_candidates(failed("a::e", status="error"), ["a::e"], always) == ["a::e"]


def test_a_time_out_marker_gets_no_rerun():
    report = failed("a::b", message=f"{TIMEOUT_MARKER} the test ran longer than 5s")
    assert recheck_candidates(report, ["a::b"], always) is None


def test_one_touched_test_among_the_ids_gets_no_rerun_for_any():
    report = failed("a::b", "a::c")
    assert recheck_candidates(report, ["a::b", "a::c"], lambda i: i != "a::c") is None


def test_untouched_finds_a_python_file_the_unit_did_not_change():
    check = untouched(TREE, {"tests/test_cart.py"}, {"tests.test_new::test_x"})
    assert check("tests.test_stack::test_ready") is True
    assert check("tests.test_cart::test_total") is False  # its file changed
    assert check("tests.test_new::test_x") is False  # a red test
    assert check("tests.test_nowhere::test_y") is False  # no file


def test_untouched_reads_a_typescript_id_among_ts_files_only():
    check = untouched(TREE, {"src/app.py", "e2e/app.spec.ts"}, set())
    assert check("auth/signin.spec.ts::form") is True  # Playwright's id: the file under its test directory
    assert check("app.spec.ts::menu") is False  # the changed spec
    assert untouched(TREE, set(), set())("auth/signin.spec.ts::form") is True


def test_the_room_a_re_run_needs_is_run_1s_duration_times_the_factor_plus_the_margin():
    import threading
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from l4 import deadline
    from l4.availability.cooldown import FakeClock
    from l4.deadline import RunDeadline

    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))

    def armed(left_s: float) -> None:
        deadline.arm(
            RunDeadline(at=clock.now() + timedelta(seconds=left_s), clock=clock, event=threading.Event()),
            timer=lambda seconds, function: SimpleNamespace(start=lambda: None, cancel=lambda: None, daemon=True),
        )

    try:
        assert short_of_time(100.0) is False  # no deadline armed
        armed(159)
        assert short_of_time(100.0) is True and short_of_time(100.0, runs=1.0) is True  # one run: 100 + 60
        armed(161)
        assert short_of_time(100.0) is False  # step 3's repeat has room
        assert short_of_time(100.0, runs=2.0) is True  # a step's re-run does not: 200 + 60 = 260
        armed(259)
        assert short_of_time(100.0, runs=2.0) is True
        armed(261)
        assert short_of_time(100.0, runs=2.0) is False
        armed(2100)  # the margin is a tenth of a long run: 2 x 1000 + 100
        assert short_of_time(1000.0, runs=2.0) is False
        armed(2099)
        assert short_of_time(1000.0, runs=2.0) is True
    finally:
        deadline.disarm()
