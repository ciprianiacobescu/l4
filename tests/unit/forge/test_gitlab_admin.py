"""`AdminApi`: the small GitLab client of `l4 setup gitlab` and `l4 ci watch` (M1.8 A10)."""

import httpx
import pytest

from l4.forge.gitlab_admin import AdminApi, AdminError

CRED = "glpat-ADMIN0123456789abcdefXYZ"
BASE = "https://gitlab.example.test/api/v4"


def api(handler, *, base: str = BASE, scheme: str = "private-token", cred: str = CRED, **kw) -> AdminApi:
    return AdminApi(base, cred, scheme=scheme, transport=httpx.MockTransport(handler), **kw)  # type: ignore[arg-type]


def test_private_token_and_bearer_headers():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    assert api(handler).get("projects/1") == {"ok": True}
    assert api(handler, scheme="bearer").get("projects/1") == {"ok": True}
    assert seen[0].headers["PRIVATE-TOKEN"] == CRED and "authorization" not in seen[0].headers
    assert seen[1].headers["Authorization"] == f"Bearer {CRED}" and "private-token" not in seen[1].headers
    assert str(seen[0].url) == f"{BASE}/projects/1"


def test_http_error_names_the_status_never_the_credential():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": f"403 Forbidden for token {CRED}"})

    with pytest.raises(AdminError) as err:
        api(handler).get("projects/1/runners")
    assert err.value.status == 403 and err.value.method == "GET" and err.value.path == "projects/1/runners"
    assert CRED not in str(err.value) and "403" in str(err.value) and "[REDACTED]" in str(err.value)
    assert len(err.value.body) <= 300


def test_a_secret_added_later_is_cut_out_too():
    secret = "glpat-BOTTOKEN0123456789abcdef"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=f"bad value {secret}")

    client = api(handler)
    client.add_secret(secret)
    with pytest.raises(AdminError) as err:
        client.post("projects/1/variables", {"key": "A", "value": secret})
    assert secret not in str(err.value) and secret not in err.value.body


def test_redirect_is_not_followed():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example.test/steal"})

    with pytest.raises(AdminError) as err:
        api(handler).get("projects/1")
    assert err.value.status == 302 and calls == [f"{BASE}/projects/1"]  # the credential never left the host


def test_pagination_follows_x_next_page():
    pages = {"1": ([{"n": 1}, {"n": 2}], "2"), "2": ([{"n": 3}], "")}
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "1")
        seen.append(page)
        body, following = pages[page]
        return httpx.Response(200, json=body, headers={"X-Next-Page": following})

    assert [i["n"] for i in api(handler).get_paged("projects/1/variables")] == [1, 2, 3] and seen == ["1", "2"]


def test_pagination_stops_if_the_server_repeats_a_page():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"n": 1}], headers={"X-Next-Page": "1"})

    assert api(handler).get_paged("projects/1/variables") == [{"n": 1}]


@pytest.mark.parametrize(
    ("base", "ok"),
    [
        ("https://gitlab.example.test/api/v4", True),
        ("http://localhost:8000/v1/call/svc_1", True),
        ("http://127.0.0.1:8000/v1/call/svc_1", True),
        ("http://[::1]:8000/x", True),
        ("http://gitlab.example.test/api/v4", False),
        ("ftp://gitlab.example.test/api/v4", False),
        ("https://user:pw@gitlab.example.test/api/v4", False),
        ("gitlab.example.test/api/v4", False),
    ],
)
def test_plain_http_only_to_loopback(base, ok):
    if ok:
        AdminApi(base, CRED)
    else:
        with pytest.raises(ValueError):
            AdminApi(base, CRED)


def test_post_put_delete_send_json_and_return_the_body_or_none():
    seen: list[tuple[str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append((request.method, json.loads(request.content) if request.content else None))
        return httpx.Response(204) if request.method == "DELETE" else httpx.Response(201, json={"id": 5})

    client = api(handler)
    assert client.post("p", {"a": 1}) == {"id": 5} and client.put("p", {"b": 2}) == {"id": 5}
    assert client.delete("p") is None
    assert seen == [("POST", {"a": 1}), ("PUT", {"b": 2}), ("DELETE", None)]
    assert [m for m, _ in client.history] == ["POST", "PUT", "DELETE"]  # the audit of what was sent


def test_a_transport_error_is_an_admin_error_without_a_status():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect with {CRED}")

    with pytest.raises(AdminError) as err:
        api(handler).get("projects/1")
    assert err.value.status == 0 and CRED not in str(err.value)


def test_get_text_returns_the_raw_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="include:\n  - local: x\n")

    assert api(handler).get_text("projects/1/repository/files/a/raw", {"ref": "main"}) == "include:\n  - local: x\n"


def test_an_answer_that_is_not_json_is_an_admin_error_that_names_the_call():
    """A login page or a web URL given as the API base answers 200 with HTML: an `AdminError` naming the request (so
    `setup gitlab` prints an ERROR row and its summary), never a bare JSONDecodeError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>Sign in</html>")

    client = api(handler)
    calls = {
        "GET projects/1": lambda: client.get("projects/1"),
        "GET projects/1/runners": lambda: client.get_paged("projects/1/runners"),
        "POST projects/1/pipeline": lambda: client.post("projects/1/pipeline", {"ref": "main"}),
        "PUT projects/1/variables/A": lambda: client.put("projects/1/variables/A", {"value": "x"}),
    }
    for name, call in calls.items():
        with pytest.raises(AdminError) as err:
            call()
        assert str(err.value).startswith(f"{name}: HTTP 200") and "not JSON" in str(err.value), str(err.value)
        assert "/api/v4" in str(err.value)


def test_a_page_that_is_not_a_list_is_an_admin_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": "proxy says no"})

    with pytest.raises(AdminError) as err:
        api(handler).get_paged("projects/1/variables")
    assert err.value.path == "projects/1/variables" and "not a list" in str(err.value)


# --- M1.10 line 21 (C8): a 401 refreshes the credential once and retries the request ---

NEW = "glpat-REFRESHED0123456789abcdef"


class Server:
    """Accepts one credential at a time: the one it was told, and answers 401 to any other."""

    def __init__(self, accepts: str, body: str = "{}") -> None:
        self.accepts, self.body, self.seen = accepts, body, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("PRIVATE-TOKEN")
        self.seen.append((request.method, str(request.url.path), token))
        if token != self.accepts:
            return httpx.Response(401, json={"message": f"401 Unauthorized: {token}"})
        return httpx.Response(200, content=self.body)


def test_a_401_refreshes_once_and_retries():
    server, calls = Server(NEW, '{"ok": true}'), []

    def refresh() -> str:
        calls.append(1)
        return NEW

    client = api(server, refresh=refresh)
    assert client.get("projects/1") == {"ok": True}
    assert len(calls) == 1 and [s[2] for s in server.seen] == [CRED, NEW]  # one 401, one retry with the new value
    assert client.post("projects/1/variables", {"key": "A"}) == {"ok": True}  # the next request uses the new one
    assert len(calls) == 1 and server.seen[-1][2] == NEW
    assert client.history == [("GET", "projects/1"), ("GET", "projects/1"), ("POST", "projects/1/variables")]


def test_a_post_that_got_a_401_did_not_land_and_is_retried():
    server = Server(NEW)
    client = api(server, refresh=lambda: NEW)
    client.post("projects/1/variables", {"key": "A"})
    assert [(m, t) for m, _, t in server.seen] == [("POST", CRED), ("POST", NEW)]


def test_a_second_401_raises():
    server, calls = Server("some-other-credential"), []

    def refresh() -> str:
        calls.append(1)
        return NEW

    with pytest.raises(AdminError) as err:
        api(server, refresh=refresh).get("projects/1")
    assert err.value.status == 401 and len(calls) == 1 and len(server.seen) == 2  # one refresh, one retry, then raise


def test_the_new_credential_is_scrubbed_from_errors():
    server = Server("some-other-credential")  # its 401 body echoes the token it was sent
    with pytest.raises(AdminError) as err:
        api(server, refresh=lambda: NEW).get("projects/1")
    assert NEW not in str(err.value) and NEW not in err.value.body and CRED not in str(err.value)
    assert "[REDACTED]" in err.value.body


def test_a_refresh_that_fails_reraises_the_401_with_the_reason_only():
    from l4.forge.gitlab_admin import RefreshFailed

    def refresh() -> str:
        raise RefreshFailed("token command failed (exit 3)")

    with pytest.raises(AdminError) as err:
        api(Server(NEW), refresh=refresh).get("projects/1")
    assert err.value.status == 401 and "token command failed (exit 3)" in str(err.value)
    empty = api(Server(NEW), refresh=lambda: "")
    with pytest.raises(AdminError) as err2:
        empty.get("projects/1")
    assert err2.value.status == 401 and "token command failed (no output)" in str(err2.value)


def test_without_a_refresh_a_401_raises_at_once():
    server = Server(NEW)
    with pytest.raises(AdminError) as err:
        api(server).get("projects/1")
    assert err.value.status == 401 and len(server.seen) == 1
