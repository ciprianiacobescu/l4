"""Live wave D, W-D1: a weak judge's repaired reply and its per-profile counters reach the ledger and the report."""

import json

import pytest

from l4.agents.factory import ADAPTERS
from l4.agents.fake import FakeAdapter, Step
from l4.cli import main
from l4.specs.criteria import openspec_criteria

from ..conftest import FIXTURE, UNIT
from ..implementer.conftest import green_step, red_step
from ..orchestrator.conftest import Run
from .conftest import judge_reply

CRITERIA = [c.id for c in openspec_criteria(FIXTURE / "openspec" / "changes" / "add-discount-codes")]
VERIFICATION = "openspec/changes/add-discount-codes/verification.md"
EVIDENCE = "openspec/changes/add-discount-codes/.l4/evidence/round-1/verdict.json"
PROFILES = {"weak": {"adapter": "fake", "vendor": "beta"}}


@pytest.fixture
def run_weak(tdd_repo, raw, monkeypatch, valid_spec, fake_clock):
    def run(script) -> Run:
        tdd_repo.write_config(profiles=PROFILES, roles={"judges": ["weak"]})
        adapter = FakeAdapter(script, served_model=False)
        monkeypatch.setitem(ADAPTERS, "fake", lambda: adapter)
        return Run(
            main(["run", "--unit", UNIT, "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ),
            adapter,
            tdd_repo,
            raw,
        )

    return run


def long_quote_judge() -> Step:
    reply = judge_reply(CRITERIA)
    reply["criteria"][0]["evidence"][0]["quote"] = "assert total == 3  # " + "padding " * 60
    reply["findings"] = [
        {"severity": "minor", "title": "t", "detail": "d", "evidence": [], "suggested_fix": ["WHEN a THEN b"]}
    ]
    return Step(structured=reply)


def test_a_repaired_reply_is_one_call_a_ledger_event_and_a_counter_in_the_report(run_weak):
    run = run_weak([red_step(), green_step(), long_quote_judge()])
    assert run.code == 0
    (judged,) = run.events("verify.judge")
    assert (judged["status"], judged["calls"], judged["reply"]) == ("ok", 1, "repaired")
    (repaired,) = run.events("judge.reply_repaired")
    assert repaired["profile"] == "weak" and "criteria[].evidence[].quote" in repaired["fields"]
    assert "findings[].suggested_fix" in repaired["fields"]
    text = run.pushed(VERIFICATION)
    assert "valid 0, repaired 1, retried 0, discarded 0; this round: repaired" in text
    verdict = json.loads(run.pushed(EVIDENCE))
    assert verdict["judge_replies"]["repaired"] == 1 and verdict["judge_reply"] == "repaired"


def test_a_clean_reply_counts_as_valid_and_raises_no_repair_event(run_weak):
    run = run_weak([red_step(), green_step(), Step(structured=judge_reply(CRITERIA))])
    assert run.events("judge.reply_repaired") == []
    assert [e["reply"] for e in run.events("verify.judge")] == ["valid"]
    assert "valid 1, repaired 0" in run.pushed(VERIFICATION)
