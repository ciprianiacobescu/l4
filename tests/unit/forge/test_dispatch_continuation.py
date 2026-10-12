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
    runs = {"branch": "main", "status": "queued", "per_page": "1"}
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
