"""github-parity D4 (L4-GHP-004): a run that ends with exit 10 because units were left at the soft deadline asks the
forge for one more run of the harness's CI, once, and says what it was told (SCN-GHP-05, SCN-GHP-06)."""

import json
import logging
from types import SimpleNamespace

import pytest

from l4 import orchestrator
from l4.exitcodes import ExitCode
from l4.forge.base import ForgeError
from l4.outcome import CommandResult, Outcome, UnitOutcome, write_outcome
from l4.redact import Redactor

LEFT = UnitOutcome(
    unit="openspec:b", phase_before="implementing", phase_after="implementing",
    exit_reason="not started: soft deadline (0 s left, next unit estimated 600 s)",
)  # fmt: skip
DONE = UnitOutcome(unit="openspec:a", phase_before="ready", phase_after="implemented")
CI = {"GITHUB_ACTIONS": "true"}


class FakeForge:
    def __init__(self, answer="dispatched", error=None):
        self.calls: list[str] = []
        self.answer, self.error = answer, error

    def dispatch_continuation(self, ref):
        self.calls.append(ref)
        if self.error:
            raise self.error
        return self.answer


def _cfg(continuation="dispatch", base="main"):
    return SimpleNamespace(forge=SimpleNamespace(base_branch=base), ci=SimpleNamespace(continuation=continuation))


@pytest.fixture
def forge(monkeypatch):
    fake = FakeForge()
    monkeypatch.setattr(orchestrator, "make_forge", lambda cfg, environ: fake)
    return fake


def _go(result, cfg=None, environ=CI):
    return orchestrator.continue_left_units(
        SimpleNamespace(environ=environ, redactor=SimpleNamespace(redact_text=lambda t: t)), cfg or _cfg(), result
    )


def test_exit_10_with_units_left_dispatches_once_and_records_the_answer(forge, caplog):
    caplog.set_level(logging.INFO, logger="l4")
    out = _go(CommandResult(ExitCode.CONTINUE, [DONE, LEFT]), _cfg(base="release/1"))
    assert forge.calls == ["release/1"]
    assert out.continuation == "dispatched" and out.code == ExitCode.CONTINUE and list(out.units) == [DONE, LEFT]
    assert "continuation: dispatched (l4.yml on release/1)" in caplog.text
    assert "[l4] continuation" not in caplog.text  # the console handler adds the prefix once (run 38173604230)


def test_an_already_queued_run_is_reported_as_such(forge, caplog):
    caplog.set_level(logging.INFO, logger="l4")
    forge.answer = "already_queued"
    out = _go(CommandResult(ExitCode.CONTINUE, [LEFT]))
    assert out.continuation == "already_queued" and "continuation: already_queued (l4.yml on main)" in caplog.text


@pytest.mark.parametrize("code", [ExitCode.OK, ExitCode.AWAITING_HUMAN, ExitCode.HALTED])
def test_not_called_when_the_exit_is_not_10(forge, code):
    out = _go(CommandResult(code, [DONE, LEFT]))
    assert forge.calls == [] and out.continuation is None


def test_not_called_when_exit_10_has_no_unit_left_at_the_deadline(forge):
    assert _go(CommandResult(ExitCode.CONTINUE, [DONE])).continuation is None and forge.calls == []


def test_not_called_with_schedule_only(forge):
    out = _go(CommandResult(ExitCode.CONTINUE, [LEFT]), _cfg("schedule-only"))
    assert forge.calls == [] and out.continuation is None


def test_not_called_outside_ci(forge):
    assert _go(CommandResult(ExitCode.CONTINUE, [LEFT]), environ={}).continuation is None and forge.calls == []


def test_a_forge_error_is_a_warning_never_a_failure(monkeypatch, caplog):
    fake = FakeForge(error=ForgeError("boom"))
    monkeypatch.setattr(orchestrator, "make_forge", lambda cfg, environ: fake)
    out = _go(CommandResult(ExitCode.CONTINUE, [LEFT]))
    assert out.code == ExitCode.CONTINUE and out.continuation is None and fake.calls == ["main"]
    assert "continuation" in caplog.text and "boom" in caplog.text


def test_no_forge_does_nothing(monkeypatch):
    from l4.forge.base import ForgeUnavailable

    def none(cfg, environ):
        raise ForgeUnavailable("L4_FORGE_TOKEN is not set")

    monkeypatch.setattr(orchestrator, "make_forge", none)
    assert _go(CommandResult(ExitCode.CONTINUE, [LEFT])).continuation is None


def test_outcome_json_records_the_continuation(tmp_path):
    base = {"run_id": "r-20261003T1312Z-7f3a", "harness_version": "0.1.0", "exit_code": 10, "units": []}
    path = write_outcome(Outcome.model_validate({**base, "continuation": "dispatched"}), tmp_path, Redactor({}))
    assert json.loads(path.read_text())["continuation"] == "dispatched"
    path = write_outcome(Outcome.model_validate(base), tmp_path, Redactor({}))
    assert "continuation" not in json.loads(path.read_text())
