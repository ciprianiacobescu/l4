import httpx
import pytest

from l4.forge.base import ForgeAuthError, ForgeError, ForgeNotFound, ForgeRateLimited
from l4.forge.github import GitHubForge

from ._github_helpers import API, REPO, TOKEN, FakeGitHub

BRANCH = "l4/openspec/add-discount-codes"


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def make(github):
    sleeps: list[float] = []

    def build(**kw) -> GitHubForge:
        kw.setdefault("sleep", sleeps.append)
        return GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), **kw)

    build.sleeps = sleeps  # type: ignore[attr-defined]
    return build


def test_create_pr_is_draft_and_idempotent(github, make):
    forge = make()
    first = forge.create_pr(BRANCH, "main", "[l4] add-discount-codes: Discounts", "body")
    assert first.draft and first.number == 1 and first.state == "open" and first.head_branch == BRANCH
    assert github.prs[1]["draft"] is True and github.prs[1]["base"]["ref"] == "main" and github.prs[1]["body"] == "body"
    assert forge.create_pr(BRANCH, "main", "other", "other") == first
    assert [m for m, _ in github.writes()] == ["POST"]


def test_ready_uses_graphql_mutation(github, make):
    forge = make()
    forge.create_pr(BRANCH, "main", "t", "b")
    ready = forge.update_pr(1, draft=False)
    assert not ready.draft
    mutation = [b for m, p, _, b in github.requests if p == "/graphql"]
    assert len(mutation) == 1 and "markPullRequestReadyForReview" in mutation[0]["query"]
    assert mutation[0]["variables"] == {"id": "PR_node_1"}
    github.requests.clear()
    assert forge.update_pr(1, draft=False) == ready
    assert github.writes() == []  # already ready: nothing is written
    assert forge.update_pr(1, draft=True).draft  # and back to a draft
    assert "convertPullRequestToDraft" in [b for _, p, _, b in github.requests if p == "/graphql"][0]["query"]


def test_update_pr_title_and_body_only_write_what_differs(github, make):
    forge = make()
    forge.create_pr(BRANCH, "main", "the title", "old")
    updated = forge.update_pr(1, title="new title", body="old")
    assert updated.title == "new title" and github.prs[1]["body"] == "old"
    assert [b for m, _, _, b in github.requests if m == "PATCH"] == [{"title": "new title"}]


def test_graphql_errors_are_reported_without_the_token(github, make):
    forge = make()
    forge.create_pr(BRANCH, "main", "t", "b")
    github.graphql_errors = [{"message": f"Resource not accessible with {TOKEN}"}]
    with pytest.raises(ForgeError) as err:
        forge.update_pr(1, draft=False)
    assert TOKEN not in str(err.value) and "GraphQL" in str(err.value)


def test_graphql_url_of_an_enterprise_host(github):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("/graphql"):
            return httpx.Response(200, json={"data": {}})
        return httpx.Response(200, json=FakeGitHub().add_pr(BRANCH))

    forge = GitHubForge(REPO, TOKEN, api_url="https://ghe.example.test/api/v3", transport=httpx.MockTransport(handler))
    forge.update_pr(1, draft=False)
    assert "https://ghe.example.test/api/graphql" in seen


def test_get_and_find_and_state_mapping(github, make):
    github.add_pr(
        BRANCH, number=5, state="closed", merged=True, merged_at="2026-01-01T00:00:00Z", merge_commit_sha="a" * 40
    )
    github.add_pr("l4/openspec/b", number=6, state="closed", draft=False)
    github.add_pr("l4/openspec/c", number=7, draft=False, labels=[{"name": "l4:in_review"}, {"name": "bug"}])
    forge = make()
    merged = forge.get_pr(5)
    assert (merged.state, merged.merge_commit_sha) == ("merged", "a" * 40)
    assert forge.get_pr(6).state == "closed" and forge.get_pr(6).merge_commit_sha is None
    open_pr = forge.get_pr(7)
    assert (open_pr.state, open_pr.draft, open_pr.labels) == ("open", False, ("l4:in_review", "bug"))
    assert forge.find_pr(BRANCH) is None  # not open any more
    assert forge.find_pr("l4/openspec/c").number == 7
    with pytest.raises(ForgeNotFound):
        forge.get_pr(99)
    assert forge.project_url() == f"https://github.test/{REPO}"


def test_list_prs_filters_prefix_state_and_forks_and_follows_pages(github, make):
    github.page_size = 2
    github.add_pr("l4/openspec/a", number=1)
    github.add_pr("l4/openspec/b", number=2, state="closed", merged=True, merged_at="x")
    github.add_pr("l4/openspec/c", number=3, state="closed")
    github.add_pr("feature/x", number=4)
    github.add_pr("l4/openspec/fork", number=5, repo="mallory/widgets")
    github.add_pr("l4/kiro/d", number=6)
    forge = make()
    assert sorted(p.number for p in forge.list_prs("l4/")) == [1, 2, 3, 6]
    assert [p.number for p in forge.list_prs("l4/openspec/", "merged")] == [2]
    assert [p.number for p in forge.list_prs("l4/openspec/", "closed")] == [3]
    assert sorted(p.number for p in forge.list_prs("l4/", "open")) == [1, 6]
    pages = [params.get("page") for m, p, params, _ in github.requests if p.endswith("/pulls")]
    assert "2" in pages  # the Link header was followed


def test_a_next_link_to_another_host_is_not_followed(github):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=[], headers={"Link": '<https://evil.example/steal>; rel="next"'})

    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=httpx.MockTransport(handler))
    assert forge.list_prs("l4/") == []
    assert len(calls) == 1
    downgraded = GitHubForge(REPO, TOKEN, api_url=API, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=[], headers={"Link": '<http://api.github.test/x?page=2>; rel="next"'})
    ))  # fmt: skip
    assert downgraded.list_prs("l4/") == []


def request_headers_checked(request: httpx.Request) -> None:
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.headers["Accept"] == "application/vnd.github+json" and request.headers["X-GitHub-Api-Version"]


def test_auth_header_and_redirects(github):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_headers_checked(request)
        seen.append(request.url.path)
        return httpx.Response(302, headers={"Location": "https://evil.example/"})

    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=httpx.MockTransport(handler))
    with pytest.raises(ForgeError):
        forge.get_pr(1)
    assert seen == [f"/repos/{REPO}/pulls/1"]  # the redirect was not followed with the token


def test_retry_on_5xx_and_429_and_secondary_rate_limits(github, make):
    github.add_pr(BRANCH)
    forge = make()
    github.fail_next = [httpx.Response(502), httpx.Response(429, headers={"Retry-After": "3"})]
    assert forge.get_pr(1).number == 1
    assert make.sleeps == [1.0, 3.0]
    make.sleeps.clear()
    github.fail_next = [httpx.Response(403, json={"message": "You have exceeded a secondary rate limit."})]
    assert forge.get_pr(1).number == 1 and make.sleeps == [1.0]
    make.sleeps.clear()
    github.fail_next = [httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1030"})]
    forge = make(now=lambda: 1000.0)
    assert forge.get_pr(1).number == 1 and make.sleeps == [30.0]


def test_exhausted_retries_and_plain_403(github, make):
    github.add_pr(BRANCH)
    forge = make()
    github.fail_next = [httpx.Response(429)] * 4
    with pytest.raises(ForgeRateLimited):
        forge.get_pr(1)
    github.fail_next = [httpx.Response(403, json={"message": "Resource not accessible by personal access token"})]
    with pytest.raises(ForgeAuthError) as err:
        forge.get_pr(1)
    assert err.value.status == 403


def test_errors_never_carry_the_token(github):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach host with {TOKEN}", request=request)

    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(ForgeError) as err:
        forge.get_pr(1)
    assert TOKEN not in str(err.value) and "[REDACTED:token]" in str(err.value)
    erroring = GitHubForge(REPO, TOKEN, api_url=API, transport=httpx.MockTransport(
        lambda r: httpx.Response(422, json={"message": f"bad value {TOKEN}"})
    ))  # fmt: skip
    with pytest.raises(ForgeError) as err2:
        erroring.get_pr(1)
    assert TOKEN not in str(err2.value)


def test_constructor_validation():
    for repo in ("noslash", "a/b/c", "../x/y", "owner/"):
        with pytest.raises(ValueError):
            GitHubForge(repo, TOKEN)
    for url in ("http://api.example.com", "https://user:pw@host/", "ftp://x"):
        with pytest.raises(ValueError):
            GitHubForge(REPO, TOKEN, api_url=url)
    GitHubForge(REPO, TOKEN, api_url="http://localhost:8080")


def test_github_has_no_label_events_yet(github, make):
    """M1: GitHub label events are not read, so the `l4:resume` label is never honoured there (it fails closed)."""
    forge = make()
    forge.create_pr(BRANCH, "main", "t", "b")
    assert forge.label_events(1) == []
    assert forge.member_access(7) is None


def test_create_pr_403_names_the_setting(github, make):
    """L4-GHP-002, SCN-GHP-03: a refused pull request says which repository setting allows it."""
    original = github.handle

    def refuse_post(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/pulls"):
            return httpx.Response(
                403, json={"message": "GitHub Actions is not permitted to create or approve pull requests."}
            )
        return original(request)

    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=httpx.MockTransport(refuse_post), sleep=lambda s: None)
    with pytest.raises(ForgeAuthError) as err:
        forge.create_pr(BRANCH, "main", "t", "b")
    message = str(err.value)
    assert err.value.status == 403
    assert "Allow GitHub Actions to create and approve pull requests" in message
    assert "Settings > Actions > General > Workflow permissions" in message
    assert "l4 setup github" in message
    assert TOKEN not in message
