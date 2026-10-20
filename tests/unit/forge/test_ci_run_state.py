"""run-continuation 7.1 (L4-IMP-073): `Forge.ci_run_state` says whether the CI run behind a `ci_url` is still going,
over, or unknown. A short read that never raises."""

import pytest

from l4.forge.github import GitHubForge
from l4.forge.gitlab import GitLabForge
from l4.forge.local import LocalForge

from ._github_helpers import API, REPO, TOKEN
from ._runs_helpers import RunsGitHub, RunsGitLab
from .conftest import API as GITLAB_API
from .conftest import PROJECT, WEB
from .conftest import TOKEN as GITLAB_TOKEN

RUN_URL = f"https://github.com/{REPO}/actions/runs/77"


@pytest.fixture
def github() -> RunsGitHub:
    return RunsGitHub()


@pytest.fixture
def forge(github) -> GitHubForge:
    return GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)


@pytest.fixture
def gitlab() -> RunsGitLab:
    return RunsGitLab()


@pytest.fixture
def lab(gitlab) -> GitLabForge:
    return GitLabForge(GITLAB_API, PROJECT, GITLAB_TOKEN, transport=gitlab.transport(), sleep=lambda s: None)


def test_a_github_run_url_is_read(github, forge):
    github.l4_runs = [{"id": 77, "status": "completed", "conclusion": "cancelled", "head_branch": "staging"}]
    assert forge.ci_run_state(RUN_URL) == ("completed", "cancelled")
    assert github.requests[-1][:2] == ("GET", f"/repos/{REPO}/actions/runs/77")
    github.l4_runs = [{"id": 77, "status": "in_progress", "conclusion": None, "head_branch": "staging"}]
    assert forge.ci_run_state(RUN_URL) == ("running", "in_progress")
    github.l4_runs = [{"id": 77, "status": "queued", "conclusion": None, "head_branch": "staging"}]
    assert forge.ci_run_state(RUN_URL)[0] == "running"


def test_the_stored_forge_form_of_a_run_url_is_read(github, forge):
    """B-M1: the path suffix names the run; the host (or its `<forge>` placeholder) is not part of the match."""
    github.l4_runs = [{"id": 77, "status": "completed", "conclusion": "success", "head_branch": "staging"}]
    assert forge.ci_run_state(f"<forge>/{REPO}/actions/runs/77") == ("completed", "success")
    assert forge.ci_run_state("<forge>/other/repo/actions/runs/77") == ("unknown", "")


def test_a_re_run_reads_its_attempt(github, forge):
    github.attempts[(77, 2)] = {"id": 77, "run_attempt": 2, "status": "completed", "conclusion": "success"}
    assert forge.ci_run_state(f"{RUN_URL}/attempts/2") == ("completed", "success")
    assert github.requests[-1][:2] == ("GET", f"/repos/{REPO}/actions/runs/77/attempts/2")


def test_a_gitlab_job_url_is_read(gitlab, lab):
    gitlab.jobs_by_id = {55: {"id": 55, "status": "failed"}, 56: {"id": 56, "status": "running"}}
    assert lab.ci_run_state(f"{WEB}/-/jobs/55") == ("completed", "failed")
    assert lab.ci_run_state(f"{WEB}/-/jobs/56") == ("running", "running")
    assert [r[1] for r in gitlab.requests if r[0] == "GET"][-1] == f"/projects/{PROJECT}/jobs/56"


def test_the_get_has_a_short_timeout(github, forge, gitlab, lab):
    github.l4_runs = [{"id": 77, "status": "completed", "conclusion": "success", "head_branch": "x"}]
    forge.ci_run_state(RUN_URL)
    assert 0 < github.timeouts[-1]["read"] <= 10
    gitlab.jobs_by_id = {55: {"id": 55, "status": "success"}}
    lab.ci_run_state(f"{WEB}/-/jobs/55")
    assert 0 < gitlab.timeouts[-1]["read"] <= 10


def test_an_unknown_url_or_an_error_is_unknown(github, forge, gitlab, lab):
    github.l4_runs = [{"id": 77, "status": "completed", "conclusion": "success", "head_branch": "x"}]
    before = len(github.requests)
    for url in ("", "not a url", "https://github.com/other/repo/actions/runs/77", f"https://github.com/{REPO}/pull/1"):
        assert forge.ci_run_state(url) == ("unknown", "")
    assert len(github.requests) == before  # nothing parsed, nothing asked
    github.run_status = 500
    assert forge.ci_run_state(RUN_URL) == ("unknown", "")
    github.run_status = 403
    assert forge.ci_run_state(RUN_URL) == ("unknown", "")
    github.run_status = 404
    assert forge.ci_run_state(f"https://github.com/{REPO}/actions/runs/999") == ("unknown", "")
    assert lab.ci_run_state(f"{WEB}/-/jobs/404") == ("unknown", "")
    assert lab.ci_run_state(f"{WEB}/-/pipelines/5") == ("unknown", "")
    gitlab.jobs_by_id = {9: {"id": 9, "status": "something_new"}}
    assert lab.ci_run_state(f"{WEB}/-/jobs/9") == ("unknown", "")


def test_local_is_unknown():
    local = LocalForge()
    assert local.ci_run_state(RUN_URL) == ("unknown", "")
    assert [call.name for call in local.calls] == ["ci_run_state"]
