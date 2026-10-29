"""ci-start D2 (L4-OPS-024, SCN-OPS-46..50): `l4 ci start [--if-idle DURATION]` starts the harness's run on the base
branch only when the forge shows none queued or running and, with `--if-idle`, the last one ended long enough ago."""

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from l4.cli import main
from l4.forge.base import AmbiguousWrite, ForgeError, make_forge
from l4.forge.local import LocalForge

from ..forge._github_helpers import REPO
from ..forge._github_helpers import TOKEN as GITHUB_TOKEN
from ..forge._gitlab_by_ref import RefAwareGitLab
from ..forge._runs_helpers import RunsGitHub
from ..forge.conftest import API as GITLAB_API
from ..forge.conftest import PROJECT
from ..forge.conftest import TOKEN as GITLAB_TOKEN

TOKEN_ENV = "L4_FORGE_TOKEN"
NOW = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)


def ago(minutes: float) -> str:
    return (NOW - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def start(tmp_path: Path, *args: str, platform: str = "github", token: bool = True) -> int:
    """Run the command through the CLI in an empty repository; `platform` is the forge type of the config."""
    config = tmp_path / "config.yaml"
    config.write_text(
        f"forge:\n  type: {platform}\n  gitlab:\n    api_url: {GITLAB_API}\n    project: '{PROJECT}'\n",
        encoding="utf-8",
    )
    secret = GITHUB_TOKEN if platform == "github" else GITLAB_TOKEN
    environ = {"PATH": os.environ["PATH"], "GITHUB_REPOSITORY": REPO, **({TOKEN_ENV: secret} if token else {})}
    argv = ["ci", "start", "--repo", str(tmp_path), "--config", str(config), *args]
    return main(argv, environ=environ)


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> RunsGitHub:
    fake = RunsGitHub()
    monkeypatch.setattr(
        "l4.ci.start.make_forge", lambda cfg, environ, **kw: make_forge(cfg, environ, transport=fake.transport(), **kw)
    )
    monkeypatch.setattr("l4.ci.start.utc_now", lambda: NOW)
    return fake


@pytest.fixture
def gitlab(monkeypatch: pytest.MonkeyPatch) -> RefAwareGitLab:
    fake = RefAwareGitLab()
    monkeypatch.setattr(
        "l4.ci.start.make_forge", lambda cfg, environ, **kw: make_forge(cfg, environ, transport=fake.transport(), **kw)
    )
    monkeypatch.setattr("l4.ci.start.utc_now", lambda: NOW)
    return fake


def run(run_id: int, status: str, updated: str | None = None, branch: str = "main") -> dict:
    return {"id": run_id, "status": status, "conclusion": None, "head_branch": branch, "updated_at": updated}


def test_a_running_run_blocks_the_start(github, tmp_path, capsys):
    """SCN-OPS-46."""
    github.l4_runs = [run(1, "in_progress")]
    assert start(tmp_path) == 0
    assert "a run is queued or running on main; nothing started" in capsys.readouterr().out
    assert github.writes() == []


def test_a_queued_run_blocks_the_start_even_with_a_long_idle_time(github, tmp_path, capsys):
    github.l4_runs = [run(1, "queued"), run(2, "completed", ago(300))]
    assert start(tmp_path, "--if-idle", "12m") == 0
    assert "nothing started" in capsys.readouterr().out
    assert github.writes() == []


def test_a_recent_run_blocks_the_start_with_if_idle(github, tmp_path, capsys):
    """SCN-OPS-47."""
    github.l4_runs = [run(1, "completed", ago(5))]
    assert start(tmp_path, "--if-idle", "12m") == 0
    assert "the last run ended 5 min ago (< 12m); nothing started" in capsys.readouterr().out
    assert github.writes() == []


def test_an_idle_base_starts_one_run(github, tmp_path, capsys):
    """SCN-OPS-48."""
    github.l4_runs = [run(1, "completed", ago(13))]
    assert start(tmp_path, "--if-idle", "12m") == 0
    assert "run started on main" in capsys.readouterr().out
    assert github.writes() == [("POST", f"/repos/{REPO}/actions/workflows/l4.yml/dispatches")]
    assert github.requests[-1][3] == {"ref": "main"}


def test_without_if_idle_a_recent_run_does_not_block(github, tmp_path, capsys):
    github.l4_runs = [run(1, "completed", ago(1))]
    assert start(tmp_path) == 0
    assert "run started on main" in capsys.readouterr().out
    assert len(github.writes()) == 1


def test_a_base_that_never_ran_is_idle(github, tmp_path):
    assert start(tmp_path, "--if-idle", "12m") == 0
    assert len(github.writes()) == 1


def test_the_idle_time_counts_from_the_end_exactly(github, tmp_path, capsys):
    github.l4_runs = [run(1, "completed", ago(12))]
    assert start(tmp_path, "--if-idle", "12m") == 0
    assert "run started on main" in capsys.readouterr().out


def test_a_forge_that_cannot_tell_starts_nothing(github, tmp_path, capsys):
    """SCN-OPS-49."""
    github.listing_status = 500
    assert start(tmp_path, "--if-idle", "12m") == 3
    assert "cannot tell whether a run is going on main; nothing started" in capsys.readouterr().err
    assert github.writes() == []


def test_the_local_forge_cannot_tell_so_nothing_is_started(tmp_path, monkeypatch, capsys):
    local = LocalForge()
    local.script_start_run("started")
    monkeypatch.setattr("l4.ci.start.make_forge", lambda *a, **k: local)
    assert start(tmp_path, platform="local") == 3
    assert local.called("start_run") == [] and "nothing started" in capsys.readouterr().err


def test_a_bad_duration_is_a_usage_error_before_any_call(github, tmp_path, capsys):
    """SCN-OPS-50."""
    assert start(tmp_path, "--if-idle", "soon") == 2
    assert "--if-idle" in capsys.readouterr().err
    assert github.requests == []


def test_a_missing_token_is_exit_3_with_the_way_to_start_a_run(tmp_path, capsys):
    """SCN-OPS-50."""
    assert start(tmp_path, token=False) == 3
    assert "gh workflow run l4.yml --ref main" in capsys.readouterr().err


def test_a_refused_dispatch_is_exit_3_and_says_how(github, tmp_path, capsys):
    github.dispatch_status = 403
    assert start(tmp_path) == 3
    err = capsys.readouterr().err
    assert "refused" in err and "gh workflow run l4.yml --ref main" in err


def test_a_workflow_that_is_not_on_the_branch_is_exit_3(github, tmp_path, capsys):
    github.dispatch_status = 404
    assert start(tmp_path) == 3
    assert "gh workflow run l4.yml --ref main" in capsys.readouterr().err


@pytest.mark.parametrize("failure", [ForgeError("HTTP 422", status=422), AmbiguousWrite("HTTP 502", status=502)])
def test_a_failed_start_is_exit_3(github, tmp_path, monkeypatch, capsys, failure):
    def fails(self, ref):
        raise failure

    monkeypatch.setattr("l4.forge.github.GitHubForge.start_run", fails)
    assert start(tmp_path) == 3
    assert "run" in capsys.readouterr().err


def test_a_run_that_queued_in_between_counts_as_busy(github, tmp_path, monkeypatch, capsys):
    """The listing lags a dispatch: when the start itself finds a waiting run, nothing was sent and the loop goes on."""

    def raced(self, ref):
        return "already_queued"

    monkeypatch.setattr("l4.forge.github.GitHubForge.start_run", raced)
    assert start(tmp_path) == 0
    assert "already queued" in capsys.readouterr().out


def test_a_running_gitlab_pipeline_blocks_the_start(gitlab, tmp_path, capsys):
    gitlab.add_ref_pipeline("main", "running")
    assert start(tmp_path, platform="gitlab") == 0
    assert "a run is queued or running on main; nothing started" in capsys.readouterr().out
    assert gitlab.writes() == []


def test_a_recent_gitlab_pipeline_blocks_and_an_old_one_does_not(gitlab, tmp_path, capsys):
    gitlab.add_ref_pipeline("main", "success", updated_at=ago(5))
    assert start(tmp_path, "--if-idle", "12m", platform="gitlab") == 0
    assert "the last run ended 5 min ago (< 12m); nothing started" in capsys.readouterr().out
    assert gitlab.writes() == []
    gitlab.pipelines.clear()
    gitlab.add_ref_pipeline("main", "failed", updated_at=ago(13))
    assert start(tmp_path, "--if-idle", "12m", platform="gitlab") == 0
    assert "run started on main" in capsys.readouterr().out
    assert [m for m, _ in gitlab.writes()] == ["POST"]


def test_a_gitlab_refusal_names_the_pipelines_page(gitlab, tmp_path, capsys):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "remote", "add", "origin", "https://gitlab.example.test/grp/proj.git"], check=True
    )
    gitlab.pipeline_post_status = 403
    assert start(tmp_path, platform="gitlab") == 3
    err = capsys.readouterr().err
    assert "refused" in err and "https://gitlab.example.test/grp/proj/-/pipelines/new?ref=main" in err


@pytest.mark.parametrize("branch", ["develop", "l4/openspec/a"])
def test_a_run_going_on_another_branch_blocks_the_start(github, tmp_path, capsys, branch):
    """The job holds one concurrency group for the repository: a scheduled run on a default branch that is not the
    base, or a push run on a unit branch, would make the started run wait."""
    github.l4_runs = [run(1, "in_progress", branch=branch)]
    assert start(tmp_path) == 0
    assert "a run is queued or running on main; nothing started" in capsys.readouterr().out
    assert github.writes() == []


def test_a_recent_end_on_another_branch_blocks_with_if_idle(github, tmp_path, capsys):
    github.l4_runs = [run(1, "completed", ago(5), branch="develop"), run(2, "completed", ago(60))]
    assert start(tmp_path, "--if-idle", "12m") == 0
    assert "the last run ended 5 min ago (< 12m); nothing started" in capsys.readouterr().out


def test_a_run_held_for_approval_blocks_the_start(github, tmp_path, capsys):
    held = {**run(1, "completed", ago(30)), "conclusion": "action_required"}
    github.l4_runs = [held]
    assert start(tmp_path) == 0
    assert "nothing started" in capsys.readouterr().out
    assert github.writes() == []


def test_a_unit_branch_pipeline_blocks_the_gitlab_start(gitlab, tmp_path, capsys):
    gitlab.add_ref_pipeline("l4/openspec/a", "running")
    assert start(tmp_path, platform="gitlab") == 0
    assert "a run is queued or running on main; nothing started" in capsys.readouterr().out
    assert gitlab.writes() == []


def test_a_pipeline_of_an_unrelated_branch_does_not_block_the_gitlab_start(gitlab, tmp_path, capsys):
    gitlab.add_ref_pipeline("feature", "running")
    assert start(tmp_path, platform="gitlab") == 0
    assert "run started on main" in capsys.readouterr().out


def test_the_configured_unit_branch_prefix_is_the_one_asked_for(gitlab, tmp_path, capsys):
    gitlab.add_ref_pipeline("bot/openspec/a", "running")
    config = tmp_path / "bot.yaml"
    config.write_text(
        f"forge:\n  type: gitlab\n  branch_prefix: bot/\n  gitlab:\n    api_url: {GITLAB_API}\n"
        f"    project: '{PROJECT}'\n",
        encoding="utf-8",
    )
    environ = {"PATH": os.environ["PATH"], TOKEN_ENV: GITLAB_TOKEN}
    assert main(["ci", "start", "--repo", str(tmp_path), "--config", str(config)], environ=environ) == 0
    assert "nothing started" in capsys.readouterr().out
