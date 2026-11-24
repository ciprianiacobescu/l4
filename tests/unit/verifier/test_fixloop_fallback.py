"""Contract C21 at the M1.3 merge: a usage limit in a fix task goes through the orchestrator's fallback
(`ctx.shared["fall_back"]`, `Orchestrator.switch_profile`) and the task is retried once on the next implementer
profile, so the cool-down, the outcome's profiles and `L4-Fallback-From` follow it. Nothing left still parks."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from l4.agents.base import LimitSignal
from l4.agents.fake import FakeAdapter, Step
from l4.verifier import fixloop

from ..implementer.conftest import red_step
from ..orchestrator.conftest import BRANCH
from .test_ladder_fix import FIX_UNIT, chore_fix, judge, noqa_green

RESETS = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
TWO = {"roles": {"implementer": ["impl", "impl-b"]}, "profiles": {"impl-b": {"adapter": "fake", "vendor": "otherco"}}}


THREE = TWO | {
    "roles": {"implementer": ["impl", "impl-b", "impl-c"]},
    "profiles": TWO["profiles"] | {"impl-c": {"adapter": "fake", "vendor": "thirdco"}},
}


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


def test_a_second_limit_on_the_same_fix_task_cools_the_profile_that_hit_it(run_l4, valid_spec, fake_clock):
    """The unit parks on the second limit, but impl-b cools too: the next run goes to impl-c, not back to impl-b."""
    run = run_l4([red_step(), noqa_green(), limited(), limited()], **THREE)
    assert run.code == 12
    assert [e["profile"] for e in run.events("availability.cooldown")] == ["impl", "impl-b"]
    assert len(run.events("availability.fallback")) == 1


def test_a_fixes_fallen_back_workbench_carries_the_longest_gate_run(run_l4, valid_spec, fake_clock, monkeypatch):
    """L4-IMP-099: the longest gate run is a fact of the unit run, so the fix loop's rebuilt workbench carries it."""
    seen: list = []
    real = fixloop._fall_back

    def planted(ctx, wb, *args, **kwargs):
        wb.gate_peak = ("baseline", 381.0)
        fresh = real(ctx, wb, *args, **kwargs)
        seen.append((wb, fresh))
        return fresh

    monkeypatch.setattr(fixloop, "_fall_back", planted)
    run = run_l4([red_step(), noqa_green(), limited(), chore_fix(), judge()], **TWO)
    assert run.code == 0, run.triggers()
    [(old, fresh)] = seen
    assert fresh is not old and fresh.gate_peak == ("baseline", 381.0)


def test_a_raised_silent_fix_step_tells_the_next_profile_the_raised_limit(run_l4, valid_spec, fake_clock, monkeypatch):
    """L4-IMP-099, `_fall_back`: the fix step of an opencode-like profile is silent for its raised limit (632 s for a
    gate of 381 s, `idle_timeout: 5m`), so the next profile is told `no output for 10m`, not `5m`."""
    caps = FakeAdapter([]).capabilities()
    monkeypatch.setattr(FakeAdapter, "capabilities", lambda self: replace(caps, open_calls=False))
    real, built = fixloop._child_workbench, []

    def planted(*args, **kwargs):
        wb = real(*args, **kwargs)
        if not built:  # the fix unit's first workbench: a gate run of 381 s is a fact of the unit run
            wb.gate_peak = ("baseline", 381.0)
        built.append(wb)
        return wb

    monkeypatch.setattr(fixloop, "_child_workbench", planted)
    quiet = Step(idle_s=632, status="timeout", writes={"leftover.txt": "half"})
    run = run_l4(
        [red_step(), noqa_green(), quiet, chore_fix(), judge()], **TWO | {"implementer": {"idle_timeout": "5m"}}
    )
    assert run.code == 0, run.triggers()
    assert run.adapter.requests[2].stall_timeout_s == 632.0
    retried = run.adapter.requests[3].prompt
    assert 'kind="previous-attempt"' in retried and "went silent: no output for 10m" in retried


def test_a_fix_tasks_limit_hands_the_carry_it_started_from_to_the_task_on_the_next_profile(
    run_l4, valid_spec, fake_clock, monkeypatch
):
    """L4-IMP-100: the carry a limited `run_task` attaches to its `RoleLimit` is the next `run_task`'s `carry` for the
    same task, as the orchestrator's fallback does for the unit's tasks."""
    from l4.implementer.held_patch import NearPass
    from l4.implementer.tdd import RoleLimit

    marker = NearPass("1", 1, "impl", b"patch", "0" * 64, ("a.py",), ("lint",))
    real, carries = fixloop.run_task, []

    def planted(wb, task, **kwargs):
        carries.append((task.key, kwargs.get("carry")))
        try:
            return real(wb, task, **kwargs)
        except RoleLimit as exc:
            exc.carry = marker
            raise

    monkeypatch.setattr(fixloop, "run_task", planted)
    run = run_l4([red_step(), noqa_green(), limited(), chore_fix(), judge()], **TWO)
    assert run.code == 0, run.triggers()
    fix_calls = [carry for _, carry in carries[-2:]]
    assert fix_calls == [None, marker]


# --- implementer-stall-limit: a stall of a fix task (L4-IMP-115) ---


def test_a_fix_tasks_first_idle_stall_moves_it_and_discards_its_work(run_l4, valid_spec, fake_clock):
    """SCN-IMP-614."""
    stalled = Step(idle_s=600, status="timeout", tool_calls=6, writes={"leftover.txt": "half"})
    run = run_l4([red_step(), noqa_green(), stalled, chore_fix(), judge()], **TWO)
    assert run.code == 0, run.triggers()
    [record] = [e for e in run.events("agent.idle") if e.get("fix_unit") == FIX_UNIT]
    assert (record["kind"], record["as_limit"]) == ("idle", True) and record["discarded_files"] == 1
    [limit] = run.events("availability.limit")
    assert limit.get("fix_unit") == FIX_UNIT and limit["kind"] == "idle"
    [cooldown] = run.events("availability.cooldown")
    assert (cooldown["profile"], cooldown["kind"]) == ("impl", "idle")
    [fallback] = run.events("availability.fallback")
    assert (fallback["from"], fallback["to"], fallback["reason"]) == ("impl", "impl-b", "idle")
    assert not [e for e in run.events("task.attempt_failed") if e.get("fix_unit") == FIX_UNIT]
    retried = run.adapter.requests[3].prompt
    assert 'limit="idle"' in retried and "went idle: no output for 10m after 6 tool calls" in retried
    assert "leftover.txt" not in run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", BRANCH)


def test_a_fix_tasks_first_time_limit_stall_moves_it(run_l4, valid_spec, fake_clock):
    run = run_l4([red_step(), noqa_green(), Step(status="timeout"), chore_fix(), judge()], **TWO)
    assert run.code == 0, run.triggers()
    [record] = [e for e in run.events("agent.time_limit") if e.get("fix_unit") == FIX_UNIT]
    assert record["as_limit"] is True
    [fallback] = run.events("availability.fallback")
    assert (fallback["from"], fallback["to"], fallback["reason"]) == ("impl", "impl-b", "time")
    assert 'limit="time"' in run.adapter.requests[3].prompt


@pytest.mark.parametrize("stall", [Step(status="timeout"), Step(idle_s=600, status="timeout", tool_calls=2)])
def test_a_fix_task_that_already_moved_does_not_park_the_unit_on_a_stall(run_l4, valid_spec, fake_clock, stall):
    """SCN-IMP-615: impl-c could take the step, but the fix loop moves a task once and parks the unit on a second limit
    and that path discards nothing, so the stall is a failed attempt, cools nothing and the task goes on."""
    run = run_l4(
        [red_step(), noqa_green(), limited(), replace(stall, writes={"leftover.txt": "half"}), chore_fix(), judge()],
        **THREE,
    )
    assert run.code == 0, run.triggers()
    [record] = [e for e in run.events("agent.idle") + run.events("agent.time_limit") if e.get("fix_unit") == FIX_UNIT]
    kind = record.get("kind", "time")
    assert record["as_limit"] is False and record["reason"] == f"{kind}: no other profile can take the step"
    assert [e["profile"] for e in run.events("availability.cooldown")] == ["impl"]  # the usage limit's alone
    assert len(run.events("availability.fallback")) == 1
    [failed] = [e for e in run.events("task.attempt_failed") if e.get("fix_unit") == FIX_UNIT]
    assert failed["profile"] == "impl-b"
    assert "leftover.txt" not in run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", BRANCH)


FOUR = THREE | {
    "roles": {"implementer": ["impl", "impl-b", "impl-c", "impl-d"]},
    "profiles": THREE["profiles"] | {"impl-d": {"adapter": "fake", "vendor": "fourthco"}},
}


def test_an_escalated_fix_task_that_already_moved_does_not_move_again_on_a_stall(run_l4, valid_spec, fake_clock):
    """X4, SCN-IMP-615: the fix task moved after a limit (impl to impl-b), then two failed attempts escalated it to
    impl-c, whose step stalls. The workbench of the escalation knows the task already moved, so impl-d, which could take
    the step, is not asked to: the stall is a failed attempt and the task goes on on impl-c."""
    invalid = Step()  # no result object: a failed attempt
    stalled = Step(status="timeout", writes={"leftover.txt": "half"})
    script = [red_step(), noqa_green(), limited(), invalid, invalid, stalled, chore_fix(), judge()]
    run = run_l4(script, **FOUR)
    assert run.code == 0, run.triggers()
    assert [(e["from"], e["to"]) for e in run.events("availability.fallback")] == [("impl", "impl-b")]
    [record] = [e for e in run.events("agent.time_limit") if e.get("fix_unit") == FIX_UNIT]
    assert (record["profile"], record["as_limit"], record["reason"]) == (
        "impl-c", False, "time: no other profile can take the step",
    )  # fmt: skip
    assert "fourthco" not in [r.profile.vendor for r in run.adapter.requests]
