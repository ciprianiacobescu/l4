"""The workflow-run and pipeline listings that the relay (L4-IMP-072) and `l4 yolo status` (L4-IMP-073) read, on top of
`FakeGitHub` and `FakeGitLab`. The shared fakes stay as they are."""

import re
from dataclasses import dataclass, field
from urllib.parse import unquote

import httpx

from ._github_helpers import REPO, FakeGitHub
from .conftest import PROJECT, FakeGitLab


@dataclass
class RunsGitHub(FakeGitHub):
    l4_runs: list[dict] = field(default_factory=list)  # {id, status, conclusion?, head_branch} of l4.yml
    listing_status: int = 200  # the answer of the l4.yml run listing
    run_status: int = 200  # the answer of GET actions/runs/:id
    timeouts: list[dict] = field(default_factory=list)  # the httpx timeout of each request that was answered here

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        params = dict(request.url.params)
        listing = re.fullmatch(rf"/repos/{REPO}/actions/workflows/[^/]+/runs", path)
        single = re.fullmatch(rf"/repos/{REPO}/actions/runs/(\d+)", path)
        if (listing and "status" not in params) or single:
            self.requests.append((request.method, path, params, None))
            self.timeouts.append(dict(request.extensions["timeout"]))
            if listing:
                if self.listing_status != 200:
                    return httpx.Response(self.listing_status, json={"message": "x"})
                found = [r for r in self.l4_runs if r.get("head_branch", params.get("branch")) == params.get("branch")]
                return httpx.Response(200, json={"total_count": len(found), "workflow_runs": found})
            assert single is not None
            found = [r for r in self.l4_runs if r["id"] == int(single.group(1))]
            if self.run_status != 200 or not found:
                return httpx.Response(self.run_status if self.run_status != 200 else 404, json={"message": "x"})
            return httpx.Response(200, json=found[0])
        return super().handle(request)


@dataclass
class RunsGitLab(FakeGitLab):
    jobs_by_id: dict[int, dict] = field(default_factory=dict)  # GET jobs/:id
    timeouts: list[dict] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.timeouts.append(dict(request.extensions["timeout"]))
        return super().handle(request)

    def route(self, method: str, path: str, query: dict, body: dict | None) -> httpx.Response:
        base = f"/projects/{PROJECT}"
        if path == f"{base}/pipelines" and method == "GET" and "ref" in query:
            found = [
                {k: v for k, v in p.items() if k != "jobs"} for p in self.pipelines if p.get("ref") == query["ref"]
            ]
            return self.paged(found, query)
        job = re.fullmatch(rf"{re.escape(base)}/jobs/(\d+)", path)
        if job and method == "GET":
            found_job = self.jobs_by_id.get(int(job.group(1)))
            if found_job is None:
                return httpx.Response(404, json={"message": "404 Not found"})
            return httpx.Response(200, json=found_job)
        return super().route(method, path, query, body)
