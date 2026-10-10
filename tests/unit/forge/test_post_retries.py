"""HB-12 (L4-ARC-002): a POST is retried blindly only when it cannot have landed (a connect error, a 429). After a read
timeout or a 5xx the forge reads first, so a lost response never yields a second note, MR or label."""

from collections.abc import Callable

import httpx
import pytest

from l4.forge.base import ForgeError
from l4.forge.github import GitHubForge

from ._github_helpers import API as GH_API
from ._github_helpers import REPO, FakeGitHub
from ._github_helpers import TOKEN as GH_TOKEN
from .conftest import API, PROJECT, TOKEN, FakeGitLab

BRANCH = "l4/openspec/x"


class Lossy(httpx.BaseTransport):
    """Passes everything to `inner`, except that the first `times` requests that `match` fail: `after` runs the request
    on the server first (the response is lost), otherwise it never reaches it."""

    def __init__(
        self, inner: httpx.BaseTransport, match: Callable[[httpx.Request], bool], error, *, after: bool, times=1
    ):
        self.inner, self.match, self.error, self.after, self.left = inner, match, error, after, times
        self.attempts = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.match(request):
            self.attempts += 1
            if self.left > 0:
                self.left -= 1
                if self.after:
                    self.inner.handle_request(request)
                if isinstance(self.error, httpx.Response):
                    return self.error
                raise self.error("simulated", request=request)
        return self.inner.handle_request(request)


def is_post(suffix: str):
    return lambda r: r.method == "POST" and r.url.path.endswith(suffix)


def gitlab_forge(gitlab: FakeGitLab, lossy: Lossy | None = None):
    from l4.forge.gitlab import GitLabForge

    return GitLabForge(API, PROJECT, TOKEN, transport=lossy or gitlab.transport(), sleep=lambda s: None)


def with_mr(gitlab: FakeGitLab) -> None:
    gitlab_forge(gitlab).create_pr(BRANCH, "main", "t", "b")


LOST = [
    pytest.param(httpx.ReadTimeout, id="read-timeout"),
    pytest.param(httpx.RemoteProtocolError, id="connection-dropped"),
    pytest.param(httpx.Response(502, json={"message": "bad gateway"}), id="502"),
]


@pytest.mark.parametrize("error", LOST)
def test_a_note_created_and_then_a_lost_response_leaves_exactly_one_note(gitlab: FakeGitLab, error):
    with_mr(gitlab)
    lossy = Lossy(gitlab.transport(), is_post("/notes"), error, after=True)
    gitlab_forge(gitlab, lossy).upsert_sticky_note(1, "- Q-001: first")
    assert len(gitlab.notes[1]) == 1 and gitlab.notes[1][0]["body"].endswith("- Q-001: first")
    assert lossy.attempts == 1  # no second POST


@pytest.mark.parametrize("error", LOST)
def test_a_note_that_never_landed_is_posted_again_after_the_read(gitlab: FakeGitLab, error):
    with_mr(gitlab)
    lossy = Lossy(gitlab.transport(), is_post("/notes"), error, after=False)
    gitlab_forge(gitlab, lossy).upsert_sticky_note(1, "- Q-001: first")
    assert len(gitlab.notes[1]) == 1 and lossy.attempts == 2


def test_a_connect_error_is_retried_blindly_without_a_read(gitlab: FakeGitLab):
    with_mr(gitlab)
    lossy = Lossy(gitlab.transport(), is_post("/notes"), httpx.ConnectError, after=False)
    gitlab.requests.clear()
    gitlab_forge(gitlab, lossy).upsert_sticky_note(1, "x")
    assert len(gitlab.notes[1]) == 1 and lossy.attempts == 2
    # the two reads before the POST (user, notes); none between the failed POST and its retry
    methods = [m for m, *_ in gitlab.requests]
    assert methods == ["GET", "GET", "POST"]


def test_a_429_is_retried_blindly(gitlab: FakeGitLab):
    with_mr(gitlab)
    lossy = Lossy(gitlab.transport(), is_post("/notes"), httpx.Response(429, headers={"Retry-After": "0"}), after=False)
    gitlab_forge(gitlab, lossy).upsert_sticky_note(1, "x")
    assert len(gitlab.notes[1]) == 1 and lossy.attempts == 2


def test_a_second_lost_response_after_a_clean_read_is_an_error(gitlab: FakeGitLab):
    with_mr(gitlab)
    lossy = Lossy(gitlab.transport(), is_post("/notes"), httpx.ReadTimeout, after=False, times=5)
    with pytest.raises(ForgeError):
        gitlab_forge(gitlab, lossy).upsert_sticky_note(1, "x")
    assert gitlab.notes.get(1, []) == []


def test_an_mr_created_and_then_a_lost_response_is_not_created_twice(gitlab: FakeGitLab):
    lossy = Lossy(gitlab.transport(), is_post("/merge_requests"), httpx.ReadTimeout, after=True)
    pr = gitlab_forge(gitlab, lossy).create_pr(BRANCH, "main", "t", "b")
    assert len(gitlab.mrs) == 1 and pr.number == 1 and lossy.attempts == 1


def test_a_label_created_and_then_a_lost_response_is_not_an_error(gitlab: FakeGitLab):
    lossy = Lossy(gitlab.transport(), is_post("/labels"), httpx.ReadTimeout, after=True)
    gitlab_forge(gitlab, lossy).ensure_labels(["l4:queued"])
    assert gitlab.labels == ["l4:queued"]


def github_forge(github: FakeGitHub, lossy: Lossy | None = None) -> GitHubForge:
    return GitHubForge(REPO, GH_TOKEN, api_url=GH_API, transport=lossy or github.transport(), sleep=lambda s: None)


@pytest.mark.parametrize("error", LOST)
def test_github_comment_created_and_then_a_lost_response_leaves_one_comment(error):
    github = FakeGitHub()
    github.add_pr(BRANCH, number=1)
    lossy = Lossy(github.transport(), is_post("/comments"), error, after=True)
    github_forge(github, lossy).upsert_sticky_note(1, "- Q-001: first")
    assert len(github.comments[1]) == 1 and lossy.attempts == 1


def test_github_pull_request_created_and_then_a_lost_response_is_not_created_twice():
    github = FakeGitHub()
    lossy = Lossy(github.transport(), is_post("/pulls"), httpx.ReadTimeout, after=True)
    # the fake derives the head from the payload: the re-read finds the PR the first POST made
    github_forge(github, lossy).create_pr(BRANCH, "main", "t", "b")
    assert len(github.prs) == 1 and lossy.attempts == 1
