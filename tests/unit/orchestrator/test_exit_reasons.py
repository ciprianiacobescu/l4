"""HB-7 and HB-8: one failing unit does not stop the run, and the outcome says why each unit stopped."""

from types import SimpleNamespace

import pytest

from l4 import orchestrator
from l4.agents.fake import Step
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.pushfail import PushFailed
from l4.orchestrator import UnitRunResult
from l4.outcome import UnitOutcome
from l4.vcs.git import Git, GitError
from l4.vcs.locks import LocalFileLease
from l4.vcs.names import UnitNames

from ..implementer.conftest import green_step, red_step, result
from .conftest import UNIT


def _unit(name: str):
    return (object(), SimpleNamespace(id=f"openspec:{name}"))


def test_a_unit_that_raises_does_not_stop_the_units_after_it(monkeypatch):
    """HB-7: the first unit raises; the second still runs and both are in the outcome, the first with exit 1."""
    monkeypatch.setattr(
        orchestrator, "load_snapshot", lambda *a, **k: SimpleNamespace(state=SimpleNamespace(phase="implementing"))
    )
    ran = []

    def fake(app, cfg, git, provider, ref, **kw):
        ran.append(ref.id)
        if ref.id.endswith("a"):
            raise RuntimeError("boom")
        return UnitRunResult(UnitOutcome(unit=ref.id, phase_before="ready", phase_after="awaiting_human"), 11)

    monkeypatch.setattr(orchestrator, "run_unit_in_worktree", fake)
    cfg = SimpleNamespace(
        forge=SimpleNamespace(branch_prefix="l4/"), ci=SimpleNamespace(time_budget="auto", soft_deadline_margin="20m")
    )
    app = SimpleNamespace(redactor=SimpleNamespace(redact_text=lambda t: t), environ={})
    out = orchestrator.run_units(app, cfg, None, [_unit("a"), _unit("b")], adapters=None)
    assert ran == ["openspec:a", "openspec:b"]
    assert out.code == 1  # the most severe of 1 and 11
    first, second = out.units
    assert (first.unit, first.phase_before, first.phase_after) == ("openspec:a", "implementing", "implementing")
    assert "RuntimeError: boom" in first.exit_reason
    assert (second.unit, second.phase_after) == ("openspec:b", "awaiting_human")


def test_a_failing_unit_is_listed_in_outcome_json_with_its_reason(run_l4, monkeypatch):
    def boom(self):
        raise RuntimeError("the unit exploded")

    monkeypatch.setattr(orchestrator.Orchestrator, "run_unit", boom)
    run = run_l4([red_step()])
    assert run.code == 1
    (unit,) = run.outcome["units"]
    assert unit["unit"] == UNIT and "the unit exploded" in unit["exit_reason"]


def test_a_halt_names_its_cause(run_l4):
    run = run_l4([Step(structured=result("red")), Step(structured=result("red"))], implementer={"max_task_attempts": 2})
    assert run.code == 13
    assert "max_task_attempts" in run.outcome["units"][0]["exit_reason"]


def test_a_busy_unit_says_it_was_skipped_because_another_run_holds_it(run_l4, tdd_repo):
    names = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=tdd_repo.cache)
    other = LocalFileLease(names.flock_path, unit=UNIT, run_id="r-20261003T0000Z-0000")
    other.acquire()
    try:
        run = run_l4([red_step()])
    finally:
        other.release()
    assert run.code == 0
    assert "locked by another run" in run.outcome["units"][0]["exit_reason"]


@pytest.fixture
def refusing(monkeypatch):
    def fail(self, remote, branch, *, config=()):
        raise GitError(["git", "push"], 1, " ! [remote rejected] HEAD -> x (pre-receive hook declined)")

    monkeypatch.setattr(Git, "push_branch", fail)


def test_a_push_the_forge_refused_is_the_units_exit_reason(run_l4, refusing):
    run = run_l4([red_step(), green_step()])
    assert run.code == 1
    (unit,) = run.outcome["units"]
    assert unit["exit_reason"].startswith("push refused by the forge:")


def test_the_human_push_hint_says_the_next_run_continues_from_it():
    from l4.forge.pushfail import explain_push_failure
    from l4.vcs.push import PushRejected

    exc = PushRejected(["git", "push"], 1, " ! [rejected] HEAD -> x (non-fast-forward)")
    text = str(explain_push_failure(exc, branch="b", token_env="T", environ={}, redact=lambda s: s))
    assert "a human pushed; the next run continues from it" in text
    assert "rebase or delete" not in text


def test_push_failed_stays_an_l4_exit_with_its_code():
    assert PushFailed(ExitCode.INTERNAL_ERROR, "m", refused=True).code == ExitCode.INTERNAL_ERROR
    assert isinstance(PushFailed(ExitCode.DOCTOR_FAILED, "m"), L4Exit)


def test_a_rejected_unit_says_why_in_its_outcome_and_the_run_lists_it(run_l4):
    """A rejection leaves the unit with no phase, so the reason is the exit reason: a delivery plan records it
    (L4-YOLO-013)."""
    run = run_l4([], test={"command": ""})
    assert run.code == 14
    (unit,) = run.outcome["units"]
    assert unit["exit_reason"] == "rejected: gates.test.command is not configured: there is no test oracle"
