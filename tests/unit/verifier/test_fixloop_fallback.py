"""Contract C21 at the M1.3 merge: a usage limit in a fix task goes through the orchestrator's fallback
(`ctx.shared["fall_back"]`, `Orchestrator.switch_profile`) and the task is retried once on the next implementer
profile, so the cool-down, the outcome's profiles and `L4-Fallback-From` follow it. Nothing left still parks."""

from datetime import UTC, datetime

import pytest

from l4.agents.base import LimitSignal
from l4.agents.fake import Step

from ..implementer.conftest import red_step
from ..orchestrator.conftest import BRANCH
from .test_ladder_fix import FIX_UNIT, chore_fix, judge, noqa_green

RESETS = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
TWO = {"roles": {"implementer": ["impl", "impl-b"]}, "profiles": {"impl-b": {"adapter": "fake", "vendor": "otherco"}}}


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """The fix loop is on, as in `test_ladder_fix`."""


def limited(**over: object) -> Step:
    limit = LimitSignal("fake", None, "usage_limit", RESETS, "test", "You have hit your usage limit")
    return Step(status="quota", limit=limit, **over)


def test_a_limit_in_a_fix_task_moves_it_to_the_next_profile_through_the_orchestrator(run_l4, valid_spec, fake_clock):
    run = run_l4([red_step(), noqa_green(), limited(writes={"leftover.txt": "half"}), chore_fix(), judge()], **TWO)
    assert run.code == 0, run.triggers()
    assert run.triggers()[-3:] == ["verify_fail_fix", "fix_unit_done", "verify_pass"]
    [limit] = run.events("availability.limit")
    assert limit.get("fix_unit") == FIX_UNIT
    fallback = run.events("availability.fallback")
    assert [(e["from"], e["to"], e["reason"]) for e in fallback] == [("impl", "impl-b", "usage_limit")]
    assert run.outcome["units"][0]["profiles"]["implementer"] == "impl-b"
    assert run.outcome["units"][0]["profiles"]["fallback_from"] == "impl"
    assert "leftover.txt" not in run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", BRANCH)
    fmt = "%s|%(trailers:key=L4-Agent,key=L4-Fallback-From,valueonly,separator=;)"
    log = run.raw(run.tdd.origin, "log", "--reverse", f"--format={fmt}", f"main..{BRANCH}")
    [fix] = [line for line in log.splitlines() if line.startswith(f"fix({FIX_UNIT})")]
    assert fix.endswith("|impl-b;impl")
    retried = run.adapter.requests[3].prompt
    assert 'kind="previous-attempt"' in retried and "usage_limit" in retried


def test_a_silent_fix_step_moves_the_task_once_and_the_next_profile_is_told(run_l4, valid_spec, fake_clock):
    quiet = Step(idle_s=600, status="timeout", writes={"leftover.txt": "half"})
    run = run_l4([red_step(), noqa_green(), quiet, chore_fix(), judge()], **TWO)
    assert run.code == 0, run.triggers()
    [limit] = run.events("availability.limit")
    assert limit.get("fix_unit") == FIX_UNIT and limit["kind"] == "silent"
    [fallback] = run.events("availability.fallback")
    assert (fallback["from"], fallback["to"], fallback["reason"]) == ("impl", "impl-b", "silent")
    assert not [e for e in run.events("task.attempt_failed") if e.get("fix_unit") == FIX_UNIT]
    assert run.outcome["units"][0]["profiles"]["implementer"] == "impl-b"
    retried = run.adapter.requests[3].prompt
    assert 'kind="previous-attempt"' in retried and "went silent: no output for 10m" in retried
    assert "leftover.txt" not in run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", BRANCH)


def test_a_second_limit_on_the_same_fix_task_parks_the_unit(run_l4, valid_spec, fake_clock):
    run = run_l4([red_step(), noqa_green(), limited(), limited()], **TWO)
    assert run.code == 12
    assert [e["to"] for e in run.events("phase.changed")][-2:] == ["fixing", "waiting_capacity"]
    assert len(run.events("availability.fallback")) == 1
