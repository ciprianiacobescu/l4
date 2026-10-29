"""fix-unit-escalate 2.1, SCN-IMP-183 (+, amended; L4-IMP-017): the tasks of a fix unit move along the implementer chain
like the tasks of the unit's own loop. Without the orchestrator's entry point in `ctx.shared` (a fix context built
without an orchestrator) the fix loop runs `run_task` with no hook, as it did before."""

from datetime import UTC, datetime

import pytest

from l4.agents.base import LimitSignal
from l4.agents.fake import Step
from l4.orchestrator import Orchestrator

from ..implementer.conftest import IMPL, green_step, red_step, result
from ..orchestrator.test_fallback import TWO
from .test_ladder_fix import FIX_UNIT, chore_fix, judge, noqa_green

RESETS = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """The fix loop is on, as in `test_ladder_fix`."""


def test_the_tasks_of_a_fix_unit_move_to_the_next_profile(run_l4, valid_spec, fake_clock):
    invalid = Step()  # no result object: a failed attempt
    run = run_l4([red_step(), noqa_green(), invalid, invalid, chore_fix(), judge()], **TWO)
    assert run.code == 0
    (moved,) = run.events("implementer.escalated")
    assert (moved["task"], moved["phase"], moved["from"], moved["to"], moved["failures"], moved["attempt"]) == (
        "1.1", "single", "impl", "impl-b", 2, 3,
    )  # fmt: skip
    assert moved["fix_unit"] == FIX_UNIT
    assert run.events("implementer.escalation_skipped") == []
    vendors = [r.profile.vendor for r in run.adapter.requests]
    assert vendors[2] == vendors[3] == vendors[1] and vendors[4] != vendors[3]  # the third attempt runs on impl-b
    fix_prompt = run.adapter.requests[4].prompt
    assert 'kind="previous-attempt"' in fix_prompt and 'reason="escalation"' in fix_prompt
    assert [e["profile"] for e in run.events("task.attempt_failed")] == ["impl", "impl"]
    assert run.events("breaker.tripped") == []
    assert run.outcome["units"][0]["profiles"].get("implementer") == "impl"  # the run's profile did not move


def test_without_the_entry_point_in_the_fix_context_the_tasks_do_not_move(run_l4, valid_spec, monkeypatch):
    init = Orchestrator.__init__

    def without(self, *args, **kwargs) -> None:
        init(self, *args, **kwargs)
        for key in ("escalate", "escalation_ended"):
            self._ctx.shared.pop(key, None)

    monkeypatch.setattr(Orchestrator, "__init__", without)
    invalid = Step()
    run = run_l4([red_step(), noqa_green(), invalid, invalid, invalid], **TWO)
    assert run.code == 13
    assert run.events("implementer.escalated") == [] and run.events("implementer.escalation_skipped") == []
    assert len(run.adapter.requests) == 5
    assert len({r.profile.vendor for r in run.adapter.requests}) == 1  # never the second profile
    assert [e["profile"] for e in run.events("task.attempt_failed")] == ["impl"] * 3
    (tripped,) = run.events("breaker.tripped")
    assert tripped["reason"] == "max_task_attempts" and tripped["profiles"] == [{"profile": "impl", "failures": 3}]


def test_a_limit_on_the_moved_profile_in_a_fix_task_cools_that_profile_only(  # SCN-IMP-421
    run_l4, valid_spec, fake_clock
):
    limit = LimitSignal("fake", None, "usage_limit", RESETS, "test", "You have hit your usage limit")
    invalid = Step()
    script = [red_step(), noqa_green(), invalid, invalid, Step(status="quota", limit=limit), chore_fix(), judge()]
    run = run_l4(script, **TWO)
    assert run.code == 0
    (cooled,) = run.events("availability.cooldown")
    assert cooled["profile"] == "impl-b"
    vendors = [r.profile.vendor for r in run.adapter.requests]
    assert vendors[4] != vendors[1] and vendors[5] == vendors[1]  # the limited step ran on impl-b, the retry on impl
    assert run.events("task.attempt_failed")[-1]["attempt"] == 2  # a limit is not an attempt
    assert run.outcome["units"][0]["profiles"].get("implementer") == "impl"
    note = run.adapter.requests[5].prompt.split('kind="previous-attempt"', 1)[1].split("</l4:data>", 1)[0]
    assert 'profile="impl-b"' in note and 'limit="usage_limit"' in note  # the profile that limited, not the run's


def noqa_and_nosec_green() -> Step:
    """Two findings, so two chore tasks: an undeclared suppression, and a `nosec` that no `[config]` task reviewed."""
    step = green_step()
    step.writes = {"src/pytdd/pricing.py": IMPL + "\nUNUSED = 1  # noqa: E501\nOTHER = 2  # nosec\n"}
    return step


def test_the_next_fix_task_starts_on_the_run_profile_after_a_task_moved(run_l4, valid_spec, fake_clock):  # SCN-IMP-421
    limit = LimitSignal("fake", None, "usage_limit", RESETS, "test", "You have hit your usage limit")
    invalid = Step()
    tidied = Step(writes={"src/pytdd/pricing.py": IMPL + "\n# tidied\n"}, structured=result("single"))
    script = [
        red_step(), noqa_and_nosec_green(), invalid, invalid, chore_fix(),  # task 1 moves to impl-b and passes
        Step(status="quota", limit=limit), tidied, judge(),  # task 2 starts on impl, which limits
    ]  # fmt: skip
    run = run_l4(script, **TWO)
    assert run.code == 0
    assert len(run.events("task.tdd_exempt")) == 2
    (moved,) = run.events("implementer.escalated")
    assert (moved["task"], moved["from"], moved["to"]) == ("1.1", "impl", "impl-b")
    vendors = [r.profile.vendor for r in run.adapter.requests]
    assert vendors[5] == vendors[1] != vendors[4]  # task 1's third step ran on impl-b, task 2's first on impl
    (cooled,) = run.events("availability.cooldown")
    assert cooled["profile"] == "impl"  # the profile task 2 ran on, not the one task 1 had moved to
