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
USER_ID = 777


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
    workflow_runs: list[dict] = field(default_factory=list)  # {id, head_sha, path, event, check_suite_id, run_attempt}
    attempts: dict[tuple[int, int], dict] = field(default_factory=dict)  # (run id, attempt) -> the run of that attempt
    workflow_runs_status: int = 200  # the answer of the workflow-runs listing (403: the token may not read actions)
    attempts_status: int = 200  # the answer of an attempt read
    jobs: dict[int, list[dict]] = field(default_factory=dict)  # workflow run id -> {id, latest} jobs of its executions
    statuses: list[dict] = field(default_factory=list)  # {sha, context, state, target_url}: commit statuses
    rules: list[dict] | None = None  # the answer of rules/branches/:branch (None: 404)
    rules_status: int = 200
    protection: dict | None = None  # the answer of the classic required_status_checks endpoint (None: 404)
    logs: dict[int, str] = field(default_factory=dict)  # check run id -> the text behind the log redirect
    redirect_to: str = "https://logs.example.test/blob"  # where `actions/jobs/:id/logs` sends the client
    issue_events: dict[int, list[dict]] = field(default_factory=dict)  # issue number -> /issues/:n/events entries
    users: dict[int, str] = field(default_factory=dict)  # user id -> login (GET /user/:id)
    permissions: dict[str, dict] = field(default_factory=dict)  # login -> collaborator permission body
    queued_runs: int = 0  # workflow runs the `status=queued` listing finds
    dispatch_status: int = 204  # the answer of a workflow_dispatch (403: the token may not start workflows)
    hosts_seen: list[tuple[str, bool]] = field(default_factory=list)  # (host, request carried a token)
    merge_status: int = 200  # the answer of PUT pulls/:n/merge (409: head moved, 405/422: refused)
    merge_message: str = "Pull Request is not mergeable"  # the body message of a failed merge call

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
        app: str | None = None,
    ) -> dict:
        run_id = 5000 + len(self.check_runs) + 1
        run = {
            "id": run_id, "name": name, "status": status, "conclusion": conclusion, "sha": sha,
            "html_url": f"https://github.test/{REPO}/runs/{run_id}", "check_suite": {"id": suite or 1},
        }  # fmt: skip
        if app is not None:
            run["app"] = {"slug": app}
        self.check_runs.append(run)
        if log is not None:
            self.logs[run_id] = log
        return run

    def add_workflow_run(
        self,
        sha: str,
        path: str,
        event: str,
        *,
        suite: int,
        run_id: int | None = None,
        attempts: tuple[int, ...] = (),
        status: str = "completed",
    ) -> dict:
        """A workflow run of `sha`: `path` is the file under `.github/workflows/`, `suite` the check suite of its latest
        attempt, `attempts` the suites of the earlier attempts, oldest first (each readable at `.../attempts/<n>`)."""
        run_id = run_id or 800 + len(self.workflow_runs) + 1
        run = {
            "id": run_id, "head_sha": sha, "path": f".github/workflows/{path}", "event": event,
            "check_suite_id": suite, "run_attempt": len(attempts) + 1, "status": status,
        }  # fmt: skip
        self.workflow_runs.append(run)
        for number, earlier in enumerate(attempts, start=1):
            self.attempts[(run_id, number)] = {**run, "check_suite_id": earlier, "run_attempt": number}
        return run

    def add_job(self, run_id: int, check_run: dict, *, latest: bool = True) -> None:
        """The check run `check_run` is a job of workflow run `run_id`; `latest: False` is a superseded execution."""
        self.jobs.setdefault(run_id, []).append({"id": check_run["id"], "latest": latest})

    def add_status(self, sha: str, context: str, state: str) -> dict:
        status = {"sha": sha, "context": context, "state": state, "target_url": f"https://ci.test/{context}"}
        self.statuses.append(status)
        return status

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
        if m := re.fullmatch(rf"/repos/{REPO}/actions/runs/(\d+)/attempts/(\d+)", path):
            found = self.attempts.get((int(m.group(1)), int(m.group(2))))
            if self.attempts_status != 200 or found is None:
                return httpx.Response(
                    self.attempts_status if self.attempts_status != 200 else 404, json={"message": "x"}
                )
            return httpx.Response(200, json=found)
        if m := re.fullmatch(rf"/repos/{REPO}/actions/runs/(\d+)/jobs", path):
            wanted = request.url.params.get("filter", "latest")
            jobs = [j for j in self.jobs.get(int(m.group(1)), []) if wanted == "all" or j["latest"]]
            return self._page(request, [{"id": j["id"], "name": "job"} for j in jobs], "jobs")
        if m := re.fullmatch(rf"/repos/{REPO}/commits/([0-9a-f]+)/status", path):
            found = [x for x in self.statuses if x["sha"] == m.group(1)]
            return self._page(request, found, "statuses")
        if re.fullmatch(rf"/repos/{REPO}/rules/branches/[^/]+", path):
            if self.rules_status != 200 or self.rules is None:
                return httpx.Response(self.rules_status if self.rules_status != 200 else 404, json={"message": "x"})
            return httpx.Response(200, json=self.rules)
        if re.fullmatch(rf"/repos/{REPO}/branches/[^/]+/protection/required_status_checks", path):
            if self.protection is None:
                return httpx.Response(404, json={"message": "Branch not protected"})
            return httpx.Response(200, json=self.protection)
        if path == f"/repos/{REPO}/actions/runs":
            if self.workflow_runs_status != 200:
                return httpx.Response(self.workflow_runs_status, json={"message": "Resource not accessible"})
            wanted = request.url.params.get("head_sha")
            runs = [r for r in self.workflow_runs if wanted is None or r["head_sha"] == wanted]
            return self._page(request, runs, "workflow_runs")
        if m := re.fullmatch(rf"/repos/{REPO}/actions/jobs/(\d+)/logs", path):
            if int(m.group(1)) not in self.logs:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(302, headers={"Location": f"{self.redirect_to}/{m.group(1)}"})
        if path == "/graphql":
            return self._graphql(body)
        if path == "/user":
            return httpx.Response(
                self.user_status, json={"login": LOGIN, "id": USER_ID} if self.user_status == 200 else {}
            )
        if m := re.fullmatch(r"/user/(\d+)", path):
            login = self.users.get(int(m.group(1)))
            return httpx.Response(200, json={"login": login}) if login else httpx.Response(404, json={"message": "x"})
        if m := re.fullmatch(rf"/repos/{REPO}/collaborators/([^/]+)/permission", path):
            body_ = self.permissions.get(m.group(1))
            return httpx.Response(200, json=body_) if body_ else httpx.Response(404, json={"message": "Not Found"})
        if m := re.fullmatch(rf"/repos/{REPO}/issues/(\d+)/events", path):
            return self._page(request, self.issue_events.get(int(m.group(1)), []))
        if m := re.fullmatch(rf"/repos/{REPO}/actions/workflows/([^/]+)/runs", path):
            return httpx.Response(200, json={"total_count": self.queued_runs, "workflow_runs": []})
        if m := re.fullmatch(rf"/repos/{REPO}/actions/workflows/([^/]+)/dispatches", path):
            if self.dispatch_status != 204:
                return httpx.Response(self.dispatch_status, json={"message": "Resource not accessible by integration"})
            return httpx.Response(204)
        if m := re.fullmatch(rf"/repos/{REPO}", path):
            return httpx.Response(200, json={"html_url": f"https://github.test/{REPO}"})
        if m := re.fullmatch(rf"/repos/{REPO}/pulls", path):
            return self._pulls(request, body)
        if m := re.fullmatch(rf"/repos/{REPO}/pulls/(\d+)/merge", path):
            return self._merge(int(m.group(1)), body)
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
            pr.update({k: v for k, v in body.items() if k in ("title", "body", "state")})
        return httpx.Response(200, json=pr)

    def _merge(self, number: int, body: dict | None) -> httpx.Response:
        if self.merge_status != 200:
            return httpx.Response(self.merge_status, json={"message": self.merge_message})
        sha = f"{number:040x}"
        self.prs[number].update(state="closed", merged=True, merge_commit_sha=sha)
        return httpx.Response(200, json={"sha": sha, "merged": True, "message": "Pull Request successfully merged"})

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
            comment = {"id": self._next_comment, "body": body["body"], "user": {"login": LOGIN, "id": USER_ID}}
            items.append(comment)
            return httpx.Response(201, json=comment)
        return self._page(request, items)


def quoted(name: str) -> str:
    return quote(name, safe="")
