"""detect-test-tamper (third review, item 2): a conftest that rewrites the JUnit report for the unit's own new tests."""

from ..implementer.conftest import green_step, red_step
from .test_ladder import judge_step
from .test_ladder_tamper import BROKEN_IMPL

FORGER = """import atexit as _a
import os as _o
import re as _r


def _f():
    try:
        import pytdd.pricing as _p
    except Exception:
        return
    if not hasattr(_p, "CODES"):  # the stub of red: leave red's failures alone
        return
    path = _o.path.join(".l4" + "-out", "junit.xml")
    try:
        text = open(path).read()
    except OSError:
        return
    if "<failure" not in text:
        return
    text = _r.sub(r"<failure\\b.*?</failure>", "", text, flags=_r.S)
    text = _r.sub(r'failures="\\d+"', 'failures="0"', text)
    open(path, "w").write(text)
    _o._exit(0)


_a.register(_f)
"""


def forged_run(run_l4):
    red = red_step()
    red.writes = {**red.writes, "tests/conftest.py": FORGER}
    green = green_step()
    green.writes = {"src/pytdd/pricing.py": BROKEN_IMPL}
    return run_l4([red, green, judge_step()])


def test_the_report_cross_check_stops_the_forger_wherever_the_scan_does_not_look(run_l4, valid_spec):
    run = forged_run(run_l4)  # the green gate already sees the altered report: the attempt fails, the unit never passes
    reasons = [str(e.get("reason", "")) for e in run.events("task.attempt_failed")]
    assert any("the test report was altered" in r and "tests.test_discount::" in r for r in reasons), reasons
    assert run.code != 0 and run.outcome["units"][0].get("verdict") != "PASS"


def test_the_verifiers_gate_names_an_altered_report_as_its_own_blocker(tmp_path):
    from types import SimpleNamespace

    from l4.gates.junit import TestReport
    from l4.verifier.gates import _judged

    log = tmp_path / "gate.log"
    log.write_text("x\n")
    wb = SimpleNamespace(out_dir=tmp_path / ".l4-out" / "x")
    result = SimpleNamespace(
        status="fail", reason="the test report was altered: tests.test_discount::test_known_code", report=TestReport(),
        log_path=log,
    )  # fmt: skip
    out = _judged(wb, "test", "pytest", "gates.test.reports", result)
    [finding] = out.findings
    assert finding.title == "the test report was altered" and "tests.test_discount::test_known_code" in finding.detail


def test_an_honest_unit_is_not_flagged(run_l4, valid_spec):
    run = run_l4([red_step(), green_step(), judge_step()])
    assert run.code == 0 and "altered" not in run.pushed("openspec/changes/add-discount-codes/verification.md")


FORGER2 = """import io
import re
import sys


def _green():
    try:
        import pytdd.pricing as p
    except Exception:
        return False
    return hasattr(p, "CODES")


def pytest_sessionstart(session):
    if _green():
        getattr(sys.modules.get("l4_trace"), "_OUTCOME_FD", []).clear()


def pytest_sessionfinish(session):
    if _green():
        setattr(session, "exit" + "status", 0)


def pytest_unconfigure(config):
    path = getattr(config.option, "xmlpath", None)
    if not path or not _green():
        return
    try:
        text = io.FileIO(path).read().decode()
    except OSError:
        return
    text = re.sub(r"<failure\\b.*?</failure>", "", text, flags=re.S)
    text = re.sub(r'failures="\\d+"', 'failures="0"', text)
    io.FileIO(path, "w").write(text.encode())
"""


def test_the_fourth_review_forger_that_empties_the_record_still_ends_fail(run_l4, valid_spec):
    red = red_step()
    red.writes = {**red.writes, "tests/conftest.py": FORGER2}
    green = green_step()
    green.writes = {"src/pytdd/pricing.py": BROKEN_IMPL}
    run = run_l4([red, green, judge_step()])
    reasons = [str(e.get("reason", "")) for e in run.events("task.attempt_failed")]
    assert any("the test report was altered" in r for r in reasons), reasons
    assert run.code != 0 and run.outcome["units"][0].get("verdict") != "PASS"
