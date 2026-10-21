import httpx
import pytest

from l4.forge.base import STICKY_MARKER, ForgeError
from l4.forge.github import GitHubForge

from ._github_helpers import API, LOGIN, REPO, TOKEN, FakeGitHub

PREFIX = "l4:"


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def forge(github) -> GitHubForge:
    return GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)


def test_ensure_labels_creates_only_the_missing_ones(github, forge):
    github.labels = ["bug", "l4:queued"]
    forge.ensure_labels(["l4:queued", "l4:in_review", "l4:halted"])
    assert github.labels == ["bug", "l4:queued", "l4:in_review", "l4:halted"]
    github.requests.clear()
    forge.ensure_labels(["l4:queued", "l4:in_review"])
    assert github.writes() == []


def test_ensure_labels_tolerates_a_concurrent_create_and_pages(github, forge):
    github.page_size = 2
    github.labels = [f"l{i}" for i in range(5)]
    forge.ensure_labels(["l4", "l0"])
    assert "l4" in github.labels
    # another run created the label between our listing and our POST: 422 already_exists
    github.fail_next = []
    racing = FakeGitHub()
    racing.labels = []
    original = racing.handle

    def handle(request):
        if request.method == "POST" and request.url.path.endswith("/labels"):
            return httpx.Response(422, json={"message": "Validation Failed"})
        return original(request)

    GitHubForge(REPO, TOKEN, api_url=API, transport=httpx.MockTransport(handle)).ensure_labels(["l4:x"])


def test_foreign_labels_are_kept(github, forge):
    github.add_pr("l4/openspec/a", draft=False, labels=[{"name": "bug"}, {"name": "l4:queued"}, {"name": "l4:halted"}])
    pr = forge.set_managed_labels(1, ["l4:in_review", "l4:halted"], PREFIX)
    assert set(pr.labels) == {"bug", "l4:in_review", "l4:halted"}
    deletes = [p for m, p, _, _ in github.requests if m == "DELETE"]
    assert deletes == [f"/repos/{REPO}/issues/1/labels/l4:queued"]


def test_label_names_are_quoted_in_the_url(github):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode())
        if request.method == "GET":
            return httpx.Response(200, json=github.add_pr("b", labels=[{"name": "l4:a/b c"}]))
        return httpx.Response(200, json=[])

    GitHubForge(REPO, TOKEN, api_url=API, transport=httpx.MockTransport(handler)).set_managed_labels(1, [], PREFIX)
    assert any(path.endswith("/labels/l4%3Aa%2Fb%20c") for path in seen)


def test_set_managed_labels_writes_nothing_when_nothing_differs(github, forge):
    github.add_pr("l4/openspec/a", labels=[{"name": "l4:queued"}, {"name": "bug"}])
    github.requests.clear()
    assert forge.set_managed_labels(1, ["l4:queued"], PREFIX).labels == ("l4:queued", "bug")
    assert github.writes() == []
    with pytest.raises(ValueError):
        forge.set_managed_labels(1, ["bug"], PREFIX)


def test_sticky_note_is_created_then_rewritten_in_place_then_left_alone(github, forge):
    github.add_pr("l4/openspec/a")
    forge.upsert_sticky_note(1, "first")
    (comment,) = github.comments[1]
    assert comment["body"] == f"{STICKY_MARKER}\nfirst"
    forge.upsert_sticky_note(1, "second")
    assert [c["body"] for c in github.comments[1]] == [f"{STICKY_MARKER}\nsecond"]
    github.requests.clear()
    forge.upsert_sticky_note(1, "second")
    assert github.writes() == []


def test_a_marker_in_someone_elses_comment_is_never_rewritten(github, forge):
    github.add_pr("l4/openspec/a")
    github.comments[1] = [
        {"id": 5, "body": f"{STICKY_MARKER}\nplanted", "user": {"login": "mallory"}},
        {"id": 6, "body": f"quoting {STICKY_MARKER} in prose", "user": {"login": LOGIN}},
    ]
    forge.upsert_sticky_note(1, "mine")
    assert github.comments[1][0]["body"].endswith("planted") and github.comments[1][1]["body"].startswith("quoting")
    assert github.comments[1][2]["body"] == f"{STICKY_MARKER}\nmine"


def test_sticky_note_needs_to_know_the_token_user(github, forge):
    github.add_pr("l4/openspec/a")
    github.user_status = 403
    with pytest.raises(ForgeError, match="which user"):
        forge.upsert_sticky_note(1, "x")
    assert github.comments == {}
