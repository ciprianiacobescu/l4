"""adoption-lessons 1.4b (L4-ADO-005, SCN-ADO-13..15): in CI with `harness.delivery: action`, a harness that is not the
base's pin does no work: `l4 plan --sweep` and `l4 run` print a `::warning::` annotation and exit 0."""

from pathlib import Path

import pytest

from l4 import orchestrator, planner
from l4.ci import pin_guard
from l4.ci.github import WORKFLOW_RELPATH, ActionPin, render_github_action_ci
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode
from l4.redact import Redactor

RUNNING = "a" * 40
PINNED = "b" * 40


class Reached(Exception):
    """The command went past the guard."""


def make_repo(tmp_path: Path, pin: str = PINNED, delivery: str = "action") -> Path:
    (tmp_path / ".l4").mkdir()
    (tmp_path / ".l4/config.yaml").write_text(f"version: 1\nharness:\n  delivery: {delivery}\n")
    (tmp_path / WORKFLOW_RELPATH).parent.mkdir(parents=True)
    (tmp_path / WORKFLOW_RELPATH).write_text(render_github_action_ci(L4Config(), ActionPin("o/harness", pin)))
    return tmp_path


def app_for(repo: Path, **environ: str) -> AppContext:
    return AppContext(
        repo=repo, config_path=None, log_format="human", verbosity=0, run_id="r-20261015T1000Z-0001",
        environ=environ, redactor=Redactor({}),
    )  # fmt: skip


@pytest.fixture
def guarded(monkeypatch):
    """Both commands raise `Reached` at their first step after the guard."""

    def reached(*args, **kwargs):
        raise Reached

    monkeypatch.setattr(planner, "snapshots", reached)
    monkeypatch.setattr(orchestrator, "preflight_run_config", reached)
    monkeypatch.setattr(pin_guard, "harness_commit", lambda: RUNNING)


CI = {"GITHUB_ACTIONS": "true"}
PLAN = dict(units=(), as_json=False, probe=False, sweep=True, detailed_exitcode=False)


def test_plan_sweep_with_an_old_pin_does_no_work_and_exits_0(tmp_path, guarded, capsys):  # SCN-ADO-13
    result = planner.run_plan(app_for(make_repo(tmp_path), **CI), **PLAN)
    assert result.code == ExitCode.OK
    err = capsys.readouterr().err
    assert err.startswith("::warning::") and RUNNING in err and PINNED in err
    assert ".github/workflows/l4.yml" in err and "default branch" in err


def test_run_with_an_old_pin_does_no_work_and_exits_0(tmp_path, guarded, capsys):  # SCN-ADO-13
    result = orchestrator.run_command(app_for(make_repo(tmp_path), **CI))
    assert result.code == ExitCode.OK
    err = capsys.readouterr().err
    assert "::warning::" in err and RUNNING in err and PINNED in err


def test_the_same_pin_goes_on(tmp_path, guarded):  # SCN-ADO-14
    repo = make_repo(tmp_path, pin=RUNNING)
    with pytest.raises(Reached):
        planner.run_plan(app_for(repo, **CI), **PLAN)
    with pytest.raises(Reached):
        orchestrator.run_command(app_for(repo, **CI))


def test_outside_ci_nothing_is_checked(tmp_path, guarded):  # SCN-ADO-15
    repo = make_repo(tmp_path)
    with pytest.raises(Reached):
        planner.run_plan(app_for(repo), **PLAN)
    with pytest.raises(Reached):
        orchestrator.run_command(app_for(repo))


def test_a_plan_without_the_sweep_is_read_only_and_goes_on(tmp_path, guarded):
    with pytest.raises(Reached):
        planner.run_plan(app_for(make_repo(tmp_path), **CI), **{**PLAN, "sweep": False})


def test_other_deliveries_and_an_unknown_running_commit_go_on(tmp_path, guarded, monkeypatch):
    (tmp_path / "v").mkdir()
    with pytest.raises(Reached):
        orchestrator.run_command(app_for(make_repo(tmp_path / "v", delivery="vendored"), **CI))
    monkeypatch.setattr(pin_guard, "harness_commit", lambda: None)
    (tmp_path / "u").mkdir()
    with pytest.raises(Reached):
        orchestrator.run_command(app_for(make_repo(tmp_path / "u"), **CI))


def test_a_run_on_a_unit_branch_names_the_branch_fix_not_the_default_branch_one(tmp_path, guarded, capsys):
    env = {**CI, "GITHUB_REF_NAME": "l4/openspec/add-thing", "GITHUB_REF_TYPE": "branch"}
    planner.run_plan(app_for(make_repo(tmp_path), **env), **PLAN)
    err = capsys.readouterr().err
    assert err.startswith("::warning::") and RUNNING in err and PINNED in err
    assert "unit branch" in err and "merge the base branch" in err
    assert "on the default branch to the base's copy" not in err


def test_a_run_elsewhere_keeps_the_default_branch_fix(tmp_path, guarded, capsys):
    env = {**CI, "GITHUB_REF_NAME": "main", "GITHUB_REF_TYPE": "branch"}
    planner.run_plan(app_for(make_repo(tmp_path), **env), **PLAN)
    assert "on the default branch to the base's copy" in capsys.readouterr().err
