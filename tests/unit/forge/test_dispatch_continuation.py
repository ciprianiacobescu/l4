"""github-parity 1.4 (L4-GHP-004): the GitHub forge continues a run with workflow_dispatch, once."""

import httpx
import pytest

from l4.ci.github import WORKFLOW_RELPATH
from l4.forge.base import ForgeAuthError
from l4.forge.github import WORKFLOW_FILE, GitHubForge

from ._github_helpers import API, REPO, TOKEN, FakeGitHub


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def forge(github) -> GitHubForge:
    return GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)


def test_the_workflow_file_is_the_one_the_template_writes():
    assert WORKFLOW_FILE == WORKFLOW_RELPATH.rsplit("/", 1)[-1] == "l4.yml"


def test_no_queued_run_dispatches_the_ref(github, forge):
    assert forge.dispatch_continuation("main") == "dispatched"
    runs = {"branch": "main", "per_page": "20"}  # C-m6: the listing is not filtered to `queued` (was status=queued)
    assert github.requests == [
        ("GET", f"/repos/{REPO}/actions/workflows/l4.yml/runs", runs, None),
        ("POST", f"/repos/{REPO}/actions/workflows/l4.yml/dispatches", {}, {"ref": "main"}),
    ]


def test_a_queued_run_sends_nothing(github, forge):
    github.queued_runs = 1
    assert forge.dispatch_continuation("main") == "already_queued"
    assert github.writes() == []


def test_a_refused_dispatch_raises_the_forges_error(github):
    original = github.handle

    def refuse(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(403, json={"message": "Resource not accessible by integration"})
        return original(request)

    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=httpx.MockTransport(refuse), sleep=lambda s: None)
    with pytest.raises(ForgeAuthError):
        forge.dispatch_continuation("main")


def test_the_dispatching_runs_own_progress_does_not_block(github, forge):
    """SCN-IMP-365: the run that dispatches is itself `in_progress` on the base and must not count; only a run that
    waits does. The count leaves `in_progress` out (C-m6: the listing is no longer filtered to `queued`)."""
    assert forge.dispatch_continuation("main") == "dispatched"  # no waiting run: sent, though this run is in progress
    [listing, _post] = github.requests
    assert "status" not in listing[2]
    github.queued_runs = 1
    assert forge.dispatch_continuation("main") == "already_queued"


@pytest.mark.parametrize("status", ["queued", "pending", "waiting", "requested"])
def test_a_run_that_waits_in_any_state_blocks_a_second_dispatch(status):
    """C-m6: GitHub's waiting states are queued, pending, waiting and requested; `in_progress` is the run itself."""
    from ._runs_helpers import RunsGitHub

    github = RunsGitHub()
    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)
    github.l4_runs = [{"id": 5, "status": status, "conclusion": None, "head_branch": "main"}]
    assert forge.dispatch_continuation("main") == "already_queued"
    assert forge.start_run("main") == "already_queued"
    assert github.writes() == []
    github.l4_runs = [{"id": 5, "status": "in_progress", "conclusion": None, "head_branch": "main"}]
    assert forge.dispatch_continuation("main") == "dispatched"
