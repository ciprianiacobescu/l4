"""A REPLAYED red step (0.4.17 accept -> replay) must meet detect-test-tamper's
pre-existing-test check exactly as an agent step does. Ports SCN-IMP-323's shape (held_new + forge_hold + accept).

A step that weakens a pre-existing test is refused before a pre-satisfied hold is taken, so a person is never asked to
accept a tampering step."""

import pytest

from l4.agents.fake import Step
from l4.implementer.loop import run_task

from .conftest import KNOWN, Bench, result
from .test_earlier_red import NEW, OLD, OLD_FILE, TASK
from .test_held_accept import forge_hold, held_new, renamed_step
from .test_held_answers import answer
from .test_held_check import held_bench, zero_says

WEAK_OLD = OLD.replace("assert total([1.0, 2.0]) == 3.0", "assert True")
SKIP_OLD = OLD.replace("def test_old_total", "@pytest.mark.skip\ndef test_old_total")
REBOUND_OLD = OLD + "\n\ndef test_old_total():\n    pass\n"


def head_text(bench: Bench, rel: str) -> str:
    return bench.wb.git.run("show", f"HEAD:{rel}").stdout


@pytest.mark.parametrize("form", ["body", "skip", "rebound"])
def test_a_replayed_red_step_that_tampers_a_preexisting_test_is_refused(make_bench, monkeypatch, raw, form):
    tampered = {"body": WEAK_OLD, "skip": SKIP_OLD, "rebound": REBOUND_OLD}[form]
    bench = held_new(make_bench, monkeypatch)  # Q-001 raised for an honest step; script: [new_step(), renamed_step()]
    forge_hold(bench, raw, {"tests/test_new.py": NEW, OLD_FILE: tampered})  # as a hold of that step would save it
    answer(bench, raw, "accept: fine")
    outcome = run_task(bench.wb, TASK)
    assert len(bench.events("held.replayed")) == 1, outcome.reason  # the replay ran
    failed = bench.events("task.attempt_failed")
    assert failed, outcome.reason
    reason = failed[0].get("reason", "")
    if form == "skip":  # skipped != passed: classify_red refuses it before the AST comparison
        assert reason.startswith("red broke existing tests"), reason
    else:
        assert reason.startswith("red changed tests that existed before this step"), reason
        hits = [e for e in bench.events("guard.test_tamper") if e.get("rule") == "pre-existing test"]
        assert hits and hits[0]["action"] == "rejected" and hits[0]["tests"] == ["test_old_total"], hits
    assert bench.events("task.done") == [] and bench.events("task.red_ok") == []
    assert head_text(bench, OLD_FILE) == OLD  # the tampered test never reached the branch
    assert len(bench.adapter.requests) == 2  # the replay is used once; attempt 2 is an agent step
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-002"]), outcome.reason  # used-up accept: new Q


def test_an_agent_step_that_tampers_while_presatisfied_is_inconclusive_is_refused_not_held(make_bench, monkeypatch):
    zero_says(monkeypatch)
    tamper = Step(writes={"tests/test_new.py": NEW, OLD_FILE: WEAK_OLD}, structured=result("red", criteria_ids=[KNOWN]))
    bench = held_bench(make_bench, [tamper, renamed_step()])
    run_task(bench.wb, TASK)
    failed = bench.events("task.attempt_failed")
    assert failed and failed[0]["reason"].startswith("red changed tests that existed before this step")
    asked = bench.events("question.raised")  # attempt 2 is another step: only the tampering step must never be asked
    assert not asked or failed[0]["seq"] < asked[0]["seq"]
    hits = [e for e in bench.events("guard.test_tamper") if e.get("rule") == "pre-existing test"]
    assert hits and hits[0]["action"] == "rejected"
    assert bench.events("task.done") == [] and head_text(bench, OLD_FILE) == OLD
