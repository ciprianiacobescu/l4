"""The judge step's follow-up calls for a criterion whose evidence the parts split (L4-VER-056 to L4-VER-058)."""

import hashlib
import json

import pytest

from l4.agents.base import RunResult
from l4.llm.agent_judge import StructuredResult
from l4.state.ledger import read_ledger
from l4.verifier import diffparts
from l4.verifier.gates import run_build_gates
from l4.verifier.ladder import VerifyContext, _events, _finalize, _judge_step, _resume, _Run
from l4.verifier.report import render_verification_md, verdict_json
from l4.verifier.types import CriterionEvidence, TracingTest, Verdict, VerifyResult
from l4.verifier.verdicts import text_sha256

from .conftest import judge_reply
from .test_judge_run import Scripted, invalid, ok
from .test_judge_step import MORE, _body, judge_events

CAP = 5000
REPORT_TEST = "from app.report import header\n" + _body("t_report", 30)
SCN_190 = {  # sizes scaled to the lowered cap like SCN-VER-190's 60000, 40000, 25000 and 16000 to 120000
    "src/app/export.py": _body("export", 140), "tests/test_export.py": _body("t_export", 92),
    "src/app/report.py": _body("report", 54), "tests/test_report.py": REPORT_TEST,
}  # fmt: skip
NOT_HERE = "not in this part"
TICK = "\n- [x] 1.1 ticked\n"


def answer(cid: str, word: str, *refs: str, **extra) -> dict:
    ev = [{"kind": "file", "ref": ref, "quote": "x"} for ref in refs] or [{"kind": "log", "ref": "gate report"}]
    return {"id": cid, "verdict": word, "evidence": ev, **extra}


def reply(*criteria: dict, **over) -> StructuredResult:
    body = judge_reply([], **over)
    body["criteria"] = list(criteria)
    return ok(body)


def passing(cid: str, tests: tuple[str, ...]) -> CriterionEvidence:
    return CriterionEvidence(cid, "alias", "covered", tuple(TracingTest(t, "passed", "red_assertion") for t in tests))


class World:
    """The bench of `parts_bench`, with task commits, a trace and `task.red_ok` events."""

    def __init__(self, make_bench, monkeypatch, *, cap: int = CAP, limit: int = 8, extra: bool = False) -> None:
        monkeypatch.setattr(diffparts, "MAX_PART_CHARS", cap)
        monkeypatch.setattr(diffparts, "MAX_JUDGE_PARTS", limit)
        self.wb = make_bench([]).wb
        if extra:  # nine criteria instead of two
            spec = self.wb.ref.path / "specs" / "pricing" / "spec.md"
            spec.write_text(spec.read_text() + MORE)
        assert run_build_gates(self.wb).ok
        self.base = self.wb.git.run("rev-parse", "origin/main").stdout.strip()
        self.criteria = self.wb.provider.criteria(self.wb.ref)
        self.ids = [c.id for c in self.criteria]

    def commit(self, task: str, files: dict[str, str], *, tick: bool = False) -> None:
        for rel, text in files.items():
            (self.wb.worktree / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.wb.worktree / rel).write_text(text)
        if tick:
            tasks = self.wb.ref.path / "tasks.md"
            tasks.write_text((tasks.read_text() if tasks.exists() else "") + TICK)
        self.wb.commit(f"feat: task {task}", task=task, attempt=1, phase="green", tdd="green")

    def proof(self, task: str, cid: str, *tests: str) -> None:
        self.wb.emit("task.red_ok", task=task, criteria={cid: {"tests": list(tests), "discriminating": list(tests)}})

    def run(self, *results, trace=(), round_no: int = 1, next_judge=None):
        self.result = VerifyResult(self.wb.ref.id, round_no, Verdict.NEEDS_HUMAN, self.base, self.wb.head())
        self.result.trace = list(trace)
        self.judge = Scripted(*results)
        self.vc = VerifyContext(self.wb, self.judge, "judge", ["impl"], round_no, 60)  # type: ignore[arg-type]
        self.vc.next_judge = next_judge
        self.run_ = _Run(self.result)
        self.events = _events(self.wb)
        _judge_step(self.vc, self.run_, self.base, self.events)
        return self.result

    def finalize(self):
        _finalize(self.vc, self.run_, self.criteria, self.events)
        return {c.id: c for c in self.result.criteria}

    def prompts(self) -> list[str]:
        return [call[0].content for call in self.judge.calls]


def scn_190(make_bench, monkeypatch, **kw) -> World:
    """The diff of SCN-VER-190: C-1 traced by `tests.test_report::test_header` (task 1.2, whose commits change
    `export.py` and `report.py`), C-2 by `tests.test_export::test_csv` (task 1.1, which also ticks `tasks.md`)."""
    world = World(make_bench, monkeypatch, **kw)
    world.commit("1.1", {"src/app/export.py": SCN_190["src/app/export.py"], "tests/test_export.py":
                         SCN_190["tests/test_export.py"]}, tick=True)  # fmt: skip
    world.commit("1.2", {"src/app/export.py": SCN_190["src/app/export.py"] + "extra = 1\n",
                         "src/app/report.py": SCN_190["src/app/report.py"],
                         "tests/test_report.py": SCN_190["tests/test_report.py"]})  # fmt: skip
    world.proof("1.1", world.ids[1], "tests.test_export::test_csv")
    world.proof("1.2", world.ids[0], "tests.test_report::test_header")
    return world


def trace_of(world: World, *, c1=("tests.test_report::test_header",), c2=("tests.test_export::test_csv",)):
    return [passing(world.ids[0], c1), passing(world.ids[1], c2)]


def parts_replies(world: World, c1=("insufficient_evidence", "insufficient_evidence"), c2=("pass", "pass")):
    """Two part replies: part 1 cites `src/app/export.py:12` for C-1."""
    c_1, c_2 = world.ids[:2]
    return [
        reply(answer(c_1, c1[0], "src/app/export.py:12"), answer(c_2, c2[0], "tests/test_export.py")),
        reply(answer(c_1, c1[1], "src/app/report.py"), answer(c_2, c2[1], "tests/test_report.py")),
    ]


def verdicts_of(world: World) -> dict[str, str]:
    return {c["id"]: c["verdict"] for c in world.result.judge_verdict["criteria"]}


NOTE = (
    "its evidence was split over parts 1 and 2 of the diff: follow-up call 1 judged its 3 files of those parts "
    "together and answered "
)


def test_a_split_criterion_is_passed_by_one_follow_up(make_bench, monkeypatch):
    world = scn_190(make_bench, monkeypatch)
    c_1 = world.ids[0]
    follow = reply(answer(c_1, "pass", "src/app/export.py:12", "src/app/report.py"))
    result = world.run(*parts_replies(world), follow, trace=trace_of(world))
    assert len(world.judge.calls) == 3 and result.judge_calls == 3
    first, second, third = world.prompts()
    assert "part 1 of 2" in first and "part 2 of 2" in second
    assert "## Diff (base...head), follow-up 1 of 1" in third
    for shown in ("src/app/export.py", "src/app/report.py", "tests/test_report.py"):
        assert f"shown: {shown} (part" in third and f"not shown: {shown}" not in third
    assert "not shown: tests/test_export.py (part 1," in third
    listed = third.split("## Criteria to judge")[1].split("## Diff")[0]
    assert c_1 in listed and world.ids[1] not in listed
    assert verdicts_of(world) == {c_1: "pass", world.ids[1]: "pass"}
    assert [c.verdict for c in world.run_.judged.criteria if c.id == c_1] == ["pass"]
    outcomes = world.finalize()
    assert outcomes[c_1].result == "pass"
    assert outcomes[c_1].reason == f"the judge passed it and a discriminating test passes; {NOTE}pass"


def test_a_criterion_in_one_part_gets_no_follow_up(make_bench, monkeypatch):
    world = scn_190(make_bench, monkeypatch)
    c_1, c_2 = world.ids[:2]
    both = [
        reply(answer(c_1, "pass", "src/app/export.py"), answer(c_2, "insufficient_evidence", "src/app/export.py")),
        reply(answer(c_1, "pass", "src/app/report.py"), answer(c_2, "insufficient_evidence", NOT_HERE)),
    ]
    result = world.run(*both, trace=trace_of(world))
    assert len(world.judge.calls) == 2 and result.judge_split == {} and result.judge_followups == []
    c_2_outcome = world.finalize()[c_2]
    assert c_2_outcome.result == "needs_human" and c_2_outcome.reason == "the judge answered insufficient_evidence"
    # a diff within one part
    one = scn_190(make_bench, monkeypatch, cap=120_000)
    result = one.run(reply(answer(c_1, "pass"), answer(c_2, "insufficient_evidence")), trace=trace_of(one))
    assert len(one.judge.calls) == 1 and result.judge_split == {}


def _decided(world: World, how: str):
    """The trace and ledger of SCN-VER-192's variants, for C-1 (insufficient_evidence from both parts)."""
    c_1 = world.ids[0]
    trace = trace_of(world)
    if how == "uncovered":
        trace[0] = CriterionEvidence(c_1, "alias", "uncovered")
    elif how == "held":
        trace[0] = CriterionEvidence(c_1, "alias", "covered", trace[0].tests, held="a failed audit test holds it")
    elif how == "decided":
        criterion = next(c for c in world.criteria if c.id == c_1)
        world.wb.emit(
            "human.verdict", question="Q-001", target=c_1, decision="accept", by="alex", reason="checked",
            text_sha256=text_sha256(criterion),
        )  # fmt: skip
    return trace


@pytest.mark.parametrize("how", ["uncovered", "held", "decided", "inadequate"])
def test_an_uncovered_held_inadequate_or_decided_criterion_gets_no_follow_up(make_bench, monkeypatch, how):
    world = scn_190(make_bench, monkeypatch)
    c_1 = world.ids[0]
    trace = _decided(world, how)
    replies = parts_replies(world)
    if how == "inadequate":
        bad = [{"test": "tests.test_report::test_header", "criterion": c_1, "adequate": False, "reason": "weak"}]
        replies[0] = reply(*[answer(c_1, "insufficient_evidence", "src/app/export.py:12")], test_adequacy=bad)
    world.run(*replies, trace=trace)
    assert len(world.judge.calls) == 2 and world.result.judge_split == {}
    outcomes = world.finalize()
    assert "split over parts" not in outcomes[c_1].reason
    if how == "uncovered":
        assert outcomes[c_1].reason == "uncovered: no adequate discriminating test traces it"
    if how == "held":
        assert outcomes[c_1].reason == "a failed audit test holds it"
    if how == "decided":
        assert outcomes[c_1].result == "pass" and outcomes[c_1].reason.startswith("accepted by")
    if how == "inadequate":
        assert outcomes[c_1].reason.startswith("uncovered:")


def test_a_follow_up_for_one_criterion_leaves_the_others_alone(make_bench, monkeypatch):
    """SCN-VER-201: a reply that marks a test of another criterion inadequate changes nothing outside its group."""
    world = scn_190(make_bench, monkeypatch)
    c_1, c_2 = world.ids[:2]
    follow = reply(
        answer(c_1, "pass", "src/app/report.py"),
        answer(c_2, "fail", "src/app/export.py", counterexample={"call": "f()", "expected": "1", "actual": "0"}),
        test_adequacy=[{"test": "tests.test_export::test_csv", "criterion": c_2, "adequate": False, "reason": "no"}],
    )  # fmt: skip
    world.run(*parts_replies(world), follow, trace=trace_of(world))
    assert verdicts_of(world) == {c_1: "pass", c_2: "pass"}
    assert world.run_.judged is not None and world.run_.judged.test_adequacy == []
    csv = next(t for e in world.result.trace if e.criterion == c_2 for t in e.tests)
    assert csv.adequate is True and world.result.cx_runs == {}


@pytest.mark.parametrize("word", ["fail", "not_verifiable"])
def test_a_fail_or_not_verifiable_of_a_part_is_not_rejudged(make_bench, monkeypatch, word):
    """SCN-VER-196."""
    world = scn_190(make_bench, monkeypatch)
    c_1 = world.ids[0]
    cx = {"counterexample": {"call": "f()", "expected": "1", "actual": "0"}} if word == "fail" else {}
    first = reply(answer(c_1, word, "src/app/export.py:12", **cx), answer(world.ids[1], "pass", "tests/test_export.py"))
    second = reply(answer(c_1, "insufficient_evidence", NOT_HERE), answer(world.ids[1], "pass", "x"))
    world.run(first, second, trace=trace_of(world))
    assert len(world.judge.calls) == 2 and world.result.judge_split == {}
    reason = world.finalize()[c_1].reason
    assert "split over parts" not in reason
    if word == "fail":
        assert reason.startswith("judge fail counted as insufficient_evidence: counterexample unexecuted (")
    else:
        assert reason == "the judge answered not_verifiable"


def side_files(world: World, count: int, extra: dict[str, str] | None = None) -> None:
    """`count` files in each of two sides (`a_n.py` and `b_n.py`) of the same size, and the `extra` files."""
    files = {f"src/{side}_{n}.py": _body(f"{side}{n}", 100) for side in ("a", "b") for n in range(1, count + 1)}
    world.commit("1.1", files | (extra or {}))


def split_replies(world: World, count: int, parts: int = 2):
    """Every part answers insufficient_evidence for the first `count` criteria; part 1 cites `a_n`, the others `b_n`."""
    ids = world.ids[:count]
    return [
        reply(
            *[answer(c, "insufficient_evidence", f"src/{'a' if k == 1 else 'b'}_{n}.py") for n, c in enumerate(ids, 1)]
        )
        for k in range(1, parts + 1)
    ]


def traced(world: World, count: int) -> list[CriterionEvidence]:
    return [passing(c, (f"t::{n}",)) for n, c in enumerate(world.ids[:count], 1)]


def test_the_calls_are_bounded_by_the_parts_judged(make_bench, monkeypatch):
    """SCN-VER-197, second case: four split criteria whose files do not fit one call together, in a diff of three
    parts (the extra scenarios change the spec file, which a third part holds): three follow-up calls, and the fourth
    criterion gets none."""
    world = World(make_bench, monkeypatch, extra=True)
    side_files(world, 4)
    c_1, c_2, c_3, c_4 = world.ids[:4]
    follows = [reply(answer(c, "pass", f"src/a_{n}.py")) for n, c in enumerate((c_1, c_2, c_3), 1)]
    result = world.run(*split_replies(world, 4, parts=3), *follows, trace=traced(world, 4))
    assert len(result.judge_parts) == 3
    assert len(world.judge.calls) == 6 and [r["criteria"] for r in result.judge_followups] == [[c_1], [c_2], [c_3]]
    assert result.judge_split[c_4]["outcome"] == "no_call_left"
    reason = world.finalize()[c_4].reason
    assert reason.endswith(
        "its evidence was split over parts 2 and 3 of the diff: no follow-up call was made, because the round's 3 "
        "follow-up calls were used"
    )


def test_two_split_criteria_that_fit_together_share_one_call(make_bench, monkeypatch):
    """SCN-VER-197, first case, at the step: the files of C-1 and C-2 fit one follow-up, so one call answers both."""
    world = World(make_bench, monkeypatch)
    c_1, c_2 = world.ids[:2]
    side_files(world, 2, {"src/m_filler.py": _body("filler", 100)})  # pushes b_2 into the second part
    first = reply(
        answer(c_1, "insufficient_evidence", "src/a_1.py"), answer(c_2, "insufficient_evidence", "src/a_2.py")
    )
    second = reply(
        answer(c_1, "insufficient_evidence", "src/b_2.py"), answer(c_2, "insufficient_evidence", "src/b_2.py")
    )
    follow = reply(answer(c_1, "pass", "src/a_1.py"), answer(c_2, "pass", "src/a_2.py"))
    result = world.run(first, second, follow, trace=traced(world, 2))
    assert [len(p) for p in ([result.judge_parts, result.judge_followups])] == [2, 1]
    assert result.judge_followups[0]["criteria"] == [c_1, c_2] and verdicts_of(world) == {c_1: "pass", c_2: "pass"}


def limit_result() -> StructuredResult:
    return StructuredResult(
        "limit", detail="usage limit", run=RunResult("quota", detail="usage limit", raw_events_path=None)
    )  # type: ignore[arg-type]


@pytest.mark.parametrize("second", ["schema", "limit"])
def test_a_follow_up_with_no_usable_answer_keeps_the_round(make_bench, monkeypatch, second):
    """SCN-VER-199."""
    world = scn_190(make_bench, monkeypatch)
    c_1 = world.ids[0]
    follow = [invalid(), invalid()] if second == "schema" else [limit_result()]
    result = world.run(*parts_replies(world), *follow, trace=trace_of(world))
    status = "schema_invalid" if second == "schema" else "limit"
    assert not [h for h in result.holds if "reply was discarded" in h]
    assert verdicts_of(world)[c_1] == "insufficient_evidence" and world.run_.judged is not None
    assert result.judge_split[c_1]["outcome"] == "no_answer" and result.judge_split[c_1]["status"] == status
    reason = world.finalize()[c_1].reason
    assert reason.endswith(
        "follow-up call 1 gave no usable answer (" + status + "), so the parts' verdict stands"
    ) and reason.startswith("the judge answered insufficient_evidence; ")
    assert result.judge_followups[0]["status"] == status


def test_a_follow_up_fail_goes_through_the_counterexample_rule(make_bench, monkeypatch):
    """SCN-VER-200."""
    world = scn_190(make_bench, monkeypatch)
    c_1 = world.ids[0]
    cx = {"counterexample": {"call": "f()", "expected": "1", "actual": "0"}}
    world.run(*parts_replies(world), reply(answer(c_1, "fail", "src/app/report.py", **cx)), trace=trace_of(world))
    assert world.result.cx_runs[c_1].status == "unexecuted"
    outcomes = world.finalize()
    assert outcomes[c_1].result == "needs_human"
    assert outcomes[c_1].reason.startswith("judge fail counted as insufficient_evidence: counterexample unexecuted (")
    assert outcomes[c_1].reason.endswith(NOTE + "fail")
    assert world.result.verdict is Verdict.NEEDS_HUMAN


def test_the_follow_up_records(make_bench, monkeypatch):
    """SCN-VER-202."""
    world = scn_190(make_bench, monkeypatch)
    c_1 = world.ids[0]
    follow = reply(answer(c_1, "pass", "src/app/report.py"))
    result = world.run(*parts_replies(world), follow, trace=trace_of(world))
    (row,) = result.judge_followups
    assert (row["followup"], row["criteria"], row["parts"], row["files"]) == (1, [c_1], [1, 2], 3)
    assert row["profile"] == "judge" and row["calls"] == 1 and row["reply"] == "valid" and row["chars"] > 0
    assert row["not_shown"] == [] or all(len(item) == 3 for item in row["not_shown"])
    split = result.judge_split[c_1]
    assert (split["outcome"], split["answer"], split["followup"], split["files"], split["status"]) == (
        "answered", "pass", 1, 3, None,
    )  # fmt: skip
    events = judge_events(world.wb)
    assert [(e.data.get("part"), e.data.get("followup")) for e in events] == [(1, None), (2, None), (None, 1)]
    assert events[2].data["followups"] == 1 and events[2].data["criteria"] == [c_1]
    assert "parts" not in events[2].data
    hashes = [r["prompt_sha256"] for r in result.judge_parts] + [row["prompt_sha256"]]
    assert result.prompt_sha256 == hashlib.sha256("\n".join(hashes).encode()).hexdigest()
    assert result.judge_reply == "valid" and result.judge_profile == "judge" and result.judge_calls == 3
    assert result.judge_replies["valid"] == 3


def test_the_question_says_the_evidence_was_split(make_bench, monkeypatch):
    """SCN-VER-195."""
    world = scn_190(make_bench, monkeypatch)
    c_1 = world.ids[0]
    world.run(
        *parts_replies(world), reply(answer(c_1, "insufficient_evidence", "src/app/report.py")), trace=trace_of(world)
    )
    outcome = world.finalize()[c_1]
    assert outcome.result == "needs_human"
    assert outcome.reason == "the judge answered insufficient_evidence; " + NOTE + "insufficient_evidence"
    from l4.verifier.verdicts import _criterion_question

    criterion = next(c for c in world.criteria if c.id == c_1)
    question = _criterion_question(outcome, criterion, trace_of(world)[0], 1)
    why = [line for line in question.context.splitlines() if line.startswith("Why:")]
    assert why == ["Why: the judge answered insufficient_evidence; " + NOTE + "insufficient_evidence"]


def test_verification_md_lists_the_follow_ups(make_bench, monkeypatch):
    """SCN-VER-202."""
    world = scn_190(make_bench, monkeypatch)
    c_1 = world.ids[0]
    result = world.run(*parts_replies(world), reply(answer(c_1, "pass", "src/app/report.py")), trace=trace_of(world))
    world.finalize()
    text = render_verification_md(result)
    assert "judged in 2 parts and 1 follow-up," in text
    (row,) = result.judge_followups
    expected = (
        f"  - follow-up 1: {c_1}; files of parts 1 and 2: 3 file(s), {row['chars']} characters, profile judge, "
        "reply valid"
    )
    assert expected in text.splitlines()
    assert text.index("  - part 2:") < text.index("  - follow-up 1:")
    row2 = dict(row, followup=2)
    result.judge_followups = [row, row2]
    assert "judged in 2 parts and 2 follow-ups," in render_verification_md(result)


def test_a_resumed_round_keeps_the_notes(make_bench, monkeypatch):
    """SCN-VER-203."""
    world = scn_190(make_bench, monkeypatch)
    c_1 = world.ids[0]
    world.run(
        *parts_replies(world), reply(answer(c_1, "insufficient_evidence", "src/app/report.py")), trace=trace_of(world)
    )
    world.finalize()
    prev = json.loads(json.dumps(verdict_json(world.result)))
    assert prev["judge_followups"] and prev["judge_split"][c_1]["outcome"] == "answered"
    backend = Scripted()
    vc = VerifyContext(world.wb, backend, "judge", ["impl"], 2, 60)  # type: ignore[arg-type]
    resumed = _resume(vc, prev, world.criteria, read_ledger(world.wb.ref.path).events, world.wb.head())
    assert backend.calls == [] and resumed.judge_followups == world.result.judge_followups
    assert resumed.judge_split == world.result.judge_split
    reason = {c.id: c.reason for c in resumed.criteria}[c_1]
    assert reason == "the judge answered insufficient_evidence; " + NOTE + "insufficient_evidence"


def test_a_resumed_round_keeps_a_follow_up_pass(make_bench, monkeypatch):
    """SCN-VER-203, second case: the follow-up passed C-1, C-2 is uncovered, so the round ended NEEDS_HUMAN."""
    world = scn_190(make_bench, monkeypatch)
    c_1, c_2 = world.ids[:2]
    trace = [passing(c_1, ("tests.test_report::test_header",)), CriterionEvidence(c_2, "alias", "uncovered")]
    world.run(*parts_replies(world), reply(answer(c_1, "pass", "src/app/report.py")), trace=trace)
    first = world.finalize()
    assert first[c_1].result == "pass" and first[c_2].result == "needs_human"
    prev = json.loads(json.dumps(verdict_json(world.result)))
    assert {c["id"]: c["verdict"] for c in prev["judge_verdict"]["criteria"]}[c_1] == "pass"
    backend = Scripted()
    vc = VerifyContext(world.wb, backend, "judge", ["impl"], 2, 60)  # type: ignore[arg-type]
    resumed = _resume(vc, prev, world.criteria, read_ledger(world.wb.ref.path).events, world.wb.head())
    outcomes = {c.id: c for c in resumed.criteria}
    assert backend.calls == [] and outcomes[c_1].result == "pass" and outcomes[c_1].reason.endswith(NOTE + "pass")


def test_a_follow_up_that_falls_back_keeps_the_round_judge_of_the_parts(make_bench, monkeypatch):
    """SCN-VER-202: the round's profile, model and independence are the parts' judge's, whatever judge the follow-up
    ran on; the follow-up's own profile is in its row and its `verify.judge` event."""
    world = scn_190(make_bench, monkeypatch)
    c_1 = world.ids[0]
    backup = Scripted(reply(answer(c_1, "pass", "src/app/report.py")))

    def next_judge(reason, limited):
        assert reason == "limit" and limited is not None
        return backup, "backup"

    result = world.run(*parts_replies(world), limit_result(), trace=trace_of(world), next_judge=next_judge)
    assert verdicts_of(world)[c_1] == "pass" and len(backup.calls) == 1
    (row,) = result.judge_followups
    assert row["profile"] == "backup" and row["reply"] == "valid"
    assert [e.data["profile"] for e in judge_events(world.wb)] == ["judge", "judge", "backup"]
    assert result.judge_profile == "judge" and world.vc.judge_profile == "judge" and world.vc.judge is world.judge
    assert result.judge_reply == "valid" and result.judge_model == "claude-sonnet-5-5"
    assert result.independence is not None and result.independence.judge.profile == "judge"
