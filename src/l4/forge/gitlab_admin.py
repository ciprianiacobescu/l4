"""The GitLab REST client of `l4 setup gitlab` and `l4 ci watch` (M1.8 A10): the maintainer's credential, a few calls.

Not `GitLabForge`: that one holds the harness bot's token and the project of a run; this one holds a credential that
can create tokens, so it is smaller and stricter. https, or plain http to a loopback host (the Mintkey proxy); redirects
are never followed (the credential must not leave the host it was meant for); every message that leaves this module has
the credential and every secret added with `add_secret` cut out; request headers and response bodies are not logged.
`history` records (method, path) of every request, for tests and the audit of "a second run sends only GETs".
"""

import re
from collections.abc import Callable
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

TIMEOUT_S = 30.0
MAX_PAGES = 100
PER_PAGE = 100
MAX_BODY = 300
NOT_JSON = "the answer is not JSON (is the API base the GitLab API, ending in /api/v4?)"
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
_SPACES = re.compile(r"\s+")


class AdminError(Exception):
    """A call that did not succeed. `status` is the HTTP status, 0 when none arrived (a transport error)."""

    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        self.method, self.path, self.status, self.body = method, path, status, body
        what = f"HTTP {status}" if status else "no answer"
        super().__init__(f"{method} {path}: {what}" + (f": {body}" if body else ""))


class RefreshFailed(Exception):
    """A `refresh` callable could not produce a new credential. The message is shown, so it must never carry the
    command's output or a credential."""


def checked_base(base: str) -> str:
    parts = urlsplit(base)
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in _LOOPBACK):
        raise ValueError("the GitLab API base must be https (plain http only for localhost)")
    if not parts.hostname or parts.username or parts.password:
        raise ValueError("the GitLab API base needs a host and must not carry credentials")
    return base.rstrip("/")


class AdminApi:
    def __init__(
        self,
        base: str,
        credential: str,
        *,
        scheme: Literal["private-token", "bearer"] = "private-token",
        transport: httpx.BaseTransport | None = None,
        refresh: Callable[[], str] | None = None,
    ) -> None:
        """`refresh`: a new credential when a request is answered with 401 (a short-lived one, such as the Mintkey
        wrapper's JWT, ran out). It is asked once per request, the request is sent again once, and a second 401
        raises as before. A request that got a 401 did not land, so a POST is sent again too."""
        self.base = checked_base(base)
        self._scheme = scheme
        self._credential = credential
        self._header = self._header_for(credential)
        self._refresh = refresh
        self._transport = transport
        self._secrets = [credential]
        self.history: list[tuple[str, str]] = []

    def _header_for(self, credential: str) -> tuple[str, str]:
        return (
            ("PRIVATE-TOKEN", credential)
            if self._scheme == "private-token"
            else ("Authorization", f"Bearer {credential}")
        )

    def add_secret(self, value: str) -> None:
        """A value (a token just created, a variable's value) that no message may carry."""
        if value and value not in self._secrets:
            self._secrets.append(value)

    def _scrub(self, text: str) -> str:
        for secret in self._secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return text

    def _send(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None
    ) -> httpx.Response:
        response = self._attempt(method, path, params, json)
        if response.status_code == 401 and self._refresh is not None:
            self._renew(method, path, response)
            response = self._attempt(method, path, params, json)
        if response.is_success:
            return response
        raise AdminError(method, path, response.status_code, self._scrub(self._detail(response)))

    def _renew(self, method: str, path: str, refused: httpx.Response) -> None:
        """Ask for a new credential after a 401. Any failure re-raises that 401 with the reason and nothing the
        command printed."""
        assert self._refresh is not None
        reason = ""
        try:
            fresh = self._refresh().strip()
            reason = "" if fresh else "token command failed (no output)"
        except RefreshFailed as exc:
            fresh, reason = "", str(exc)
        if reason:
            detail = self._scrub(self._detail(refused))
            raise AdminError(method, path, 401, f"{detail}; {reason}" if detail else reason)
        self._credential = fresh
        self._header = self._header_for(fresh)
        self.add_secret(fresh)

    def _attempt(self, method: str, path: str, params: dict[str, Any] | None, json: Any) -> httpx.Response:
        self.history.append((method, path))
        url = f"{self.base}/{path.lstrip('/')}"
        headers = {self._header[0]: self._header[1], "Accept": "application/json"}
        try:
            with httpx.Client(transport=self._transport, timeout=TIMEOUT_S, follow_redirects=False) as client:
                response = client.request(method, url, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise AdminError(method, path, 0, self._scrub(type(exc).__name__)) from None
        return response

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            body = response.json()
            text = body.get("message") or body.get("error") if isinstance(body, dict) else None
            raw = str(text) if text else ""
        except ValueError:
            raw = response.text
        return _SPACES.sub(" ", raw).strip()[:MAX_BODY]

    @staticmethod
    def _json(method: str, path: str, response: httpx.Response) -> Any:
        """The body as JSON. A body that is not (a login page, a web URL given as the API base) is an `AdminError`
        naming the request, like an HTTP error, so the command reports it as one."""
        try:
            return response.json()
        except ValueError:
            raise AdminError(method, path, response.status_code, NOT_JSON) from None

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._json("GET", path, self._send("GET", path, params=params))

    def get_text(self, path: str, params: dict[str, Any] | None = None) -> str:
        return self._send("GET", path, params=params).text

    def get_paged(self, path: str, params: dict[str, Any] | None = None) -> list[Any]:
        items: list[Any] = []
        page = 1
        for _ in range(MAX_PAGES):
            response = self._send("GET", path, params={**(params or {}), "per_page": PER_PAGE, "page": page})
            found = self._json("GET", path, response)
            if not isinstance(found, list):
                raise AdminError("GET", path, response.status_code, "the answer is not a list")
            items.extend(found)
            following = response.headers.get("X-Next-Page", "")
            if not following.isdigit() or int(following) <= page:
                break
            page = int(following)
        return items

    def post(self, path: str, body: Any = None) -> Any:
        response = self._send("POST", path, json=body)
        return self._json("POST", path, response) if response.content else None

    def put(self, path: str, body: Any = None) -> Any:
        response = self._send("PUT", path, json=body)
        return self._json("PUT", path, response) if response.content else None

    def delete(self, path: str) -> None:
        self._send("DELETE", path)
