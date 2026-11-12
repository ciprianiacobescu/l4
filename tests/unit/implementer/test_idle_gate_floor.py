"""idle-gate-floor (L4-IMP-099): the idle limit of an implementer step on an adapter whose stream reader cannot show an
open tool call waits for the longest gate run of the unit run."""

from dataclasses import replace

import pytest

import l4.implementer.workbench as workbench
from l4.agents.fake import Step
from l4.implementer.tdd import RoleLimit, run_red

from .conftest import Bench, green_step, red_step
from .test_escalation import TWO
from .test_tdd_red import TASK


@pytest.fixture
def timed(monkeypatch):
    """The wall time (and the flags) a gate run reports, by gate name: the harness's own `run_gate` runs the command,
    the result then says what the test wants (`GateResult.seconds` is the command's wall time, L4-IMP-097)."""
    said: dict[str, dict] = {}
    real = workbench.run_gate

    def run(spec, **kwargs):
        return replace(real(spec, **kwargs), **said.get(spec.name, {}))

    monkeypatch.setattr(workbench, "run_gate", run)
    return said


def _test_gate(bench: Bench, name: str):
    return bench.wb.run_gate(name, bench.wb.cfg.gates.test.command, reports=bench.wb.cfg.gates.test.reports)


# --- 2.1: the longest gate run (D2) ---


def test_the_peak_is_the_longest_counted_run_with_its_name(make_bench, timed):
    bench: Bench = make_bench([], lint=["true"], typecheck=["true"])
    assert bench.wb.gate_peak is None
    timed["baseline"], timed["lint-baseline"], timed["typecheck-baseline"] = (
        {"seconds": 381.0}, {"seconds": 15.0}, {"seconds": 16.0},
    )  # fmt: skip
    _test_gate(bench, "baseline")
    assert bench.wb.gate_peak == ("baseline", 381.0)
    bench.wb.run_gate("lint-baseline", "true")
    bench.wb.run_gate("typecheck-baseline", "true")
    assert bench.wb.gate_peak == ("baseline", 381.0)  # a shorter run does not lower it
    timed["typecheck"] = {"seconds": 400.5}
    bench.wb.run_gate("typecheck", "true")
    assert bench.wb.gate_peak == ("typecheck", 400.5)
    timed["test"] = {"seconds": 500.0}
    _test_gate(bench, "test")
    assert bench.wb.gate_peak == ("test", 500.0)


@pytest.mark.parametrize("name", ["lint", "lint-baseline", "typecheck", "typecheck-baseline"])
def test_a_static_run_of_a_configured_command_counts(make_bench, timed, name):
    bench: Bench = make_bench([], lint=["true"], typecheck=["true"])
    timed[name] = {"seconds": 42.0}
    bench.wb.run_gate(name, "true")
    assert bench.wb.gate_peak == (name, 42.0)


@pytest.mark.parametrize("name", ["test-base-run", "test-at-red", "test-extra-base", "setup", "build", "e2e"])
def test_a_variant_or_other_run_does_not_count(make_bench, timed, name):
    bench: Bench = make_bench([], lint=["true"])
    timed[name] = {"seconds": 900.0}
    _test_gate(bench, name)
    assert bench.wb.gate_peak is None
    timed["lint"] = {"seconds": 30.0}
    bench.wb.run_gate("lint", "true")
    _test_gate(bench, name)
    assert bench.wb.gate_peak == ("lint", 30.0)


def test_a_run_of_a_command_that_is_not_the_configured_one_does_not_count(make_bench, timed):
    bench: Bench = make_bench([], lint=["true"])
    timed["baseline"], timed["lint"] = {"seconds": 900.0}, {"seconds": 900.0}
    bench.wb.run_gate("baseline", "echo not the test command")
    bench.wb.run_gate("lint", "echo not the lint command")
    assert bench.wb.gate_peak is None


def test_a_run_that_timed_out_or_was_stopped_by_the_deadline_does_not_count(make_bench, timed, armed_deadline):
    from l4.deadline import DeadlineReached

    bench: Bench = make_bench([], lint=["true"])
    timed["baseline"] = {"seconds": 1800.0, "timed_out": True}
    _test_gate(bench, "baseline")
    assert bench.wb.gate_peak is None
    timed["test"] = {"seconds": 700.0, "deadline": True}
    with pytest.raises(DeadlineReached):
        _test_gate(bench, "test")
    assert bench.wb.gate_peak is None
    timed["lint"] = {"seconds": 0.0}  # a command that did not start
    bench.wb.run_gate("lint", "true")
    assert bench.wb.gate_peak is None


# --- 3.1: the limit, the event and the texts (D3, D4, D5) ---


def _opencode_like(bench: Bench, monkeypatch, *, open_calls: bool = False) -> None:
    """The fake adapter says its stream shows no open call, as opencode's does."""
    caps = replace(bench.adapter.capabilities(), open_calls=open_calls)
    monkeypatch.setattr(bench.adapter, "capabilities", lambda: caps)


def _stall(bench: Bench, peak: tuple[str, float] | None = ("baseline", 381.0)) -> float | None:
    bench.wb.gate_peak = peak
    run_red(bench.wb, TASK, attempt=1)
    return bench.adapter.requests[0].stall_timeout_s


def test_scn_imp_537_the_limit_is_the_measured_gate_run_times_one_and_a_half_plus_a_minute(make_bench, monkeypatch):
    bench = make_bench([red_step()], implementer={"idle_timeout": "5m"})
    _opencode_like(bench, monkeypatch)
    assert _stall(bench) == 632.0  # ceil(1.5 * 381) = 572, plus 60


def test_scn_imp_537_an_adapter_that_shows_open_calls_keeps_the_key(make_bench, monkeypatch):
    bench = make_bench([red_step()], implementer={"idle_timeout": "5m"})
    _opencode_like(bench, monkeypatch, open_calls=True)
    assert _stall(bench) == 300.0


def test_scn_imp_539_no_measured_run_keeps_the_key(make_bench, monkeypatch):
    bench = make_bench([red_step()], implementer={"idle_timeout": "5m"})
    _opencode_like(bench, monkeypatch)
    assert _stall(bench, None) == 300.0


def test_scn_imp_539_a_watchdog_that_is_off_stays_off(make_bench, monkeypatch):
    bench = make_bench([red_step()], implementer={"idle_timeout": "0"})
    _opencode_like(bench, monkeypatch)
    assert _stall(bench) is None


def test_scn_imp_539_the_limit_is_at_most_the_steps_wall_clock_limit(make_bench, monkeypatch):
    bench = make_bench([red_step()], implementer={"idle_timeout": "5m"})
    _opencode_like(bench, monkeypatch)
    assert _stall(bench, ("baseline", 1400.0)) == 1800.0  # not 2160


def test_a_gate_run_shorter_than_the_key_does_not_lower_it(make_bench, monkeypatch):
    bench = make_bench([red_step()], implementer={"idle_timeout": "10m"})
    _opencode_like(bench, monkeypatch)
    assert _stall(bench, ("lint-baseline", 15.0)) == 600.0
    assert not bench.events("agent.idle")


def test_scn_imp_538_an_idle_stop_at_the_raised_limit_names_it(make_bench, monkeypatch):
    bench = make_bench(
        [Step(idle_s=632, status="timeout", tool_calls=3), red_step(), green_step()],
        implementer={"idle_timeout": "5m"},
    )
    _opencode_like(bench, monkeypatch)
    bench.wb.gate_peak = ("baseline", 381.0)
    profile = bench.wb.selected.profile.model_copy(update={"adapter": "opencode"})
    bench.wb.selected = replace(bench.wb.selected, profile=profile)
    outcome = run_red(bench.wb, TASK, attempt=1)
    [idle] = bench.events("agent.idle")
    assert (idle["limit_s"], idle["raised_by"], idle["silent"]) == (632, {"gate": "baseline", "seconds": 381}, False)
    assert outcome.status == "failed"
    assert outcome.reason == (
        "the agent showed no activity for 10m (implementer.idle_timeout 5m, raised to the longest gate run of this run "
        "plus a margin, because opencode shows no open tool call), so L4 stopped it"
    )


def test_an_idle_stop_that_was_not_raised_records_the_limit_and_keeps_todays_reason(make_bench, monkeypatch):
    bench = make_bench([Step(idle_s=300, status="timeout", tool_calls=2)], implementer={"idle_timeout": "5m"})
    outcome = run_red(bench.wb, TASK, attempt=1)  # the fake's caps show open calls
    [idle] = bench.events("agent.idle")
    assert idle["limit_s"] == 300 and "raised_by" not in idle
    assert outcome.reason == "the agent showed no activity for 5m (implementer.idle_timeout), so L4 stopped it"


def test_scn_imp_540_a_silent_stop_uses_the_raised_limit_and_names_it(make_bench, monkeypatch):
    bench = make_bench([Step(idle_s=632, status="timeout")], implementer={"idle_timeout": "5m"}, **TWO)
    _opencode_like(bench, monkeypatch)
    bench.wb.gate_peak = ("baseline", 381.0)
    with pytest.raises(RoleLimit) as caught:
        run_red(bench.wb, TASK, attempt=1)
    assert bench.adapter.requests[0].stall_timeout_s == 632.0
    signal = caught.value.result.limit
    assert (signal.kind, signal.raw_excerpt) == ("silent", "no output for 10m")
    [idle] = bench.events("agent.idle")
    assert (idle["silent"], idle["limit_s"], idle["raised_by"]) == (True, 632, {"gate": "baseline", "seconds": 381})
    assert not bench.events("task.attempt_failed")


def test_the_previous_attempt_block_of_a_raised_silent_stop_names_the_raised_limit(make_bench):
    from l4.implementer.workbench import PreviousAttempt

    from .test_escalation import prompt_of

    bench = make_bench([], implementer={"idle_timeout": "5m"})
    bench.wb.previous_attempt = PreviousAttempt("impl", "silent", task="1.1", detail="no output for 10m")
    assert "went silent: no output for 10m, so L4 stopped it" in prompt_of(bench)
    bench.wb.previous_attempt = PreviousAttempt("impl", "silent", task="1.1")
    assert "went silent: no output for 5m, so L4 stopped it" in prompt_of(bench)
