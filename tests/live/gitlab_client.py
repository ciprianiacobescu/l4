"""A read-only view of the dummy repository for the M1.1 acceptance protocol (G13).

Two ways in, both GET-only (there is no method here that writes):
- the Mintkey proxy, the way `scripts/dev/mk-gitlab-api.sh` does it: `list_services` -> the service with the slug
  (default `example-gitlab`) -> `request_token` with `action: call` -> `GET <proxy>/v1/call/<service>/<path>` with the
  brokered JWT. The agent key comes from `MINTKEY_AUTH` (the whole `Authorization` header value) or, failing that,
  from `~/.claude.json` as the script reads it. Neither it nor the JWT is ever printed or stored.
- a direct token: `L4_LIVE_API_URL` (ending in `/api/v4`) and `L4_LIVE_TOKEN` (a read-only token).
The git refs that the REST API cannot show (`refs/l4/locks/*`) are read with `git ls-remote` and a fetch into a scratch
bare repository, authenticated by `L4_FORGE_TOKEN` through the harness' own credential helper, or, when no token
variable is set, by whatever git credentials the operator's machine already has (`L4_LIVE_GIT_TOKEN_ENV` names another
variable, for example one that holds a `read_repository` token).
"""

import json
import os
import subprocess
import tempfile
import time
import zipfile
from collections.abc import Iterator, Mapping
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

TIMEOUT_S = 30.0
RETRY_STATUSES = frozenset({502, 503, 504})
BACKOFF_S = (1.0, 2.0, 4.0)  # a transient proxy error is retried after each of these pauses
PER_PAGE = 100
MAX_PAGES = 50


class LiveUnavailable(Exception):
    """No way to reach the repository was configured: the live tests skip."""


class LiveGitLab:
    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        clock=time.time,
        sleep=time.sleep,
    ) -> None:
        self._env = os.environ if environ is None else environ
        self._transport = transport
        self._clock = clock
        self._sleep = sleep
        self.project = self._env.get("L4_LIVE_PROJECT", "118")
        self._jwt: tuple[str, float] | None = None
        self._service: str | None = None
        if self._env.get("L4_LIVE_API_URL") and self._env.get("L4_LIVE_TOKEN"):
            api, token = self._env["L4_LIVE_API_URL"], self._env["L4_LIVE_TOKEN"]
            self._direct: tuple[str, str] | None = (api.rstrip("/"), token)
        else:
            self._direct = None
            self._auth_header()  # LiveUnavailable now rather than in the middle of a test

    # --- access ---------------------------------------------------------------------------------------------------

    def _auth_header(self) -> str:
        header = self._env.get("MINTKEY_AUTH")
        if header:
            return header
        try:
            config = json.loads((Path(self._env.get("HOME", "~")).expanduser() / ".claude.json").read_text())
            return str(config["mcpServers"]["mintkey"]["headers"]["Authorization"])
        except (OSError, ValueError, KeyError, TypeError):
            raise LiveUnavailable(
                "set MINTKEY_AUTH (the Authorization header of the mintkey MCP server) or L4_LIVE_API_URL and "
                "L4_LIVE_TOKEN"
            ) from None

    def _tools(self) -> str:
        return self._env.get("MINTKEY_URL", "http://localhost:8082").rstrip("/")

    def _proxy(self) -> str:
        return self._env.get("MINTKEY_PROXY_URL", "http://localhost:8000").rstrip("/")

    def _client(self) -> httpx.Client:
        return httpx.Client(transport=self._transport, timeout=TIMEOUT_S, follow_redirects=False)

    def _brokered(self) -> tuple[str, str]:
        """(service id, JWT), refreshed a minute before it expires."""
        if self._jwt is not None and self._service is not None and self._clock() < self._jwt[1] - 60:
            return self._service, self._jwt[0]
        headers = {"Authorization": self._auth_header()}
        slug = self._env.get("L4_LIVE_SERVICE", "example-gitlab")
        with self._client() as client:
            if self._service is None:
                listing = client.get(f"{self._tools()}/v1/tools/list_services", headers=headers)
                listing.raise_for_status()
                found = [s["id"] for s in listing.json().get("services", []) if s.get("slug") == slug]
                if not found:
                    raise LiveUnavailable(f"the Mintkey agent has no service with the slug {slug!r}")
                self._service = found[0]
            reply = client.post(
                f"{self._tools()}/v1/tools/request_token", headers=headers,
                json={"service_id": self._service, "action": "call"},
            )  # fmt: skip
            reply.raise_for_status()
            body = reply.json()
        expires = body.get("expires_at")
        self._jwt = (str(body["token"]), float(expires) if isinstance(expires, int | float) else self._clock() + 540)
        return self._service, self._jwt[0]

    def _request(self, path: str, params: Mapping[str, Any] | None) -> httpx.Response:
        if self._direct is not None:
            base, token = self._direct
            url, headers = f"{base}{path}", {"PRIVATE-TOKEN": token}
        else:
            service, jwt = self._brokered()
            url, headers = f"{self._proxy()}/v1/call/{service}{path}", {"Authorization": f"Bearer {jwt}"}
        with self._client() as client:
            response = client.get(url, params=dict(params or {}), headers=headers)
            for pause in BACKOFF_S:
                if response.status_code not in RETRY_STATUSES:
                    break
                self._sleep(pause)
                response = client.get(url, params=dict(params or {}), headers=headers)
        return response

    # --- reads ----------------------------------------------------------------------------------------------------

    def _project_path(self, tail: str) -> str:
        return f"/projects/{quote(self.project, safe='')}{tail}"

    def get(self, tail: str, **params: Any) -> Any | None:
        """JSON of `GET /projects/<id><tail>`; None for a 404 (the thing does not exist yet)."""
        response = self._request(self._project_path(tail), params)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def text(self, tail: str, **params: Any) -> str | None:
        response = self._request(self._project_path(tail), params)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text

    def pages(self, tail: str, **params: Any) -> Iterator[Any]:
        """Every item of a paged list; nothing for a 404 (the branch or the path does not exist yet), as `get`."""
        for page in range(1, MAX_PAGES + 1):
            response = self._request(self._project_path(tail), {**params, "per_page": PER_PAGE, "page": page})
            if response.status_code == 404:
                return
            response.raise_for_status()
            yield from response.json()
            if not response.headers.get("X-Next-Page"):
                return

    def file(self, path: str, ref: str) -> str | None:
        return self.text(f"/repository/files/{quote(path, safe='')}/raw", ref=ref)

    def tree(self, path: str, ref: str) -> list[str]:
        return [e["path"] for e in self.pages("/repository/tree", path=path, ref=ref) if e["type"] == "blob"]

    def commit(self, sha: str) -> dict[str, Any] | None:
        return self.get(f"/repository/commits/{sha}")

    def commits(self, ref: str, limit: int = 100) -> list[dict[str, Any]]:
        out = []
        for item in self.pages("/repository/commits", ref_name=ref):
            out.append(item)
            if len(out) >= limit:
                break
        return out

    def pipeline_of(self, sha: str) -> dict[str, Any] | None:
        found = self.get("/pipelines", sha=sha, order_by="id", sort="desc")
        return found[0] if found else None

    def jobs(self, pipeline_id: int) -> list[dict[str, Any]]:
        return list(self.pages(f"/pipelines/{pipeline_id}/jobs"))

    def trace(self, job_id: int) -> str:
        return self.text(f"/jobs/{job_id}/trace") or ""

    def artifact_texts(self, job_id: int) -> dict[str, str]:
        """Every text file in the job's artifact archive (the `.l4-out/` directory), by path."""
        response = self._request(self._project_path(f"/jobs/{job_id}/artifacts"), None)
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        out: dict[str, str] = {}
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            for info in archive.infolist():
                if not info.is_dir() and info.file_size <= 5 * 1024 * 1024:
                    out[info.filename] = archive.read(info).decode("utf-8", "replace")
        return out

    def merge_requests(self, **params: Any) -> list[dict[str, Any]]:
        return list(self.pages("/merge_requests", **params))

    def notes(self, iid: int) -> list[dict[str, Any]]:
        return list(self.pages(f"/merge_requests/{iid}/notes"))

    def repo_url(self) -> str:
        info = self.get("") or {}
        return str(info["http_url_to_repo"])


class LiveRemote:
    """The refs the REST API cannot show, through git. With `L4_FORGE_TOKEN` (or the variable `L4_LIVE_GIT_TOKEN_ENV`
    names; any token that can read) the harness' credential helper is used; without one, git falls back to the
    credentials the operator's machine already has (a keychain, a netrc), and never prompts."""

    def __init__(self, url: str, environ: Mapping[str, str] | None = None) -> None:
        from l4.forge.gitlab import git_auth_config
        from l4.vcs.git import Git

        env = dict(os.environ if environ is None else environ)
        token_env = env.get("L4_LIVE_GIT_TOKEN_ENV", "L4_FORGE_TOKEN")
        self.auth: tuple[tuple[str, str], ...] = git_auth_config(token_env) if env.get(token_env) else ()
        self.url = str(httpx.URL(url).copy_with(userinfo=b"oauth2")) if self.auth else url
        self._dir = Path(tempfile.mkdtemp(prefix="l4-live-"))
        subprocess.run(["git", "init", "-q", "--bare", str(self._dir)], check=True, capture_output=True)
        self.git = Git(self._dir, environ=env)

    def refs(self, pattern: str = "refs/l4/locks/*") -> dict[str, str]:
        out = self.git.run("ls-remote", self.url, pattern, config=self.auth).stdout
        return {name: sha for sha, _, name in (line.partition("\t") for line in out.splitlines())}

    def pending_events(self, ref: str) -> list[dict[str, Any]]:
        """Every event of every `ledger-pending/*.jsonl` of a lock ref, in file and line order."""
        self.git.run("fetch", "--quiet", self.url, f"+{ref}:{ref}", config=self.auth)
        listing = self.git.run("ls-tree", "-r", "--name-only", ref).stdout.split()
        events = []
        for name in sorted(n for n in listing if n.startswith("ledger-pending/") and n.endswith(".jsonl")):
            for line in self.git.run("show", f"{ref}:{name}").stdout.splitlines():
                events.append(json.loads(line))
        return events

    def close(self) -> None:
        import shutil

        shutil.rmtree(self._dir, ignore_errors=True)
