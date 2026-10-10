import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import parse_qs

import httpx
import pytest

API = "https://gitlab.example.test/api/v4"
PROJECT = "118"
WEB = "https://gitlab.example.test/example-group/dummy-agentic"
TOKEN = "glpat-FAKE0123456789abcdefXYZ"  # a fake token shape: never a real credential


@dataclass
class FakeGitLab:
    """A stateful stand-in for the few GitLab REST v4 endpoints the forge uses, behind `httpx.MockTransport`."""

    token: str = TOKEN
    mrs: dict[int, dict] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)
    requests: list[tuple[str, str, dict, dict | None]] = field(default_factory=list)
    label_page_size: int = 100
    notes: dict[int, list[dict]] = field(default_factory=dict)  # per MR iid: {id, body, system, author: {id}}
    bot_id: int = 7
    user_status: int = 200  # the answer of GET /user
    members: list[dict] = field(default_factory=list)  # GET /members/all
    note_page_size: int = 100
    fail_next: list[httpx.Response] = field(default_factory=list)  # served before the real answer
    clock: int = 0
    pipelines: list[dict] = field(default_factory=list)  # {id, sha, status, jobs: [job], ...}
    traces: dict[int, str] = field(default_factory=dict)  # job id -> log text
    label_events: dict[int, list[dict]] = field(default_factory=dict)  # per MR iid: GitLab's resource_label_events

    def add_pipeline(self, sha: str, jobs: list[tuple], *, status: str = "success") -> int:
        """A pipeline for `sha`: `jobs` are `(name, status[, {stage, allow_failure, trace}])`. Returns its id."""
        pipeline_id = len(self.pipelines) + 1
        built = []
        for spec in jobs:
            name, job_status, extra = (*spec, {})[:3]
            job_id = 1000 + sum(len(p["jobs"]) for p in self.pipelines) + len(built) + 1
            if "trace" in extra:
                self.traces[job_id] = extra["trace"]
            built.append({
                "id": job_id, "name": name, "status": job_status, "stage": extra.get("stage", "test"),
                "allow_failure": extra.get("allow_failure", False), "web_url": f"{WEB}/-/jobs/{job_id}",
            })  # fmt: skip
        self.pipelines.append({"id": pipeline_id, "sha": sha, "status": status, "jobs": built})
        return pipeline_id

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def writes(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _, _ in self.requests if m != "GET"]

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers.get("PRIVATE-TOKEN") == self.token
        assert "authorization" not in request.headers
        path = request.url.path.removeprefix("/api/v4")
        query = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, query, body))
        if self.fail_next:
            return self.fail_next.pop(0)
        return self.route(request.method, path, query, body)

    def route(self, method: str, path: str, query: dict, body: dict | None) -> httpx.Response:
        base = f"/projects/{PROJECT}"
        if path == base and method == "GET":
            return httpx.Response(200, json={"id": 118, "web_url": WEB})
        if path == f"{base}/members/all" and method == "GET":
            return httpx.Response(200, json=self.members)
        member = re.fullmatch(rf"{re.escape(base)}/members/all/(\d+)", path)
        if member and method == "GET":
            found = next((m for m in self.members if m["id"] == int(member[1])), None)
            return httpx.Response(200, json=found) if found else httpx.Response(404, json={"message": "404 Not found"})
        events = re.fullmatch(rf"{re.escape(base)}/merge_requests/(\d+)/resource_label_events", path)
        if events and method == "GET":
            return self.paged(self.label_events.get(int(events[1]), []), query)
        if path == "/user" and method == "GET":
            if self.user_status != 200:
                return httpx.Response(self.user_status, json={"message": "nope"})
            return httpx.Response(200, json={"id": self.bot_id, "username": "l4-bot"})
        notes = re.fullmatch(rf"{re.escape(base)}/merge_requests/(\d+)/notes(?:/(\d+))?", path)
        if notes:
            return self.notes_route(method, int(notes[1]), int(notes[2]) if notes[2] else None, query, body)
        if path == f"{base}/labels":
            return self.labels_route(method, query, body)
        if path == f"{base}/pipelines" and method == "GET":
            found = [{k: v for k, v in p.items() if k != "jobs"} for p in self.pipelines if p["sha"] == query["sha"]]
            return self.paged(found, query)
        listed = re.fullmatch(rf"{re.escape(base)}/pipelines/(\d+)/jobs", path)
        if listed and method == "GET":
            pipeline = next((p for p in self.pipelines if p["id"] == int(listed[1])), None)
            if pipeline is None:
                return httpx.Response(404, json={"message": "404 Not found"})
            return self.paged([{**j, "pipeline": {"id": pipeline["id"]}} for j in pipeline["jobs"]], query)
        trace = re.fullmatch(rf"{re.escape(base)}/jobs/(\d+)/trace", path)
        if trace and method == "GET":
            if int(trace[1]) not in self.traces:
                return httpx.Response(404, json={"message": "404 Not found"})
            return httpx.Response(200, text=self.traces[int(trace[1])])
        if path == f"{base}/merge_requests":
            if method == "GET":
                found = [
                    self.mr_json(m) for m in self.mrs.values()
                    if query.get("source_branch", m["source_branch"]) == m["source_branch"]
                    and query.get("state", "all") in ("all", m["state"])
                ]  # fmt: skip
                if query.get("order_by") == "updated_at":  # GitLab's default order is created_at, newest first
                    found.sort(key=lambda m: m["updated_at"], reverse=query.get("sort", "desc") == "desc")
                page, size = int(query.get("page", "1")), int(query.get("per_page", "20"))
                more = page * size < len(found)
                headers = {"X-Next-Page": str(page + 1) if more else ""}
                return httpx.Response(200, json=found[(page - 1) * size : page * size], headers=headers)
            assert body is not None
            iid = len(self.mrs) + 1
            self.mrs[iid] = {
                "iid": iid, "source_branch": body["source_branch"], "target_branch": body["target_branch"],
                "title": body["title"], "description": body.get("description", ""), "state": "opened", "labels": [],
                "source_project_id": int(PROJECT), "target_project_id": int(PROJECT), "updated_at": self.touch(),
            }  # fmt: skip
            return httpx.Response(201, json=self.mr_json(self.mrs[iid]))
        match = re.fullmatch(rf"{re.escape(base)}/merge_requests/(\d+)", path)
        if match and int(match[1]) in self.mrs:
            mr = self.mrs[int(match[1])]
            if method == "PUT":
                assert body is not None
                for key in ("title", "description"):
                    if key in body:
                        mr[key] = body[key]
                for name in filter(None, body.get("remove_labels", "").split(",")):
                    mr["labels"].remove(name)
                for name in filter(None, body.get("add_labels", "").split(",")):
                    if name not in mr["labels"]:
                        mr["labels"].append(name)
            return httpx.Response(200, json=self.mr_json(mr))
        return httpx.Response(404, json={"message": "404 Not found"})

    @staticmethod
    def paged(items: list[dict], query: dict) -> httpx.Response:
        page, size = int(query.get("page", "1")), int(query.get("per_page", "20"))
        more = page * size < len(items)
        return httpx.Response(
            200, json=items[(page - 1) * size : page * size], headers={"X-Next-Page": str(page + 1) if more else ""}
        )

    def notes_route(self, method: str, iid: int, note_id: int | None, query: dict, body: dict | None) -> httpx.Response:
        if iid not in self.mrs:
            return httpx.Response(404, json={"message": "404 Not found"})
        notes = self.notes.setdefault(iid, [])
        if method == "GET":
            page, size = int(query.get("page", "1")), self.note_page_size
            more = page * size < len(notes)
            return httpx.Response(
                200, json=notes[(page - 1) * size : page * size], headers={"X-Next-Page": str(page + 1) if more else ""}
            )
        assert body is not None
        if method == "POST":
            note = {"id": 1000 + sum(len(v) for v in self.notes.values()), "body": body["body"], "system": False,
                    "author": {"id": self.bot_id}}  # fmt: skip
            notes.append(note)
            return httpx.Response(201, json=note)
        note = next(n for n in notes if n["id"] == note_id)
        note["body"] = body["body"]
        return httpx.Response(200, json=note)

    def labels_route(self, method: str, query: dict, body: dict | None) -> httpx.Response:
        if method == "GET":
            page, size = int(query.get("page", "1")), min(int(query.get("per_page", "20")), self.label_page_size)
            chunk = self.labels[(page - 1) * size : page * size]
            more = page * size < len(self.labels)
            return httpx.Response(
                200, json=[{"name": n} for n in chunk], headers={"X-Next-Page": str(page + 1) if more else ""}
            )
        assert body is not None
        if body["name"] in self.labels:
            return httpx.Response(409, json={"message": "Label already exists"})
        self.labels.append(body["name"])
        return httpx.Response(201, json={"name": body["name"]})

    def touch(self) -> str:
        """A strictly increasing `updated_at`, in the sortable shape GitLab uses."""
        self.clock += 1
        return f"2026-10-04T09:00:{self.clock:02d}.000Z"

    def merge(self, iid: int, merge_commit_sha: str | None) -> None:
        """A human merged the MR: GitLab says `merged`, with the merge commit when the method made one."""
        self.mrs[iid]["state"] = "merged"
        self.mrs[iid]["updated_at"] = self.touch()
        self.mrs[iid]["merge_commit_sha"] = merge_commit_sha

    @staticmethod
    def mr_json(mr: dict) -> dict:
        draft = mr["title"].lower().startswith("draft:")
        return {**mr, "draft": draft, "web_url": f"{WEB}/-/merge_requests/{mr['iid']}", "labels": list(mr["labels"])}


@pytest.fixture
def gitlab() -> FakeGitLab:
    return FakeGitLab()


@pytest.fixture
def make_forge_client(gitlab: FakeGitLab) -> Callable[..., object]:
    from l4.forge.gitlab import GitLabForge

    def make(**kw: object) -> GitLabForge:
        sleeps: list[float] = kw.pop("sleeps", [])  # type: ignore[assignment]
        return GitLabForge(
            API,
            PROJECT,
            kw.pop("token", TOKEN),
            transport=gitlab.transport(),
            sleep=sleeps.append,
            **kw,  # type: ignore[arg-type]
        )

    return make
