# ruff: noqa: F811
"""The repository's CI on the hand-off commit H is read through one function, `read_handoff_ci`, by the sweep and by the
guarded merge (L4-CI-012; SCN-CI-060)."""

import pytest

from l4.ci.handoff_ci import NO_CHECK_RUN, NO_PIPELINE_JOB, ONLY_HARNESS_JOB, read_handoff_ci
from l4.forge.base import JobResult

from ..archive.conftest import forge_env, use_fake_gitlab  # noqa: F401  (a fake GitLab for the hand-off)
from .test_sweeper import ci_sweep, review  # noqa: F401  (the CI duty's world)

RUN_ID = "r-20261005T1000Z-0001"

# (name, jobs on H, jobs on the base, the verdict of the reader, the word of the sweep's duty)
CASES = [
    ("running", [("test", "running")], [], "running", "ci_waiting"),
    ("green", [("test", "success")], [], "green", "ci_green"),
    ("failed", [("test", "failed")], [("test", "success")], "failed", "ci_failed"),
    ("preexisting", [("test", "failed")], [("test", "failed")], "preexisting", "ci_preexisting"),
    ("none", [], [], "not_run", "ci_not_run"),
]


@pytest.mark.parametrize(("name", "on_h", "on_base", "status", "word"), CASES, ids=[c[0] for c in CASES])
def test_the_sweep_and_the_merge_read_the_same_verdict(review, name, on_h, on_base, status, word):
    """SCN-CI-060"""
    review.cfg.forge.type = "gitlab"
    if on_h:
        review.gitlab.add_pipeline(review.handoff, on_h)
    if on_base:
        review.gitlab.add_pipeline(review.base, on_base)
    read = read_handoff_ci(review.forge(), review.handoff, review.base, "gitlab")
    assert read.status == status and read.head == review.handoff
    (action,) = ci_sweep(review, RUN_ID)
    assert action.what == word


def job(name: str, status: str = "success") -> JobResult:
    return JobResult(name, "", status, False, 1, 1, "")


class Jobs:
    """A forge that answers `list_pipeline_jobs` from a table."""

    def __init__(self, table: dict[str, list[JobResult]]) -> None:
        self.table = table

    def list_pipeline_jobs(self, sha: str, *, settled: bool = False) -> list[JobResult]:
        return self.table.get(sha, [])


def test_the_not_run_reason_names_the_case():
    no_job = Jobs({})
    assert read_handoff_ci(no_job, "h", "b", "github").reason == NO_CHECK_RUN
    only_l4 = Jobs({"h": [job("l4", "skipped")]})
    assert read_handoff_ci(only_l4, "h", "b", "github").reason == ONLY_HARNESS_JOB
    assert read_handoff_ci(no_job, "h", "b", "gitlab").reason == NO_PIPELINE_JOB
    assert "GITHUB_TOKEN" in NO_CHECK_RUN and "GITHUB_TOKEN" not in ONLY_HARNESS_JOB


def test_a_base_that_is_still_running_defers_the_verdict_and_says_so():
    forge = Jobs({"h": [job("test", "failed")], "b": [job("test", "running")]})
    read = read_handoff_ci(forge, "h", "b", "gitlab")
    assert read.status == "running" and "base" in read.reason
