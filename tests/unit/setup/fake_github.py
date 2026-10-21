"""A fake of the part of the GitHub REST API that `l4 setup github` and `l4 ci watch` use, behind an httpx
MockTransport. The API may sit behind a path prefix (a credential broker): the fake strips it, and it refuses any
request that is not for the base host or that carries another token."""

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from nacl import public

TOKEN = "ghp_maintainertokenvalue0123456789"
REPO = "acme/widgets"
API = "https://api.github.com"


@dataclass
class FakeGitHub:
    base: str = API
    token: str = TOKEN
    admin: bool = True
    default_branch: str = "main"
    key: public.PrivateKey = field(default_factory=public.PrivateKey.generate)
    workflow_permissions: dict[str, Any] | None = None
    environments: dict[str, dict[str, Any]] = field(default_factory=dict)
    policies: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    secrets: dict[tuple[str, str], dict[str, str]] = field(default_factory=dict)
    variables: dict[str, str] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    jobs: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    logs: dict[int, str] = field(default_factory=dict)
    script: list[tuple[str, str | None]] = field(default_factory=lambda: [("queued", None), ("completed", "success")])
    requests: list[tuple[str, str]] = field(default_factory=list)  # (method, path below the base)
    strays: list[str] = field(default_factory=list)  # requests that left the base host or carried another token
    steps: dict[int, int] = field(default_factory=dict)
    files: dict[tuple[str, str], str] = field(default_factory=dict)  # (ref, path) -> text, for the contents API

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def writes(self) -> list[tuple[str, str]]:
        return [r for r in self.requests if r[0] != "GET"]

    def gets(self) -> list[tuple[str, str]]:
        return [r for r in self.requests if r[0] == "GET"]

    def add_run(self, run_id: int, ref: str = "main") -> dict[str, Any]:
        run = {
            "id": run_id,
            "head_branch": ref,
            "status": "queued",
            "conclusion": None,
            "html_url": f"https://x/{run_id}",
        }
        self.runs.append(run)
        self.steps[run_id] = 0
        return run

    def handle(self, request: httpx.Request) -> httpx.Response:
        base = urlsplit(self.base)
        url = urlsplit(str(request.url))
        if (url.scheme, url.netloc) != (base.scheme, base.netloc) or request.headers.get(
            "authorization"
        ) != f"Bearer {self.token}":
            self.strays.append(f"{request.method} {request.url}")
            return httpx.Response(401, json={"message": "Bad credentials"})
        path = url.path.removeprefix(base.path.rstrip("/"))
        self.requests.append((request.method, path))
        body = json.loads(request.content) if request.content else None
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        return self.route(request.method, path, query, body)

    # --- routes ------------------------------------------------------------------------------------------------

    def route(self, method: str, path: str, query: dict, body: Any) -> httpx.Response:  # noqa: C901
        prefix = f"/repos/{REPO}"
        if not path.startswith(prefix):
            return httpx.Response(404, json={"message": "Not Found"})
        rest = path[len(prefix) :]
        if rest == "":
            return httpx.Response(
                200,
                json={
                    "full_name": REPO,
                    "default_branch": self.default_branch,
                    "html_url": f"https://github.com/{REPO}",
                    "permissions": {"admin": self.admin},
                },
            )
        if rest == "/actions/permissions/workflow":
            if method == "PUT":
                self.workflow_permissions = body
                return httpx.Response(204)
            return httpx.Response(
                200,
                json=self.workflow_permissions
                or {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False},
            )
        if m := re.fullmatch(r"/environments/([^/]+)", rest):
            env = m.group(1)
            if method == "PUT":
                created = env not in self.environments
                self.environments[env] = {"name": env, **(body or {})}
                return (
                    httpx.Response(200, json=self.environments[env])
                    if not created
                    else httpx.Response(200, json=self.environments[env])
                )
            if env not in self.environments:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json=self.environments[env])
        if m := re.fullmatch(r"/environments/([^/]+)/deployment-branch-policies", rest):
            env = m.group(1)
            if env not in self.environments:
                return httpx.Response(404, json={"message": "Not Found"})
            found = self.policies.setdefault(env, [])
            if method == "POST":
                found.append({"id": len(found) + 1, **body})
                return httpx.Response(200, json=found[-1])
            return httpx.Response(200, json={"total_count": len(found), "branch_policies": found})
        if m := re.fullmatch(r"/environments/([^/]+)/secrets/public-key", rest):
            if m.group(1) not in self.environments:
                return httpx.Response(404, json={"message": "Not Found"})
            raw = bytes(self.key.public_key)
            return httpx.Response(200, json={"key_id": "kid-1", "key": base64.b64encode(raw).decode()})
        if m := re.fullmatch(r"/environments/([^/]+)/secrets/([A-Za-z0-9_]+)", rest):
            if m.group(1) not in self.environments:
                return httpx.Response(404, json={"message": "Not Found"})
            existed = (m.group(1), m.group(2)) in self.secrets
            self.secrets[(m.group(1), m.group(2))] = body
            return httpx.Response(204 if existed else 201)
        if rest == "/actions/variables" and method == "POST":
            self.variables[body["name"]] = body["value"]
            return httpx.Response(201)
        if m := re.fullmatch(r"/actions/variables/([A-Za-z0-9_]+)", rest):
            name = m.group(1)
            if name not in self.variables:
                return httpx.Response(404, json={"message": "Not Found"})
            if method == "PATCH":
                self.variables[name] = body["value"]
                return httpx.Response(204)
            return httpx.Response(200, json={"name": name, "value": self.variables[name]})
        if rest == "/labels":
            if method == "POST":
                self.labels.append(body["name"])
                return httpx.Response(201, json=body)
            return httpx.Response(
                200,
                json=[{"name": n} for n in self.labels],
                headers={"Link": '<https://elsewhere.example.test/repositories/1/labels?page=2>; rel="next"'},
            )
        if m := re.fullmatch(r"/contents/(.+)", rest):
            ref = query.get("ref", self.default_branch)
            text = self.files.get((ref, m.group(1)))
            if text is None:
                return httpx.Response(404, json={"message": "Not Found"})
            encoded = base64.b64encode(text.encode()).decode()
            return httpx.Response(
                200, json={"type": "file", "path": m.group(1), "encoding": "base64", "content": encoded}
            )
        if rest == "/actions/workflows/l4.yml/dispatches" and method == "POST":
            self.add_run(max([r["id"] for r in self.runs], default=100) + 1, body["ref"])
            return httpx.Response(204)
        if rest == "/actions/workflows/l4.yml/runs":
            found = [r for r in reversed(self.runs) if r["head_branch"] == query.get("branch", r["head_branch"])]
            for run in found[:1]:
                self.advance(run)
            return httpx.Response(
                200, json={"total_count": len(found), "workflow_runs": found[: int(query.get("per_page", 30))]}
            )
        if m := re.fullmatch(r"/actions/runs/(\d+)/jobs", rest):
            return httpx.Response(200, json={"total_count": 1, "jobs": self.jobs.get(int(m.group(1)), [])})
        if m := re.fullmatch(r"/actions/jobs/(\d+)/logs", rest):
            return httpx.Response(200, text=self.logs.get(int(m.group(1)), ""))
        return httpx.Response(404, json={"message": "Not Found"})

    def advance(self, run: dict[str, Any]) -> None:
        step = self.steps.get(run["id"], 0)
        status, conclusion = self.script[min(step, len(self.script) - 1)]
        run["status"], run["conclusion"] = status, conclusion
        self.steps[run["id"]] = step + 1
