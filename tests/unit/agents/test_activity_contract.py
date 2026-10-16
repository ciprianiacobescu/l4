"""The contracts of run-liveness 0.1: new fields default to None, the keys load, `ago` formats times."""

import inspect
from collections.abc import Callable
from pathlib import Path

import pytest

from l4.agents import activity
from l4.agents.activity import ActivityWatch, Beat, Signal, ago
from l4.agents.base import RunRequest
from l4.agents.fake import Step
from l4.agents.proc import ProcRunner
from l4.config.schema import ImplementerCfg, Profile
from l4.implementer.workbench import Workbench
from l4.state.status import Activity, OpenRun, UnitSnapshot


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0s"), (59, "59s"), (60, "1m"), (119, "1m"), (3599, "59m"), (3600, "1h 0m"), (3725, "1h 2m")],
)
def test_ago(seconds, text):
    assert ago(seconds) == text


def test_new_fields_default_to_none(tmp_path: Path):
    request = RunRequest(
        profile=Profile.model_construct(), role="implementer", cwd=tmp_path, prompt="p",
        result_path=tmp_path / "r", raw_events_path=tmp_path / "e", env={},
    )  # fmt: skip
    assert request.watch is None
    assert Step().idle_s is None
    fields = UnitSnapshot.__dataclass_fields__
    assert fields["last_activity"].default is None
    assert fields["open_run"].default is None
    assert Activity("2026-10-16T10:00:00Z", "task.red_ok", "2.1", "r-1").task == "2.1"
    assert OpenRun("r-1", "2026-10-16T10:00:00Z", None).ci_url is None


def test_heartbeat_and_idle_timeout_keys_load_with_their_defaults():
    cfg = ImplementerCfg()
    assert (cfg.heartbeat, cfg.idle_timeout) == ("2m", "10m")
    cfg = ImplementerCfg.model_validate({"heartbeat": 0, "idle_timeout": "0"})
    assert (cfg.heartbeat, cfg.idle_timeout) == ("0", "0")
    with pytest.raises(ValueError):
        ImplementerCfg.model_validate({"heartbeat": "soon"})


def test_runner_and_gate_accept_the_new_arguments():
    assert {"watch", "reader"} <= set(inspect.signature(ProcRunner.run).parameters)
    for method in (Workbench.run_gate, Workbench.run_gate_spec):
        assert inspect.signature(method).parameters["note"].default is None


def test_watch_and_readers_are_contract_only():
    watch = ActivityWatch(120, lambda beat: None)
    assert watch.stopped_idle_s is None
    assert isinstance(watch.clock, Callable)
    calls = [
        lambda: watch.start(0.0, None), lambda: watch.line("x"), lambda: watch.tick(0.0),
        watch.has_open_call, lambda: watch.snapshot(0.0),
    ]  # fmt: skip
    readers = ("opencode_signals", "claude_code_signals", "codex_signals", "kiro_signals")
    calls += [lambda name=name: getattr(activity, name)("x") for name in readers]
    for call in calls:
        with pytest.raises(NotImplementedError):
            call()
    assert Signal("start").id is None
    assert Beat(1.0, 0, 1.0, 0, 0.0, False).counts is False
