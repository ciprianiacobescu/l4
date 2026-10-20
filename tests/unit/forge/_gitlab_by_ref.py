"""A `FakeGitLab` whose `GET /pipelines` also lists by `ref` (the continuation looks at the base's pipelines)."""

from dataclasses import dataclass

import httpx

from .conftest import PROJECT, FakeGitLab


@dataclass
class RefAwareGitLab(FakeGitLab):
    def add_ref_pipeline(self, ref: str, status: str) -> int:
        """A pipeline on `ref` with the given status; returns its id."""
        pipeline_id = len(self.pipelines) + 1
        self.pipelines.append({"id": pipeline_id, "sha": "1" * 40, "status": status, "jobs": [], "ref": ref})
        return pipeline_id

    def route(self, method: str, path: str, query: dict, body: dict | None) -> httpx.Response:
        if path == f"/projects/{PROJECT}/pipelines" and method == "GET" and "ref" in query:
            found = [
                {k: v for k, v in p.items() if k != "jobs"} for p in self.pipelines if p.get("ref") == query["ref"]
            ]
            return self.paged(found, query)
        return super().route(method, path, query, body)
