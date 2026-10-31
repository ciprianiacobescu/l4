"""The carry-over of L4-VER-072 inside a round: step 10 after a step 9 whose judge gave no verdict (SCN-VER-273,
SCN-VER-277). Round 1 passes three criteria at head H1 and stores its evidence; round 3 adds one test file at H3 and its
judge times out. A real bench (a worktree with a ledger), a stub judge, the real ladder functions."""

import json

import pytest

from l4.llm.agent_judge import StructuredResult
from l4.state.ledger import read_ledger
from l4.verifier import ladder
from l4.verifier.aggregate import aggregate_criterion
from l4.verifier.ladder import VerifyContext, _calibrate, _events, _resume, _Run
from l4.verifier.report import verdict_json, write_round_evidence
from l4.verifier.types import CriterionEvidence, HumanVerdict, StepRecord, TracingTest, Verdict, VerifyResult
from l4.verifier.verdicts import finding_sha256, hold_id, text_sha256

from .conftest import judge_reply
from .test_judge_run import Scripted, ok
from .test_judge_step_followup import SCN_190, World, passing

THIRD = "\n#### Scenario: Third\n- **WHEN** `total([])` is called\n- **THEN** it returns `0`\n"
T_EXPORT, T_REPORT = "tests.test_export::test_csv", "tests.test_report::test_header"
NEW_TEST = "def test_new():\n    assert True\n"
DISCARDED = "the judge's reply was discarded (timeout: no answer within 60s)"
NONE_ASKED = "the judge gave no verdict for this criterion"


def timeouts() -> Scripted:
    return Scripted(*(StructuredResult("timeout", detail="no answer within 60s") for _ in range(2)))


class Carry(World):
    """Round 1 at H1: A and C traced by `tests.test_export::test_csv`, B by `tests.test_report::test_header`; the judge
    passes all three and the round's evidence is stored in the unit directory."""

    def __init__(self, make_bench, monkeypatch, *, adequacy=()) -> None:
        super().__init__(make_bench, monkeypatch, cap=120_000)
        spec = self.wb.ref.path / "specs" / "pricing" / "spec.md"
        spec.write_text(spec.read_text() + THIRD)
        self.wb.cfg.verifier.judge_length_splits = 0  # a timeout is retried once, then holds the round
        self.commit("1.1", {"src/app/export.py": SCN_190["src/app/export.py"], "tests/test_export.py":
                            SCN_190["tests/test_export.py"]}, tick=True)  # fmt: skip
        self.commit("1.2", {"src/app/report.py": SCN_190["src/app/report.py"],
                            "tests/test_report.py": SCN_190["tests/test_report.py"]})  # fmt: skip
        self.criteria = self.wb.provider.criteria(self.wb.ref)
        self.a, self.b, self.c = self.ids = [c.id for c in self.criteria]
        assert len(self.ids) == 3
        named = {"a": self.a, "b": self.b, "c": self.c, "": ""}
        rows = [{"test": t, "criterion": named[who], "adequate": good, "reason": "r"} for t, who, good in adequacy]
        self.run(ok(judge_reply(self.ids, test_adequacy=rows)), trace=self.trace1(), round_no=1)
        self.finalize()
        assert self.result.verdict is (Verdict.NEEDS_HUMAN if adequacy else Verdict.PASS)
        self.rows = {row["id"]: row for row in self.result.judge_verdict["criteria"]}
        write_round_evidence(self.wb.ref.path, 1, self.result, self.wb.redactor)
        self.h1 = self.result.head_sha
        self.commit("1.3", {})  # the evidence is committed with the unit, as a real round's is

    def trace1(self):
        return [passing(self.a, (T_EXPORT,)), passing(self.b, (T_REPORT,)), passing(self.c, (T_EXPORT,))]

    def trace3(self, c_tests=(T_EXPORT, "tests.test_new::test_new")):
        return [passing(self.a, (T_EXPORT,)), passing(self.b, (T_REPORT,)), passing(self.c, c_tests)]

    def add_new_test(self) -> None:
        self.commit("2.1", {"tests/test_new.py": NEW_TEST})

    def round3(self, backend=None, *, trace=None, round_no: int = 3):
        """Step 9 with `backend` (a judge that times out) and step 10, as a fresh round does."""
        self.result = VerifyResult(self.wb.ref.id, round_no, Verdict.NEEDS_HUMAN, self.base, self.wb.head())
        self.result.trace = list(trace if trace is not None else self.trace3())
        self.judge = backend or timeouts()
        self.vc = VerifyContext(self.wb, self.judge, "judge", ["impl"], round_no, 60)  # type: ignore[arg-type]
        self.run_ = _Run(self.result)
        self.events = _events(self.wb)
        ladder._judge_step(self.vc, self.run_, self.base, self.events)
        return self.finalize()

    def data(self, kind: str) -> list[dict]:
        return [dict(e.data) for e in _events(self.wb) if e.type == kind]

    def carried_reason(self) -> str:
        return (
            f"the judge of round 1 passed it at {self.h1[:10]}, and only tests that do not trace it changed since "
            "(carried)"
        )


@pytest.fixture
def carry(make_bench, monkeypatch) -> Carry:
    return Carry(make_bench, monkeypatch)


# --- SCN-VER-273 -------------------------------------------------------------------------------------------------


def test_scn_ver_273_a_timed_out_judge_after_a_test_only_change_asks_only_about_the_new_tests_criteria(carry):
    carry.add_new_test()
    out = carry.round3()
    a, b, c = out[carry.a], out[carry.b], out[carry.c]
    assert carry.judge.calls and len(carry.judge.calls) == 2  # the judge was asked, twice, and gave nothing
    assert (a.result, a.reason) == ("pass", carry.carried_reason())
    assert (b.result, b.reason) == ("pass", carry.carried_reason())
    assert (c.result, c.reason) == ("needs_human", NONE_ASKED)  # C is traced by the new test: asked as before
    assert carry.result.holds == [DISCARDED] and carry.result.verdict is Verdict.NEEDS_HUMAN
    assert carry.run_.records["9"].status == "failed"
    events = carry.data("verify.carried")
    assert [(e["criterion"], e["round"], e["from_round"], e["from_head"]) for e in events] == [
        (carry.a, 3, 1, carry.h1), (carry.b, 3, 1, carry.h1),
    ]  # fmt: skip
    assert carry.data("verify.not_carried") == []


def test_scn_ver_273_the_round_keeps_its_hold_and_cannot_pass_even_when_every_criterion_is_carried(carry):
    carry.commit("2.1", {"tests/test_new.py": NEW_TEST})  # a test that traces no criterion
    out = carry.round3(trace=carry.trace1())
    assert {o.result for o in out.values()} == {"pass"} and {o.reason for o in out.values()} == {carry.carried_reason()}
    assert carry.result.holds == [DISCARDED] and carry.result.verdict is Verdict.NEEDS_HUMAN
    assert carry.result.findings == []  # findings are not carried


def test_the_judge_columns_stored_verdict_and_calibration_see_no_carried_verdict(carry, monkeypatch):
    carry.add_new_test()
    carry.round3()
    assert carry.run_.judged is None and carry.result.judge_verdict is None
    stored = verdict_json(carry.result)
    assert stored["judge_verdict"] is None
    assert sorted(stored["judge_carried"]) == sorted([carry.a, carry.b])
    assert stored["judge_carried"][carry.a] == {
        "round": 1, "head": carry.h1, "verdict": carry.rows[carry.a], "adequacy": [],
    }  # fmt: skip
    seen: dict = {}
    monkeypatch.setattr(ladder, "record_rows", lambda *a, **kw: seen.update(kw))
    carry.run_.s1, carry.vc.s1 = object(), object()  # type: ignore[assignment]
    _calibrate(carry.vc, carry.run_)
    assert seen["judge"] == {}


def test_a_person_s_verdict_and_a_failing_tracing_test_still_decide_a_carried_criterion(carry):
    carry.add_new_test()
    criterion = next(c for c in carry.criteria if c.id == carry.a)
    carry.wb.emit(
        "human.verdict", question="Q-001", target=carry.a, decision="reject", by="alex", reason="wrong",
        text_sha256=text_sha256(criterion),
    )  # fmt: skip
    trace = carry.trace3(c_tests=(T_EXPORT,))
    trace[1] = CriterionEvidence(carry.b, "alias", "fail", (TracingTest(T_REPORT, "failed", "red_assertion"),))
    out = carry.round3(trace=trace)
    assert out[carry.a].result == "fail" and out[carry.a].reason.startswith("rejected by alex")
    assert out[carry.b].result == "fail" and out[carry.b].reason.startswith("a tracing test fails at head")
    assert (out[carry.c].result, out[carry.c].reason) == ("pass", carry.carried_reason())


@pytest.mark.parametrize("who", ["b", ""])  # a row for B, and a row of no criterion (the test everywhere)
def test_the_adequacy_rows_of_the_earlier_judge_are_applied_with_the_carried_pass_and_stored(
    make_bench, monkeypatch, who
):
    world = Carry(make_bench, monkeypatch, adequacy=[(T_REPORT, who, False)])  # B's test, called inadequate in round 1
    world.commit("2.1", {"tests/test_new.py": NEW_TEST})
    out = world.round3(trace=world.trace1())
    # the carried pass cannot make B a pass: its only test is inadequate again, as in round 1
    assert out[world.b].result == "needs_human" and out[world.b].reason.startswith("uncovered: the tests that trace")
    assert out[world.a].result == "pass"
    stored = {e.criterion: e for e in world.result.trace}
    assert [t.adequate for t in stored[world.b].tests] == [False] and [t.adequate for t in stored[world.a].tests] == [
        True
    ]
    assert world.result.judge_carried[world.b]["adequacy"][0]["adequate"] is False


# --- SCN-VER-274 and the reads that fail -------------------------------------------------------------------------


def test_scn_ver_274_a_production_change_carries_nothing_and_the_ledger_says_why(carry):
    carry.commit("2.1", {"tests/test_new.py": NEW_TEST, "src/app/export.py": SCN_190["src/app/export.py"] + "y = 2\n"})
    out = carry.round3()
    assert {o.reason for o in out.values()} == {NONE_ASKED} and carry.result.judge_carried == {}
    assert carry.data("verify.carried") == []
    (event,) = carry.data("verify.not_carried")
    assert event["reason"] == "a non-test file changed" and event["paths"] == ["src/app/export.py"]
    assert (event["round"], event["from_round"]) == (3, 1)


def test_a_round_with_no_earlier_judge_verdict_carries_nothing_and_says_so(carry):
    carry.add_new_test()
    (carry.wb.ref.path / ".l4" / "evidence" / "round-1" / "verdict.json").unlink()
    out = carry.round3()
    assert {o.reason for o in out.values()} == {NONE_ASKED}
    (event,) = carry.data("verify.not_carried")
    assert event["from_round"] is None and "no earlier round" in event["reason"] and event["paths"] == []


# --- SCN-VER-277 -------------------------------------------------------------------------------------------------


def test_scn_ver_277_a_round_whose_judge_answered_carries_nothing(carry):
    carry.add_new_test()
    answered = judge_reply(carry.ids, "insufficient_evidence")
    out = carry.round3(Scripted(ok(answered)))
    assert {o.reason for o in out.values()} == {"the judge answered insufficient_evidence"}
    assert (
        carry.result.judge_carried == {}
        and carry.data("verify.carried") == []
        and carry.data("verify.not_carried") == []
    )
    assert carry.run_.judged is not None and carry.result.judge_verdict is not None


def test_scn_ver_277_a_round_whose_step_9_did_not_run_carries_nothing(carry):
    carry.add_new_test()
    carry.result = VerifyResult(carry.wb.ref.id, 3, Verdict.NEEDS_HUMAN, carry.base, carry.wb.head())
    carry.result.trace = carry.trace3()
    carry.vc = VerifyContext(carry.wb, Scripted(), "judge", ["impl"], 3, 60)  # type: ignore[arg-type]
    carry.run_ = _Run(carry.result)
    carry.run_.records["9"] = StepRecord("9", "judge", "not_run", note="an earlier step failed")
    carry.events = _events(carry.wb)
    out = carry.finalize()
    assert {o.reason for o in out.values()} == {NONE_ASKED}
    assert (
        carry.result.judge_carried == {}
        and carry.data("verify.carried") == []
        and carry.data("verify.not_carried") == []
    )


def test_scn_ver_277_a_resumed_round_keeps_its_carried_passes_with_no_judge_call_and_no_read_of_round_1(carry):
    carry.add_new_test()
    carry.round3()
    hold = carry.result.holds[0]
    prev = json.loads(json.dumps(verdict_json(carry.result)))
    for target, sha in ((hold_id(hold), finding_sha256(hold_id(hold))), (carry.c, text_sha256(carry.criteria[2]))):
        carry.wb.emit(
            "human.verdict", question="Q-002", target=target, decision="accept", by="alex", reason="checked",
            text_sha256=sha,
        )  # fmt: skip
    # nothing of round 1 can be read: the verdicts must come from round 3's own record
    shutil_round = carry.wb.ref.path / ".l4" / "evidence" / "round-1"
    for path in shutil_round.iterdir():
        path.unlink()
    shutil_round.rmdir()
    mark = len(carry.wb.git.history)
    backend = Scripted()
    vc = VerifyContext(carry.wb, backend, "judge", ["impl"], 4, 60)  # type: ignore[arg-type]
    resumed = _resume(vc, prev, carry.criteria, read_ledger(carry.wb.ref.path).events, carry.wb.head())
    out = {c.id: c for c in resumed.criteria}
    assert (out[carry.a].result, out[carry.a].reason) == ("pass", carry.carried_reason())
    assert (out[carry.b].result, out[carry.b].reason) == ("pass", carry.carried_reason())
    assert out[carry.c].result == "pass" and out[carry.c].reason.startswith("accepted by alex")
    assert resumed.holds == [] and resumed.verdict is Verdict.PASS  # the hold was accepted, the passes stand
    assert backend.calls == []
    assert not [argv for argv in carry.wb.git.history[mark:] if any(carry.h1 in part for part in argv)]
    assert sorted(resumed.judge_carried) == sorted([carry.a, carry.b])  # kept for the next resume
    assert resumed.judge_verdict is None and carry.data("verify.carried")[-1]["round"] == 3  # none recorded again
    assert len(carry.data("verify.carried")) == 2


def test_a_resumed_round_without_the_person_s_answers_keeps_the_carried_passes_and_the_open_questions(carry):
    carry.add_new_test()
    carry.round3()
    prev = json.loads(json.dumps(verdict_json(carry.result)))
    vc = VerifyContext(carry.wb, Scripted(), "judge", ["impl"], 4, 60)  # type: ignore[arg-type]
    resumed = _resume(vc, prev, carry.criteria, read_ledger(carry.wb.ref.path).events, carry.wb.head())
    out = {c.id: c for c in resumed.criteria}
    assert out[carry.a].result == "pass" and out[carry.b].result == "pass" and out[carry.c].result == "needs_human"
    assert resumed.holds == [DISCARDED] and resumed.verdict is Verdict.NEEDS_HUMAN


def test_a_resumed_round_does_not_compute_the_rule_again(carry):
    """Round 3 stored nothing carried (`judge_carried` empty): the resumed round has no step records, so it takes the
    stored record as it is, although the rule would carry A and B from round 1 now."""
    carry.add_new_test()
    carry.round3()
    prev = json.loads(json.dumps(verdict_json(carry.result)))
    prev["judge_carried"] = {}
    mark = len(carry.wb.git.history)
    vc = VerifyContext(carry.wb, Scripted(), "judge", ["impl"], 4, 60)  # type: ignore[arg-type]
    resumed = _resume(vc, prev, carry.criteria, read_ledger(carry.wb.ref.path).events, carry.wb.head())
    assert {c.reason for c in resumed.criteria} == {NONE_ASKED} and resumed.judge_carried == {}
    assert not [argv for argv in carry.wb.git.history[mark:] if any(carry.h1 in part for part in argv)]
    assert len(carry.data("verify.carried")) == 2 and carry.data("verify.not_carried") == []  # round 3's two only


def test_a_resumed_round_of_a_round_with_a_judge_verdict_carries_nothing(carry):
    carry.add_new_test()
    carry.run(ok(judge_reply(carry.ids, "insufficient_evidence")), trace=carry.trace3(), round_no=3)
    carry.finalize()
    prev = json.loads(json.dumps(verdict_json(carry.result)))
    assert prev["judge_carried"] == {}
    vc = VerifyContext(carry.wb, Scripted(), "judge", ["impl"], 4, 60)  # type: ignore[arg-type]
    resumed = _resume(vc, prev, carry.criteria, read_ledger(carry.wb.ref.path).events, carry.wb.head())
    assert {c.reason for c in resumed.criteria} == {"the judge answered insufficient_evidence"}


# --- aggregate_criterion(carried=) -------------------------------------------------------------------------------


def _verdict(word: str):
    from l4.verifier.judge import CriterionVerdict

    return CriterionVerdict.model_validate(
        {"id": "C-0a1b2c3d", "verdict": word, "evidence": [{"kind": "log", "ref": "gate report"}]}
    )


def _traced(status: str = "passed") -> CriterionEvidence:
    return CriterionEvidence("C-0a1b2c3d", "a", "covered", (TracingTest("t::x", status, "red_assertion"),))


def test_a_carried_pass_reads_its_round_and_head_and_a_judge_pass_of_this_round_does_not():
    carried = aggregate_criterion("C-0a1b2c3d", "a", _verdict("pass"), None, trace=_traced(), carried=(1, "ab" * 20))
    assert carried.result == "pass"
    assert carried.reason == (
        "the judge of round 1 passed it at ababababab, and only tests that do not trace it changed since (carried)"
    )
    plain = aggregate_criterion("C-0a1b2c3d", "a", _verdict("pass"), None, trace=_traced())
    assert plain.reason == "the judge passed it and a discriminating test passes"


def test_a_carried_pass_without_a_passing_adequate_test_is_not_a_pass():
    uncovered = CriterionEvidence("C-0a1b2c3d", "a", "uncovered")
    out = aggregate_criterion("C-0a1b2c3d", "a", _verdict("pass"), None, trace=uncovered, carried=(1, "ab" * 20))
    assert out.result == "needs_human" and out.reason.startswith("uncovered:")
    failing = aggregate_criterion(
        "C-0a1b2c3d", "a", _verdict("pass"), None, trace=_traced("failed"), carried=(1, "ab" * 20)
    )
    assert failing.result == "fail"
    human = HumanVerdict("Q-001", "C-0a1b2c3d", "reject", "alex", "no", "x")
    rejected = aggregate_criterion(
        "C-0a1b2c3d", "a", _verdict("pass"), None, trace=_traced(), carried=(1, "ab" * 20), human=human
    )
    assert rejected.result == "fail" and rejected.reason.startswith("rejected by")
