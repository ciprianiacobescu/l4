"""run-liveness wave 2 (Agent I): the heartbeat and the idle watchdog in `agent_step` (L4-IMP-023, L4-IMP-024) and the
red note of the red gate (L4-OBS-004)."""

import logging

from l4.agents.activity import Beat
from l4.agents.fake import Step
from l4.implementer.loop import run_task
from l4.implementer.tdd import run_red

from .conftest import green_step, red_step
from .test_tdd_red import TASK


def _first_request(bench):
    return bench.adapter.requests[0]


def test_the_request_watch_and_stall_follow_the_keys(make_bench):
    bench = make_bench([red_step()], implementer={"heartbeat": "3m", "idle_timeout": "15m"})
    run_red(bench.wb, TASK, attempt=1)
    req = _first_request(bench)
    assert req.stall_timeout_s == 900
    assert req.watch is not None and req.watch.heartbeat_s == 180


def test_zero_gives_no_stall_and_no_beat(make_bench):
    bench = make_bench([red_step()], implementer={"heartbeat": "0", "idle_timeout": "0"})
    run_red(bench.wb, TASK, attempt=1)
    req = _first_request(bench)
    assert req.stall_timeout_s is None
    assert req.watch is not None and req.watch.heartbeat_s == 0


def test_the_watch_uses_the_runner_clock(make_bench):
    import time

    bench = make_bench([red_step()])
    run_red(bench.wb, TASK, attempt=1)
    assert _first_request(bench).watch.clock is time.monotonic


def test_the_beat_callback_logs_one_info_line_and_no_ledger_event(make_bench, caplog):
    """SCN-IMP-200 at the line level."""
    bench = make_bench([red_step()])
    run_red(bench.wb, TASK, attempt=1)
    watch = _first_request(bench).watch
    with caplog.at_level(logging.INFO, logger="l4"):
        watch.on_beat(Beat(360, 14, 20, 0, 0, True))
    [line] = [r for r in caplog.records if r.name == "l4"]
    assert line.levelno == logging.INFO
    assert line.getMessage() == (
        f"{bench.wb.ref.id} task 1.1 red attempt 1: {bench.wb.selected.profile_name} "
        "working 6m, 14 tool calls, last activity 20s ago"
    )
    assert not bench.events("heartbeat")


def test_the_beat_line_names_the_fix_unit(make_bench, caplog):
    bench = make_bench([red_step()])
    object.__setattr__(bench.wb, "event_context", {"fix_unit": "fix-1"})
    run_red(bench.wb, TASK, attempt=1)
    watch = _first_request(bench).watch
    with caplog.at_level(logging.INFO, logger="l4"):
        watch.on_beat(Beat(120, 0, 5, 0, 0, False))
    [line] = [r for r in caplog.records if r.name == "l4"]
    assert line.getMessage().endswith(f"[fix-1] task 1.1 red attempt 1: {bench.wb.selected.profile_name} working 2m")


def test_an_idle_stop_is_recorded_before_agent_finished_and_fails_with_the_idle_reason(make_bench):
    """SCN-IMP-202."""
    bench = make_bench([Step(idle_s=600, status="timeout"), red_step(), green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    types = [e["type"] for e in map(__import__("json").loads, _ledger_lines(bench))]
    first = types.index("agent.idle")
    assert types[first + 1] == "agent.finished"
    [idle] = bench.events("agent.idle")
    got = (idle["task"], idle["phase"], idle["attempt"], idle["silent_s"], idle["tool_calls"])
    assert got == ("1.1", "red", 1, 600, 0)
    assert idle["profile"] == bench.wb.selected.profile_name
    [failed] = bench.events("task.attempt_failed")
    assert failed["reason"] == "the agent showed no activity for 10m (implementer.idle_timeout), so L4 stopped it"
    assert failed["reason"] in bench.adapter.requests[1].prompt


def _ledger_lines(bench):
    return (bench.wb.ref.path / ".l4" / "ledger" / "r-20261003T1312Z-7f3a.jsonl").read_text().splitlines()


def test_a_fractional_idle_is_rounded_to_whole_seconds(make_bench):
    bench = make_bench([Step(idle_s=600.7, status="timeout")])
    run_red(bench.wb, TASK, attempt=1)
    [idle] = bench.events("agent.idle")
    assert idle["silent_s"] == 601 and isinstance(idle["silent_s"], int)


def test_a_timeout_without_the_idle_mark_says_the_time_limit(make_bench):
    """SCN-IMP-204."""
    bench = make_bench([Step(status="timeout"), red_step(), green_step()], implementer={"idle_timeout": "0"})
    assert run_task(bench.wb, TASK).status == "done"
    assert not bench.events("agent.idle")
    [failed] = bench.events("task.attempt_failed")
    assert failed["reason"] == "the agent step reached its time limit (30m)"


def test_the_other_statuses_keep_their_text(make_bench):
    bench = make_bench([Step(status="error", final_text="")])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.reason.startswith("the agent step ended with status error")
