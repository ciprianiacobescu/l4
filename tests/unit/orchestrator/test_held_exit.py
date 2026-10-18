# ruff: noqa: F811
"""A held task ends the run awaiting a person with exit 11, and a second run with no answer starts no agent step
(L4-IMP-063, SCN-IMP-312)."""

from l4.agents.fake import Step
from l4.implementer import tdd
from l4.implementer.base_run import BaseRunResult
from l4.implementer.discrimination import PreSatisfied

from ..archive.conftest import forge_env, gitlab, use_fake_gitlab  # noqa: F401
from ..implementer.conftest import KNOWN, result
from ..implementer.test_base_run import PASSES_AT_BASE
from ..verifier.conftest import valid_spec  # noqa: F401

REASON = "the test-presatisfied run ran no test (exit 2, 45 collection errors)"


def inconclusive(monkeypatch) -> None:
    monkeypatch.setattr(
        tdd,
        "confirm_pre_satisfied",
        lambda wb, cands, *, real=None: PreSatisfied(inconclusive={c: REASON for c in cands}),
    )
    monkeypatch.setattr(
        tdd, "confirmed_by_base_run", lambda wb, cands, ids, *, real=None: BaseRunResult(reason="no failure")
    )


def test_a_held_task_ends_awaiting_human_with_exit_11(run_l4, monkeypatch):
    inconclusive(monkeypatch)
    step = Step(writes={"tests/test_new.py": PASSES_AT_BASE}, structured=result("red", criteria_ids=[KNOWN]))
    first = run_l4([step])
    assert first.code == 11
    assert first.outcome["units"][0]["phase_after"] == "awaiting_human"
    assert first.events("task.attempt_failed") == []
    [held] = first.events("check.inconclusive")
    assert held["reason"] == REASON and held["question"] == "Q-001"
    [raised] = first.events("question.raised")
    assert raised["kind"] == "harness"
    again = run_l4([step])
    assert again.code == 11 and again.adapter.requests == []  # nothing answered: no agent step
    assert again.outcome["units"][0]["phase_after"] == "awaiting_human"
