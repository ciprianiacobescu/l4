"""The two delegate loops in the simulator (delegate-answers 16.1; L4-DLG-003, L4-DLG-006, L4-DLG-007, design D4,
D13; SCN-DLG-24): a scripted `fake` profile of `roles.delegate` answers, in the run that parks the unit, a question the
implementer raised and a verdict question of the verifier. The next run reads the answer and goes on. The lifecycle has
no new edge (SPEC 12.0)."""

from pathlib import Path

import pytest

from l4.sim.runner import ScenarioResult, run_scenario
from l4.sim.scenarios import Scenario, ScenarioError, load_scenario
from l4.state.lifecycle import all_edges

SCENARIOS = Path(__file__).parent / "scenarios"
QUESTION, VERDICT = "delegate-answers-question", "delegate-answers-verdict"


def scenario(name: str) -> Scenario:
    return load_scenario((SCENARIOS / f"{name}.yaml").read_text(encoding="utf-8"), source=f"{name}.yaml")


@pytest.fixture(scope="module")
def question() -> ScenarioResult:
    return run_scenario(scenario(QUESTION))


@pytest.fixture(scope="module")
def verdict() -> ScenarioResult:
    return run_scenario(scenario(VERDICT))


def of(result: ScenarioResult, kind: str) -> list[dict]:
    return [e for e in result.events if e["type"] == kind]


def phases(result: ScenarioResult) -> list[str]:
    return [e["to"] for e in of(result, "phase.changed")]


def test_an_implementer_question_answered_by_the_delegate(question):
    assert question.status == "pass", question.report
    assert (question.exit_code, question.final_phase) == (0, "in_review")
    raised, asked, result, answered = (
        of(question, k)[0] for k in ("question.raised", "delegate.asked", "delegate.result", "question.answered")
    )
    assert raised["id"] == "Q-001" and asked["question"] == "Q-001" and asked["profile"] == "delegate"
    assert result["status"] == "answered" and result["model"] == "sim-delegate-model" and result["cli"] == "fake"
    assert answered["by"] == "delegate" and answered["answer_sha256"] == result["answer_sha256"]
    order = [e["type"] if e["type"] != "phase.changed" else "->" + e["to"] for e in question.events]
    park, ask, done = order.index("->awaiting_human"), order.index("delegate.asked"), order.index("question.answered")
    assert park < ask < done < order.index("->implementing", done)  # the delegate works while the unit is parked,
    assert order.count("run.started") == 2  # and the next run (not the same one, D4) moves the unit on
    after = phases(question)[phases(question).index("awaiting_human") :]
    assert after[:2] == ["awaiting_human", "implementing"] and after[-1] == "in_review"


def test_a_verdict_accepted_by_the_delegate_hands_off(verdict):  # SCN-DLG-24
    assert verdict.status == "pass", verdict.report
    assert (verdict.exit_code, verdict.final_phase) == (0, "in_review")
    verdicts = [e["verdict"] for e in of(verdict, "verify.verdict")]
    assert verdicts == ["NEEDS_HUMAN", "PASS"]  # the next round aggregates the accept
    (human,) = of(verdict, "human.verdict")
    assert human["decision"] == "accept" and human["by"] == "delegate"  # labelled, never `human`
    (result,) = of(verdict, "delegate.result")
    assert result["status"] == "answered" and result["kind"] == "verdict" and result["decision"] == "accept"
    assert "merged" not in phases(verdict)  # a PASS hands off; merging stays a person's (D13)
    assert phases(verdict)[-2:] == ["verified", "in_review"]


def test_no_new_lifecycle_edge(question, verdict):
    table = {(None if s is None else s.value, t.value, None if g is None else g.value) for s, t, g in all_edges()}
    taken = {
        (e.get("from"), e["trigger"], e["to"]) for result in (question, verdict) for e in of(result, "phase.changed")
    }
    assert taken and all(
        (source, trigger, target) in table or any(s == source and t == trigger and g is None for s, t, g in table)
        for source, trigger, target in taken
    ), sorted(taken - table)


def test_the_delegate_profile_is_scripted_per_scenario():
    base = scenario(QUESTION)
    assert list(base.delegates) == ["delegate"] and base.delegates["delegate"].replies[0]["decision"] == "answer"
    with pytest.raises(ScenarioError, match="delegate_script"):  # strict models: a mistyped key is refused
        load_scenario((SCENARIOS / f"{QUESTION}.yaml").read_text().replace("delegates:", "delegate_script:"))


def test_a_delegate_with_no_reply_leaves_the_question_to_a_person():
    text = (SCENARIOS / f"{QUESTION}.yaml").read_text(encoding="utf-8")
    start, end = text.index("    replies:"), text.index("expect:")
    result = run_scenario(load_scenario(text[:start] + "    replies: []\n" + text[end:]))
    assert result.status == "fail" and result.final_phase == "awaiting_human"  # nothing answered, the unit waits
    assert [e["status"] for e in of(result, "delegate.result")][0] != "answered"
    assert not of(result, "question.answered")
