"""A stateful stand-in for the GitLab REST v4 endpoints `l4 setup gitlab` and `l4 ci watch` use, behind
`httpx.MockTransport`. No live call is ever made by these tests."""

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from urllib.parse import parse_qs, quote, unquote

import httpx
import pytest

MAINTAINER = "glpat-MAINTAINER0123456789abcd"
HOST = "https://gitlab.example.test"
API = f"{HOST}/api/v4"
PATH = "example-group/sample-consumer"
INCLUDE_FILE = ".l4/ci/l4.gitlab-ci.yml"
GOOD_CI = f"include:\n  - local: {INCLUDE_FILE}\ntest:\n  stage: test\n  tags: [agentic]\n  script: [pytest]\n"


def runner(rid: int, kind: str, *, online: bool = True, description: str = "", tags: list[str] | None = None) -> dict:
    found = {
        "id": rid, "description": description or f"runner{rid}", "runner_type": kind, "active": True,
        "online": online, "status": "online" if online else "offline", "is_shared": kind == "instance_type",
    }  # fmt: skip
    return {**found, "tag_list": tags} if tags is not None else found


@dataclass
class FakeGitLab:
    pid: int = 119
    path: str = PATH
    visibility: str = "private"
    default_branch: str = "main"
    shared_runners_enabled: bool = True
    runners: list[dict] = field(default_factory=lambda: [runner(12, "instance_type", description="l4-runner")])
    tokens: list[dict] = field(default_factory=list)
    variables: list[dict] = field(default_factory=list)
    schedules: list[dict] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=lambda: {".gitlab-ci.yml": GOOD_CI, INCLUDE_FILE: "l4: {}\n"})
    pipelines: list[dict] = field(default_factory=list)
    jobs: dict[int, list[dict]] = field(default_factory=dict)  # pipeline id -> jobs
    finishing: list[int] = field(default_factory=list)  # triggered pipelines that end at their first poll
    traces: dict[int, str] = field(default_factory=dict)  # job id -> trace text
    deny: set[str] = field(default_factory=set)  # "runners", "schedules": answer 403
    files_ref: str | None = None  # the branch the files are read on; None: the default branch
    issued: list[str] = field(default_factory=list)  # every bot token value ever created
    requests: list[dict] = field(default_factory=list)
    next_id: int = 1000
    page_size: int = 100
    scheme: str = "private-token"
    credential: str = MAINTAINER
    reject_bot: bool = False  # a new token that cannot read the project (the verification fails)
    pipeline_status: str = "success"  # what a triggered pipeline turns out to be (it is finished at the first poll)

    # --- plumbing ---------------------------------------------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def writes(self) -> list[tuple[str, str]]:
        return [(r["method"], r["path"]) for r in self.requests if r["method"] != "GET"]

    def gets(self) -> list[tuple[str, str]]:
        return [(r["method"], r["path"]) for r in self.requests if r["method"] == "GET"]

    def fresh_id(self) -> int:
        self.next_id += 1
        return self.next_id

    def project_ref(self) -> list[str]:
        return [str(self.pid), quote(self.path, safe="")]

    def authorised(self, request: httpx.Request) -> str | None:
        """'maintainer', 'bot' or None. The maintainer may come with either scheme (a proxy takes a bearer JWT); the
        bot token only as PRIVATE-TOKEN, to the real server."""
        bearer = request.headers.get("authorization", "")
        bearer = bearer.removeprefix("Bearer ") if bearer.startswith("Bearer ") else ""
        private = request.headers.get("private-token", "")
        assert not (bearer and private), "one credential per request"
        if self.scheme == "bearer" and request.url.host == "localhost":
            assert private == "" and bearer == self.credential, "the proxy takes the bearer credential"
        if bearer == self.credential or private == self.credential:
            return "maintainer"
        if private in self.issued and not self.revoked(private) and not self.reject_bot:
            return "bot"
        return None

    def revoked(self, value: str) -> bool:
        return any(t.get("_value") == value and t.get("revoked") for t in self.tokens)

    def handle(self, request: httpx.Request) -> httpx.Response:
        raw = request.url.raw_path.decode()
        path, _, _ = raw.partition("?")
        for prefix in ("/v1/call/svc_1",):  # the Mintkey proxy form of the same API
            path = path.removeprefix(prefix) if path.startswith(prefix) else path
            if path.startswith("/projects"):
                path = "/api/v4" + path
        query = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        body = json.loads(request.content) if request.content else None
        self.requests.append(
            {"method": request.method, "path": unquote(path).removeprefix("/api/v4"), "raw": path, "query": query,
             "body": body, "who": self.authorised(request)}
        )  # fmt: skip
        who = self.requests[-1]["who"]
        if who is None:
            return httpx.Response(401, json={"message": "401 Unauthorized"})
        return self.route(request.method, path.removeprefix("/api/v4"), query, body, who)

    def route(self, method: str, raw: str, query: dict, body: Any, who: str) -> httpx.Response:
        single = re.fullmatch(r"/runners/(\d+)", raw)
        if single is not None and method == "GET":  # one runner, with its tag_list (the project's list omits it)
            if "runner-details" in self.deny:
                return httpx.Response(403, json={"message": "403 Forbidden"})
            found = next((r for r in self.runners if r["id"] == int(single[1])), None)
            if found is None:
                return httpx.Response(404, json={"message": "404 Runner Not Found"})
            return httpx.Response(200, json={"run_untagged": False, "tag_list": ["agentic"], **found})
        match = re.fullmatch(r"/projects/([^/]+)(/.*)?", raw)
        if match is None:
            return httpx.Response(404, json={"message": "404 Not Found"})
        if match[1] not in self.project_ref():
            return httpx.Response(404, json={"message": "404 Project Not Found"})
        rest = match[2] or ""
        if rest == "" and method == "GET":
            return httpx.Response(200, json=self.project_json())
        if who != "maintainer":
            return httpx.Response(403, json={"message": "403 Forbidden"})
        for name, handler in (
            ("runners", self.runners_route), ("repository/files", self.files_route),
            ("access_tokens", self.tokens_route), ("variables", self.variables_route),
            ("pipeline_schedules", self.schedules_route), ("pipelines", self.pipelines_route),
            ("pipeline", self.trigger_route), ("jobs", self.jobs_route),
        ):  # fmt: skip
            if rest == f"/{name}" or rest.startswith(f"/{name}/"):
                return handler(method, rest.removeprefix(f"/{name}"), query, body)
        return httpx.Response(404, json={"message": "404 Not Found"})

    def project_json(self) -> dict:
        return {
            "id": self.pid, "path_with_namespace": self.path, "visibility": self.visibility,
            "default_branch": self.default_branch, "shared_runners_enabled": self.shared_runners_enabled,
            "web_url": f"{HOST}/{self.path}",
        }  # fmt: skip

    def paged(self, items: list, query: dict) -> httpx.Response:
        page, size = int(query.get("page", "1")), min(int(query.get("per_page", "20")), self.page_size)
        more = page * size < len(items)
        return httpx.Response(
            200, json=items[(page - 1) * size : page * size], headers={"X-Next-Page": str(page + 1) if more else ""}
        )

    # --- endpoints --------------------------------------------------------------------------------------------

    def runners_route(self, method: str, rest: str, query: dict, body: Any) -> httpx.Response:
        if "runners" in self.deny:
            return httpx.Response(403, json={"message": "403 Forbidden"})
        wanted = [t for t in query.get("tag_list", "").split(",") if t]
        found = [r for r in self.runners if all(t in r.get("tag_list", ["agentic"]) for t in wanted)]
        return self.paged([{k: v for k, v in r.items() if k != "tag_list"} for r in found], query)

    def files_route(self, method: str, rest: str, query: dict, body: Any) -> httpx.Response:
        name = unquote(rest.removeprefix("/").removesuffix("/raw"))
        assert query.get("ref") == (self.files_ref or self.default_branch)
        if name not in self.files:
            return httpx.Response(404, json={"message": "404 File Not Found"})
        return httpx.Response(200, text=self.files[name])

    def tokens_route(self, method: str, rest: str, query: dict, body: Any) -> httpx.Response:
        if method == "GET":
            return self.paged([{k: v for k, v in t.items() if not k.startswith("_")} for t in self.tokens], query)
        if method == "POST":
            tid = self.fresh_id()
            value = f"glpat-BOTTOKEN{tid:08d}abcdefghijkl"
            token = {
                "id": tid, "name": body["name"], "scopes": body["scopes"], "access_level": body["access_level"],
                "expires_at": body["expires_at"], "user_id": 90 + tid, "active": True, "revoked": False,
                "_value": value,
            }  # fmt: skip
            self.tokens.append(token)
            self.issued.append(value)
            return httpx.Response(201, json={**{k: v for k, v in token.items() if k != "_value"}, "token": value})
        if method == "DELETE":
            tid = int(rest.removeprefix("/"))
            token = next((t for t in self.tokens if t["id"] == tid), None)
            if token is None:
                return httpx.Response(404, json={"message": "404 Not Found"})
            token.update(revoked=True, active=False)
            return httpx.Response(204)
        return httpx.Response(405)

    def find_variable(self, key: str, scope: str) -> dict | None:
        return next((v for v in self.variables if v["key"] == key and v["environment_scope"] == scope), None)

    def variables_route(self, method: str, rest: str, query: dict, body: Any) -> httpx.Response:
        if method == "GET" and rest == "":
            return self.paged(self.variables, query)
        if method == "POST":
            if self.find_variable(body["key"], body.get("environment_scope", "*")):
                return httpx.Response(400, json={"message": {"key": ["has already been taken"]}})
            self.variables.append({"environment_scope": "*", "masked": False, "protected": False, "raw": False, **body})
            return httpx.Response(201, json={k: v for k, v in body.items() if k != "value"})
        if method == "PUT":
            key = rest.removeprefix("/")
            scope = query.get("filter[environment_scope]", "*")
            existing = self.find_variable(key, scope)
            if existing is None:
                return httpx.Response(404, json={"message": "404 Variable Not Found"})
            existing.update(body)
            return httpx.Response(200, json={k: v for k, v in existing.items() if k != "value"})
        return httpx.Response(405)

    def schedules_route(self, method: str, rest: str, query: dict, body: Any) -> httpx.Response:
        if "schedules" in self.deny:
            return httpx.Response(403, json={"message": "403 Forbidden"})
        if method == "GET":
            return self.paged(self.schedules, query)
        if method == "POST":
            schedule = {"id": self.fresh_id(), "active": True, "cron_timezone": "UTC", **body}
            schedule["ref"] = f"refs/heads/{body['ref']}"  # GitLab answers either form; both are normalised
            self.schedules.append(schedule)
            return httpx.Response(201, json=schedule)
        if method == "PUT":
            sid = int(rest.removeprefix("/"))
            schedule = next(s for s in self.schedules if s["id"] == sid)
            for key, value in body.items():
                schedule[key] = f"refs/heads/{value}" if key == "ref" else value
            return httpx.Response(200, json=schedule)
        return httpx.Response(405)

    def trigger_route(self, method: str, rest: str, query: dict, body: Any) -> httpx.Response:
        assert method == "POST" and rest == ""
        pipeline = {
            "id": self.fresh_id(), "status": "created", "ref": body["ref"], "source": "api",
            "web_url": f"{HOST}/{self.path}/-/pipelines/{self.next_id}", "variables": body.get("variables", []),
        }  # fmt: skip
        self.pipelines.append(pipeline)
        ok = self.pipeline_status == "success"
        job_id = self.fresh_id()
        pipeline["status"] = "created"  # the answer to the trigger; the first poll finds the end
        self.jobs[pipeline["id"]] = [
            {"id": job_id, "name": "l4", "stage": ".post", "status": "success" if ok else "failed",
             "allow_failure": False, "runner": {"id": 12, "description": "l4-runner"}},
        ]  # fmt: skip
        self.traces[job_id] = "\n".join(["doctor --ci --adoption", "GATE-001 fail: 2 tests fail at the base", "exit 3"])
        self.finishing.append(pipeline["id"])
        return httpx.Response(201, json=pipeline)

    def pipelines_route(self, method: str, rest: str, query: dict, body: Any) -> httpx.Response:
        if rest == "":
            found = [p for p in reversed(self.pipelines) if query.get("ref") in (None, p["ref"])]
            return self.paged(found, query)
        match = re.fullmatch(r"/(\d+)(/jobs)?", rest)
        assert match, rest
        pipeline = next((p for p in self.pipelines if p["id"] == int(match[1])), None)
        if pipeline is None:
            return httpx.Response(404, json={"message": "404 Not Found"})
        if pipeline["id"] in self.finishing and not match[2]:  # a triggered pipeline ends at its first poll
            pipeline["status"] = self.pipeline_status
        if match[2]:
            return self.paged(self.jobs.get(pipeline["id"], []), query)
        return httpx.Response(200, json=pipeline)

    def jobs_route(self, method: str, rest: str, query: dict, body: Any) -> httpx.Response:
        match = re.fullmatch(r"/(\d+)/trace", rest)
        assert match, rest
        return httpx.Response(200, text=self.traces.get(int(match[1]), ""))


@pytest.fixture
def gitlab() -> FakeGitLab:
    return FakeGitLab()


def expiry(days: int = 365) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def bot_token(gl: FakeGitLab, *, name: str = "l4-bot", active: bool = True) -> dict:
    """An existing project access token, as GitLab lists it (never with its value)."""
    tid = gl.fresh_id()
    value = f"glpat-OLDTOKEN{tid:08d}abcdefghijkl"
    token = {
        "id": tid, "name": name, "scopes": ["api", "write_repository"], "access_level": 30, "expires_at": expiry(),
        "user_id": 90 + tid, "active": active, "revoked": not active, "_value": value,
    }  # fmt: skip
    gl.tokens.append(token)
    gl.issued.append(value)
    return token


def variable(gl: FakeGitLab, key: str, value: str, scope: str = "l4", **flags: Any) -> dict:
    var = {"key": key, "value": value, "environment_scope": scope, "masked": True, "protected": False, "raw": True}
    var.update(flags)
    gl.variables.append(var)
    return var


@pytest.fixture
def setup_repo(tmp_path, git_environ, raw):
    """A project checkout whose `origin` is on the fake server, without a `.l4/config.yaml` (schema defaults)."""
    repo = tmp_path / "project"
    repo.mkdir()
    raw(repo, "init", "-q")
    raw(repo, "remote", "add", "origin", f"{HOST}/{PATH}.git")
    return repo


@pytest.fixture
def app_of(setup_repo, git_environ):
    from l4.context import AppContext
    from l4.redact import Redactor

    def make(**env: str) -> "AppContext":
        environ = {**git_environ, "GITLAB_TOKEN": MAINTAINER, **env}
        return AppContext(
            repo=setup_repo, config_path=None, log_format="human", verbosity=0, run_id="r-20261005T1000Z-0001",
            environ=environ, redactor=Redactor({}),
        )  # fmt: skip

    return make


@pytest.fixture
def run_setup(app_of, gitlab, capsys):
    """`run_setup(**options) -> (exit code, stdout)`; schedule and pipeline are off unless a test asks for them."""
    from l4.setup.gitlab import run_setup_gitlab

    def run(*, env: dict | None = None, **options: Any) -> tuple[int, str]:
        from l4.exitcodes import L4Exit

        defaults: dict[str, Any] = {"project": PATH, "api_base": API, "no_schedule": True, "no_pipeline": True}
        try:
            code = run_setup_gitlab(app_of(**(env or {})), **{**defaults, **options}, transport=gitlab.transport())
        except L4Exit as exc:  # what `run_guarded` turns into the exit code and one console line
            out = capsys.readouterr()
            return int(exc.code), out.out + out.err + str(exc)
        out = capsys.readouterr()
        return int(code), out.out + out.err

    return run
