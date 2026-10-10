import httpx
import pytest

from l4.exitcodes import ExitCode
from l4.forge.base import ForgeAuthError, ForgeError, ForgeNotFound, ForgeRateLimited
from l4.forge.gitlab import GitLabForge

from .conftest import API, TOKEN, FakeGitLab


def test_429_retries_then_succeeds(gitlab: FakeGitLab, make_forge_client):
    sleeps: list[float] = []
    gitlab.fail_next = [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(503)]
    forge = make_forge_client(sleeps=sleeps)
    assert forge.find_pr("l4/openspec/x") is None
    assert len(gitlab.requests) == 3
    assert sleeps[0] == 7  # Retry-After is honoured
    assert 0 < sleeps[1] <= 60  # no header: a backoff


def test_retries_stop_after_three_and_say_rate_limited(gitlab: FakeGitLab, make_forge_client):
    gitlab.fail_next = [httpx.Response(429)] * 9
    forge = make_forge_client()
    with pytest.raises(ForgeRateLimited):
        forge.find_pr("b")
    assert len(gitlab.requests) == 4  # the first try and three retries


def test_5xx_after_retries_is_a_forge_error(gitlab: FakeGitLab, make_forge_client):
    gitlab.fail_next = [httpx.Response(502)] * 9
    with pytest.raises(ForgeError) as err:
        make_forge_client().find_pr("b")
    assert err.value.status == 502 and err.value.code == ExitCode.INTERNAL_ERROR


def test_a_transport_error_is_retried_too(make_forge_client):
    calls = []

    def flaky(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json=[])

    forge = GitLabForge(API, "118", TOKEN, transport=httpx.MockTransport(flaky), sleep=lambda s: None)
    assert forge.find_pr("b") is None and len(calls) == 2


def test_pagination_follows_x_next_page(gitlab: FakeGitLab, make_forge_client):
    gitlab.labels = [f"l{i}" for i in range(5)]
    gitlab.label_page_size = 2
    forge = make_forge_client()
    assert forge.label_names() == gitlab.labels
    pages = [q["page"] for m, p, q, _ in gitlab.requests if p.endswith("/labels")]
    assert pages == ["1", "2", "3"]


def test_pagination_stops_if_the_server_repeats_a_page(make_forge_client):
    def stuck(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"name": "a"}], headers={"X-Next-Page": "1"})

    forge = GitLabForge(API, "118", TOKEN, transport=httpx.MockTransport(stuck), sleep=lambda s: None)
    assert forge.label_names() == ["a"]


@pytest.mark.parametrize(
    ("status", "error"), [(401, ForgeAuthError), (403, ForgeAuthError), (404, ForgeNotFound), (422, ForgeError)]
)
def test_status_maps_to_the_error_tree(status: int, error: type[ForgeError], gitlab: FakeGitLab, make_forge_client):
    gitlab.fail_next = [httpx.Response(status, json={"message": "nope"})]
    with pytest.raises(error):
        make_forge_client().find_pr("b")


def test_auth_errors_are_exit_3(gitlab: FakeGitLab, make_forge_client):
    gitlab.fail_next = [httpx.Response(401, json={"message": "401 Unauthorized"})]
    with pytest.raises(ForgeAuthError) as err:
        make_forge_client().find_pr("b")
    assert err.value.code == ExitCode.DOCTOR_FAILED


def test_token_never_in_error_message(gitlab: FakeGitLab, make_forge_client):
    gitlab.fail_next = [httpx.Response(401, json={"message": f"bad token {TOKEN}"})]
    with pytest.raises(ForgeAuthError) as err:
        make_forge_client().find_pr("b")
    assert TOKEN not in str(err.value) and TOKEN not in repr(err.value)


def test_token_not_in_a_transport_error_message():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.headers['PRIVATE-TOKEN']}")

    forge = GitLabForge(API, "118", TOKEN, transport=httpx.MockTransport(boom), sleep=lambda s: None)
    with pytest.raises(ForgeError) as err:
        forge.find_pr("b")
    assert TOKEN not in str(err.value)


def test_a_redirect_is_not_followed(make_forge_client):
    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://elsewhere.example/x"})

    forge = GitLabForge(API, "118", TOKEN, transport=httpx.MockTransport(redirect), sleep=lambda s: None)
    with pytest.raises(ForgeError):
        forge.find_pr("b")


def test_the_project_path_is_url_encoded():
    seen = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode())
        return httpx.Response(200, json=[])

    forge = GitLabForge(
        API, "example-group/dummy-agentic", TOKEN, transport=httpx.MockTransport(record), sleep=lambda s: None
    )
    forge.find_pr("b")
    assert seen[0].startswith("/api/v4/projects/example-group%2Fdummy-agentic/merge_requests")


@pytest.mark.parametrize(
    "url",
    ["http://gitlab.example.test/api/v4", "ftp://x/api/v4", "https://u:p@gitlab.example.test/api/v4", "gitlab", ""],
)
def test_an_unsafe_api_url_is_refused(url: str):
    with pytest.raises(ValueError):
        GitLabForge(url, "118", TOKEN)


def test_plain_http_is_allowed_only_for_loopback():
    GitLabForge("http://127.0.0.1:8080/api/v4", "118", TOKEN)
    GitLabForge("http://localhost/api/v4", "118", TOKEN)
