"""A criterion that only the per-test cap left uncovered says so (L4-VER-055, SCN-VER-185 to SCN-VER-188)."""

from l4.verifier.aggregate import CAP_ONLY, aggregate_criterion, pick_verdicts
from l4.verifier.judge import JudgeVerdict, named_tests
from l4.verifier.traceability import count_named, trace_criteria
from l4.verifier.types import CriterionEvidence, TracingTest

from .conftest import judge_reply
from .test_traceability import CFG, case, crit, proof, red_ok, report

ID = "C-dddddddd"
TODAY = "uncovered: no adequate discriminating test traces it"


def cv(verdict: str = "pass", cid: str = ID):
    return JudgeVerdict.model_validate(judge_reply([cid], verdict)).criteria[0]


def uncovered(*capped: TracingTest) -> CriterionEvidence:
    return CriterionEvidence(ID, "a", "uncovered", (), (), capped=capped)


def flow(n: int, name: str = "t::missing") -> TracingTest:
    return TracingTest(name, "passed", "red_assertion", over_cap=n)


def reason(trace, judge="pass", **over) -> str:
    return aggregate_criterion(ID, "a", cv(judge) if judge else None, None, trace=trace, **over).reason


def test_the_reason_says_the_judge_passed_it_and_only_the_cap_left_it():
    got = reason(uncovered(flow(7)), cap=3, unit_size=29)
    assert got == (
        "uncovered: the judge passed it, and only the per-test cap left it uncovered: t::missing traces 7 criteria, "
        "more than verifier.max_criteria_per_test (3); the judge did not confirm it for this criterion"
    )
    assert got.startswith(CAP_ONLY)
    result = aggregate_criterion(ID, "a", cv(), None, trace=uncovered(flow(7)), cap=3, unit_size=29)
    assert result.result == "needs_human"


def test_a_candidate_over_the_ceiling_says_so():
    got = reason(uncovered(flow(5)), cap=3, unit_size=8)
    assert got.endswith("(3); it traces more than 4 of the unit's 8 criteria, the most the judge can make count")
    big = reason(uncovered(flow(10)), cap=3, unit_size=29)  # min(14, 9) = 9
    assert big.endswith("it traces more than 9 of the unit's 29 criteria, the most the judge can make count")


def test_more_candidates_name_the_one_with_fewest_criteria():
    got = reason(uncovered(flow(7, "t::seven"), flow(5, "t::five")), cap=3, unit_size=29)
    assert "t::five traces 5 criteria" in got and "t::seven" not in got and got.endswith("criterion (+1 more)")
    tie = reason(uncovered(flow(5, "t::b"), flow(5, "t::a")), cap=3, unit_size=29)
    assert "t::a traces 5 criteria" in tie


def test_a_criterion_the_judge_did_not_pass_keeps_todays_reason():
    capped = uncovered(flow(7))
    for judge in ("fail", "insufficient_evidence", None):
        assert reason(capped, judge, cap=3, unit_size=29) == TODAY
    assert reason(uncovered(), cap=3, unit_size=29) == TODAY  # a pass with no candidate
    assert reason(None) == TODAY


def test_an_in_cap_test_the_judge_called_inadequate_keeps_the_inadequate_reason():
    """SCN-VER-187: the cap is not why the criterion is uncovered when a passing test within it traces it."""
    own = TracingTest("t::own", "passed", "red_assertion", adequate=False)
    inadequate = CriterionEvidence(ID, "a", "uncovered", (own,), (), capped=(flow(7),))
    got = reason(inadequate, cap=3, unit_size=29)
    assert got == "uncovered: the tests that trace it are inadequate or did not pass"
    adequate_and_capped = CriterionEvidence(
        ID, "a", "covered", (TracingTest("t::own", "passed", "red_assertion"),), (), capped=(flow(7),)
    )
    assert not reason(adequate_and_capped, cap=3, unit_size=29).startswith("uncovered")


def test_require_traceability_off_keeps_its_suffix():
    got = reason(uncovered(flow(7)), cap=3, unit_size=29, require_traceability=False)
    assert got.startswith(CAP_ONLY) and got.endswith("; sdd.require_traceability is off but S1 is not available")


def test_a_round_like_the_incident():
    ids = [f"C-{i:08x}" for i in range(29)]
    cases = [case("t::left", "passed", *ids[:6]), case("t::right", "passed", *ids[5:11])]  # 11 criteria, 6 per test
    cases += [case(f"t::own{n}", "passed", cid) for n, cid in enumerate(ids[11:])]  # 18 covered within the cap
    red = {cid: proof([c.id for c in cases if cid in c.criteria]) for cid in ids}
    trace = trace_criteria([crit(i) for i in ids], report(*cases), [red_ok(red)], CFG)
    assert sum(e.state == "covered" for e in trace) == 18 and sum(bool(e.capped) for e in trace) == 11
    capped = [e for e in trace if e.capped]
    cited, uncited, failed = capped[:8], capped[8:10], capped[10]
    reply = judge_reply([e.criterion for e in trace if e is not failed])
    reply["criteria"] += judge_reply([failed.criterion], "fail")["criteria"]
    reply["test_adequacy"] = [{"test": e.capped[0].id, "criterion": e.criterion, "adequate": True} for e in cited] + [
        {"test": failed.capped[0].id, "criterion": failed.criterion, "adequate": False}
    ]
    judge = JudgeVerdict.model_validate(reply)
    picked = pick_verdicts(judge)
    results = {
        e.criterion: aggregate_criterion(e.criterion, "a", picked.get(e.criterion), None, trace=e, cap=3, unit_size=29)
        for e in count_named(trace, *named_tests(judge), cap=3)
    }
    assert sum(r.result == "pass" for r in results.values()) == 26
    for e in uncited:
        assert results[e.criterion].result == "needs_human" and results[e.criterion].reason.startswith(CAP_ONLY)
    assert results[failed.criterion].result == "needs_human" and results[failed.criterion].reason == TODAY
