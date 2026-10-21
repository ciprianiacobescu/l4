"""`l4 run` and a set `ci.time_budget` (budget-guard D2, D3; L4-IMP-076, L4-IMP-077)."""

import pytest

from l4 import orchestrator
from l4.cli import main
from l4.vcs.names import UnitNames

from ..implementer.conftest import green_step, red_step
from .conftest import BRANCH, UNIT

INCIDENT = {"time_budget": "21m", "soft_deadline_margin": "20m"}
TEXT = (
    "ci.time_budget 21m minus soft_deadline_margin 20m leaves 1 min, less than one step (10 min): "
    "set ci.time_budget: auto (the job timeout) or raise it"
)
SHORTENS = "is shorter than the job's timeout"


@pytest.fixture(autouse=True)
def no_token_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("l4.config.preflight.require_token_in_ci", lambda cfg, environ: None)


def test_run_refuses_a_budget_below_one_step_before_any_unit(run_l4, tdd_repo, capsys):
    """SCN-IMP-386: exit 2, the text, and nothing written."""
    tdd_repo.environ["L4_JOB_TIMEOUT_MINUTES"] = "180"
    run = run_l4([red_step(), green_step()], ci=INCIDENT)
    assert run.code == 2
    assert TEXT in capsys.readouterr().err
    assert run.adapter.requests == []
    names = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=tdd_repo.cache, repo_key=tdd_repo.key)
    assert not names.worktree.exists()
    assert run.raw(tdd_repo.origin, "branch", "--list", BRANCH).strip() == ""  # no unit-branch commit
    assert not [p for p in tdd_repo.repo.rglob("*.jsonl") if ".l4-out" not in p.parts]  # no unit ledger event


def test_the_refusal_comes_before_the_follow_ups_and_the_plan_step(run_l4, tdd_repo, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(orchestrator, "perform_follow_ups", lambda *a, **kw: calls.append("follow_ups") or [])
    monkeypatch.setattr(orchestrator, "yolo_step", lambda *a, **kw: calls.append("yolo_step"))
    monkeypatch.setattr(orchestrator, "make_forge", lambda *a, **kw: calls.append("make_forge"))
    run = run_l4([red_step()], ci=INCIDENT)
    assert run.code == 2 and calls == []


def test_a_budget_that_shortens_the_job_warns_once_and_runs(run_l4, tdd_repo, capsys):
    """SCN-IMP-388: one warning with the text, and the unit goes on to its red. (`l4 run` configures the `l4` logger
    with its own console handler and no propagation, so the warning is read from stderr, not from `caplog`.)"""
    tdd_repo.environ["L4_JOB_TIMEOUT_MINUTES"] = "180"
    run = run_l4([red_step(), green_step()], ci={"time_budget": "60m"})
    err = capsys.readouterr().err
    assert err.count(SHORTENS) == 1
    assert "the soft deadline comes at minute 40, not at minute 160" in err
    assert run.adapter.requests  # the red was requested


def test_the_incident_prints_only_the_refusal(run_l4, tdd_repo, capsys):
    tdd_repo.environ["L4_JOB_TIMEOUT_MINUTES"] = "180"
    run = run_l4([red_step()], ci=INCIDENT)
    assert run.code == 2
    assert SHORTENS not in capsys.readouterr().err


def test_status_and_the_dry_run_are_not_refused(run_l4, tdd_repo, capsys):
    """SCN-IMP-387: the configuration loads, so `l4 status` runs; the dry run is not the run."""
    tdd_repo.write_config(ci=INCIDENT)
    assert main(["status", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 0
    capsys.readouterr()
    run = run_l4([], "--dry-run", unit=False, ci=INCIDENT)
    assert run.code != 2
    assert TEXT not in capsys.readouterr().err
