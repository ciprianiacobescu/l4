"""operator-commands 3.2 (L4-OPS-002): `Forge.start_run` starts the harness's CI on a ref and never raises for a
refusal: the command prints how to start a run by hand instead."""

import pytest

from l4.forge.base import ForgeError
from l4.forge.github import GitHubForge
from l4.forge.local import LocalForge

from ._github_helpers import API, REPO, TOKEN, FakeGitHub
from ._gitlab_by_ref import RefAwareGitLab
from .conftest import PROJECT, FakeGitLab


@pytest.fixture
def gitlab() -> FakeGitLab:
    return RefAwareGitLab()  # the continuation lists the base's pipelines by ref (L4-IMP-070)


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def gh(github) -> GitHubForge:
    return GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)


def test_github_dispatches_l4_yml_and_says_started(github, gh):
    assert gh.start_run("main") == "started"
    assert github.writes() == [("POST", f"/repos/{REPO}/actions/workflows/l4.yml/dispatches")]
    assert github.requests[-1][3] == {"ref": "main"}


def test_github_a_waiting_run_counts_as_already_queued(github, gh):
    github.queued_runs = 1
    assert gh.start_run("main") == "already_queued"
    assert github.writes() == []


@pytest.mark.parametrize("status", [401, 403])
def test_github_a_refused_dispatch_is_refused_not_an_exception(github, gh, status):
    github.dispatch_status = status
    assert gh.start_run("main") == "refused"


def test_github_without_the_workflow_on_the_ref_is_unsupported(github, gh):
    github.dispatch_status = 404
    assert gh.start_run("main") == "unsupported"


def test_github_a_server_error_is_still_an_error(github, gh):
    github.dispatch_status = 500
    with pytest.raises(ForgeError):
        gh.start_run("main")


def test_github_dispatch_continuation_still_answers_in_its_own_words(github, gh):
    assert gh.dispatch_continuation("main") == "dispatched"


def test_gitlab_posts_a_pipeline_for_the_ref(gitlab: FakeGitLab, make_forge_client):
    """The exchange is GitLab's documented one: `POST /projects/:id/pipeline {"ref"}` answers 201 with the pipeline."""
    assert make_forge_client().start_run("main") == "started"
    assert gitlab.writes() == [("POST", f"/projects/{PROJECT}/pipeline")]
    assert gitlab.requests[-1][3] == {"ref": "main"}
    assert gitlab.pipelines[0]["ref"] == "main"


@pytest.mark.parametrize("status", [401, 403])
def test_gitlab_a_token_that_may_not_start_pipelines_is_refused(gitlab: FakeGitLab, make_forge_client, status):
    gitlab.pipeline_post_status = status
    assert make_forge_client().start_run("main") == "refused"


@pytest.mark.parametrize("status", [400, 404])
def test_gitlab_a_ref_or_project_that_cannot_run_is_unsupported(gitlab: FakeGitLab, make_forge_client, status):
    gitlab.pipeline_post_status = status
    assert make_forge_client().start_run("main") == "unsupported"


def test_gitlab_a_server_error_is_still_an_error(gitlab: FakeGitLab, make_forge_client):
    gitlab.pipeline_post_status = 500
    with pytest.raises(ForgeError):
        make_forge_client().start_run("main")


def test_gitlab_dispatch_continuation_starts_a_pipeline_now(gitlab: FakeGitLab, make_forge_client):
    """L4-IMP-070 (was: `unsupported` until forge-and-ci 2.6): with no pipeline of the base waiting, it is a start."""
    assert make_forge_client().dispatch_continuation("main") == "dispatched"
    assert gitlab.writes() == [("POST", f"/projects/{PROJECT}/pipeline")]


def test_the_local_forge_logs_the_start_and_answers_as_scripted():
    forge = LocalForge()
    assert forge.start_run("main") == "unsupported"  # the default, as for `dispatch_continuation`
    forge.script_start_run("started")
    assert forge.start_run("develop") == "started"
    assert [c.args for c in forge.called("start_run")] == [("main",), ("develop",)]
    assert [c.name for c in forge.writes()] == ["start_run", "start_run"]
