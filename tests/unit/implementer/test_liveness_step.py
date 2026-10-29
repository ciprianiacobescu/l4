"""run-liveness wave 2 (Agent I): the heartbeat and the idle watchdog in `agent_step` (L4-IMP-023, L4-IMP-024) and the
red note of the red gate (L4-OBS-004)."""

import json
import logging
import os
import re
import sys
from dataclasses import replace

import pytest

from l4.agents.activity import Beat, codex_signals
from l4.agents.base import LimitSignal, RunRequest, RunResult
from l4.agents.fake import FakeAdapter, Step
from l4.agents.proc import ProcOutcome, ProcRunner
from l4.deadline import DeadlineReached
from l4.gates.junit import TestCase, TestReport
from l4.implementer.loop import run_task
from l4.implementer.tdd import RoleLimit, red_note, run_red

from .conftest import green_step, red_step
from .test_escalation import TWO, Hook
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


# --- the red note (design D9) ---


def _case(i, status, kind=None, message=""):
    return TestCase(i, status, message, failure_kind=kind)


BASE = TestReport({k: TestCase(k, "passed") for k in "abcde"})


def test_red_note_counts_new_failing_tests_by_assertion_or_not_implemented():
    """SCN-OBS-03."""
    tests = dict(BASE.tests)
    for n in range(7):
        tests[f"new{n}"] = _case(f"new{n}", "failed", "assertion" if n % 2 else "not_implemented")
    assert red_note(BASE)(TestReport(tests)) == {"red_new_failing": 7}
    one = dict(BASE.tests) | {"x": _case("x", "failed", "assertion")}
    assert red_note(BASE)(TestReport(one)) == {"red_new_failing": 1}


def test_red_note_is_empty_in_every_other_case():
    """SCN-OBS-04: the five cases (a gate that is not red or has no report never reaches the note)."""
    base = BASE.tests
    other = TestReport(base | {"n": _case("n", "failed", "other")})
    old_fails = TestReport(base | {"a": _case("a", "failed", "assertion"), "n": _case("n", "failed", "assertion")})
    collection = TestReport(base | {"n": _case("n", "failed", "assertion")}, collection_errors=["tests.test_new"])
    hung = TestReport(base | {"n": _case("n", "failed", "assertion", "Failed: l4-test-timeout: 5s")})
    nothing_failing = TestReport(base | {"n": _case("n", "passed")})
    note = red_note(BASE)
    for report in (other, old_fails, collection, hung, nothing_failing):
        assert note(report) == {}


def test_a_collection_error_the_base_already_has_does_not_block_the_note():
    base = TestReport(dict(BASE.tests), collection_errors=["tests.broken"])
    head = TestReport(dict(BASE.tests) | {"n": _case("n", "failed", "assertion")}, collection_errors=["tests.broken"])
    assert red_note(base)(head) == {"red_new_failing": 1}


def test_a_red_step_records_red_new_failing_on_its_test_gate(make_bench):
    bench = make_bench([red_step()])
    assert run_red(bench.wb, TASK, attempt=1).status == "ok"
    tests_gate = [e for e in bench.events("gate.finished") if e["name"] == "test"]
    assert any(e.get("red_new_failing", 0) >= 1 for e in tests_gate)
    assert all("red_new_failing" not in e for e in bench.events("gate.finished") if e["name"] != "test")


@pytest.mark.parametrize("name", ["run_single", "run_green"])
def test_green_and_single_pass_no_note(name):
    import inspect

    import l4.implementer.tdd as tdd

    assert "note=" not in inspect.getsource(getattr(tdd, name))


# --- end to end: a real ProcRunner under agent_step (run-liveness 3.1, 3.2) ---


class ScriptAdapter(FakeAdapter):
    """Runs a Python script through a real `ProcRunner` with `codex_signals` and maps a stall to `timeout`, as the
    codex adapter does. It writes no result, so a run that is not stopped still fails the attempt."""

    def __init__(self, scripts: list[str]) -> None:
        super().__init__([])
        self.scripts = scripts
        self.reader = codex_signals  # `None`: a `command` profile, which has no stream reader
        self.outcomes: list[ProcOutcome] = []

    def run(self, req: RunRequest) -> RunResult:
        self.requests.append(req)
        req.raw_events_path.parent.mkdir(parents=True, exist_ok=True)
        outcome = ProcRunner().run(
            [sys.executable, "-c", self.scripts.pop(0)], dict(os.environ), req.cwd,
            stdout_path=req.raw_events_path, timeout_s=req.timeout_s, stall_timeout_s=req.stall_timeout_s,
            watch=req.watch, reader=self.reader,
        )  # fmt: skip
        self.outcomes.append(outcome)
        status = "timeout" if outcome.timed_out or outcome.stalled else "ok"
        return RunResult(status=status, raw_events_path=req.raw_events_path, exit_code=outcome.returncode)


STARTED = json.dumps({"type": "item.started", "item": {"id": "i1", "type": "command_execution"}})
OPEN_CALL = f"import time; print({STARTED!r}, flush=True); time.sleep(4)"
SILENT = "import time; print('{}', flush=True); time.sleep(4)"


def _fast(bench, adapter: ScriptAdapter) -> None:
    """A 1s heartbeat and a 2s idle limit (the config minimums apply to a loaded config only)."""
    impl = bench.wb.cfg.implementer.model_copy(update={"heartbeat": "1s", "idle_timeout": "2s"})
    bench.wb.cfg = bench.wb.cfg.model_copy(update={"implementer": impl})
    bench.wb.selected = replace(bench.wb.selected, impl=adapter)


def test_an_open_call_is_not_idle_and_the_beats_are_logged(make_bench, caplog):
    """SCN-IMP-203 end to end: the codex call is open for 4s, the limit is 2s."""
    bench = make_bench([])
    adapter = ScriptAdapter([OPEN_CALL])
    _fast(bench, adapter)
    with caplog.at_level(logging.INFO, logger="l4"):
        outcome = run_red(bench.wb, TASK, attempt=1)
    [proc] = adapter.outcomes
    assert not proc.stalled and not proc.timed_out
    assert not bench.events("agent.idle")
    assert "no activity" not in outcome.reason
    beats = [r.getMessage() for r in caplog.records if r.name == "l4" and "working" in r.getMessage()]
    assert len(beats) >= 2
    assert all("1 tool call" in b for b in beats)
    assert any("1 tool call open for" in b for b in beats)


def test_a_silent_agent_is_stopped_and_idle_is_recorded(make_bench):
    """SCN-IMP-202 and SCN-IMP-203 end to end: one line, no open call, then silence."""
    bench = make_bench([])
    adapter = ScriptAdapter([SILENT])
    _fast(bench, adapter)
    outcome = run_red(bench.wb, TASK, attempt=1)
    [proc] = adapter.outcomes
    assert proc.stalled
    [idle] = bench.events("agent.idle")
    assert (idle["task"], idle["phase"], idle["attempt"]) == ("1.1", "red", 1)
    assert idle["silent_s"] >= 2
    assert outcome.reason == "the agent showed no activity for 2s (implementer.idle_timeout), so L4 stopped it"
    [finished] = bench.events("agent.finished")
    assert finished["status"] == "timeout"


def test_two_idle_attempts_move_the_phase_to_the_second_profile(make_bench):
    """SCN-IMP-202, the escalation part: an idle attempt is a failed attempt and counts for `escalate_after`."""
    bench = make_bench(
        [Step(idle_s=600, status="timeout", tool_calls=1)] * 2 + [red_step(), green_step()],
        implementer={"escalate_after": 2}, **TWO,
    )  # fmt: skip
    hook = Hook()
    outcome = run_task(bench.wb, TASK, escalate=hook)
    assert outcome.status == "done"
    [request] = hook.requests
    assert (request.task, request.phase, request.profile, request.attempt) == ("1.1", "red", "impl", 3)
    assert len(bench.events("agent.idle")) == 2
    assert not bench.events("role.limit") and not bench.events("limit.hit")
    assert [(e["phase"], e["agent"], e["attempt"]) for e in bench.events("step.started")] == [
        ("red", "impl", 1), ("red", "impl", 2), ("red", "impl-b", 3), ("green", "impl-b", 1),
    ]  # fmt: skip


# --- a silent stop is a limit of its profile (silent-stop-limit 1.1, L4-IMP-087) ---


def test_a_silent_step_with_a_second_profile_raises_a_silent_limit_and_counts_nothing(make_bench):
    """SCN-IMP-426 at the step: no tool call before the idle stop, and a later profile in the chain."""
    bench = make_bench([Step(idle_s=600, status="timeout")], **TWO)
    with pytest.raises(RoleLimit) as caught:
        run_red(bench.wb, TASK, attempt=1)
    run = caught.value.result
    assert run.status == "timeout"
    signal = run.limit
    assert (signal.kind, signal.source, signal.raw_excerpt) == ("silent", "run.idle", "no output for 10m")
    assert signal.resets_at is None
    assert (signal.tool, signal.model) == ("fake", bench.wb.selected.profile.model)
    assert str(caught.value) == "no output for 10m"
    [idle] = bench.events("agent.idle")
    assert (idle["silent"], idle["tool_calls"], idle["silent_s"]) == (True, 0, 600)
    assert [e["status"] for e in bench.events("agent.finished")] == ["timeout"]
    assert not bench.events("task.attempt_failed")


def test_tokens_do_not_decide_a_silent_stop(make_bench):
    bench = make_bench([Step(idle_s=600, status="timeout", input_tokens=900, output_tokens=40)], **TWO)
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=1)
    [idle] = bench.events("agent.idle")
    assert idle["silent"] is True


def test_an_idle_stop_after_a_tool_call_counts_as_before(make_bench):
    """SCN-IMP-427: one tool call, then idle; the chain has a second profile."""
    bench = make_bench([Step(idle_s=600, status="timeout", tool_calls=1), red_step(), green_step()], **TWO)
    assert run_task(bench.wb, TASK).status == "done"
    [idle] = bench.events("agent.idle")
    assert (idle["silent"], idle["tool_calls"]) == (False, 1)
    [failed] = bench.events("task.attempt_failed")
    assert failed["reason"] == "the agent showed no activity for 10m (implementer.idle_timeout), so L4 stopped it"
    assert not bench.events("availability.cooldown") and not bench.events("availability.fallback")


def test_a_step_that_reaches_its_time_limit_with_no_tool_call_counts_as_before(make_bench):
    """SCN-IMP-428: no idle mark (the wall-clock limit), a second profile, no tool call."""
    bench = make_bench([Step(status="timeout"), red_step(), green_step()], **TWO)
    assert run_task(bench.wb, TASK).status == "done"
    assert not bench.events("agent.idle")
    [failed] = bench.events("task.attempt_failed")
    assert failed["reason"] == "the agent step reached its time limit (30m)"


def test_a_single_profile_counts_its_silent_stops(make_bench):
    """SCN-IMP-429: the chain has one profile, so a silent stop is a failed attempt and the profile is not cooled."""
    bench = make_bench([Step(idle_s=600, status="timeout"), red_step(), green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    [idle] = bench.events("agent.idle")
    assert (idle["silent"], idle["tool_calls"]) == (False, 0)
    [failed] = bench.events("task.attempt_failed")
    assert failed["reason"] == "the agent showed no activity for 10m (implementer.idle_timeout), so L4 stopped it"
    assert not bench.events("availability.cooldown")


def test_a_profile_without_a_stream_reader_cannot_be_silent(make_bench):
    """It counts no tool calls at all, so 0 says nothing: the stop counts as before."""
    bench = make_bench([Step(idle_s=600, status="timeout", stream_reader=False), red_step(), green_step()], **TWO)
    assert run_task(bench.wb, TASK).status == "done"
    [idle] = bench.events("agent.idle")
    assert idle["silent"] is False
    assert len(bench.events("task.attempt_failed")) == 1


def test_a_second_silent_stop_of_a_task_counts_as_a_failed_attempt(make_bench):
    """SCN-IMP-438: the first silent stop is a limit; a later one of the same task is an attempt, so a chain whose
    profiles all go silent halts on `max_task_attempts` instead of parking for ever."""
    bench = make_bench([Step(idle_s=600, status="timeout"), Step(idle_s=600, status="timeout")], **TWO)
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=1)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed"
    assert outcome.reason == "the agent showed no activity for 10m (implementer.idle_timeout), so L4 stopped it"
    first, second = bench.events("agent.idle")
    assert (first["silent"], second["silent"]) == (True, False)
    assert second["reason"] == "silent: already once for this task" and "reason" not in first


def test_a_silent_stop_of_another_task_is_a_first_one(make_bench):
    other = replace(TASK, key="1.2", number="1.2")
    bench = make_bench([Step(idle_s=600, status="timeout"), Step(idle_s=600, status="timeout")], **TWO)
    with pytest.raises(RoleLimit):
        run_red(bench.wb, other, attempt=1)
    with pytest.raises(RoleLimit):  # task 1.1 has not been silent yet
        run_red(bench.wb, TASK, attempt=1)
    assert [e["silent"] for e in bench.events("agent.idle")] == [True, True]


def test_an_idle_timeout_of_zero_is_never_silent(make_bench):
    """D3: the watchdog is off, so a timeout is the wall-clock limit."""
    bench = make_bench([Step(status="timeout")], implementer={"idle_timeout": "0"}, **TWO)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "time limit" in outcome.reason
    assert not bench.events("agent.idle")


def test_the_deadline_cancelling_an_idle_stop_is_not_silent(make_bench, armed_deadline):
    """D3: the soft deadline wins over the idle rule: `DeadlineReached`, no `agent.idle`, no limit."""
    dl = armed_deadline()
    bench = make_bench([Step(idle_s=600, status="timeout", on_start=lambda req: dl.fire())], **TWO)
    with pytest.raises(DeadlineReached):
        run_red(bench.wb, TASK, attempt=1)
    assert not bench.events("agent.idle")


def test_a_limit_the_adapter_already_found_on_a_timeout_is_kept(make_bench):
    """An adapter that read a throttle (with a reset time) and then ended `timeout` has said more than `silent`."""
    throttle = LimitSignal("fake", None, "rate_limit", None, "fake.throttle", "request throttled")
    bench = make_bench([Step(idle_s=600, status="timeout", limit=throttle, detail="throttled")], **TWO)
    with pytest.raises(RoleLimit) as caught:
        run_red(bench.wb, TASK, attempt=1)
    assert caught.value.result.limit is throttle and caught.value.result.detail == "throttled"


# --- SCN-IMP-201 at the bench (run-liveness 4.1) ---

STEP = "import time; print('output', flush=True); time.sleep(2.5)"


def _beats(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "l4" and " working " in r.getMessage()]


def test_no_heartbeat_when_it_is_off(make_bench, caplog):
    bench = make_bench([])
    adapter = ScriptAdapter([STEP])
    _fast(bench, adapter)
    bench.wb.cfg = bench.wb.cfg.model_copy(
        update={"implementer": bench.wb.cfg.implementer.model_copy(update={"heartbeat": "0", "idle_timeout": "0"})}
    )
    with caplog.at_level(logging.INFO, logger="l4"):
        run_red(bench.wb, TASK, attempt=1)
    assert len(adapter.outcomes) == 1 and _beats(caplog) == []


def test_no_heartbeat_when_the_step_ends_before_the_first_interval(make_bench, caplog):
    bench = make_bench([])
    adapter = ScriptAdapter(["print('output')"])
    _fast(bench, adapter)
    bench.wb.cfg = bench.wb.cfg.model_copy(
        update={"implementer": bench.wb.cfg.implementer.model_copy(update={"heartbeat": "60s"})}
    )
    with caplog.at_level(logging.INFO, logger="l4"):
        run_red(bench.wb, TASK, attempt=1)
    assert len(adapter.outcomes) == 1 and _beats(caplog) == []


def test_a_command_profile_shows_the_elapsed_time_and_no_count(make_bench, caplog):
    bench = make_bench([])
    adapter = ScriptAdapter([STEP])
    adapter.reader = None
    _fast(bench, adapter)
    with caplog.at_level(logging.INFO, logger="l4"):
        run_red(bench.wb, TASK, attempt=1)
    beats = _beats(caplog)
    profile = bench.wb.selected.profile_name
    assert beats and all(b.startswith(f"{bench.wb.ref.id} task 1.1 red attempt 1: {profile} working ") for b in beats)
    assert not any("tool call" in b or "last activity" in b for b in beats)
    assert all(re.search(r"working \d+s$", b) for b in beats)
