"""The replies of a diff judged in parts become one verdict (L4-VER-042)."""

from l4.verifier.judge import JudgeVerdict, parse_judge_output
from l4.verifier.judge_parts import merge_part_verdicts

from .conftest import judge_reply

C1, C2, C3 = "C-00000001", "C-00000002", "C-00000003"
NOT_HERE = "not in this part"
CX = {"call": "def test_x():\n    assert f() == 1\n", "expected": "1", "actual": "0"}


def verdict(**over) -> JudgeVerdict:
    ids = over.pop("ids", [C1])
    reply = judge_reply(ids, **over)
    parsed = parse_judge_output(reply)
    assert isinstance(parsed, JudgeVerdict), parsed
    return parsed


def crit(cid: str, word: str, reasoning: str = "", **extra) -> dict:
    ev = [{"kind": "file", "ref": f"src/{reasoning or word}.py", "quote": "x"}]
    return {"id": cid, "verdict": word, "evidence": ev, "reasoning": reasoning, **extra}


def by_id(merged: JudgeVerdict) -> dict:
    return {c.id: c for c in merged.criteria}


def test_one_reply_comes_back_unchanged():
    only = verdict()
    assert merge_part_verdicts([only]) is only


def test_scn_ver_132_a_pass_in_one_part_beats_a_part_that_cannot_see_the_code():
    one = verdict(
        criteria=[crit(C1, "pass", "part-one")],
        feedback=[{"id": "FB-001", "addressed": True, "evidence": "src/a.py:3"}],
    )
    two = verdict(
        criteria=[crit(C1, "insufficient_evidence", NOT_HERE)],
        feedback=[{"id": "FB-001", "addressed": False, "evidence": "not in this part"}],
    )
    merged = merge_part_verdicts([one, two])
    assert by_id(merged)[C1].verdict == "pass" and by_id(merged)[C1].evidence[0].ref == "src/part-one.py"
    (fb,) = merged.feedback or []
    assert fb.addressed is True and fb.evidence == "src/a.py:3"


def test_scn_ver_133_a_fail_in_one_part_wins_and_a_test_any_part_calls_inadequate_is_inadequate():
    adequate = {"test": "tests/test_t.py::t", "criterion": C2, "adequate": True, "reason": "ok"}
    inadequate = {**adequate, "adequate": False, "reason": "asserts nothing"}
    one = verdict(criteria=[crit(C2, "pass", "p1")], test_adequacy=[adequate])
    two = verdict(criteria=[crit(C2, "fail", "p2", counterexample=CX)], test_adequacy=[inadequate])
    merged = merge_part_verdicts([one, two])
    got = by_id(merged)[C2]
    assert got.verdict == "fail" and got.counterexample is not None and got.counterexample.actual == "0"
    (adequacy,) = merged.test_adequacy
    assert adequacy.adequate is False and adequacy.reason == "asserts nothing"


def test_scn_ver_133_the_first_fail_in_part_order_is_the_one_kept():
    one = verdict(criteria=[crit(C1, "fail", "first", counterexample=CX)])
    two = verdict(criteria=[crit(C1, "fail", "second", counterexample=CX)])
    assert by_id(merge_part_verdicts([one, two]))[C1].reasoning == "first"


def test_scn_ver_134_a_part_that_shows_an_item_undone_keeps_it_open_with_its_evidence():
    seen = "src/app/export.py:40 still writes the old header"
    one = verdict(feedback=[{"id": "FB-002", "addressed": True, "evidence": "src/app/a.py:1"}])
    two = verdict(feedback=[{"id": "FB-002", "addressed": False, "evidence": seen}])
    (fb,) = merge_part_verdicts([one, two]).feedback or []
    assert fb.addressed is False and fb.evidence == seen


def test_not_verifiable_beats_insufficient_evidence_and_a_pass_beats_both():
    one = verdict(
        ids=[C1, C2], criteria=[crit(C1, "insufficient_evidence", NOT_HERE), crit(C2, "not_verifiable", "nv")]
    )
    two = verdict(
        ids=[C1, C2], criteria=[crit(C1, "not_verifiable", "nv2"), crit(C2, "insufficient_evidence", NOT_HERE)]
    )
    three = verdict(criteria=[crit(C2, "pass", "yes")])
    merged = by_id(merge_part_verdicts([one, two]))
    assert merged[C1].verdict == "not_verifiable" and merged[C2].verdict == "not_verifiable"
    assert by_id(merge_part_verdicts([one, two, three]))[C2].verdict == "pass"


def test_a_criterion_listed_twice_inside_one_part_counts_its_worst_answer_first():
    one = verdict(criteria=[crit(C1, "pass", "a"), crit(C1, "fail", "b", counterexample=CX)])
    two = verdict(criteria=[crit(C1, "pass", "c")])
    assert by_id(merge_part_verdicts([one, two]))[C1].verdict == "fail"


def test_findings_repeated_across_parts_appear_once():
    f = {"severity": "major", "criterion": C1, "title": "Rounds  Half Up", "detail": "d", "evidence": []}
    g = {**f, "title": "rounds half up", "detail": "other words"}
    h = {**f, "severity": "minor", "title": "style"}
    merged = merge_part_verdicts([verdict(findings=[f]), verdict(findings=[g, h])])
    assert [(x.severity, x.title) for x in merged.findings] == [("major", "Rounds  Half Up"), ("minor", "style")]


def test_riskiest_assumptions_are_three_taken_in_turn():
    one = verdict(riskiest_assumptions=["a1", "a2", "a3"])
    two = verdict(riskiest_assumptions=["b1", "b2", "b3"])
    assert merge_part_verdicts([one, two]).riskiest_assumptions == ["a1", "b1", "a2"]


def test_riskiest_assumptions_stay_three_when_the_parts_repeat_each_other():
    same = ["x", "y", "z"]
    merged = merge_part_verdicts([verdict(riskiest_assumptions=same), verdict(riskiest_assumptions=same)])
    assert merged.riskiest_assumptions == ["x", "y", "z"]
    short = merge_part_verdicts(
        [verdict(riskiest_assumptions=["x", "x", "x"]), verdict(riskiest_assumptions=["x", "x", "x"])]
    )
    assert len(short.riskiest_assumptions) == 3


def test_accepted_and_satisfied_follow_the_feedback_rule():
    one = verdict(
        accepted=[
            {"id": "F-aaaaaa", "addressed": True, "evidence": "src/a.py:1"},
            {"id": "F-bbbbbb", "addressed": True, "evidence": "e"},
        ],
        satisfied=[{"task": "1.1", "holds": True, "evidence": "src/a.py:2"}],
    )
    two = verdict(
        accepted=[
            {"id": "F-aaaaaa", "addressed": False, "evidence": "  Not in this part"},
            {"id": "F-bbbbbb", "addressed": False, "evidence": "src/b.py:9 not done"},
        ],
        satisfied=[{"task": "1.1", "holds": False, "evidence": "src/b.py:3 not done"}],
    )
    merged = merge_part_verdicts([one, two])
    acc = {a.id: a for a in merged.accepted or []}
    assert acc["F-aaaaaa"].addressed is True and acc["F-aaaaaa"].evidence == "src/a.py:1"
    assert acc["F-bbbbbb"].addressed is False and acc["F-bbbbbb"].evidence == "src/b.py:9 not done"
    (sat,) = merged.satisfied or []
    assert sat.holds is False and sat.evidence == "src/b.py:3 not done"


def test_an_item_every_part_says_false_for_with_not_in_this_part_stays_false_with_the_first_evidence():
    one = verdict(feedback=[{"id": "FB-003", "addressed": False, "evidence": "not in this part: one"}])
    two = verdict(feedback=[{"id": "FB-003", "addressed": False, "evidence": "not in this part: two"}])
    (fb,) = merge_part_verdicts([one, two]).feedback or []
    assert fb.addressed is False and fb.evidence == "not in this part: one"


def test_a_list_every_part_left_out_stays_none_and_a_list_one_part_has_is_kept():
    merged = merge_part_verdicts([verdict(), verdict()])
    assert merged.feedback is None and merged.accepted is None and merged.satisfied is None
    kept = merge_part_verdicts([verdict(), verdict(feedback=[{"id": "FB-001", "addressed": True, "evidence": "e"}])])
    assert [f.id for f in kept.feedback or []] == ["FB-001"] and kept.accepted is None


def test_a_part_that_cannot_see_a_test_cannot_mark_it_inadequate():
    """Review N6: the not-in-this-part filter of the feedback items applies to the adequacy of a test too."""
    ok_ = {"test": "tests/test_t.py::t", "criterion": C2, "adequate": True, "reason": "asserts the total"}
    blind = {**ok_, "adequate": False, "reason": "Not in this part: the body of the test is elsewhere"}
    for order in ((ok_, blind), (blind, ok_)):
        merged = merge_part_verdicts([verdict(test_adequacy=[order[0]]), verdict(test_adequacy=[order[1]])])
        (item,) = merged.test_adequacy
        assert item.adequate is True and item.reason == "asserts the total"
    only_blind = merge_part_verdicts([verdict(test_adequacy=[blind]), verdict(test_adequacy=[blind])])
    assert only_blind.test_adequacy[0].adequate is True  # nobody saw it: it is not called inadequate
