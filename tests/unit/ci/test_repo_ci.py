"""github-parity D8 (L4-GHP-008, SCN-GHP-11): the repository-CI duty at the hand-off commit never reads "no check run"
as green on GitHub, where a push made with the workflow's GITHUB_TOKEN starts no workflow."""

from l4.ci.repo_ci import evaluate_ci
from l4.forge.base import JobResult

from ..archive.conftest import forge_env, use_fake_gitlab  # noqa: F401  (a fake GitLab for the hand-off)
from .test_sweeper import ci_sweep, review  # noqa: F401  (the CI duty's world)

REASON = (
    "no workflow ran on the hand-off commit; pushes made with GITHUB_TOKEN start no runs "
    "(use a token that does, or a GitHub App)"
)


def test_no_check_run_is_not_run(review):  # noqa: F811
    """SCN-GHP-11, SCN-CI-050: GitHub lists no check run at H: the duty is `not_run` with the reason, never
    `ci_green`."""
    review.cfg.forge.type = "github"
    (action,) = ci_sweep(review, "r-20261005T1000Z-0001")
    assert action.what == "ci_not_run" and REASON in action.detail and review.handoff[:10] in action.detail


def test_gitlab_without_a_pipeline_job_is_not_run(review):  # noqa: F811
    """SCN-CI-059 (L4-CI-012 changes the old expectation `ci_green`): no pipeline job on H is never green."""
    review.cfg.forge.type = "gitlab"
    (action,) = ci_sweep(review, "r-20261005T1000Z-0001")
    assert action.what == "ci_not_run"
    assert "no pipeline of the project has a job on the hand-off commit" in action.detail


def _job(workflow: str, name: str, status: str) -> JobResult:
    return JobResult(name, "", status, False, 1, 1, "", workflow=workflow)


def test_the_base_comparison_matches_workflow_and_job():
    """SCN-CI-056: a job red on H is pre-existing only when the same workflow's job of that name is red on the base."""
    head = [_job("tests.yml", "build", "failed")]
    other = evaluate_ci(head, [_job("docs.yml", "build", "failed")])
    assert other.status == "failed" and [j.key for j in other.failed] == ["tests.yml / build"]
    same = evaluate_ci(head, [_job("tests.yml", "build", "failed")])
    assert same.status == "preexisting" and [j.key for j in same.preexisting] == ["tests.yml / build"]
