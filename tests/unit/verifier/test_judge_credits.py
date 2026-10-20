"""kiro-judge 7.1, SCN-KJD-11: a judge's plan credits are summed over its calls and recorded, never as dollars."""

import pytest

from l4.agents.base import Usage
from l4.agents.factory import ADAPTERS
from l4.agents.fake import FakeAdapter, Step
from l4.cli import main
from l4.llm.agent_judge import StructuredResult
from l4.specs.criteria import openspec_criteria
from l4.verifier.judge import JudgePrompt, run_judge

from ..conftest import FIXTURE, UNIT
from ..implementer.conftest import green_step, red_step
from ..orchestrator.conftest import Run
from .conftest import judge_reply

CRITERIA = [c.id for c in openspec_criteria(FIXTURE / "openspec" / "changes" / "add-discount-codes")]
PROMPT = JudgePrompt("SYSTEM", "USER", "0" * 64, "judge@1")


class Scripted:
    def __init__(self, *results: StructuredResult) -> None:
        self._results = list(results)

    def complete_structured(self, system, messages, json_schema, *, effort, max_tokens, timeout_s):
        return self._results.pop(0)


def test_the_credits_of_every_call_add_up_and_the_dollars_stay_apart():
    bad = StructuredResult("schema_invalid", detail="x", usage=Usage(credits=0.05, credits_source="kiro.stream"))
    good = StructuredResult(
        "ok", parsed=judge_reply(["C-0a1b2c3d"]), usage=Usage(credits=0.02, credits_source="kiro.stream")
    )
    run = run_judge(Scripted(bad, good), PROMPT, timeout_s=60, redact=str)
    assert run.status == "ok" and run.calls == 2
    assert run.credits == pytest.approx(0.07) and run.credits_source == "kiro.stream"
    assert run.cost_usd == 0.0


def test_a_judge_that_meters_no_credits_has_none():
    ok = StructuredResult("ok", parsed=judge_reply(["C-0a1b2c3d"]), usage=Usage(cost_usd=0.05))
    run = run_judge(Scripted(ok), PROMPT, timeout_s=60, redact=str)
    assert run.credits is None and run.credits_source is None


@pytest.fixture
def run_credit_judge(tdd_repo, raw, monkeypatch, valid_spec, fake_clock):
    def run(script) -> Run:
        tdd_repo.write_config(profiles={"kj": {"adapter": "fake", "vendor": "beta"}}, roles={"judges": ["kj"]})
        adapter = FakeAdapter(script, served_model=False)
        monkeypatch.setitem(ADAPTERS, "fake", lambda: adapter)
        argv = ["run", "--unit", UNIT, "--repo", str(tdd_repo.repo)]
        return Run(main(argv, environ=tdd_repo.environ), adapter, tdd_repo, raw)

    return run


def test_scn_kjd_11_the_verify_and_budget_events_carry_the_credits(run_credit_judge):
    first = Step(structured={"nonsense": 1}, credits=0.05, credits_source="kiro.stream")
    second = Step(structured=judge_reply(CRITERIA), credits=0.02, credits_source="kiro.stream")
    run = run_credit_judge([red_step(), green_step(), first, second])
    assert run.code == 0
    (judged,) = run.events("verify.judge")
    assert judged["calls"] == 2 and judged["credits"] == pytest.approx(0.07)
    costs = [e for e in run.events("budget.cost") if e.get("role") == "judge"]
    assert len(costs) == 1
    (cost,) = costs
    assert cost["credits"] == pytest.approx(0.07) and cost["credits_source"] == "kiro.stream"
    assert cost["profile"] == "kj" and "usd" not in cost


def test_a_judge_without_credits_writes_no_credit_fields(run_credit_judge):
    run = run_credit_judge([red_step(), green_step(), Step(structured=judge_reply(CRITERIA), cost_usd=0.03)])
    (judged,) = run.events("verify.judge")
    assert "credits" not in judged
    assert all("credits" not in e for e in run.events("budget.cost"))
