# ruff: noqa: F811  (delegate_run is a fixture imported by name)
"""The orchestrator calls the delegate pass at the end of the run that parks the unit (delegate-answers 9.2; L4-DLG-003,
L4-CLR-002; SCN-DLG-01, SCN-DLG-09, SCN-DLG-44): after the clarifier, before the run closes, under the unit's lease, and
never when the base branch has not turned the delegate on."""

import pytest

from l4 import services

from ..clarifier.test_hook import CLARIFIER_CONFIG, clarifier_reply, s1
from ..delegate.conftest import blocked, delegate_run, no_hooks_but_the_delegate, publish_base, reply  # noqa: F401
from .conftest import UNIT_DIR

CLARIFY = "l4.clarifier.clarifier:clarify_hook"


@pytest.fixture
def with_clarifier(monkeypatch):
    monkeypatch.setitem(services.HOOKS, "clarify", CLARIFY)


def order(run, *types: str) -> list[str]:
    return [e["type"] for e in run.ledger() if e["type"] in types]


def test_the_parking_run_calls_the_pass_after_the_clarifier(delegate_run, with_clarifier):  # SCN-DLG-09
    script = [blocked("product"), clarifier_reply(kind="product", confidence="medium"), reply("Q-001")]
    run = delegate_run(script, **CLARIFIER_CONFIG)
    assert run.code == 11
    assert order(run, "clarifier.result", "delegate.asked", "delegate.result", "run.finished") == [
        "clarifier.result", "delegate.asked", "delegate.result", "run.finished",
    ]  # fmt: skip
    assert [e["question"] for e in run.events("delegate.asked")] == ["Q-001"]
    assert "- **Status:** answered" in run.pushed(f"{UNIT_DIR}/questions.md")


def test_the_clarifier_answers_first_and_the_delegate_takes_the_rest(delegate_run, with_clarifier):  # SCN-DLG-44
    script = [
        blocked("technical", "product"),
        clarifier_reply(question_id="Q-001"), s1(False), s1(True),  # the clarifier auto-answers the technical one
        clarifier_reply(question_id="Q-002", kind="product", confidence="medium"),  # a suggestion only
        reply("Q-002"),
    ]  # fmt: skip
    run = delegate_run(script, **CLARIFIER_CONFIG)
    assert run.code == 11
    assert [(e["id"], e["by"]) for e in run.events("question.answered")] == [
        ("Q-001", "clarifier"),
        ("Q-002", "delegate"),
    ]
    assert [e["question"] for e in run.events("delegate.asked")] == ["Q-002"]


def test_off_by_default(run_l4):  # SCN-DLG-01
    run = run_l4([blocked("technical")], roles={"delegate": ["judge"]})
    assert run.code == 11
    assert [t for t in (e["type"] for e in run.ledger()) if t.startswith("delegate.")] == []
    assert not any(subject.endswith("delegate [skip ci]") for subject in run.subjects())
    assert run.outcome["units"][0]["phase_after"] == "awaiting_human"


def test_the_exit_stays_11(delegate_run):
    run = delegate_run([blocked("technical"), reply()])
    assert run.code == 11 and run.outcome["units"][0]["phase_after"] == "awaiting_human"
    assert run.outcome["units"][0]["open_questions"] == []  # the answer is read by the next run, which moves the unit
