"""A `FakeGitLab` whose `GET /pipelines` also lists by `ref` (the continuation looks at the base's pipelines)."""

from dataclasses import dataclass

import httpx

from .conftest import PROJECT, WEB, FakeGitLab


@dataclass
class RefAwareGitLab(FakeGitLab):
    default_branch: str | None = "main"  # what the project read says (None: it names none)

    def add_ref_pipeline(self, ref: str, status: str, **extra: str) -> int:
        """A pipeline on `ref` with the given status (`extra`: more fields of its listing row, e.g. `updated_at`);
        returns its id."""
        pipeline_id = len(self.pipelines) + 1
        self.pipelines.append({"id": pipeline_id, "sha": "1" * 40, "status": status, "jobs": [], "ref": ref, **extra})
        return pipeline_id

    def route(self, method: str, path: str, query: dict, body: dict | None) -> httpx.Response:
        if path == f"/projects/{PROJECT}" and method == "GET" and self.default_branch is not None:
            return httpx.Response(200, json={"id": 118, "web_url": WEB, "default_branch": self.default_branch})
        if path == f"/projects/{PROJECT}/pipelines" and method == "GET" and "ref" not in query and "sha" not in query:
            return self.paged([{k: v for k, v in p.items() if k != "jobs"} for p in self.pipelines], query)
        if path == f"/projects/{PROJECT}/pipelines" and method == "GET" and "ref" in query:
            found = [
                {k: v for k, v in p.items() if k != "jobs"} for p in self.pipelines if p.get("ref") == query["ref"]
            ]
            return self.paged(found, query)
        return super().route(method, path, query, body)
