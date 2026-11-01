# ruff: noqa: F401, F811  (the fixtures are imported by name; `no_verifier` is overridden on purpose)
"""The verdict questions of one round share a delegate call (L4-DLG-028; SCN-DLG-127 to SCN-DLG-133): the real
orchestrator runs the implementer and the judge (one round, N blocking findings, N verdict questions with the same
askers), the fake adapter plays the delegate, and the pass asks them in batches."""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from l4.agents.fake import Step
from l4.config.schema import DelegateCfg
from l4.delegate import run as pass_module
from l4.delegate.independence import Asker
from l4.delegate.limits import batch_failed, delegate_cost
from l4.delegate.run import _Pass, _Target
from l4.specs.criteria import openspec_criteria
from l4.specs.questions import QuestionKind, QuestionsFile
from l4.state.ledger import LedgerEvent

from ..conftest import FIXTURE
from ..implementer.conftest import green_step, red_step
from ..verifier.conftest import judge_reply, valid_spec
from .conftest import (
    UNIT_DIR,
    blocked,
    delegate_run,
    escalation,
    fake_clock,
    limit_step,
    no_hooks_but_the_delegate,
    publish_base,
    reply,
)

CRITERIA = [c.id for c in openspec_criteria(FIXTURE / "openspec" / "changes" / "add-discount-codes")]
QUESTIONS = f"{UNIT_DIR}/questions.md"
JUDGE = {"judge": {"adapter": "fake", "vendor": "other", "model": "judge-model-1"}}  # not the delegate's model
OFF = {"enabled": False}
# a larger batch and cap than the defaults (5 and 15: five answers of 3, the money fit of L4-DLG-009)
ROOMY = {"max_cost_usd_per_unit": 60.0, "batch_size": 6}


@pytest.fixture(autouse=True)
def no_verifier() -> None:
    """Overrides the orchestrator's switch: the verifier runs, and its judge raises the verdict questions."""


def finding(n: int) -> dict:
    return {
        "severity": "major", "title": f"Case {n} of the code", "evidence": [], "spec_gap": True,
        "detail": f"case {n}: the spec does not say what happens",
    }  # fmt: skip


def park(delegate_run, n: int, after: tuple[Step, ...] = (), **config):
    """The first run: the unit is implemented, the judge raises one verdict question for each of `n` findings (Q-001
    to Q-00n, one round), and the delegate is off, so nothing is asked yet (`after`: its replies, if it is on)."""
    config.setdefault("delegate", OFF)
    config["profiles"] = {**JUDGE, **config.get("profiles", {})}
    judged = Step(structured=judge_reply(CRITERIA, findings=[finding(i) for i in range(1, n + 1)]))
    run = delegate_run([red_step(), green_step(), judged, *after], **config)
    assert run.code == 11 and len(run.events("question.raised")) == n
    return run


def accept(qid: str, **over) -> dict:
    return reply(qid, "accept", text="Waived: the proposal covers it.", **over).structured


def batch_reply(*results: dict, cost: float | None = 0.6) -> Step:
    return Step(structured={"results": list(results)}, cost_usd=cost)


def status_of(run, qid: str) -> str:
    return QuestionsFile.parse(run.pushed(QUESTIONS).encode()).get(qid).status.value


def test_a_single_verdict_question_is_asked_and_answered_as_before(delegate_run, valid_spec):
    park(delegate_run, 1)
    run = delegate_run([reply("Q-001", "accept", text="Waived: the proposal covers it.")], profiles=JUDGE)
    assert run.adapter.requests[0].result_schema["$id"] == "l4/delegate-result@1"
    (asked,) = run.events("delegate.asked")
    assert asked["question"] == "Q-001" and "batch" not in asked
    assert status_of(run, "Q-001") == "answered"


def test_six_verdict_questions_are_one_call_with_a_larger_batch_and_cap(delegate_run, valid_spec):
    park(delegate_run, 6)
    ids = [f"Q-00{n}" for n in range(1, 7)]
    run = delegate_run([batch_reply(*(accept(q) for q in ids), cost=0.6)], profiles=JUDGE, delegate=ROOMY)
    delegate = run.adapter.requests
    assert len(delegate) == 1  # one call for the six questions (the implementer and the judge ran in the first run)
    request = delegate[0]
    assert request.max_budget_usd == 6 * 3.0 and request.max_turns == 40 + 20 * 5
    assert request.result_schema["$id"] == "l4/delegate-batch@1"
    assert request.result_schema["properties"]["results"]["maxItems"] == 6
    asked = run.events("delegate.asked")
    assert [e["question"] for e in asked] == ids
    assert len({e["prompt_sha256"] for e in asked}) == 1 and {e["batch"] for e in asked} == {"Q-001+6"}
    assert {e["batch_size"] for e in asked} == {6}
    (cost,) = [e for e in run.events("budget.cost") if e.get("role") == "delegate"]
    assert (cost["usd"], cost["question"], cost["questions"], cost["batch"]) == (0.6, "Q-001", ids, "Q-001+6")
    results = run.events("delegate.result")
    assert [(r["question"], r["status"], r["cost_usd"], r["batch"]) for r in results] == [
        (q, "answered", 0.1, "Q-001+6") for q in ids
    ]
    assert [status_of(run, q) for q in ids] == ["answered"] * 6
    subjects = [s for s in run.subjects() if s.startswith("answer Q-00")]
    assert len(subjects) == 6  # one commit for each answer
    assert [p["calls"] for p in run.events("delegate.pass")][-1] == 1


def test_five_verdict_questions_of_one_round_are_one_call_with_the_defaults(delegate_run, valid_spec):  # SCN-DLG-127
    park(delegate_run, 5)
    ids = [f"Q-00{n}" for n in range(1, 6)]
    run = delegate_run([batch_reply(*(accept(q) for q in ids), cost=0.5)], profiles=JUDGE)  # no delegate settings
    (request,) = run.adapter.requests
    assert request.max_budget_usd == 5 * 3.0 and request.max_turns == 40 + 20 * 4
    asked = run.events("delegate.asked")
    assert [e["question"] for e in asked] == ids
    assert len({e["prompt_sha256"] for e in asked}) == 1 and {e["batch"] for e in asked} == {"Q-001+5"}
    (cost,) = [e for e in run.events("budget.cost") if e.get("role") == "delegate"]
    assert (cost["usd"], cost["questions"]) == (0.5, ids)
    assert [(r["question"], r["status"], r["cost_usd"]) for r in run.events("delegate.result")] == [
        (q, "answered", 0.1) for q in ids
    ]
    assert [status_of(run, q) for q in ids] == ["answered"] * 5
    assert len([s for s in run.subjects() if s.startswith("answer Q-00")]) == 5


def results_of(run) -> dict[str, dict]:
    return {r["question"]: r for r in run.events("delegate.result")}


def test_each_result_of_a_batch_stands_on_its_own(delegate_run, valid_spec):  # SCN-DLG-128
    park(delegate_run, 6)
    unresolved = [{"ref": "spec:proposal.md", "quote": "a sentence the proposal does not hold", "claim": "it is there"}]
    ids = [f"Q-00{n}" for n in range(1, 7)]
    got = [
        accept("Q-001"),
        accept("Q-002"),
        accept("Q-003"),
        accept("Q-004", checked=unresolved),
        escalation("Q-005").structured,
    ]
    run = delegate_run([batch_reply(*got, cost=0.6)], profiles=JUDGE, delegate=ROOMY)  # no result for Q-006
    assert len(run.adapter.requests) == 1
    done = results_of(run)
    assert [done[q]["status"] for q in ids] == ["answered"] * 3 + ["deferred", "escalated", "deferred"]
    assert "asked again" in done["Q-004"]["reason"] and "does not resolve" in done["Q-004"]["discarded"]
    assert done["Q-006"]["reason"] == "the batch reply had no result for Q-006" and "discarded" not in done["Q-006"]
    assert done["Q-005"]["decision"] == "escalate" and done["Q-005"]["reason"] == "no project document decides this"
    assert {r["batch"] for r in done.values()} == {"Q-001+6"} and {r["cost_usd"] for r in done.values()} == {0.1}
    assert [status_of(run, q) for q in ids] == ["answered"] * 3 + ["open"] * 3
    assert "Escalated by" in run.pushed(QUESTIONS)


def test_a_question_with_two_results_or_one_for_a_stranger_is_a_failed_attempt(delegate_run, valid_spec):
    park(delegate_run, 4)
    got = [
        accept("Q-001"),
        accept("Q-001"),
        accept("Q-002"),
        accept("Q-009"),
    ]  # two for Q-001, none for Q-003 and Q-004
    run = delegate_run([batch_reply(*got)], profiles=JUDGE)
    done = results_of(run)
    assert [(q, done[q]["status"]) for q in ("Q-001", "Q-002", "Q-003", "Q-004")] == [
        ("Q-001", "deferred"), ("Q-002", "answered"), ("Q-003", "deferred"), ("Q-004", "deferred"),
    ]  # fmt: skip
    assert done["Q-001"]["reason"] == "the batch reply had two results for Q-001"
    assert done["Q-003"]["reason"] == "the batch reply had no result for Q-003" and "Q-009" not in done


def test_a_missing_result_escalates_when_no_attempt_is_left(delegate_run, valid_spec):  # L4-DLG-009
    park(delegate_run, 2)
    run = delegate_run([batch_reply(accept("Q-001"))], profiles=JUDGE, delegate={"max_attempts_per_question": 1})
    done = results_of(run)
    assert (done["Q-001"]["status"], done["Q-002"]["status"]) == ("answered", "escalated")
    assert done["Q-002"]["reason"] == "the batch reply had no result for Q-002" and done["Q-002"]["called"] is True
    assert "Escalated by" in run.pushed(QUESTIONS)


def test_a_batch_fits_the_money_that_is_left(delegate_run, valid_spec):  # SCN-DLG-129
    park(delegate_run, 5)
    run = delegate_run(
        [batch_reply(accept("Q-001"), accept("Q-002"), cost=3.5)], profiles=JUDGE,
        delegate={"max_cost_usd_per_unit": 6.0},
    )  # fmt: skip
    (request,) = run.adapter.requests
    assert request.max_budget_usd == 6.0  # twice max_cost_usd_per_answer
    assert [e["question"] for e in run.events("delegate.asked")] == ["Q-001", "Q-002"]
    done = results_of(run)
    assert [(q, done[q]["status"]) for q in sorted(done)] == [
        ("Q-001", "answered"), ("Q-002", "answered"), ("Q-003", "escalated"), ("Q-004", "escalated"),
        ("Q-005", "escalated"),
    ]  # fmt: skip
    assert (
        done["Q-003"]["reason"].startswith("the delegate's cost cap of the unit is used")
        and not done["Q-003"]["called"]
    )
    assert done["Q-001"]["cost_usd"] == 1.75
    (end,) = run.events("delegate.pass")
    assert (end["bound"], end["calls"]) == ("cost", 1)


def test_askers_that_differ_are_asked_in_different_calls(delegate_run, valid_spec, monkeypatch):  # SCN-DLG-130
    park(delegate_run, 4)
    real = pass_module.askers

    def other_judge(events, key, configured=()):
        extra = (Asker("judge-b", "judge-b-model-1", "judged"),) if key in ("Q-003", "Q-004") else ()
        return (*real(events, key, configured), *extra)

    monkeypatch.setattr(pass_module, "askers", other_judge)
    script = [batch_reply(accept("Q-001"), accept("Q-002")), batch_reply(accept("Q-003"), accept("Q-004"))]
    run = delegate_run(script, profiles=JUDGE)
    assert len(run.adapter.requests) == 2
    assert [(e["question"], e["batch"]) for e in run.events("delegate.asked")] == [
        ("Q-001", "Q-001+2"), ("Q-002", "Q-001+2"), ("Q-003", "Q-003+2"), ("Q-004", "Q-003+2"),
    ]  # fmt: skip
    assert [status_of(run, f"Q-00{n}") for n in range(1, 5)] == ["answered"] * 4


def test_batch_size_one_asks_one_question_per_call(delegate_run, valid_spec):  # SCN-DLG-130
    park(delegate_run, 3)
    run = delegate_run(
        [reply(f"Q-00{n}", "accept", text="Waived.") for n in (1, 2, 3)], profiles=JUDGE, delegate={"batch_size": 1}
    )
    assert len(run.adapter.requests) == 3
    assert {r.result_schema["$id"] for r in run.adapter.requests} == {"l4/delegate-result@1"}
    assert all("batch" not in e for e in run.events("delegate.asked") + run.events("delegate.result"))
    assert [status_of(run, f"Q-00{n}") for n in (1, 2, 3)] == ["answered"] * 3


def test_a_technical_question_is_asked_alone_with_the_single_prompt(delegate_run):  # SCN-DLG-130
    run = delegate_run([blocked("technical", "technical"), reply("Q-001"), reply("Q-002")])
    assert len(run.adapter.requests) == 3  # the implementer's step, then one call for each question
    assert {r.result_schema["$id"] for r in run.adapter.requests[1:]} == {"l4/delegate-result@1"}
    assert all("batch" not in e for e in run.events("delegate.asked"))


def test_a_batch_that_timed_out_is_asked_question_by_question(delegate_run, valid_spec, fake_clock):  # SCN-DLG-131
    park(delegate_run, 4)
    first = delegate_run([Step(status="timeout")], profiles=JUDGE, delegate=ROOMY)
    assert len(first.adapter.requests) == 1
    done = results_of(first)
    assert [(q, r["status"], r["reason"], r["batch"]) for q, r in sorted(done.items())] == [
        (f"Q-00{n}", "deferred", "timeout", "Q-001+4") for n in range(1, 5)
    ]
    events = [LedgerEvent(e["ts"], e["run_id"], e["unit"], e["seq"], e["type"], e) for e in first.ledger()]
    assert all(batch_failed(events, f"Q-00{n}") for n in range(1, 5))
    assert delegate_cost(events, 3.0) == 4 * 3.0  # a call that reported no cost counts at the budget it was given
    fake_clock.advance(timedelta(minutes=6))
    script = [reply(f"Q-00{n}", "accept", text="Waived.") for n in range(1, 5)]
    second = delegate_run(script, profiles=JUDGE, delegate=ROOMY)
    assert len(second.adapter.requests) == 4  # each in its own call
    assert {r.result_schema["$id"] for r in second.adapter.requests} == {"l4/delegate-result@1"}
    again = [e for e in second.events("delegate.asked") if "batch" not in e]
    assert len(again) == 4
    assert [status_of(second, f"Q-00{n}") for n in range(1, 5)] == ["answered"] * 4


def test_a_batch_reply_that_breaks_the_schema_is_a_failed_attempt_asked_alone_next(
    delegate_run, valid_spec, fake_clock
):  # L4-DLG-005, L4-DLG-013
    park(delegate_run, 3)
    broken = Step(structured={"results": [accept("Q-001")], "extra": 1})  # not an l4/delegate-batch@1 document
    first = delegate_run([broken], profiles=JUDGE, delegate=ROOMY)
    done = results_of(first)
    assert [(q, r["status"], r["reason"], r["batch"]) for q, r in sorted(done.items())] == [
        (f"Q-00{n}", "deferred", "error", "Q-001+3") for n in range(1, 4)
    ]
    events = [LedgerEvent(e["ts"], e["run_id"], e["unit"], e["seq"], e["type"], e) for e in first.ledger()]
    assert all(batch_failed(events, f"Q-00{n}") for n in range(1, 4))
    fake_clock.advance(timedelta(minutes=6))
    script = [reply(f"Q-00{n}", "accept", text="Waived.") for n in range(1, 4)]
    second = delegate_run(script, profiles=JUDGE, delegate=ROOMY)
    assert len(second.adapter.requests) == 3
    assert {r.result_schema["$id"] for r in second.adapter.requests} == {"l4/delegate-result@1"}
    assert [status_of(second, f"Q-00{n}") for n in range(1, 4)] == ["answered"] * 3


def test_a_batch_that_fails_with_no_attempt_left_escalates_each_question(delegate_run, valid_spec):  # L4-DLG-013
    park(delegate_run, 3)
    run = delegate_run([Step(status="timeout")], profiles=JUDGE, delegate={"max_attempts_per_question": 1})
    done = results_of(run)
    assert {r["status"] for r in done.values()} == {"escalated"} and len(done) == 3
    assert {r["reason"] for r in done.values()} == {"delegate attempts used (1)"}


def test_a_capped_pass_counts_questions_not_calls(delegate_run, valid_spec):  # SCN-DLG-132
    ids = [f"Q-00{n}" for n in range(1, 6)]
    run = park(
        delegate_run, 7, (batch_reply(*(accept(q) for q in ids)),),
        delegate={**ROOMY, "enabled": True, "max_questions_per_run": 5},
    )  # fmt: skip
    assert len(run.adapter.requests) == 4  # the implementer's two steps, the judge, one batch
    assert [(e["question"], e["batch"]) for e in run.events("delegate.asked")] == [(q, "Q-001+5") for q in ids]
    (end,) = run.events("delegate.pass")
    assert (end["bound"], end["delegate_only"], end["calls"]) == ("cap", False, 1)
    assert [status_of(run, q) for q in (*ids, "Q-006", "Q-007")] == ["answered"] * 5 + ["open"] * 2
    assert set(results_of(run)) == set(ids)


def test_a_batch_prompt_is_bounded_and_the_rest_is_asked_by_a_later_batch(
    delegate_run, valid_spec, monkeypatch
):  # SCN-DLG-133
    park(delegate_run, 6)
    monkeypatch.setattr(pass_module, "BATCH_MAX_CHARS", 1)  # every batch is too long: it shrinks to two questions
    script = [batch_reply(accept(f"Q-00{a}"), accept(f"Q-00{a + 1}"), cost=0.2) for a in (1, 3, 5)]
    run = delegate_run(script, profiles=JUDGE, delegate=ROOMY)
    assert [r.result_schema["properties"]["results"]["maxItems"] for r in run.adapter.requests] == [2, 2, 2]
    assert [(e["question"], e["batch"], e["batch_size"]) for e in run.events("delegate.asked")] == [
        (f"Q-00{n}", f"Q-00{n - (n + 1) % 2}+2", 2) for n in range(1, 7)
    ]  # the questions left out of a batch are not recorded as asked
    assert [status_of(run, f"Q-00{n}") for n in range(1, 7)] == ["answered"] * 6
    assert [p["calls"] for p in run.events("delegate.pass")] == [3]


def test_an_odd_question_left_by_the_prompt_bound_is_asked_as_a_single(
    delegate_run, valid_spec, monkeypatch
):  # SCN-DLG-133
    park(delegate_run, 3)
    monkeypatch.setattr(pass_module, "BATCH_MAX_CHARS", 1)
    script = [batch_reply(accept("Q-001"), accept("Q-002")), reply("Q-003", "accept", text="Waived.")]
    run = delegate_run(script, profiles=JUDGE)
    assert [r.result_schema["$id"] for r in run.adapter.requests] == ["l4/delegate-batch@1", "l4/delegate-result@1"]
    assert "batch" not in [e for e in run.events("delegate.asked") if e["question"] == "Q-003"][0]


def test_a_limit_moves_the_whole_batch_to_the_next_profile(delegate_run, valid_spec):
    park(delegate_run, 3)
    second = {"dlg2": {"adapter": "fake", "vendor": "dlgco", "model": "delegate-model-2"}}
    run = delegate_run(
        [limit_step(), batch_reply(*(accept(f"Q-00{n}") for n in (1, 2, 3)), cost=0.3)],
        profiles={**JUDGE, **second}, roles={"delegate": ["dlg", "dlg2"]},
    )  # fmt: skip
    assert len(run.adapter.requests) == 2 and {r.result_schema["$id"] for r in run.adapter.requests} == {
        "l4/delegate-batch@1"
    }
    asked = run.events("delegate.asked")
    assert [(e["question"], e["profile"]) for e in asked] == [
        (f"Q-00{n}", p) for p in ("dlg", "dlg2") for n in (1, 2, 3)
    ]
    assert [(r["status"], r["profile"]) for r in results_of(run).values()] == [("answered", "dlg2")] * 3
    assert [p["calls"] for p in run.events("delegate.pass")] == [2]


# -- which questions share a call: the forming rules, over the ledger (L4-DLG-028) ---------------------------------


def judged_by(*profiles: str) -> list[dict]:
    return [{"profile": p, "model": f"{p}-model"} for p in profiles]


def raised(seq: int, qid: str, target: str, judges: list[dict]) -> LedgerEvent:
    data = {"id": qid, "kind": "verdict", "source": "verifier", "target": target, "judges": judges}
    return LedgerEvent("2026-11-01T10:00:00Z", "r-1", "u", seq, "question.raised", data)


def deferred(seq: int, qid: str, reason: str, **more) -> LedgerEvent:
    data = {"question": qid, "status": "deferred", "reason": reason, "called": True, **more}
    return LedgerEvent("2026-11-01T10:01:00Z", "r-1", "u", seq, "delegate.result", data)


def forming(work, events, *, only=True, calls=0, **cfg):
    """The questions `_batched` takes from `work[0]` on, and the work indices it marks as taken."""
    p = object.__new__(_Pass)
    p.cfg, p.only, p.calls, p.implementers, p._events = DelegateCfg(**cfg), only, calls, (), lambda: events
    taken: list[str] = []
    p._prechecks = lambda target, question: taken.append(question.id)  # type: ignore[method-assign]
    p._question = lambda target, question: taken.append(f"{question.id}!")  # type: ignore[method-assign]
    done: set[int] = set()
    p._batched(work, 0, done)
    return taken, done


FOLDER, OTHER = _Target(Path("."), "", None, "u"), _Target(Path("."), "", None, "u")


def asking(*pairs, kind=QuestionKind.VERDICT):
    return [(t, SimpleNamespace(id=qid, kind=kind, blocking_tasks=())) for t, qid in pairs]


def test_a_batch_takes_the_questions_of_its_folder_with_its_askers():
    events = [raised(n, f"Q-00{n}", f"C-{n}", judged_by("j1")) for n in (1, 2, 3)]
    work = asking((FOLDER, "Q-001"), (FOLDER, "Q-002"), (OTHER, "Q-003"))
    assert forming(work, events) == (["Q-001", "Q-002"], {1})  # Q-003 is a question of another folder
    events[1] = raised(2, "Q-002", "C-2", judged_by("j2"))
    assert forming(work, events) == (["Q-001"], set())  # other askers: another call


def test_a_batch_leaves_out_other_kinds_and_keys_in_common():
    events = [raised(n, f"Q-00{n}", f"C-{n}", judged_by("j1")) for n in (1, 2, 3)]
    work = (
        asking((FOLDER, "Q-001")) + asking((FOLDER, "Q-002"), kind=QuestionKind.TECHNICAL) + asking((FOLDER, "Q-003"))
    )
    assert forming(work, events) == (["Q-001", "Q-003"], {2})  # the technical question is asked alone, in its turn
    events[2] = raised(3, "Q-003", "C-1", judged_by("j1"))  # the same verdict target as Q-001
    assert forming(work, events) == (["Q-001"], set())


def test_a_question_whose_batch_failed_is_asked_alone_and_joins_no_batch():
    events = [raised(n, f"Q-00{n}", f"C-{n}", judged_by("j1")) for n in (1, 2, 3)]
    work = asking((FOLDER, "Q-001"), (FOLDER, "Q-002"), (FOLDER, "Q-003"))
    failed = [*events, deferred(4, "Q-002", "timeout", batch="Q-001+3", batch_size=3)]
    assert forming(work, failed) == (["Q-001", "Q-003"], {2})  # Q-002 stays for its own turn
    alone = [*events, deferred(4, "Q-001", "error", batch="Q-001+3", batch_size=3)]
    assert forming(work, alone) == (["Q-001!"], set())  # the first one is asked alone
    other = [*events, deferred(4, "Q-002", "the batch reply had no result for Q-002", batch="Q-001+3")]
    assert forming(work, other)[0] == ["Q-001", "Q-002", "Q-003"]  # another reason: it joins again
    single = [*events, deferred(4, "Q-002", "timeout")]  # a deferral of a call that was not a batch
    assert forming(work, single)[0] == ["Q-001", "Q-002", "Q-003"]


def test_the_room_of_a_batch_is_the_batch_size_and_in_a_capped_pass_the_cap_left():
    events = [raised(n, f"Q-00{n}", f"C-{n}", judged_by("j1")) for n in range(1, 8)]
    work = asking(*((FOLDER, f"Q-00{n}") for n in range(1, 8)))
    assert forming(work, events, batch_size=3)[0] == ["Q-001", "Q-002", "Q-003"]
    assert len(forming(work, events)[0]) == 5  # the default batch size
    assert len(forming(work, events, only=False, calls=0, max_questions_per_run=5)[0]) == 5
    assert len(forming(work, events, only=False, calls=3, max_questions_per_run=5)[0]) == 2
    assert len(forming(work, events, only=True, calls=3, max_questions_per_run=5)[0]) == 5  # a delegate-only pass
