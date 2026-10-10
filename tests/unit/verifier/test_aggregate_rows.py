"""SPEC 10.4 rows with tracing evidence and human verdicts (verifier 1.13, 4.7)."""

import pytest

from l4.verifier.aggregate import aggregate_criterion, aggregate_unit
from l4.verifier.judge import JudgeVerdict
from l4.verifier.types import (
    CounterexampleRun,
    CriterionEvidence,
    Finding,
    HumanVerdict,
    Severity,
    TracingTest,
    Verdict,
)

from .conftest import judge_reply

ID = "C-0a1b2c3d"


def verdict(word: str | None):
    return JudgeVerdict.model_validate(judge_reply([ID], word)).criteria[0] if word else None


def evidence(*tests: TracingTest, state: str = "covered", held: str = "") -> CriterionEvidence:
    return CriterionEvidence(ID, "a", state, tests, held=held)  # type: ignore[arg-type]


PASSING = TracingTest("t::a", "passed", "zero_value")
FAILING = TracingTest("t::a", "failed", "zero_value")
INADEQUATE = TracingTest("t::a", "passed", "zero_value", adequate=False)
ACCEPT = HumanVerdict("Q-001", ID, "accept", "ana", "fine", "0" * 64)
REJECT = HumanVerdict("Q-001", ID, "reject", "ana", "wrong rounding", "0" * 64)


def crit(judge, trace, *, human=None, cx=None, strict=True):
    return aggregate_criterion(
        ID, "alias", verdict(judge), cx, trace=trace, human=human, require_traceability=strict
    ).result


@pytest.mark.parametrize(
    ("judge", "trace", "human", "cx", "result"),
    [
        ("pass", evidence(PASSING), None, None, "pass"),
        ("pass", evidence(PASSING, TracingTest("t::b", "passed", "audit")), None, None, "pass"),
        ("fail", evidence(PASSING), None, CounterexampleRun("reproduced"), "disputed"),
        ("fail", evidence(PASSING), None, CounterexampleRun("unexecuted"), "needs_human"),
        ("pass", evidence(FAILING, state="fail"), None, None, "fail"),
        ("pass", evidence(FAILING), None, None, "fail"),  # a failing tracing test beats the judge
        ("pass", evidence(), None, None, "needs_human"),  # uncovered
        ("pass", None, None, None, "needs_human"),  # no trace at all
        ("pass", evidence(INADEQUATE), None, None, "needs_human"),  # an inadequate test is not evidence
        ("not_verifiable", evidence(PASSING), None, None, "needs_human"),
        (None, evidence(PASSING), None, None, "needs_human"),
        ("pass", evidence(PASSING, held="audit test fails at head"), None, None, "needs_human"),
        ("fail", evidence(), ACCEPT, None, "pass"),  # a human accept overrides the judge and uncovered
        ("pass", evidence(PASSING), REJECT, None, "fail"),
        ("pass", evidence(FAILING, state="fail"), ACCEPT, None, "fail"),  # a regression always wins over an accept
        ("pass", evidence(PASSING, held="audit test fails at head"), ACCEPT, None, "pass"),
    ],
)
def test_criterion_rows(judge, trace, human, cx, result):
    assert crit(judge, trace, human=human, cx=cx) == result


def test_uncovered_stays_needs_human_with_traceability_off_because_s1_is_not_built():
    out = aggregate_criterion(ID, "a", verdict("pass"), None, trace=evidence(), require_traceability=False)
    assert out.result == "needs_human" and "S1" in out.reason


def test_unit_fails_on_a_failing_criterion_and_on_a_human_rejected_finding():
    failing = aggregate_criterion(ID, "a", verdict("pass"), None, trace=evidence(FAILING, state="fail"))
    assert aggregate_unit([], [failing], []) is Verdict.FAIL
    rejected = Finding(Severity.MAJOR, "t", "d", "human")
    assert aggregate_unit([rejected], [], []) is Verdict.FAIL
    assert aggregate_unit([Finding(Severity.MAJOR, "t", "d", "judge")], [], []) is Verdict.NEEDS_HUMAN


def test_a_disputed_criterion_needs_a_human():
    out = aggregate_criterion(ID, "a", verdict("fail"), CounterexampleRun("reproduced"), trace=evidence(PASSING))
    assert aggregate_unit([], [out], []) is Verdict.NEEDS_HUMAN


def test_finding_ids_follow_title_and_criterion_not_the_detail():
    a = Finding(Severity.MAJOR, "Rounds wrong", "detail one", "judge", criterion=ID)
    b = Finding(Severity.MAJOR, "Rounds wrong", "another wording", "judge", criterion=ID)
    c = Finding(Severity.MAJOR, "Rounds wrong", "detail one", "judge")
    assert a.id == b.id != c.id and a.id.startswith("F-") and len(a.id) == 10
