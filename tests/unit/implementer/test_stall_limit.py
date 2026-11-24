"""implementer-stall-limit (L4-IMP-112..116, L4-AVL-014..015): an implementer step that stalls on a profile is a limit
of that profile when another profile can take the step, once per task window, and no failed attempt. The step's side of
the rules: the three kinds, the records, the once-per-window count, a chain of one, the owner's plan."""

from dataclasses import replace

import pytest

from l4.agents.base import LimitSignal
from l4.agents.fake import Step
from l4.implementer.loop import run_task
from l4.implementer.tdd import RoleLimit, run_red
from l4.implementer.workbench import StallPlan

from .conftest import green_step, red_step
from .test_escalation import BAD, INVALID, TWO, Hook
from .test_tdd_red import TASK

IDLE_REASON = "the agent showed no activity for 10m (implementer.idle_timeout), so L4 stopped it"
TIME_REASON = "the agent step reached its time limit (30m)"
THREE = {
    "roles": {"implementer": ["impl", "impl-b", "impl-c"]},
    "profiles": {
        "impl-b": {"adapter": "fake", "vendor": "otherco"},
        "impl-c": {"adapter": "fake", "vendor": "thirdco"},
    },
}


def idle(tool_calls: int = 14, **over) -> Step:
    """FAKE: an agent that made `tool_calls` calls and then printed nothing for 10 minutes."""
    return Step(idle_s=600, status="timeout", tool_calls=tool_calls, **over)


def timed_out(**over) -> Step:
    """FAKE: an agent that reached the step's wall-clock limit."""
    return Step(status="timeout", **over)


def stall_limit(bench, kind: str, **over) -> None:
    """A stall limit of task 1.1 already in the window, as an earlier step of this run left it."""
    if kind == "time":
        bench.wb.emit("agent.time_limit", task="1.1", phase="red", attempt=1, profile="impl", limit_s=1800,
                      as_limit=True, **over)  # fmt: skip
    else:
        bench.wb.emit("agent.idle", task="1.1", phase="red", attempt=1, profile="impl", silent_s=600, tool_calls=3,
                      silent=kind == "silent", kind=kind, as_limit=True, limit_s=600, **over)  # fmt: skip


# --- L4-IMP-112: the three kinds -----------------------------------------------------------------------------------


def test_an_idle_stop_after_tool_calls_is_an_idle_limit_and_counts_nothing(make_bench):
    """SCN-IMP-602 at the step."""
    bench = make_bench([idle(14)], **TWO)
    with pytest.raises(RoleLimit) as caught:
        run_red(bench.wb, TASK, attempt=1)
    signal = caught.value.result.limit
    assert (signal.kind, signal.source, signal.resets_at) == ("idle", "run.idle", None)
    assert signal.raw_excerpt == "no output for 10m after 14 tool calls"
    assert (signal.tool, signal.model) == ("fake", bench.wb.selected.profile.model)
    [record] = bench.events("agent.idle")
    assert (record["kind"], record["as_limit"], record["silent"], record["tool_calls"]) == ("idle", True, False, 14)
    assert "reason" not in record
    assert [e["status"] for e in bench.events("agent.finished")] == ["timeout"]
    assert not bench.events("task.attempt_failed") and not bench.events("agent.time_limit")


def test_a_time_limit_stop_is_a_time_limit_and_counts_nothing(make_bench):
    """SCN-IMP-603 at the step."""
    bench = make_bench([timed_out()], **TWO)
    with pytest.raises(RoleLimit) as caught:
        run_red(bench.wb, TASK, attempt=1)
    signal = caught.value.result.limit
    assert (signal.kind, signal.source, signal.resets_at) == ("time", "run.timeout", None)
    assert signal.raw_excerpt == "the agent step reached its time limit (30m)"
    [record] = bench.events("agent.time_limit")
    assert (record["task"], record["phase"], record["attempt"], record["limit_s"]) == ("1.1", "red", 1, 1800)
    assert record["profile"] == bench.wb.selected.profile_name and record["as_limit"] is True
    assert "reason" not in record
    assert not bench.events("agent.idle") and not bench.events("task.attempt_failed")


def test_a_time_limit_record_comes_before_agent_finished(make_bench):
    bench = make_bench([timed_out()], **TWO)
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=1)
    types = [e["type"] for e in _all(bench)]
    assert types.index("agent.time_limit") + 1 == types.index("agent.finished")


def _all(bench):
    import json

    from .conftest import RUN_ID

    path = bench.wb.ref.path / ".l4" / "ledger" / f"{RUN_ID}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_time_limit_record_carries_the_tool_calls_the_reader_counted(make_bench):
    bench = make_bench([timed_out(tool_calls=7)], **TWO)
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=1)
    [record] = bench.events("agent.time_limit")
    assert record["tool_calls"] == 7


def test_a_time_limit_record_has_no_count_when_no_reader_counted(make_bench):
    bench = make_bench([timed_out(stream_reader=False)], **TWO)
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=1)
    [record] = bench.events("agent.time_limit")
    assert "tool_calls" not in record and record["as_limit"] is True


def test_an_idle_stop_with_no_stream_reader_is_an_idle_stall_with_no_count(make_bench):
    """SCN-IMP-617."""
    bench = make_bench([Step(idle_s=600, status="timeout", stream_reader=False)], **TWO)
    with pytest.raises(RoleLimit) as caught:
        run_red(bench.wb, TASK, attempt=1)
    signal = caught.value.result.limit
    assert (signal.kind, signal.raw_excerpt) == ("idle", "no output for 10m")
    [record] = bench.events("agent.idle")
    assert (record["kind"], record["as_limit"], record["silent"]) == ("idle", True, False)
    assert "tool_calls" not in record
    assert not bench.events("task.attempt_failed")


def test_an_idle_stop_that_also_reached_the_time_limit_keeps_its_idle_kind(make_bench):
    """SCN-IMP-618: the runner sets both flags when the idle stop crosses the limit inside the grace; the adapter's
    status is `timeout` either way and the idle mark is what says it was idle."""
    bench = make_bench([idle(2)], **TWO)
    with pytest.raises(RoleLimit) as caught:
        run_red(bench.wb, TASK, attempt=1)
    assert caught.value.result.limit.kind == "idle"
    assert [e["kind"] for e in bench.events("agent.idle")] == ["idle"]
    assert not bench.events("agent.time_limit")


def test_a_silent_stop_records_its_kind_and_stays_silent(make_bench):
    bench = make_bench([Step(idle_s=600, status="timeout")], **TWO)
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=1)
    [record] = bench.events("agent.idle")
    assert (record["kind"], record["as_limit"], record["silent"], record["tool_calls"]) == ("silent", True, True, 0)


@pytest.mark.parametrize("step", [idle(5), timed_out()], ids=["idle", "time"])
def test_a_limit_the_adapter_found_on_a_stalled_run_is_kept(make_bench, step):
    """SCN-IMP-616: the cool-down is that limit's; the stall is still recorded."""
    throttle = LimitSignal("fake", None, "rate_limit", None, "fake.throttle", "request throttled")
    bench = make_bench([replace(step, limit=throttle, detail="throttled")], **TWO)
    with pytest.raises(RoleLimit) as caught:
        run_red(bench.wb, TASK, attempt=1)
    assert caught.value.result.limit is throttle and caught.value.result.detail == "throttled"
    assert len(bench.events("agent.idle") + bench.events("agent.time_limit")) == 1


def test_a_green_stall_raises_with_the_red_commit_kept(make_bench):
    bench = make_bench([red_step(), timed_out()], **TWO)
    with pytest.raises(RoleLimit):
        run_task(bench.wb, TASK)
    assert [e["phase"] for e in bench.events("agent.time_limit")] == ["green"]
    assert len(bench.events("task.red_committed")) == 1


def test_a_chore_step_stalls_too(make_bench):
    """The single step of a unit's chore goes through `agent_step` as red and green do."""
    from l4.implementer.tdd import agent_step

    bench = make_bench([timed_out()], **TWO)
    with pytest.raises(RoleLimit):
        agent_step(bench.wb, "single", TASK, 1, None)
    [record] = bench.events("agent.time_limit")
    assert record["phase"] == "single" and record["as_limit"] is True


# --- L4-IMP-114: one stall limit per task window --------------------------------------------------------------------


def test_a_second_stall_of_another_kind_counts_as_a_failed_attempt(make_bench):
    """SCN-IMP-607: an idle stop was the task's limit; a time-limit stop after it is an attempt."""
    bench = make_bench([idle(3), timed_out()], **TWO)
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=1)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert (outcome.status, outcome.reason) == ("failed", TIME_REASON)
    [record] = bench.events("agent.time_limit")
    assert (record["as_limit"], record["reason"]) == (False, "time: already once for this task")
    assert "discarded_files" not in record


def test_an_idle_stall_after_a_time_limit_says_idle_already_once(make_bench):
    bench = make_bench([timed_out(), idle(3)], **TWO)
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=1)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert (outcome.status, outcome.reason) == ("failed", IDLE_REASON)
    [record] = bench.events("agent.idle")
    assert (record["as_limit"], record["silent"], record["reason"]) == (
        False,
        False,
        "idle: already once for this task",
    )


def test_the_third_stall_is_a_failed_attempt_too(make_bench):
    bench = make_bench([idle(3), idle(3), idle(3)], **TWO)
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=1)
    assert run_red(bench.wb, TASK, attempt=1).status == "failed"
    assert run_red(bench.wb, TASK, attempt=1).status == "failed"
    assert [e["as_limit"] for e in bench.events("agent.idle")] == [True, False, False]


def test_a_stall_that_was_not_a_limit_does_not_count_as_one(make_bench):
    """A stall with `as_limit: false` is a failed attempt, so the first stall that is a limit is still to come."""
    bench = make_bench([idle(3)], **TWO)
    bench.wb.emit("agent.idle", task="1.1", phase="red", attempt=1, profile="impl", silent_s=600, tool_calls=3,
                  silent=False, kind="idle", as_limit=False, reason="idle: already once for this task")  # fmt: skip
    bench.wb.emit("agent.time_limit", task="1.1", phase="red", attempt=2, profile="impl", limit_s=1800,
                  as_limit=False, reason="time: no other profile can take the step")  # fmt: skip
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=3)


def test_a_silent_stop_of_an_earlier_release_is_the_tasks_first_stall(make_bench):
    """SCN-IMP-608: `agent.idle{silent: true}` with no `kind` and no `as_limit`."""
    bench = make_bench([timed_out()], **TWO)
    bench.wb.emit("agent.idle", task="1.1", phase="red", attempt=1, profile="impl", silent_s=600, tool_calls=0,
                  silent=True, limit_s=600)  # fmt: skip
    outcome = run_red(bench.wb, TASK, attempt=2)
    assert (outcome.status, outcome.reason) == ("failed", TIME_REASON)
    [record] = bench.events("agent.time_limit")
    assert record["reason"] == "time: already once for this task"


def test_an_earlier_idle_record_with_no_as_limit_and_no_silent_is_not_a_limit(make_bench):
    """A 0.4.60 `agent.idle{silent: false}` was a failed attempt."""
    bench = make_bench([timed_out()], **TWO)
    bench.wb.emit("agent.idle", task="1.1", phase="red", attempt=1, profile="impl", silent_s=600, tool_calls=2,
                  silent=False, limit_s=600)  # fmt: skip
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=2)


def test_a_stall_limit_of_another_task_or_fix_unit_is_not_this_tasks(make_bench):
    bench = make_bench([timed_out(), timed_out()], **TWO)
    bench.wb.emit("agent.time_limit", task="1.2", phase="red", attempt=1, profile="impl", limit_s=1800, as_limit=True)
    bench.wb.emit("agent.time_limit", task="1.1", phase="red", attempt=1, profile="impl", limit_s=1800, as_limit=True,
                  fix_unit="p-fix-1")  # fmt: skip
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=1)


def test_a_checkpoint_opens_a_new_window_and_a_renewal_does_not(make_bench):
    """SCN-IMP-609: a red step that was a stall limit, a red commit, and a green step that stalls: a limit again,
    because the red commit ended the window. A renewal does not end the green window, so the next stall counts."""
    bench = make_bench([timed_out(), red_step(), timed_out(), timed_out(), green_step()], **TWO)
    with pytest.raises(RoleLimit):
        run_task(bench.wb, TASK)  # the red stall limit
    with pytest.raises(RoleLimit):
        run_task(bench.wb, TASK)  # red passes and commits; the green stall is a limit of the new window
    bench.wb.emit("task.attempts_renewed", task="1.1", phase="green", attempt=1)
    assert run_task(bench.wb, TASK).status == "done"  # the next green stall is a failed attempt, then green passes
    assert [(e["phase"], e["as_limit"]) for e in bench.events("agent.time_limit")] == [
        ("red", True), ("green", True), ("green", False),
    ]  # fmt: skip
    [failed] = bench.events("task.attempt_failed")
    assert failed["phase"] == "green" and failed["reason"] == TIME_REASON


def test_a_retry_resume_or_restart_opens_a_new_window(make_bench):
    bench = make_bench([timed_out()], **TWO)
    stall_limit(bench, "time")
    bench.wb.emit("unit.retried")
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=1)


def test_a_chain_of_one_profile_is_unchanged(make_bench):
    """SCN-IMP-610: each stall is a failed attempt with its reason of before, as_limit false and no reason."""
    bench = make_bench([idle(3), timed_out(), red_step(), green_step()])
    assert run_red(bench.wb, TASK, attempt=1).reason == IDLE_REASON
    assert run_red(bench.wb, TASK, attempt=2).reason == TIME_REASON
    [first] = bench.events("agent.idle")
    assert (first["kind"], first["as_limit"], first["silent"]) == ("idle", False, False) and "reason" not in first
    [second] = bench.events("agent.time_limit")
    assert second["as_limit"] is False and "reason" not in second
    assert not bench.events("availability.cooldown")


def test_a_chain_of_one_profile_with_no_tool_call_is_a_failed_attempt(make_bench):
    bench = make_bench([Step(idle_s=600, status="timeout")])
    assert run_red(bench.wb, TASK, attempt=1).reason == IDLE_REASON
    [record] = bench.events("agent.idle")
    assert (record["kind"], record["as_limit"], record["silent"]) == ("silent", False, False)
    assert "reason" not in record


def test_an_idle_timeout_of_zero_leaves_the_wall_clock_limit_as_the_stall(make_bench):
    bench = make_bench([timed_out()], implementer={"idle_timeout": "0"}, **TWO)
    with pytest.raises(RoleLimit) as caught:
        run_red(bench.wb, TASK, attempt=1)
    assert caught.value.result.limit.kind == "time" and not bench.events("agent.idle")


@pytest.mark.parametrize("status", ["error", "max_turns", "budget", "permission_blocked"])
def test_no_other_status_is_a_stall(make_bench, status):
    bench = make_bench([Step(status=status, final_text="")], **TWO)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and outcome.reason.startswith(f"the agent step ended with status {status}")
    assert not bench.events("agent.time_limit") and not bench.events("agent.idle")


def test_the_deadline_cancelling_a_step_is_never_a_stall(make_bench, armed_deadline):
    """SCN-IMP-613, first half: the soft deadline wins over the idle rule and over the time limit."""
    from l4.deadline import DeadlineReached

    dl = armed_deadline()
    bench = make_bench([Step(idle_s=600, status="timeout", tool_calls=4, on_start=lambda req: dl.fire())], **TWO)
    with pytest.raises(DeadlineReached):
        run_red(bench.wb, TASK, attempt=1)
    assert not bench.events("agent.idle") and not bench.events("agent.time_limit")


def test_the_deadline_cancelling_a_time_limit_step_writes_no_stall(make_bench, armed_deadline):
    from l4.deadline import DeadlineReached

    dl = armed_deadline()
    bench = make_bench([Step(status="timeout", on_start=lambda req: dl.fire())], **TWO)
    with pytest.raises(DeadlineReached):
        run_red(bench.wb, TASK, attempt=1)
    assert not bench.events("agent.time_limit")


# --- the escalation counts are untouched (SCN-IMP-612) -------------------------------------------------------------


def test_a_stall_limit_adds_nothing_to_the_escalation_counts(make_bench):
    """SCN-IMP-612: the stall limit of `impl` is no failed attempt of it, so its two failures that follow are all that
    the hook is told, and the move is the escalation's and not the stall's."""
    bench = make_bench([idle(2), INVALID, BAD, red_step(), green_step()], implementer={"escalate_after": 2}, **TWO)
    with pytest.raises(RoleLimit):
        run_task(bench.wb, TASK)
    hook = Hook()
    assert run_task(bench.wb, TASK, escalate=hook).status == "done"
    [request] = hook.requests
    assert [p for p, _ in request.failures] == ["impl", "impl"]
    [moved] = bench.events("implementer.escalated")
    assert moved["failures"] == 2
    assert len(bench.events("task.attempt_failed")) == 2


# --- L4-IMP-115 at the step: the plan of the workbench's owner ------------------------------------------------------


def with_plan(bench, *, replaceable: bool = True, veto=None) -> list:
    asked: list = []

    def plan(task, phase):
        asked.append((task.key, phase))
        return StallPlan(replaceable, veto)

    bench.wb.stall_plan = plan
    return asked


@pytest.mark.parametrize("step,kind", [(idle(3), "idle"), (timed_out(), "time")], ids=["idle", "time"])
def test_a_stall_with_no_replacement_is_a_failed_attempt_with_its_reason(make_bench, step, kind):
    """SCN-IMP-611 at the step."""
    bench = make_bench([step], **TWO)
    with_plan(bench, replaceable=False)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed"
    assert outcome.reason == (IDLE_REASON if kind == "idle" else TIME_REASON)
    [record] = bench.events("agent.idle") or bench.events("agent.time_limit")
    assert (record["as_limit"], record["reason"]) == (False, f"{kind}: no other profile can take the step")
    assert "discarded_files" not in record


def test_a_silent_stop_is_a_limit_whatever_the_plan_says_about_a_replacement(make_bench):
    """SCN-IMP-621 at the step: no check for a replacement; the plan's veto rides on the signal."""
    spent = lambda name, profile: "spent: test"  # noqa: E731
    bench = make_bench([Step(idle_s=600, status="timeout")], **TWO)
    with_plan(bench, replaceable=False, veto=spent)
    with pytest.raises(RoleLimit) as caught:
        run_red(bench.wb, TASK, attempt=1)
    assert caught.value.result.limit.kind == "silent" and caught.value.result.limit.veto is spent


def test_a_stall_limit_asks_the_plan_once_and_carries_its_veto(make_bench):
    spent = lambda name, profile: "spent: test"  # noqa: E731
    bench = make_bench([timed_out()], **TWO)
    asked = with_plan(bench, veto=spent)
    with pytest.raises(RoleLimit) as caught:
        run_red(bench.wb, TASK, attempt=1)
    assert asked == [("1.1", "red")]
    assert caught.value.result.limit.veto is spent


def test_the_plan_is_asked_with_the_phase_of_the_step(make_bench):
    bench = make_bench([red_step(), timed_out()], **TWO)
    asked = with_plan(bench)
    with pytest.raises(RoleLimit):
        run_task(bench.wb, TASK)
    assert asked == [("1.1", "green")]


def test_the_plan_is_not_asked_for_a_chain_of_one_or_a_second_stall(make_bench):
    bench = make_bench([timed_out()])
    asked = with_plan(bench)
    run_red(bench.wb, TASK, attempt=1)
    assert asked == []
    two = make_bench([idle(3), idle(3)], **TWO)
    asked = with_plan(two)
    with pytest.raises(RoleLimit):
        run_red(two.wb, TASK, attempt=1)
    run_red(two.wb, TASK, attempt=1)
    assert asked == [("1.1", "red")]


def test_an_adapters_own_limit_carries_no_veto(make_bench):
    throttle = LimitSignal("fake", None, "rate_limit", None, "fake.throttle", "request throttled")
    bench = make_bench([replace(idle(3), limit=throttle)], **TWO)
    with_plan(bench, veto=lambda name, profile: "spent: test")
    with pytest.raises(RoleLimit) as caught:
        run_red(bench.wb, TASK, attempt=1)
    assert caught.value.result.limit.veto is None


# --- the signal's veto is no part of its identity ---------------------------------------------------------------


def test_the_veto_takes_no_part_in_equality_or_repr():
    a = LimitSignal("fake", None, "time", None, "run.timeout", "x", veto=lambda n, p: "spent")
    b = LimitSignal("fake", None, "time", None, "run.timeout", "x")
    assert a == b and "veto" not in repr(a)


def test_only_an_implementer_step_makes_a_stall_signal():
    """SCN-IMP-619: a judge, the clarifier, the delegate and the verifier agent keep their own rules, because the signal
    of kind `idle` or `time` and the record `agent.time_limit` are made by `agent_step` alone."""
    from pathlib import Path

    import l4

    root = Path(l4.__file__).parent
    makers = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "agent.time_limit" in path.read_text(encoding="utf-8") and "lang" not in path.relative_to(root).parts
    }
    assert makers == {"implementer/tdd.py", "progress.py"}  # the step writes it, the progress log prints it
