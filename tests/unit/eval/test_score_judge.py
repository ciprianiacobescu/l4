from l4.eval.score import score_judge

from ._ledgers import ev

PASS = {"judge": {"verdict": "PASS"}}
DEFECT = {"judge": {"verdict": "NEEDS_HUMAN", "min_findings": 1, "designed_defect": True}}
REPORT = """# Verification

## Findings

- [major, judge] Fee ignores the balance (criterion C-a6a0f5c9): the fee is constant.
- [minor, judge] Negative balance accepted (spec gap): no check.

## New tests
"""


def verdict(v: str, findings: int = 0, round_: int = 1):
    return ev("verify.verdict", round=round_, verdict=v, findings=findings, criteria_passed=1, criteria_total=2)


def judged(status: str = "ok", round_: int = 1):
    return ev(
        "verify.judge", round=round_, profile="j", status=status, calls=1, model=None, prompt_sha256="x", template="t"
    )


def test_a_pass_on_a_clean_unit_agrees() -> None:
    score = score_judge([judged(), verdict("PASS")], PASS)
    assert score["outcome"] == "pass" and score["agreement"] is True
    assert score["verdict"] == "PASS" and score["findings"] == 0 and score["worst_severity"] is None
    assert score["missed_defect"] is False


def test_holding_back_the_defective_unit_is_agreement() -> None:
    score = score_judge([judged(), verdict("NEEDS_HUMAN", 2)], DEFECT, REPORT)
    assert score["agreement"] is True and score["outcome"] == "pass"
    assert score["findings"] == 2 and score["worst_severity"] == "major"
    assert score["missed_defect"] is False


def test_passing_the_defective_unit_is_a_miss() -> None:
    score = score_judge([judged(), verdict("PASS")], DEFECT)
    assert score["agreement"] is False and score["outcome"] == "fail"
    assert score["missed_defect"] is True


def test_a_verdict_with_fewer_findings_than_the_minimum_does_not_agree() -> None:
    score = score_judge([judged(), verdict("NEEDS_HUMAN", 0)], DEFECT)
    assert score["agreement"] is False and score["missed_defect"] is False


def test_a_fail_where_pass_was_expected_disagrees() -> None:
    score = score_judge([judged(), verdict("FAIL", 1)], PASS, "## Findings\n\n- [blocker, deterministic] boom\n")
    assert score["agreement"] is False and score["worst_severity"] == "blocker"


def test_an_unparsable_reply_is_a_fail_with_the_schema_error_not_invalid() -> None:
    events = [judged("schema_invalid"), judged("schema_invalid")]
    score = score_judge(events, PASS)
    assert score["outcome"] == "fail" and score["verdict"] is None and score["agreement"] is False
    assert score["errors"] == ["schema", "schema"]
    assert score["judge_calls"] == 2


def test_a_schema_error_then_a_valid_verdict_still_counts_the_error() -> None:
    score = score_judge([judged("schema_invalid"), judged(), verdict("PASS")], PASS)
    assert score["outcome"] == "pass" and score["errors"] == ["schema"]


def test_only_the_first_round_scores() -> None:
    score = score_judge([judged(), verdict("NEEDS_HUMAN", 1), judged(round_=2), verdict("PASS", 0, round_=2)], PASS)
    assert score["verdict"] == "NEEDS_HUMAN" and score["agreement"] is False


def test_no_events_is_a_fail() -> None:
    score = score_judge([], PASS)
    assert score["outcome"] == "fail" and score["verdict"] is None
