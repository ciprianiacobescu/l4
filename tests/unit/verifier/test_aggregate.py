import pytest

from l4.verifier.aggregate import aggregate_criterion, aggregate_unit, judge_findings, pick_verdicts
from l4.verifier.judge import CriterionVerdict, JudgeVerdict
from l4.verifier.types import (
    CounterexampleRun,
    CriterionEvidence,
    CriterionOutcome,
    Finding,
    Severity,
    TracingTest,
    Verdict,
)

from .conftest import judge_reply

ID = "C-0a1b2c3d"
COVERED = CriterionEvidence(ID, "a", "covered", (TracingTest("t.test_a::test_a", "passed", "zero_value"),))


def cv(verdict: str, cid: str = ID) -> CriterionVerdict:
    reply = judge_reply([cid], verdict)
    return JudgeVerdict.model_validate(reply).criteria[0]


def outcome(result: str) -> CriterionOutcome:
    return CriterionOutcome(ID, "a › b › c", result, None, "")  # type: ignore[arg-type]


def finding(severity: Severity, source: str = "deterministic") -> Finding:
    return Finding(severity, "t", "d", source)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("judge", "cx", "result"),
    [
        ("pass", None, "pass"),
        ("fail", "reproduced", "disputed"),  # disputed: a human decides (no tie-breaker); never a FAIL
        ("fail", "not_reproduced", "needs_human"),  # downgraded to insufficient_evidence
        ("fail", "unexecuted", "needs_human"),  # an unexecuted counterexample never makes a FAIL
        ("fail", None, "needs_human"),  # a fail without any counterexample
        ("insufficient_evidence", None, "needs_human"),
        ("not_verifiable", None, "needs_human"),
        (None, None, "needs_human"),  # the judge gave no verdict for this criterion
    ],
)
def test_criterion_rows(judge, cx, result):
    verdict = cv(judge) if judge else None
    run = CounterexampleRun(cx) if cx else None
    assert aggregate_criterion(ID, "alias", verdict, run, trace=COVERED).result == result


def test_a_fail_without_a_reproducing_counterexample_is_recorded_as_insufficient_evidence():
    out = aggregate_criterion(
        ID, "alias", cv("fail"), CounterexampleRun("unexecuted", "not a pytest snippet"), trace=COVERED
    )
    assert out.judge == "fail" and "insufficient_evidence" in out.reason and "not a pytest snippet" in out.reason


@pytest.mark.parametrize(
    ("findings", "criteria", "holds", "verdict"),
    [
        ([], ["pass", "pass"], [], Verdict.PASS),
        ([finding(Severity.MINOR), finding(Severity.MINOR, "judge")], ["pass"], [], Verdict.PASS),
        ([finding(Severity.BLOCKER)], ["pass"], [], Verdict.FAIL),  # a failed step 0, 2 or 3 carries a blocker
        ([finding(Severity.MAJOR)], ["needs_human"], [], Verdict.FAIL),
        ([finding(Severity.BLOCKER)], ["needs_human"], [], Verdict.FAIL),  # FAIL beats NEEDS_HUMAN
        ([], ["pass", "needs_human"], [], Verdict.NEEDS_HUMAN),
        ([finding(Severity.MAJOR, "judge")], ["pass"], [], Verdict.NEEDS_HUMAN),  # judge-only major
        ([finding(Severity.BLOCKER, "judge")], ["pass"], [], Verdict.NEEDS_HUMAN),  # judge-only blocker: never FAIL
        ([], ["pass"], ["the diff was truncated"], Verdict.NEEDS_HUMAN),
        ([], [], ["the unit has no criteria"], Verdict.NEEDS_HUMAN),
    ],
)
def test_unit_verdict(findings, criteria, holds, verdict):
    assert aggregate_unit(findings, [outcome(r) for r in criteria], holds) is verdict


def test_judge_only_major_finding_is_needs_human_not_fail():
    judge = JudgeVerdict.model_validate(
        judge_reply([ID], findings=[{"severity": "major", "title": "t", "detail": "d", "evidence": []}])
    )
    found = judge_findings(judge, known={ID})
    assert [(f.source, f.severity) for f in found] == [("judge", Severity.MAJOR)]
    assert aggregate_unit(found, [outcome("pass")], []) is Verdict.NEEDS_HUMAN


def test_judge_findings_keep_the_spec_gap_flag_and_ignore_an_unknown_criterion_id():
    judge = JudgeVerdict.model_validate(
        judge_reply(
            [ID],
            findings=[
                {
                    "severity": "minor",
                    "title": "t",
                    "detail": "d",
                    "evidence": [],
                    "spec_gap": True,
                    "criterion": "C-ffffffff",
                }
            ],
        )
    )
    (found,) = judge_findings(judge, known={ID})
    assert found.spec_gap and found.criterion is None


def test_when_a_criterion_appears_twice_the_worst_verdict_counts():
    reply = judge_reply([ID, ID])
    reply["criteria"][1]["verdict"] = "fail"
    reply["criteria"][0]["verdict"] = "pass"
    picked = pick_verdicts(JudgeVerdict.model_validate(reply))
    assert picked[ID].verdict == "fail"
    reply["criteria"][1]["verdict"] = "insufficient_evidence"
    assert pick_verdicts(JudgeVerdict.model_validate(reply))[ID].verdict == "insufficient_evidence"


def test_a_reproduced_counterexample_is_disputed_and_needs_a_human_never_a_fail():
    cx = CounterexampleRun("reproduced", "the test failed")
    out = aggregate_criterion(ID, "alias", cv("fail"), cx, trace=COVERED)
    assert out.result == "disputed" and out.reason == "disputed: judge counterexample reproduced"
    assert out.counterexample is cx
    assert aggregate_unit([], [out], []) is Verdict.NEEDS_HUMAN
