"""A stateful stand-in for the GitHub REST/GraphQL endpoints `GitHubForge` and the CI tests use, behind
`httpx.MockTransport`. The token is a fake shape: never a real credential."""

import json
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote, unquote

import httpx

API = "https://api.github.test"
REPO = "acme/widgets"
TOKEN = "ghp_FAKE0123456789abcdefghijklmnopqrstuv"
LOGIN = "l4-bot"


@dataclass
class FakeGitHub:
    token: str = TOKEN
    prs: dict[int, dict] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)
    comments: dict[int, list[dict]] = field(default_factory=dict)
    requests: list[tuple[str, str, dict, object]] = field(default_factory=list)
    page_size: int = 100
    user_status: int = 200
    fail_next: list[httpx.Response] = field(default_factory=list)
    graphql_errors: list[dict] = field(default_factory=list)
    _next_comment: int = 1000
    check_runs: list[dict] = field(default_factory=list)  # {id, name, status, conclusion, sha, ...}
    logs: dict[int, str] = field(default_factory=dict)  # check run id -> the text behind the log redirect
    redirect_to: str = "https://logs.example.test/blob"  # where `actions/jobs/:id/logs` sends the client
    hosts_seen: list[tuple[str, bool]] = field(default_factory=list)  # (host, request carried a token)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def writes(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _, _ in self.requests if m != "GET"]

    def add_pr(self, head: str, *, number: int | None = None, draft: bool = True, repo: str = REPO, **extra) -> dict:
        number = number or len(self.prs) + 1
        pr = {
            "number": number, "node_id": f"PR_node_{number}", "html_url": f"https://github.test/{REPO}/pull/{number}",
            "title": "t", "body": "", "state": "open", "draft": draft, "merged": False, "merged_at": None,
            "merge_commit_sha": None, "labels": [], "head": {"ref": head, "repo": {"full_name": repo}},
            "base": {"ref": "main"}, **extra,
        }  # fmt: skip
        self.prs[number] = pr
        return pr

    def add_check_run(
        self,
        sha: str,
        name: str,
        status: str,
        conclusion: str | None,
        *,
        suite: int | None = None,
        log: str | None = None,
    ) -> dict:
        run_id = 5000 + len(self.check_runs) + 1
        run = {
            "id": run_id, "name": name, "status": status, "conclusion": conclusion, "sha": sha,
            "html_url": f"https://github.test/{REPO}/runs/{run_id}", "check_suite": {"id": suite or 1},
        }  # fmt: skip
        self.check_runs.append(run)
        if log is not None:
            self.logs[run_id] = log
        return run

    def _page(self, request: httpx.Request, items: list[dict], key: str | None = None) -> httpx.Response:
        query = parse_qs(request.url.query.decode())
        page = int(query.get("page", ["1"])[0])
        chunk = items[(page - 1) * self.page_size : page * self.page_size]
        headers = {}
        if page * self.page_size < len(items):
            nxt = request.url.copy_merge_params({"page": str(page + 1)})
            headers["Link"] = f'<{nxt}>; rel="next"'
        body = {"total_count": len(items), key: chunk} if key else chunk
        return httpx.Response(200, json=body, headers=headers)

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = unquote(request.url.path)
        self.hosts_seen.append((request.url.host, "authorization" in request.headers))
        if request.url.host == "logs.example.test":  # behind the redirect: a pre-signed URL, never the token
            assert "authorization" not in request.headers
            return (
                httpx.Response(200, text=self.logs[int(path.rsplit("/", 1)[-1])])
                if path != "/plain"
                else (httpx.Response(200, text="plain"))
            )
        self.requests.append((request.method, path, dict(request.url.params), body))
        assert request.headers["Authorization"] == f"Bearer {self.token}"
        assert "private-token" not in request.headers
        if self.fail_next:
            return self.fail_next.pop(0)
        if m := re.fullmatch(rf"/repos/{REPO}/commits/([0-9a-f]+)/check-runs", path):
            runs = [r for r in self.check_runs if r["sha"] == m.group(1)]
            return self._page(request, runs, "check_runs")
        if m := re.fullmatch(rf"/repos/{REPO}/actions/jobs/(\d+)/logs", path):
            if int(m.group(1)) not in self.logs:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(302, headers={"Location": f"{self.redirect_to}/{m.group(1)}"})
        if path == "/graphql":
            return self._graphql(body)
        if path == "/user":
            return httpx.Response(self.user_status, json={"login": LOGIN} if self.user_status == 200 else {})
        if m := re.fullmatch(rf"/repos/{REPO}", path):
            return httpx.Response(200, json={"html_url": f"https://github.test/{REPO}"})
        if m := re.fullmatch(rf"/repos/{REPO}/pulls", path):
            return self._pulls(request, body)
        if m := re.fullmatch(rf"/repos/{REPO}/pulls/(\d+)", path):
            return self._pull(int(m.group(1)), request.method, body)
        if re.fullmatch(rf"/repos/{REPO}/labels", path):
            if request.method == "GET":
                return self._page(request, [{"name": n} for n in self.labels])
            if body["name"] in self.labels:
                return httpx.Response(422, json={"message": "Validation Failed"})
            self.labels.append(body["name"])
            return httpx.Response(201, json=body)
        if m := re.fullmatch(rf"/repos/{REPO}/issues/(\d+)/labels(?:/(.+))?", path):
            return self._issue_labels(int(m.group(1)), m.group(2), request.method, body)
        if m := re.fullmatch(rf"/repos/{REPO}/issues/(\d+)/comments", path):
            return self._comments(int(m.group(1)), request, body)
        if m := re.fullmatch(rf"/repos/{REPO}/issues/comments/(\d+)", path):
            for items in self.comments.values():
                for comment in items:
                    if comment["id"] == int(m.group(1)):
                        comment["body"] = body["body"]
                        return httpx.Response(200, json=comment)
        return httpx.Response(404, json={"message": f"no route {request.method} {path}"})

    def _pulls(self, request: httpx.Request, body: dict | None) -> httpx.Response:
        if request.method == "POST":
            pr = self.add_pr(body["head"], draft=body.get("draft", False), title=body["title"], body=body["body"])
            pr["base"] = {"ref": body["base"]}
            return httpx.Response(201, json=pr)
        params = request.url.params
        items = list(self.prs.values())
        if "head" in params:
            branch = params["head"].partition(":")[2]
            items = [p for p in items if p["head"]["ref"] == branch]
        if params.get("state") == "open":
            items = [p for p in items if p["state"] == "open"]
        return self._page(request, items)

    def _pull(self, number: int, method: str, body: dict | None) -> httpx.Response:
        pr = self.prs.get(number)
        if pr is None:
            return httpx.Response(404, json={"message": "Not Found"})
        if method == "PATCH":
            pr.update({k: v for k, v in body.items() if k in ("title", "body")})
        return httpx.Response(200, json=pr)

    def _graphql(self, body: dict) -> httpx.Response:
        if self.graphql_errors:
            return httpx.Response(200, json={"errors": self.graphql_errors})
        node = body["variables"]["id"]
        pr = next(p for p in self.prs.values() if p["node_id"] == node)
        pr["draft"] = "convertPullRequestToDraft" in body["query"]
        return httpx.Response(200, json={"data": {}})

    def _issue_labels(self, number: int, name: str | None, method: str, body: dict | None) -> httpx.Response:
        pr = self.prs[number]
        if method == "POST":
            for label in body["labels"]:
                if label not in [x["name"] for x in pr["labels"]]:
                    pr["labels"].append({"name": label})
        elif method == "DELETE":
            pr["labels"] = [x for x in pr["labels"] if x["name"] != name]
        return httpx.Response(200, json=pr["labels"])

    def _comments(self, number: int, request: httpx.Request, body: dict | None) -> httpx.Response:
        items = self.comments.setdefault(number, [])
        if request.method == "POST":
            self._next_comment += 1
            comment = {"id": self._next_comment, "body": body["body"], "user": {"login": LOGIN}}
            items.append(comment)
            return httpx.Response(201, json=comment)
        return self._page(request, items)


def quoted(name: str) -> str:
    return quote(name, safe="")
