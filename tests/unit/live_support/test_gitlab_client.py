import json

import httpx
import pytest

from ...live.gitlab_client import LiveGitLab, LiveRemote, LiveUnavailable

AGENT = "Bearer mk_agent_FAKEKEY0123456789"


def proxy(seen: list[httpx.Request], *, paged: bool = False) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/v1/tools/list_services":
            services = [{"id": "svc_a", "slug": "other"}, {"id": "svc_b", "slug": "example-gitlab"}]
            return httpx.Response(200, json={"services": services})
        if path == "/v1/tools/request_token":
            assert json.loads(request.content) == {"service_id": "svc_b", "action": "call"}
            return httpx.Response(200, json={"token": "JWT-FAKE", "expires_at": 10_000})
        assert path.startswith("/v1/call/svc_b/projects/118/")
        assert request.headers["Authorization"] == "Bearer JWT-FAKE" and "PRIVATE-TOKEN" not in request.headers
        if path.endswith("/merge_requests"):
            page = int(request.url.params["page"])
            more = str(page + 1) if page < 3 and paged else ""
            return httpx.Response(200, json=[{"iid": page}], headers={"X-Next-Page": more})
        return httpx.Response(404, json={"message": "404 Not found"})

    return httpx.MockTransport(handle)


def client(seen, environ=None, **kw) -> LiveGitLab:
    env = {"MINTKEY_AUTH": AGENT, **(environ or {})}
    return LiveGitLab(env, transport=proxy(seen, **kw), clock=lambda: 0.0)


def test_the_brokered_flow_lists_services_then_requests_a_call_token_then_calls_through_the_proxy():
    seen: list[httpx.Request] = []
    gl = client(seen, paged=True)
    assert [m["iid"] for m in gl.merge_requests(state="all")] == [1, 2, 3]
    assert [r.url.path for r in seen][:2] == ["/v1/tools/list_services", "/v1/tools/request_token"]
    assert len([r for r in seen if r.url.path == "/v1/tools/request_token"]) == 1  # one token for the three pages
    assert all(r.method == "GET" for r in seen if r.url.path.startswith("/v1/call/")) is True
    assert seen[0].headers["Authorization"] == AGENT and seen[0].url.host == "localhost" and seen[0].url.port == 8082
    assert seen[2].url.port == 8000


def test_a_missing_resource_is_none_not_an_error():
    assert client([]).get("/repository/commits/abc") is None
    assert client([]).file("openspec/changes/x/tasks.md", "main") is None


def test_a_tree_or_list_of_a_branch_that_does_not_exist_yet_is_empty_not_an_error():
    # GitLab answers 404 for `/repository/tree?ref=<missing branch>`; a live test then skips instead of failing
    assert client([]).tree("openspec/changes/x/.l4/ledger", "l4/openspec/x") == []
    assert client([]).commits("l4/openspec/x") == []


def test_the_token_is_requested_again_a_minute_before_it_expires():
    seen: list[httpx.Request] = []
    now = [0.0]
    gl = LiveGitLab({"MINTKEY_AUTH": AGENT}, transport=proxy(seen), clock=lambda: now[0])
    gl.get("/x")
    now[0] = 9_950.0
    gl.get("/x")
    assert len([r for r in seen if r.url.path == "/v1/tools/request_token"]) == 2


def test_a_direct_token_sends_private_token_to_the_api_url():
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    gl = LiveGitLab(
        {"L4_LIVE_API_URL": "https://gl.example.test/api/v4/", "L4_LIVE_TOKEN": "glpat-FAKE"},
        transport=httpx.MockTransport(handle),
    )
    assert gl.get("/x") == {"ok": True}
    assert str(seen[0].url) == "https://gl.example.test/api/v4/projects/118/x"
    assert seen[0].headers["PRIVATE-TOKEN"] == "glpat-FAKE"


def test_without_any_credential_the_live_tests_skip(tmp_path):
    with pytest.raises(LiveUnavailable):
        LiveGitLab({"HOME": str(tmp_path)})


def test_the_client_has_no_method_that_writes():
    names = {n for n in dir(LiveGitLab) if not n.startswith("_")}
    assert not names & {"post", "put", "delete", "patch", "create", "update", "merge", "close"}


def flaky(failures: int, status: int = 502) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.startswith("/v1/tools/"):
            return proxy([]).handle_request(request)
        calls = [r for r in seen if r.url.path.startswith("/v1/call/")]
        if len(calls) <= failures:
            return httpx.Response(status, text="Bad Gateway")
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handle), seen


def test_a_transient_proxy_5xx_is_retried_with_a_backoff():
    transport, seen = flaky(2)
    pauses: list[float] = []
    gl = LiveGitLab({"MINTKEY_AUTH": AGENT}, transport=transport, clock=lambda: 0.0, sleep=pauses.append)
    assert gl.get("/x") == {"ok": True}
    assert len([r for r in seen if r.url.path.startswith("/v1/call/")]) == 3
    assert len(pauses) == 2 and pauses[0] < pauses[1]


def test_a_persistent_5xx_still_fails_after_the_retries():
    transport, seen = flaky(99, status=503)
    gl = LiveGitLab({"MINTKEY_AUTH": AGENT}, transport=transport, clock=lambda: 0.0, sleep=lambda s: None)
    with pytest.raises(httpx.HTTPStatusError):
        gl.get("/x")
    assert len([r for r in seen if r.url.path.startswith("/v1/call/")]) == 4


def test_a_4xx_is_not_retried():
    transport, seen = flaky(99, status=403)
    gl = LiveGitLab({"MINTKEY_AUTH": AGENT}, transport=transport, clock=lambda: 0.0, sleep=lambda s: None)
    with pytest.raises(httpx.HTTPStatusError):
        gl.get("/x")
    assert len([r for r in seen if r.url.path.startswith("/v1/call/")]) == 1


def test_the_remote_without_a_token_uses_the_operators_own_git_credentials():
    remote = LiveRemote("https://gl.example.test/g/p.git", {"PATH": "/usr/bin:/bin"})
    try:
        assert remote.url == "https://gl.example.test/g/p.git" and remote.auth == ()
    finally:
        remote.close()


def test_the_remote_with_a_token_resets_the_helpers_and_names_the_variable_not_its_value():
    env = {"PATH": "/usr/bin:/bin", "L4_FORGE_TOKEN": "glpat-FAKE0123"}
    remote = LiveRemote("https://gl.example.test/g/p.git", env)
    try:
        assert remote.url.startswith("https://oauth2@") and ("credential.helper", "") in remote.auth
        assert "glpat-FAKE0123" not in repr(remote.auth)
    finally:
        remote.close()
