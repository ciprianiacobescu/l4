import pytest

from .conftest import judge_reply
from .test_ladder import CRITERIA, IMPLEMENT, failing_reply, judge_step


@pytest.mark.parametrize(
    ("reply", "code", "phase", "verdict"),
    [
        (judge_reply(CRITERIA), 0, "verified", "PASS"),
        (failing_reply(), 11, "awaiting_human", "NEEDS_HUMAN"),  # a judge fail is needs_human, never FAIL
        (judge_reply(CRITERIA, "insufficient_evidence"), 11, "awaiting_human", "NEEDS_HUMAN"),
    ],
    ids=["pass", "judge-fail", "needs_human"],
)
def test_l4_verify_exit_codes_per_verdict(run_verify, valid_spec, reply, code, phase, verdict):
    run_verify(IMPLEMENT, via="run")  # the judge's turn fails: the unit is left `verifying`, exit 1
    verified = run_verify([judge_step(reply)], via="verify")
    assert verified.code == code
    unit = verified.outcome["units"][0]
    assert unit["phase_before"] == "verifying" and unit["phase_after"] == phase and unit["verdict"] == verdict
