# ruff: noqa: F811
"""The repository's CI on the hand-off commit H is read through one function, `read_handoff_ci`, by the sweep and by the
guarded merge (L4-CI-012; SCN-CI-060)."""

from datetime import UTC, datetime, timedelta

import pytest

from l4.ci.handoff_ci import (
    ALL_SKIPPED,
    NO_CHECK_RUN,
    NO_PIPELINE_JOB,
    NOT_CREATED_YET,
    ONLY_HARNESS_JOB,
    WINDOW,
    read_handoff_ci,
)
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
    ("cancelled", [("test", "canceled")], [], "blocked", "ci_blocked"),
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


def test_a_cancelled_job_blocks_and_a_job_that_did_not_pass_is_red():
    """F1: cancelled is neither green nor a fix round; action_required and stale (mapped to failed) are red."""
    cancelled = read_handoff_ci(Jobs({"h": [job("test", "canceled"), job("lint")]}), "h", "b", "github")
    assert cancelled.status == "blocked" and [j.key for j in cancelled.blocked] == ["test"]
    red = read_handoff_ci(
        Jobs({"h": [job("test", "failed"), job("lint", "canceled")], "b": [job("test")]}), "h", "b", "github"
    )
    assert red.status == "failed"  # a red job comes first: the unit is verified again
    both = read_handoff_ci(
        Jobs({"h": [job("test", "failed"), job("x", "canceled")], "b": [job("test", "failed")]}), "h", "b", "github"
    )
    assert both.status == "blocked"  # red on the base too, but the cancelled job still blocks


def test_a_manual_job_that_may_not_fail_blocks_and_an_allowed_one_passes():
    held = JobResult("deploy", "", "manual", False, 1, 1, "")
    optional = JobResult("deploy", "", "manual", True, 1, 1, "")
    assert read_handoff_ci(Jobs({"h": [job("test"), held]}), "h", "b", "gitlab").status == "blocked"
    assert read_handoff_ci(Jobs({"h": [job("test"), optional]}), "h", "b", "gitlab").status == "green"


def test_every_project_job_skipped_is_not_run():
    read = read_handoff_ci(Jobs({"h": [job("test", "skipped"), job("lint", "skipped")]}), "h", "b", "gitlab")
    assert read.status == "not_run" and read.reason == ALL_SKIPPED
    assert read_handoff_ci(Jobs({"h": [job("test", "skipped"), job("lint")]}), "h", "b", "gitlab").status == "green"


def test_a_job_named_l4_of_another_workflow_is_a_project_job():
    """F7: only the harness's own job (workflow `l4.yml`, job `l4`) is ignored."""
    ours = JobResult("l4", "", "failed", False, 1, 1, "", workflow="l4.yml")
    theirs = JobResult("l4", "", "failed", False, 1, 1, "", workflow="tests.yml")
    other_app = JobResult("l4", "", "failed", False, 1, 1, "", workflow="codecov")
    assert read_handoff_ci(Jobs({"h": [ours, job("lint")], "b": []}), "h", "b", "github").status == "green"
    for project in (theirs, other_app):
        read = read_handoff_ci(Jobs({"h": [project, job("lint")], "b": []}), "h", "b", "github")
        assert read.status == "failed" and [j.workflow for j in read.failed] == [project.workflow]


NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def test_no_ci_within_ten_minutes_of_the_hand_off_is_running_not_not_run():
    """F2 (L4-CI-014): CI that is not created yet must not read as not_run; after the window it is final."""
    soon = read_handoff_ci(Jobs({}), "h", "b", "github", ready_at=NOW - timedelta(minutes=3), now=NOW)
    assert soon.status == "running" and soon.reason == NOT_CREATED_YET
    late = read_handoff_ci(Jobs({}), "h", "b", "github", ready_at=NOW - WINDOW - timedelta(seconds=1), now=NOW)
    assert late.status == "not_run" and late.reason == NO_CHECK_RUN
    unknown = read_handoff_ci(Jobs({}), "h", "b", "github", ready_at=None, now=NOW)
    assert unknown.status == "not_run"  # no recorded time, no window


def test_every_skipped_job_also_waits_out_the_window():
    skipped = Jobs({"h": [job("test", "skipped")]})
    assert (
        read_handoff_ci(skipped, "h", "b", "gitlab", ready_at=NOW - timedelta(minutes=1), now=NOW).status == "running"
    )


class Required(Jobs):
    def required_checks(self, branch: str) -> list[str]:
        return ["build", "lint"]


def test_a_required_check_not_yet_reported_is_running_then_not_run():
    """F2: a required status check of the base branch that H has not reported yet is CI that is still to come."""
    forge = Required({"h": [job("build")]})
    soon = read_handoff_ci(forge, "h", "b", "github", base_branch="main", ready_at=NOW - timedelta(minutes=2), now=NOW)
    assert soon.status == "running" and "lint" in soon.reason
    late = read_handoff_ci(forge, "h", "b", "github", base_branch="main", ready_at=NOW - timedelta(hours=1), now=NOW)
    assert late.status == "not_run" and "lint" in late.reason
    done = read_handoff_ci(
        Required({"h": [job("build"), job("lint")]}), "h", "b", "github", base_branch="main", now=NOW
    )
    assert done.status == "green"
