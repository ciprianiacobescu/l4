"""run-continuation 6.1 (L4-IMP-072): `Forge.relay_run` starts `l4.yml` on the base unless another run of it is
waiting or running there; `Forge.base_runs` counts those runs."""

import httpx
import pytest

from l4.forge.github import GitHubForge
from l4.forge.gitlab import GitLabForge
from l4.forge.local import LocalForge

from ._github_helpers import API, REPO, TOKEN
from ._runs_helpers import RunsGitHub, RunsGitLab
from .conftest import API as GITLAB_API
from .conftest import PROJECT
from .conftest import TOKEN as GITLAB_TOKEN


@pytest.fixture
def github() -> RunsGitHub:
    return RunsGitHub()


@pytest.fixture
def forge(github) -> GitHubForge:
    return GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)


def _run(run_id: int, status: str, branch: str = "staging", conclusion: str | None = None) -> dict:
    return {"id": run_id, "status": status, "conclusion": conclusion, "head_branch": branch}


def test_no_other_active_run_dispatches_the_base(github, forge):
    assert forge.relay_run("staging", exclude_run_id="11") == "dispatched"
    base = f"/repos/{REPO}/actions/workflows/l4.yml"
    assert github.requests == [
        ("GET", f"{base}/runs", {"branch": "staging", "per_page": "20"}, None),
        ("POST", f"{base}/dispatches", {}, {"ref": "staging"}),
    ]


@pytest.mark.parametrize("status", ["queued", "pending", "waiting", "requested", "in_progress"])
def test_an_active_run_sends_nothing(github, forge, status):
    github.l4_runs = [_run(12, status)]
    assert forge.relay_run("staging", exclude_run_id="11") == "already_running"
    assert github.writes() == []


def test_the_own_run_is_left_out(github, forge):
    github.l4_runs = [_run(11, "in_progress")]
    assert forge.relay_run("staging", exclude_run_id="11") == "dispatched"


def test_completed_runs_do_not_count(github, forge):
    github.l4_runs = [_run(12, "completed", conclusion="cancelled"), _run(13, "completed", conclusion="success")]
    assert forge.relay_run("staging", exclude_run_id=None) == "dispatched"


def test_403_is_refused_and_404_is_unsupported(github, forge):
    github.dispatch_status = 403
    assert forge.relay_run("staging", exclude_run_id="11") == "refused"
    github.dispatch_status = 404
    assert forge.relay_run("staging", exclude_run_id="11") == "unsupported"
    github.dispatch_status = 204
    github.listing_status = 403
    assert forge.relay_run("staging", exclude_run_id="11") == "refused"


def test_base_runs_counts_the_waiting_and_running_runs(github, forge):
    github.l4_runs = [_run(1, "queued"), _run(2, "in_progress"), _run(3, "completed"), _run(4, "waiting")]
    assert forge.base_runs("staging") == 3
    assert forge.base_runs("staging", exclude_run_id="2") == 2
    github.listing_status = 500
    assert forge.base_runs("staging") is None

    gitlab = RunsGitLab()
    for status in ("created", "pending", "running", "success", "failed", "canceled"):
        gitlab.pipelines.append({"id": len(gitlab.pipelines) + 1, "sha": "a" * 40, "status": status, "jobs": [],
                                 "ref": "staging"})  # fmt: skip
    gitlab.pipelines.append({"id": 50, "sha": "a" * 40, "status": "running", "jobs": [], "ref": "main"})
    lab = GitLabForge(GITLAB_API, PROJECT, GITLAB_TOKEN, transport=gitlab.transport(), sleep=lambda s: None)
    assert lab.base_runs("staging") == 3
    assert lab.base_runs("staging", exclude_run_id="3") == 2
    gitlab.fail_next = [httpx.Response(403, json={"message": "no"})]
    assert lab.base_runs("staging") is None


def test_gitlab_and_local_relay_answers_unsupported():
    lab = GitLabForge(GITLAB_API, PROJECT, GITLAB_TOKEN, transport=RunsGitLab().transport(), sleep=lambda s: None)
    assert lab.relay_run("staging", exclude_run_id="1") == "unsupported"
    local = LocalForge()
    assert local.relay_run("staging", exclude_run_id="1") == "unsupported"
    assert local.base_runs("staging") is None
    assert [call.name for call in local.calls] == ["relay_run", "base_runs"]


def test_base_runs_is_a_quick_read_one_try_and_a_short_timeout(github, forge):
    """B-m1, D9: `base_runs` decorates a status line; a 502 is asked once, within the quick timeout."""
    github.listing_status = 502
    assert forge.base_runs("staging") is None
    assert [r[0] for r in github.requests] == ["GET"]
    assert 0 < github.timeouts[-1]["read"] <= 10
    github.listing_status = 200
    forge.base_runs("staging")
    assert 0 < github.timeouts[-1]["read"] <= 10


def test_gitlab_base_runs_is_a_quick_read(monkeypatch):
    gitlab = RunsGitLab()
    gitlab.fail_next = [httpx.Response(502, json={"message": "bad gateway"})]
    lab = GitLabForge(GITLAB_API, PROJECT, GITLAB_TOKEN, transport=gitlab.transport(), sleep=lambda s: None)
    assert lab.base_runs("staging") is None
    assert len(gitlab.timeouts) == 1 and 0 < gitlab.timeouts[0]["read"] <= 10


def test_relay_run_keeps_its_retries_for_the_listing(github, forge):
    github.listing_status = 502
    with pytest.raises(Exception):  # noqa: B017, PT011 - the point is the number of tries
        forge.relay_run("staging", exclude_run_id=None)
    assert len(github.requests) > 1
