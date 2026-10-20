"""`count_named` and `named_tests` (L4-VER-054, SCN-VER-178..181): a test over the cap counts if named."""

from l4.verifier.judge import JudgeVerdict, named_tests
from l4.verifier.judge_parts import _adequacy
from l4.verifier.traceability import count_named, rescue_ceiling, trace_criteria
from l4.verifier.types import CriterionEvidence

from .conftest import judge_reply
from .test_traceability import CFG, case, crit, proof, red_ok, report

A, B, C = "C-aaaaaaaa", "C-bbbbbbbb", "C-cccccccc"


def unit(size: int, traces: int, status: str = "passed") -> list[CriterionEvidence]:
    """`size` criteria (A, B, C, then fillers); `t::flow` traces the first `traces` of them and is proved for each."""
    ids = [A, B, C, *(f"C-{i:08x}" for i in range(size - 3))][:size]
    traced = ids[:traces]
    ledger = [red_ok({i: proof(["t::flow"]) for i in traced})]
    return trace_criteria([crit(i) for i in ids], report(case("t::flow", status, *traced)), ledger, CFG)


def verdict(passed: list[str], failed: list[str] = (), adequacy: list[dict] = (), evidence: dict | None = None):
    reply = judge_reply(passed)
    reply["criteria"] += judge_reply(list(failed), "fail")["criteria"]
    for item in reply["criteria"]:
        if item["id"] in (evidence or {}):
            item["evidence"] = [{"kind": "test", "ref": evidence[item["id"]]}]
    reply["test_adequacy"] = list(adequacy)
    return JudgeVerdict.model_validate(reply)


def entry(criterion: str, adequate: bool = True, test: str = "t::flow", **over) -> dict:
    return {"test": test, "criterion": criterion, "adequate": adequate, **over}


def counted(evidence: list[CriterionEvidence], judge: JudgeVerdict, cap: int = 3) -> dict[str, CriterionEvidence]:
    return {e.criterion: e for e in count_named(evidence, *named_tests(judge), cap=cap)}


def test_a_judge_named_test_over_the_cap_covers_its_criterion():
    out = counted(unit(12, 5), verdict([A], adequacy=[entry(A)]))
    [test] = out[A].tests
    assert out[A].state == "covered"
    assert (test.id, test.proof, test.adequate, test.over_cap, test.status) == (
        "t::flow",
        "zero_value",
        True,
        5,
        "passed",
    )
    assert out[A].ignored == ()
    assert out[B].state == "uncovered" and out[B].ignored  # no entry for B: untouched


def test_a_test_cited_only_by_the_pass_does_not_count():
    judge = verdict([A, B], evidence={A: "t::flow"})
    assert counted(unit(12, 5), judge)[A].state == "uncovered"
    with_entry = verdict([A, B], adequacy=[entry(A)], evidence={A: "t::flow"})
    out = counted(unit(12, 5), with_entry)
    assert out[A].state == "covered" and out[B].state == "uncovered"  # B passed with a file quote only


def test_a_test_over_the_ceiling_never_counts():
    assert rescue_ceiling(5, 3) == 2 and rescue_ceiling(29, 3) == 9 and rescue_ceiling(12, 3) == 6
    all_five = unit(5, 5)
    ids = [e.criterion for e in all_five]
    judge = verdict(ids, adequacy=[entry(i) for i in ids])
    assert {e.state for e in counted(all_five, judge).values()} == {"uncovered"}
    for traces in (15, 10):
        wide = unit(29, traces)
        ids = [e.criterion for e in wide]
        judge = verdict(ids, adequacy=[entry(i) for i in ids])
        assert {e.state for e in counted(wide, judge).values()} == {"uncovered"}
    nine = unit(29, 9)
    judge = verdict([A], adequacy=[entry(A)])
    assert counted(nine, judge)[A].state == "covered"


def test_the_ceiling_follows_the_configured_cap():
    judge = verdict([A], adequacy=[entry(A)])
    assert counted(unit(29, 10), judge, cap=3)[A].state == "uncovered"  # min(14, 9) = 9 < 10
    assert counted(unit(29, 10), judge, cap=4)[A].state == "covered"  # min(14, 12) = 12 >= 10


def test_the_judges_doubt_wins():
    evidence = unit(12, 5)
    both = verdict([A, B], failed=[C], adequacy=[entry(A), entry(B, False)])
    out = counted(evidence, both)
    assert [e.criterion for e in out.values() if e.state == "covered"] == [A]
    assert out[B].state == "uncovered" and out[C].state == "uncovered"
    wholesale = verdict([A, B], failed=[C], adequacy=[entry(A), entry("", False)])
    assert {e.state for e in counted(evidence, wholesale).values()} == {"uncovered"}


def test_a_failing_criterion_stays_failing_and_an_unpassed_one_is_untouched():
    evidence = unit(12, 5)
    judge = verdict([], failed=[A], adequacy=[entry(A)])
    assert counted(evidence, judge)[A].state == "uncovered"
    failing = [
        CriterionEvidence(e.criterion, e.alias, "fail", e.tests, e.ignored, e.held, e.capped) if e.criterion == A else e
        for e in evidence
    ]
    assert counted(failing, verdict([A], adequacy=[entry(A)]))[A].state == "fail"


def test_named_tests_reads_the_worst_verdict_and_the_adequacy_entries():
    reply = judge_reply([A, B])
    reply["criteria"].append({"id": A, "verdict": "fail", "evidence": [{"kind": "file", "ref": "x", "quote": "y"}]})
    reply["criteria"][1]["evidence"] = [{"kind": "test", "ref": "t::flow"}]
    reply["test_adequacy"] = [entry(B), entry(B, False, test="t::other"), entry("", False, test="t::all")]
    passed, named, rejected = named_tests(JudgeVerdict.model_validate(reply))
    assert passed == {B}  # A was answered twice, pass and fail: the worst counts
    assert named == {("t::flow", B)}  # the evidence item of B's pass adds nothing
    assert rejected == {("t::other", B), ("t::all", "")}


def test_a_part_that_never_saw_the_test_names_nothing():
    blind = judge_reply([A])
    blind["test_adequacy"] = [entry(A, False, reason="not in this part")]
    sighted = judge_reply([A])
    merged = _adequacy([JudgeVerdict.model_validate(blind), JudgeVerdict.model_validate(sighted)])
    assert [(m.test, m.criterion, m.adequate) for m in merged] == [("t::flow", A, True)]  # the merge flips it
    reply = judge_reply([A])
    reply["test_adequacy"] = [m.model_dump() for m in merged]
    judge = JudgeVerdict.model_validate(reply)
    assert named_tests(judge)[1] == frozenset()
    assert counted(unit(12, 5), judge)[A].state == "uncovered"
    seen = judge_reply([A])
    seen["test_adequacy"] = [entry(A, reason="Not in this part, but the test asserts it"), entry(A)]
    assert named_tests(JudgeVerdict.model_validate(seen))[1] == frozenset({("t::flow", A)})
