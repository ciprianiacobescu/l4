"""A judge whose reply stops at the output limit, or whose call times out, is asked again with fewer criteria
(L4-VER-071; SCN-VER-265 to -272).

The stub backend `Limited` reads the criteria a prompt lists and stops at the limit (`length_stop`) for any prompt that
lists more than `k` of them; it answers every other prompt with a valid verdict for exactly the criteria listed."""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from l4.agents.base import RunResult, Usage
from l4.agents.factory import RoleUnavailable
from l4.config.schema import VerifierCfg
from l4.llm.agent_judge import StructuredResult
from l4.state.ledger import read_ledger
from l4.verifier import ladder
from l4.verifier.judge import AcceptedRef, BatchView, build_judge_prompt
from l4.verifier.ladder import VerifyContext, _ask_judges, _events, _judge_step, _resume, _Run
from l4.verifier.report import verdict_json
from l4.verifier.selection import JudgeSeat
from l4.verifier.types import FeedbackRef, Verdict, VerifyResult

from .conftest import judge_reply
from .test_judge_run import invalid
from .test_judge_step_followup import CAP, SCN_190, World, answer, trace_of
from .test_prompt import LISTING, build, criterion

LENGTH = "the stream ended without a final stop (last reason: length)"
MODEL = "claude-sonnet-5-5"
LISTED = re.compile(r"^(C-[0-9a-f]{8})  ", re.M)
BATCH = "This call judges {} of the unit's {} criteria, listed below"
BLOCKS = ('kind="feedback"', 'kind="accepted"', 'kind="satisfied"', "## Done tasks")


def stopped(model: str = MODEL) -> StructuredResult:
    return StructuredResult("error", detail=LENGTH, length_stop=True, model_resolved=model, usage=Usage(cost_usd=0.01))


def timed_out() -> StructuredResult:
    return StructuredResult("timeout", detail="no answer within 60s", usage=Usage(cost_usd=0.01))


def limit_result() -> StructuredResult:
    run = RunResult("quota", detail="usage limit", raw_events_path=None)  # type: ignore[arg-type]
    return StructuredResult("limit", detail="usage limit", run=run)


@dataclass
class Call:
    text: str
    ids: list[str]
    messages: int
    n: int = 0  # the call's number in the backend's order, from 1

    @property
    def batch(self) -> bool:
        return "This call judges" in self.text


def listed(text: str) -> list[str]:
    return LISTED.findall(text.split("## Criteria to judge")[1].split("## Diff")[0])


def block_ids(text: str, kind: str, pattern: str) -> list[str]:
    if f'<l4:data kind="{kind}">' not in text:
        return []
    return re.findall(pattern, text.split(f'<l4:data kind="{kind}">')[1].split("</l4:data>")[0], re.M)


def passes(call: Call) -> dict[str, Any]:
    """A valid reply for the criteria listed, with an answer for each feedback, accepted and satisfied id shown."""
    body = judge_reply(call.ids)
    text = call.text
    if fb := block_ids(text, "feedback", r"^### (FB-\d+) "):
        body["feedback"] = [{"id": i, "addressed": True, "evidence": "src/app/export.py:1"} for i in fb]
    if acc := block_ids(text, "accepted", r"^### (F-[0-9a-f]{6}) "):
        body["accepted"] = [{"id": i, "addressed": True, "evidence": "src/app/export.py:1"} for i in acc]
    if sat := block_ids(text, "satisfied", r"^### Task (\S+)$"):
        body["satisfied"] = [{"task": i, "holds": True, "evidence": "src/app/export.py:1"} for i in sat]
    return body


class Limited:
    """A judge backend that stops at the output limit for any prompt that lists more than `k` criteria. `serve(call, n)`
    may answer the n-th call (1-based) itself; None leaves it to the rule."""

    def __init__(
        self, k: int, *, answers: Callable[[Call], dict] = passes, model: str = MODEL,
        serve: Callable[[Call, int], StructuredResult | None] | None = None,
    ) -> None:  # fmt: skip
        self.k, self.answers, self.model, self.serve = k, answers, model, serve
        self.calls: list[Call] = []

    def complete_structured(self, system, messages, json_schema, *, effort, max_tokens, timeout_s):
        text = messages[0].content
        call = Call(text, listed(text), len(messages), len(self.calls) + 1)
        self.calls.append(call)
        if self.serve is not None and (made := self.serve(call, len(self.calls))) is not None:
            return made
        if len(call.ids) > self.k:
            return stopped(self.model)
        return StructuredResult(
            "ok", parsed=self.answers(call), model_resolved=self.model, usage=Usage(cost_usd=0.02)
        )  # fmt: skip

    def sizes(self) -> list[int]:
        return [len(c.ids) for c in self.calls]


def never(reason, limited):
    raise AssertionError(f"the next judge was asked ({reason}): the same judge had to answer")


def backup(k: int = 99, **kw) -> tuple[Limited, Callable[..., Any], list[str]]:
    """A second judge that answers the whole prompt, and a `next_judge` that gives it out."""
    second = Limited(k, **kw)
    reasons: list[str] = []

    def next_judge(reason, limited):
        reasons.append(reason)
        return second, "backup"

    return second, next_judge, reasons


class Split(World):
    """The bench of `World` with nine criteria and a judge backend of the test's own."""

    def __init__(self, make_bench, monkeypatch, *, cap: int = CAP) -> None:
        super().__init__(make_bench, monkeypatch, cap=cap, extra=True)
        self.commit("1.1", {"src/app/export.py": SCN_190["src/app/export.py"], "tests/test_export.py":
                            SCN_190["tests/test_export.py"]}, tick=True)  # fmt: skip
        self.commit("1.2", {"src/app/export.py": SCN_190["src/app/export.py"] + "extra = 1\n",
                            "src/app/report.py": SCN_190["src/app/report.py"],
                            "tests/test_report.py": SCN_190["tests/test_report.py"]})  # fmt: skip
        self.proof("1.1", self.ids[1], "tests.test_export::test_csv")
        self.proof("1.2", self.ids[0], "tests.test_report::test_header")
        assert len(self.ids) == 9

    def ask(self, backend, *, trace=(), next_judge=None, seat: JudgeSeat | None = None):
        self.result = VerifyResult(self.wb.ref.id, 1, Verdict.NEEDS_HUMAN, self.base, self.wb.head())
        self.result.trace = list(trace)
        self.judge = backend
        self.vc = VerifyContext(self.wb, backend, "judge", ["impl"], 1, 60)  # type: ignore[arg-type]
        self.vc.next_judge = next_judge
        if seat is not None:
            self.vc.seat = seat
        self.run_ = _Run(self.result)
        self.events = _events(self.wb)
        _judge_step(self.vc, self.run_, self.base, self.events)
        return self.result

    def data(self, kind: str) -> list[dict]:
        return [dict(e.data) for e in _events(self.wb) if e.type == kind]

    def verdicts(self) -> dict[str, str]:
        assert self.run_.judged is not None
        return {c.id: c.verdict for c in self.run_.judged.criteria}


@pytest.fixture
def two_parts(make_bench, monkeypatch) -> Split:
    return Split(make_bench, monkeypatch)


@pytest.fixture
def one_prompt(make_bench, monkeypatch) -> Split:
    return Split(make_bench, monkeypatch, cap=120_000)


# --- SCN-VER-265 -----------------------------------------------------------------------------------------------------


def test_scn_ver_265_a_part_that_stops_at_the_limit_is_judged_in_two_batches_by_the_same_judge(two_parts):
    world = two_parts
    backend = Limited(5)
    result = world.ask(backend, next_judge=never)
    assert backend.sizes() == [9, 5, 4, 9, 5, 4] and result.judge_calls == 6
    assert result.cost_usd == pytest.approx(2 * 0.01 + 4 * 0.02)
    assert [c.batch for c in backend.calls] == [False, True, True, False, True, True]
    first, second = backend.calls[1].ids, backend.calls[2].ids
    assert first == world.ids[:5] and second == world.ids[5:]  # the criteria's order, the first half has ceil(n/2)
    # one merged reply of 9 verdicts per part: two part rows, each with its two batches
    assert world.verdicts() == dict.fromkeys(world.ids, "pass") and len(world.run_.judged.criteria) == 9  # type: ignore[union-attr]
    assert [(r["part"], r["calls"], r["reply"], r["batches"]) for r in result.judge_parts] == [
        (1, 3, "valid", 2), (2, 3, "valid", 2),
    ]  # fmt: skip
    splits = world.data("judge.length_split")
    assert [(s["part"], s["parts"], s["criteria"], s["into"], s["depth"], s["profile"]) for s in splits] == [
        (1, 2, world.ids, [5, 4], 1, "judge"), (2, 2, world.ids, [5, 4], 1, "judge"),
    ]  # fmt: skip
    rows = result.judge_batches
    assert [(r["part"], r["depth"], len(r["criteria"]), r["profile"], r["calls"], r["reply"]) for r in rows] == [
        (1, 1, 5, "judge", 1, "valid"), (1, 1, 4, "judge", 1, "valid"),
        (2, 1, 5, "judge", 1, "valid"), (2, 1, 4, "judge", 1, "valid"),
    ]  # fmt: skip
    assert [r["criteria"] for r in rows] == [first, second, first, second]
    assert len({r["prompt_sha256"] for r in rows}) == 4
    events = world.data("verify.judge")
    assert [e["status"] for e in events] == ["error", "ok", "ok", "error", "ok", "ok"]
    assert [e.get("batch_criteria") for e in events] == [None, first, second, None, first, second]
    assert [e.get("batch_depth") for e in events] == [None, 1, 1, None, 1, 1]
    # the round's prompt hash covers the parts' prompts, then the batch prompts (as for parts)
    hashes = [r["prompt_sha256"] for r in result.judge_parts] + [r["prompt_sha256"] for r in rows]
    assert result.prompt_sha256 == hashlib.sha256("\n".join(hashes).encode()).hexdigest()


def test_scn_ver_265_the_batches_of_a_part_are_merged_into_one_reply_before_the_parts_are(two_parts):
    """Each reply names three assumptions of its own. The parts' merge takes them part by part, so the batches of a
    part must already be one reply: appended one by one, the third assumption would be a batch's, not a part's."""
    world = two_parts

    def own_assumptions(call: Call) -> dict:
        return {**passes(call), "riskiest_assumptions": [f"call{call.n}-{k}" for k in range(3)]}

    backend = Limited(5, answers=own_assumptions)
    world.ask(backend, next_judge=never)
    assert backend.sizes() == [9, 5, 4, 9, 5, 4]
    # part 1 = batches 2 and 3 -> [call2-0, call3-0, call2-1]; part 2 = batches 5 and 6 -> [call5-0, call6-0, call5-1]
    assert world.run_.judged is not None
    assert world.run_.judged.riskiest_assumptions == ["call2-0", "call5-0", "call3-0"]


def test_scn_ver_265_the_batches_of_a_part_are_one_reply_for_the_follow_ups(two_parts):
    """The follow-ups read the part-to-reply alignment: C-1's evidence is split over parts 1 and 2 (each part's reply
    cites its own file), so one follow-up is asked, although each part was answered in two batches."""
    world = two_parts
    c_1, c_2 = world.ids[:2]

    def by_part(call: Call) -> dict:
        first = "part 1 of 2" in call.text
        if "follow-up 1 of 1" in call.text:
            made = [answer(c, "pass", "src/app/export.py:12", "src/app/report.py") for c in call.ids]
        else:
            made = [
                answer(c_1, "insufficient_evidence", "src/app/export.py:12" if first else "src/app/report.py")
                if c == c_1
                else answer(c, "pass", "tests/test_export.py" if first else "tests/test_report.py")
                for c in call.ids
            ]
        return {**judge_reply([]), "criteria": made}

    backend = Limited(5, answers=by_part)
    result = world.ask(backend, trace=trace_of(world), next_judge=never)
    assert backend.sizes() == [9, 5, 4, 9, 5, 4, 1] and "follow-up 1 of 1" in backend.calls[-1].text
    assert [r["criteria"] for r in result.judge_followups] == [[c_1]] and len(result.judge_parts) == 2
    assert world.verdicts()[c_1] == "pass" and result.judge_split[c_1]["outcome"] == "answered"
    assert not world.data("judge.length_split")[2:]  # the follow-up is never split


def test_scn_ver_265_a_batch_that_stops_again_is_split_again_and_the_round_is_recorded_and_resumed(one_prompt):
    world = one_prompt
    backend = Limited(4)
    result = world.ask(backend, next_judge=never)
    # 9 stops -> 5 and 4; 5 stops -> 3 and 2; every other batch fits; the stopped batch is a row of its own
    assert backend.sizes() == [9, 5, 3, 2, 4] and result.judge_calls == 5
    splits = world.data("judge.length_split")
    assert [(s["into"], s["depth"], "part" in s) for s in splits] == [([5, 4], 1, False), ([3, 2], 2, False)]
    assert splits[1]["criteria"] == world.ids[:5]
    assert [(r["part"], r["depth"], len(r["criteria"]), r["reply"]) for r in result.judge_batches] == [
        (0, 1, 5, ""), (0, 2, 3, "valid"), (0, 2, 2, "valid"), (0, 1, 4, "valid"),
    ]  # fmt: skip
    assert [e.get("batch_depth") for e in world.data("verify.judge")] == [None, 1, 2, 2, 1]
    assert result.judge_parts == [] and world.verdicts() == dict.fromkeys(world.ids, "pass")
    hashes = [world.data("verify.judge")[0]["prompt_sha256"]] + [r["prompt_sha256"] for r in result.judge_batches]
    assert result.prompt_sha256 == hashlib.sha256("\n".join(hashes).encode()).hexdigest()
    world.finalize()
    prev = json.loads(json.dumps(verdict_json(world.result)))
    assert prev["judge_batches"] == result.judge_batches and len(prev["judge_batches"]) == 4
    resumed = _resume(
        VerifyContext(world.wb, Limited(0), "judge", ["impl"], 2, 60),  # type: ignore[arg-type]
        prev, world.criteria, read_ledger(world.wb.ref.path).events, world.wb.head(),
    )  # fmt: skip
    assert resumed.judge_batches == result.judge_batches


def test_a_diff_whose_judge_answers_within_its_limit_makes_no_extra_call_and_has_no_batch_record(one_prompt):
    world = one_prompt
    backend = Limited(9)
    result = world.ask(backend, next_judge=never)
    assert backend.sizes() == [9] and result.judge_calls == 1 and result.judge_batches == []
    assert not world.data("judge.length_split") and "batch_criteria" not in world.data("verify.judge")[0]
    assert result.prompt_sha256 == world.data("verify.judge")[0]["prompt_sha256"]


# --- SCN-VER-266 -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("splits", "sizes", "detail"),
    [(2, [9, 5, 3], "batch of 3 criteria at depth 2: "), (1, [9, 5], "batch of 5 criteria at depth 1: ")],
)
def test_scn_ver_266_a_judge_whose_smallest_batch_still_stops_is_discarded_and_the_next_gets_the_whole_part(
    two_parts, splits, sizes, detail
):
    world = two_parts
    world.wb.cfg.verifier.judge_length_splits = splits
    first = Limited(0)
    second, next_judge, reasons = backup()
    result = world.ask(first, next_judge=next_judge)
    assert first.sizes() == sizes and reasons == ["error"]
    (error,) = world.data("availability.judge_error")
    assert error["profile"] == "judge" and error["detail"] == detail + LENGTH
    assert second.sizes() == [9, 9] and not any(c.batch for c in second.calls)  # both parts, whole, in one call each
    assert world.verdicts() == dict.fromkeys(world.ids, "pass")
    assert [(r["profile"], r["batches"], r["calls"]) for r in result.judge_parts] == [("backup", 0, 1)] * 2
    assert result.judge_profile == "backup" and result.judge_calls == len(sizes) + 2


def test_scn_ver_266_with_no_judge_left_the_round_has_no_capacity_and_names_the_batch(one_prompt):
    with pytest.raises(RoleUnavailable, match=r"batch of 3 criteria at depth 2: "):
        one_prompt.ask(Limited(0))


def test_scn_ver_266_a_batch_that_errors_for_another_reason_discards_the_judge_too(one_prompt):
    world = one_prompt

    def serve(call, n):
        return StructuredResult("error", detail="api_error_status 502") if n == 2 else None

    second, next_judge, _ = backup()
    world.ask(Limited(5, serve=serve), next_judge=next_judge)
    assert second.sizes() == [9]
    (error,) = world.data("availability.judge_error")
    assert error["detail"] == "batch of 5 criteria at depth 1: api_error_status 502"


# --- SCN-VER-267 -----------------------------------------------------------------------------------------------------


def test_scn_ver_267_only_the_first_batch_carries_the_unit_wide_asks(one_prompt, monkeypatch):
    world = one_prompt
    monkeypatch.setattr(ladder, "_asked_feedback", lambda wb: [FeedbackRef("FB-001", "fix", "t", "text", "alex")])
    accepted = [AcceptedRef("F-0a1b2c", "testability", "major", "t", "r")]
    monkeypatch.setattr(ladder, "accepted_refs", lambda path: accepted)
    world.wb.emit("task.red_ok", task="1.1", criteria={world.ids[0]: {"tests": ["t::a"], "discriminating": ["t::a"]}})
    world.wb.emit("task.done", task="1.1", tdd="already-satisfied")
    tasks = world.wb.ref.path / "tasks.md"
    tasks.write_text(tasks.read_text() + "\n- [x] 2.1 a done task of its own\n")  # the done-task block
    backend = Limited(5)
    result = world.ask(backend, next_judge=never)
    whole, first, second = backend.calls
    assert backend.sizes() == [9, 5, 4]
    for marker in BLOCKS:
        assert marker in whole.text and marker in first.text and marker not in second.text
    assert BATCH.format(5, 9) in first.text and BATCH.format(4, 9) in second.text and not whole.batch
    assert all(c.messages == 1 for c in backend.calls)  # no call asks for a missing id, in the second batch or any
    assert "did not say whether task" not in " ".join(f.title for f in result.findings)
    reply = world.run_.judged
    assert reply is not None and [a.id for a in reply.accepted or []] == ["F-0a1b2c"]
    assert [a.id for a in reply.feedback or []] == ["FB-001"] and [s.task for s in reply.satisfied or []] == ["1.1"]
    # what every batch keeps: the criteria it judges, the gate report and the diff
    assert "## Gate report" in second.text and "## Diff (base...head)" in second.text


# --- SCN-VER-269 -----------------------------------------------------------------------------------------------------


def test_scn_ver_269_with_splits_turned_off_a_length_stop_discards_the_judge_as_before(one_prompt):
    world = one_prompt
    world.wb.cfg.verifier.judge_length_splits = 0
    second, next_judge, reasons = backup()
    result = world.ask(Limited(5), next_judge=next_judge)
    assert not world.data("judge.length_split") and result.judge_batches == []
    assert reasons == ["error"] and second.sizes() == [9]
    (error,) = world.data("availability.judge_error")
    assert error["detail"] == LENGTH


def test_scn_ver_269_a_prompt_of_one_criterion_is_not_split(one_prompt):
    world = one_prompt
    world.ask(Limited(99))  # a world to borrow the bench from
    backend = Limited(0)
    vc = VerifyContext(world.wb, backend, "judge", ["impl"], 1, 60)  # type: ignore[arg-type]
    result = VerifyResult(world.wb.ref.id, 1, Verdict.NEEDS_HUMAN, world.base, world.wb.head())

    def rebuild(subset, first):
        raise AssertionError("a prompt of one criterion has nothing to split")

    judged = _ask_judges(vc, build(), result, criteria=[criterion()], rebuild=rebuild)
    assert judged.status == "error" and judged.length_stop and backend.sizes() == [1]


def test_scn_ver_269_a_follow_up_whose_reply_stops_at_the_limit_keeps_the_parts_verdict(two_parts):
    world = two_parts
    c_1 = world.ids[0]

    def by_part(call: Call) -> dict:
        first = "part 1 of 2" in call.text
        made = [
            answer(c_1, "insufficient_evidence", "src/app/export.py:12" if first else "src/app/report.py")
            if c == c_1
            else answer(c, "pass", "tests/test_export.py" if first else "tests/test_report.py")
            for c in call.ids
        ]
        return {**judge_reply([]), "criteria": made}

    def serve(call, n):
        return stopped() if "follow-up" in call.text else None

    backend = Limited(99, answers=by_part, serve=serve)
    result = world.ask(backend, trace=trace_of(world))  # no judge after this one: the follow-up gives no answer
    assert backend.sizes() == [9, 9, 1] and "follow-up 1 of 1" in backend.calls[-1].text
    assert not world.data("judge.length_split") and result.judge_batches == []
    assert [r["status"] for r in result.judge_followups] == ["error"]
    assert world.verdicts()[c_1] == "insufficient_evidence"


# --- a limit, a bad reply and the served model inside a batch --------------------------------------------------------


def test_a_usage_limit_in_a_batch_moves_to_the_next_judge_with_the_whole_prompt(one_prompt):
    world = one_prompt

    def serve(call, n):
        return limit_result() if n == 2 else None

    second, next_judge, reasons = backup()
    result = world.ask(Limited(5, serve=serve), next_judge=next_judge)
    assert reasons == ["limit"] and second.sizes() == [9] and not second.calls[0].batch
    assert world.verdicts() == dict.fromkeys(world.ids, "pass") and result.judge_profile == "backup"
    assert result.judge_calls == 2  # the stopped whole prompt; the limited call gave no result; the backup's one


def test_a_batch_whose_reply_breaks_the_schema_twice_holds_the_round_without_asking_the_next_judge(one_prompt):
    world = one_prompt

    def serve(call, n):
        return invalid() if n in (2, 3) else None  # the first batch and its repair

    backend = Limited(5, serve=serve)
    result = world.ask(backend, next_judge=never)
    assert backend.sizes() == [9, 5, 5] and world.run_.judged is None
    assert any(h.startswith("the judge's reply was discarded (schema_invalid:") for h in result.holds)


def test_the_served_model_of_a_batch_is_checked_for_independence(one_prompt):
    world = one_prompt
    world.wb.cfg.profiles["impl"].vendor = "anthropic"  # the implementer's vendor is the first judge's served vendor
    second, next_judge, reasons = backup(model="gpt-5-codex")
    seat = JudgeSeat(reports_served=True)
    result = world.ask(Limited(5), next_judge=next_judge, seat=seat)
    assert reasons == ["model_mismatch"] and second.sizes() == [9]
    (mismatch,) = world.data("availability.model_mismatch")
    assert mismatch["profile"] == "judge"
    assert world.verdicts() == dict.fromkeys(world.ids, "pass") and result.judge_profile == "backup"


# --- the prompt and the configuration --------------------------------------------------------------------------------


def three() -> list:
    return [criterion(f"C-0a1b2c3{n}") for n in range(3)]


def test_scn_ver_267_the_batch_section_says_which_criteria_the_call_judges_and_nothing_else_changes():
    sentence = (
        "This call judges 2 of the unit's 3 criteria, listed below; the unit's other criteria are judged in other "
        "calls with the same diff. Answer only these criteria, and give test adequacy only for them."
    )
    batch = build(criteria=three()[:2], batch=BatchView(2, 3))
    plain = build(criteria=three()[:2])
    heading = "## Criteria to judge (one verdict per id)\n"
    assert heading + sentence + "\n<l4:data" in batch.user
    assert batch.user.replace(sentence + "\n", "") == plain.user and batch.system == plain.system
    assert batch.sha256 != plain.sha256 and batch.version == plain.version


def test_a_batch_composes_with_a_part_and_is_exclusive_with_a_follow_up():
    from l4.verifier.judge import FollowUpView, PartView

    text = build(part=PartView(1, 2, LISTING), batch=BatchView(1, 3)).user
    assert "part 1 of 2" in text and BATCH.format(1, 3) in text
    with pytest.raises(ValueError, match="follow-up"):
        build(followup=FollowUpView(1, 1, 2, (1, 2), ()), batch=BatchView(1, 3))


def test_a_prompt_without_a_batch_is_the_prompt_of_before():
    plain = build()
    assert "This call judges" not in plain.user
    assert build_judge_prompt(
        unit_id="u", sources=[], criteria=[], diff="", diff_truncated=False, gate_report="", notes_for_verifier="",
        redact=str,
    ).user == build_judge_prompt(
        unit_id="u", sources=[], criteria=[], diff="", diff_truncated=False, gate_report="", notes_for_verifier="",
        redact=str, batch=None,
    ).user  # fmt: skip


def test_judge_length_splits_defaults_to_two_and_is_bounded_by_zero_and_four():
    assert VerifierCfg().judge_length_splits == 2
    assert VerifierCfg(judge_length_splits=0).judge_length_splits == 0
    assert VerifierCfg(judge_length_splits=4).judge_length_splits == 4
    for bad in (-1, 5):
        with pytest.raises(ValueError):
            VerifierCfg(judge_length_splits=bad)


# --- SCN-VER-270..272: a timeout is split like a length stop, and not retried while it can be split ------------------


def times_out_over(k: int, *, answers: Callable[[Call], dict] = passes) -> Limited:
    """A judge that never answers a prompt that lists more than `k` criteria within its time."""
    return Limited(99, answers=answers, serve=lambda call, n: timed_out() if len(call.ids) > k else None)


def test_scn_ver_270_a_part_that_times_out_is_judged_in_two_batches_without_a_retry_of_the_whole_prompt(two_parts):
    world = two_parts
    backend = times_out_over(5)
    result = world.ask(backend, next_judge=never)
    # each part: the whole prompt once (no retry), then the two batches; the same judge answers both
    assert backend.sizes() == [9, 5, 4, 9, 5, 4] and result.judge_calls == 6
    assert [c.batch for c in backend.calls] == [False, True, True, False, True, True]
    assert world.verdicts() == dict.fromkeys(world.ids, "pass") and len(world.run_.judged.criteria) == 9  # type: ignore[union-attr]
    splits = world.data("judge.length_split")
    assert [(s["part"], s["parts"], s["into"], s["depth"], s["cause"], s["profile"]) for s in splits] == [
        (1, 2, [5, 4], 1, "timeout", "judge"), (2, 2, [5, 4], 1, "timeout", "judge"),
    ]  # fmt: skip
    assert [(r["part"], r["calls"], r["reply"], r["batches"]) for r in result.judge_parts] == [
        (1, 3, "valid", 2), (2, 3, "valid", 2),
    ]  # fmt: skip
    assert [e["status"] for e in world.data("verify.judge")] == ["timeout", "ok", "ok", "timeout", "ok", "ok"]
    assert not world.data("availability.judge_error")


def test_scn_ver_270_a_length_stop_names_its_cause_and_a_half_that_times_out_is_split_with_its_own(one_prompt):
    world = one_prompt

    def serve(call, n):
        if len(call.ids) == 9:
            return stopped()
        return timed_out() if len(call.ids) > 4 else None

    backend = Limited(99, serve=serve)
    world.ask(backend, next_judge=never)
    assert backend.sizes() == [9, 5, 3, 2, 4]  # the 5-criteria batch is split at once, not asked again
    splits = world.data("judge.length_split")
    assert [(s["into"], s["depth"], s["cause"]) for s in splits] == [([5, 4], 1, "length"), ([3, 2], 2, "timeout")]
    assert world.verdicts() == dict.fromkeys(world.ids, "pass")


@pytest.mark.parametrize(
    ("splits", "sizes", "cuts"),
    [
        (0, [9, 9], 0),  # splits turned off: today's one retry of the whole prompt
        (1, [9, 5, 5], 1),  # the whole prompt once, the first batch cannot be cut again and keeps its retry
        (2, [9, 5, 3, 3], 2),  # the whole prompt and the first half once each, the first quarter twice
        (4, [9, 5, 3, 2, 1, 1], 4),  # a batch of one criterion is never cut: it keeps the retry
    ],
)
def test_scn_ver_271_a_batch_that_cannot_be_split_again_keeps_one_retry_and_its_timeout_holds_the_round(
    one_prompt, splits, sizes, cuts
):
    world = one_prompt
    world.wb.cfg.verifier.judge_length_splits = splits
    backend = times_out_over(0)
    result = world.ask(backend, next_judge=never)
    assert backend.sizes() == sizes and result.judge_calls == len(sizes)
    assert world.run_.judged is None and world.run_.records["9"].status == "failed"
    (hold,) = [h for h in result.holds if "reply was discarded" in h]
    assert hold == "the judge's reply was discarded (timeout: no answer within 60s)"
    assert len(world.data("judge.length_split")) == cuts
    assert {s["cause"] for s in world.data("judge.length_split")} <= {"timeout"}


def test_scn_ver_271_the_hold_names_the_part_whose_batches_all_time_out(two_parts):
    world = two_parts
    backend = Limited(99, serve=lambda call, n: timed_out() if "part 2 of 2" in call.text else None)
    result = world.ask(backend, next_judge=never)
    # part 1 answers its whole prompt; part 2 times out at every size: whole once, 5 once, 3 twice
    assert backend.sizes() == [9, 9, 5, 3, 3]
    assert result.holds[-1] == "the judge's reply was discarded (part 2 of 2, timeout: no answer within 60s)"


def test_scn_ver_272_a_prompt_of_one_criterion_keeps_the_one_retry_and_is_not_split(one_prompt):
    world = one_prompt
    world.ask(Limited(99))  # a world to borrow the bench from
    backend = Limited(0, serve=lambda call, n: timed_out())
    vc = VerifyContext(world.wb, backend, "judge", ["impl"], 1, 60)  # type: ignore[arg-type]
    result = VerifyResult(world.wb.ref.id, 1, Verdict.NEEDS_HUMAN, world.base, world.wb.head())

    def rebuild(subset, first):
        raise AssertionError("a prompt of one criterion has nothing to split")

    judged = _ask_judges(vc, build(), result, criteria=[criterion()], rebuild=rebuild)
    assert judged.status == "timeout" and backend.sizes() == [1, 1] and judged.calls == 2
    assert not world.data("judge.length_split")[1:]


def test_scn_ver_272_a_follow_up_whose_call_times_out_is_retried_once_and_keeps_the_parts_verdict(two_parts):
    world = two_parts
    c_1 = world.ids[0]

    def by_part(call: Call) -> dict:
        first = "part 1 of 2" in call.text
        made = [
            answer(c_1, "insufficient_evidence", "src/app/export.py:12" if first else "src/app/report.py")
            if c == c_1
            else answer(c, "pass", "tests/test_export.py" if first else "tests/test_report.py")
            for c in call.ids
        ]
        return {**judge_reply([]), "criteria": made}

    backend = Limited(99, answers=by_part, serve=lambda call, n: timed_out() if "follow-up" in call.text else None)
    result = world.ask(backend, trace=trace_of(world))
    assert backend.sizes() == [9, 9, 1, 1] and all("follow-up 1 of 1" in c.text for c in backend.calls[2:])
    assert backend.calls[2].text == backend.calls[3].text  # the same question
    assert len(world.data("judge.length_split")) == 0 and result.judge_batches == []
    assert [r["status"] for r in result.judge_followups] == ["timeout"]
    assert world.verdicts()[c_1] == "insufficient_evidence"
