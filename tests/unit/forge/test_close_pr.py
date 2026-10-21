"""operator-commands 3.3 (L4-OPS-004 step 6, L4-OPS-009): `Forge.close_pr` comments, then closes; `get_pr` already
says whether a pull request is open, closed or merged."""

import pytest

from l4.forge.base import ForgeNotFound
from l4.forge.github import GitHubForge
from l4.forge.local import LocalForge

from ._github_helpers import API, REPO, TOKEN, FakeGitHub
from .conftest import PROJECT, FakeGitLab

BRANCH = "l4/openspec/add-discount-codes"
NOTE = "Restarted: the old head is refs/l4/attempts/openspec/x/1."


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def gh(github) -> GitHubForge:
    return GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)


def test_github_comments_then_closes(github, gh):
    github.add_pr(BRANCH)
    closed = gh.close_pr(1, NOTE)
    assert closed.state == "closed" and gh.get_pr(1).state == "closed"
    assert [c["body"] for c in github.comments[1]] == [NOTE]
    assert github.writes() == [
        ("POST", f"/repos/{REPO}/issues/1/comments"),
        ("PATCH", f"/repos/{REPO}/pulls/1"),
    ]
    assert [b for m, _, _, b in github.requests if m == "PATCH"] == [{"state": "closed"}]


@pytest.mark.parametrize("state", ["closed", "merged"])
def test_github_a_pull_request_that_is_not_open_is_left_alone(github, gh, state):
    pr = github.add_pr(BRANCH)
    pr["state"] = "closed"
    pr["merged"] = state == "merged"
    assert gh.close_pr(1, NOTE).state == state
    assert github.writes() == [] and github.comments == {}


def test_github_an_unknown_pull_request_is_not_found(gh):
    with pytest.raises(ForgeNotFound):
        gh.close_pr(9, NOTE)


def test_github_state_reads_open_closed_and_merged(github, gh):
    github.add_pr(BRANCH)
    assert gh.get_pr(1).state == "open"
    github.prs[1].update(state="closed", merged=True)
    assert gh.get_pr(1).state == "merged"


def test_gitlab_comments_then_closes(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b")
    gitlab.requests.clear()
    closed = forge.close_pr(1, NOTE)
    assert closed.state == "closed" and gitlab.mrs[1]["state"] == "closed"
    assert [n["body"] for n in gitlab.notes[1]] == [NOTE]
    base = f"/projects/{PROJECT}/merge_requests/1"
    assert gitlab.writes() == [("POST", f"{base}/notes"), ("PUT", base)]
    assert gitlab.requests[-1][3] == {"state_event": "close"}


@pytest.mark.parametrize("state", ["closed", "merged"])
def test_gitlab_a_merge_request_that_is_not_open_is_left_alone(gitlab: FakeGitLab, make_forge_client, state):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b")
    gitlab.mrs[1]["state"] = state
    gitlab.requests.clear()
    assert forge.close_pr(1, NOTE).state == state
    assert gitlab.writes() == [] and gitlab.notes == {}


def test_gitlab_a_comment_that_landed_before_a_lost_response_is_not_posted_twice(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b")
    gitlab.notes[1] = [{"id": 5, "body": NOTE, "system": False, "author": {"id": gitlab.bot_id}}]
    forge.close_pr(1, NOTE)  # a second attempt of the same restart: the note is there, the close is not
    assert [n["body"] for n in gitlab.notes[1]] == [NOTE]
    assert gitlab.mrs[1]["state"] == "closed"


def test_the_local_forge_comments_then_closes_and_keeps_the_comment(tmp_path):
    forge = LocalForge(tmp_path)
    forge.create_pr(BRANCH, "main", "t", "b")
    assert forge.close_pr(1, NOTE).state == "closed"
    assert forge.comments(1) == [NOTE] and LocalForge(tmp_path).comments(1) == [NOTE]
    forge.close_pr(1, "again")  # not open any more: nothing is written
    assert forge.comments(1) == [NOTE]
    assert [c.name for c in forge.writes()] == ["create_pr", "close_pr", "close_pr"]
    assert forge.get_pr(1).state == "closed"
    with pytest.raises(ForgeNotFound):
        forge.close_pr(9, NOTE)
