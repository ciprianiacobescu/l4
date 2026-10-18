# ruff: noqa: F811
"""A GitHub check run is one job of one workflow (L4-CI-010, L4-CI-011), and a hand-off commit whose only check run is
the harness's own `l4` job is `not_run` (L4-CI-012). The sweep's CI duty (`Sweeper._ci_duty`) runs over the fake GitLab
world, with `list_pipeline_jobs` answered by a real `GitHubForge` over a mock transport that serves GitHub's check-run
and workflow-run JSON, so the GitHub mapping and the sweep verdict are both the code under test."""

import httpx

from l4.forge.github import GitHubForge
from l4.forge.gitlab import GitLabForge

from ..archive.conftest import forge_env, use_fake_gitlab  # noqa: F401
from .test_sweeper import ci_sweep, review  # noqa: F401

RUN_ID = "r-20261005T1000Z-0001"


def _github_checks(
    monkeypatch, runs_by_sha: dict[str, list[dict]], workflows_by_sha: dict[str, list[tuple[str, int]]] | None = None
) -> None:
    """`workflows_by_sha`: sha -> [(workflow file, check suite id)] of the push runs the listing serves."""
    workflows = workflows_by_sha or {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/o/r/actions/runs":
            sha = request.url.params.get("head_sha")
            found = [
                {"id": 700 + n, "head_sha": sha, "path": f".github/workflows/{path}", "event": "push",
                 "check_suite_id": suite, "run_attempt": 1}
                for n, (path, suite) in enumerate(workflows.get(sha, []))
            ]  # fmt: skip
            return httpx.Response(200, json={"total_count": len(found), "workflow_runs": found})
        for sha, runs in runs_by_sha.items():
            if request.url.path == f"/repos/o/r/commits/{sha}/check-runs":
                return httpx.Response(200, json={"total_count": len(runs), "check_runs": runs})
        return httpx.Response(200, json={"total_count": 0, "check_runs": []})

    gh = GitHubForge("o/r", "tok", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    monkeypatch.setattr(
        GitLabForge,
        "list_pipeline_jobs",
        lambda self, sha, *, settled=False: gh.list_pipeline_jobs(sha, settled=settled),
    )


def _run(rid, name, conclusion, suite):
    return {"id": rid, "name": name, "status": "completed", "conclusion": conclusion,
            "app": {"slug": "github-actions"}, "check_suite": {"id": suite},
            "html_url": f"https://github.com/o/r/runs/{rid}"}  # fmt: skip


def test_a_failed_job_of_one_workflow_is_not_hidden(review, monkeypatch):
    """SCN-CI-051: `build` of tests.yml fails, `build` of docs.yml passes (newer); the base is green."""
    review.cfg.forge.type = "github"
    _github_checks(
        monkeypatch,
        {
            review.handoff: [_run(101, "build", "failure", 1), _run(102, "build", "success", 2)],
            review.base: [_run(201, "build", "success", 3), _run(202, "build", "success", 4)],
        },
        {
            review.handoff: [("tests.yml", 1), ("docs.yml", 2)],
            review.base: [("tests.yml", 3), ("docs.yml", 4)],
        },
    )
    (action,) = ci_sweep(review, RUN_ID)
    assert action.what == "ci_failed", "a red job on H was reported as " + action.what
    assert "tests.yml / build" in action.detail


def test_control_a_failure_newer_than_the_success_is_seen(review, monkeypatch):
    review.cfg.forge.type = "github"
    _github_checks(
        monkeypatch,
        {
            review.handoff: [_run(102, "build", "failure", 1), _run(101, "build", "success", 2)],
            review.base: [_run(201, "build", "success", 3)],
        },
        {review.handoff: [("tests.yml", 1), ("docs.yml", 2)], review.base: [("tests.yml", 3)]},
    )
    (action,) = ci_sweep(review, RUN_ID)
    assert action.what == "ci_failed"


def test_only_the_skipped_l4_job_is_not_run(review, monkeypatch):
    """SCN-CI-058: H's only check run is the harness's own `l4` job, skipped by its `if:` on an `L4-Run:` push."""
    review.cfg.forge.type = "github"
    _github_checks(monkeypatch, {review.handoff: [_run(301, "l4", "skipped", 9)]}, {review.handoff: [("l4.yml", 9)]})
    (action,) = ci_sweep(review, RUN_ID)
    assert action.what == "ci_not_run", "nothing but the skipped l4 job ran, yet the duty says " + action.what
    assert "its only check run is the harness's own l4 job" in action.detail and "GITHUB_TOKEN" not in action.detail


def test_control_no_check_run_is_not_run(review, monkeypatch):
    review.cfg.forge.type = "github"
    _github_checks(monkeypatch, {review.handoff: []})
    (action,) = ci_sweep(review, RUN_ID)
    assert action.what == "ci_not_run" and "GITHUB_TOKEN" in action.detail
