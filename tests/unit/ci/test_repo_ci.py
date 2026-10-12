"""github-parity D8 (L4-GHP-008, SCN-GHP-11): the repository-CI duty at the hand-off commit never reads "no check run"
as green on GitHub, where a push made with the workflow's GITHUB_TOKEN starts no workflow."""

from ..archive.conftest import forge_env, use_fake_gitlab  # noqa: F401  (a fake GitLab for the hand-off)
from .test_sweeper import ci_sweep, review  # noqa: F401  (the CI duty's world)

REASON = (
    "no workflow ran on the hand-off commit; pushes made with GITHUB_TOKEN start no runs "
    "(use a token that does, or a GitHub App)"
)


def test_no_check_run_is_not_run(review):  # noqa: F811
    """SCN-GHP-11: GitHub lists no check run at H: the duty is `not_run` with the reason, never `ci_green`."""
    review.cfg.forge.type = "github"
    (action,) = ci_sweep(review, "r-20261005T1000Z-0001")
    assert action.what == "ci_not_run" and REASON in action.detail and review.handoff[:10] in action.detail


def test_gitlab_without_a_pipeline_keeps_its_behaviour(review):  # noqa: F811
    review.cfg.forge.type = "gitlab"
    assert [a.what for a in ci_sweep(review, "r-20261005T1000Z-0001")] == ["ci_green"]
