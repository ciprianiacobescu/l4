"""L4-IMP-088 D3: the workbench the orchestrator builds anew after a fall-back or an escalation carries the baselines
and nothing else of the kept green run."""

from l4.gates.junit import TestReport
from l4.implementer.workbench import KeptRun
from l4.orchestrator import Orchestrator

from ..implementer.conftest import green_step, red_step
from .test_escalation import FAIL
from .test_fallback import TWO, limited


def plant(monkeypatch, method: str, seen: list) -> None:
    """Give the workbench a kept run just before the orchestrator rebuilds it, and note what the new one holds."""
    real = getattr(Orchestrator, method)

    def wrapped(self, *args, **kwargs):
        wb = next(a for a in (*args, *kwargs.values()) if hasattr(a, "last_tested"))
        wb.last_tested = KeptRun("t" * 40, "d", TestReport({}), "s" * 40)
        fresh = real(self, *args, **kwargs)
        seen.append((wb, fresh, fresh.last_tested))  # the run goes on and may keep a green run of its own
        return fresh

    monkeypatch.setattr(Orchestrator, method, wrapped)


def test_an_escalated_workbench_does_not_carry_the_kept_run(run_l4, monkeypatch):
    seen: list = []
    plant(monkeypatch, "_escalate", seen)
    run = run_l4([FAIL, FAIL, red_step(), green_step()], **TWO)
    assert run.code == 0
    [(old, fresh, kept)] = seen
    assert fresh is not old and kept is None
    assert fresh.baselines is old.baselines  # what is carried


def test_a_fallen_back_workbench_does_not_carry_the_kept_run(run_l4, monkeypatch, fake_clock):
    seen: list = []
    plant(monkeypatch, "_fall_back", seen)
    run = run_l4([red_step(), limited(), green_step()], **TWO)
    assert run.code == 0
    [(old, fresh, kept)] = seen
    assert fresh is not old and kept is None
    assert fresh.baselines is old.baselines
