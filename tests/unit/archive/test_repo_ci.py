"""What the project's own CI says about the hand-off commit H (forge-and-ci 2.44, L4-ARC-002 (d), M1.9 decision 8)."""

from l4.ci.repo_ci import CiVerdict, evaluate_ci
from l4.forge.base import JobResult


def job(name: str, status: str, *, allow_failure: bool = False) -> JobResult:
    return JobResult(name, "test", status, allow_failure, 1, hash(name) % 1000, f"https://forge.test/jobs/{name}")


def test_preexisting_red_job_is_not_a_finding():
    """SCN-ARC-19: red on H and on the base: not this unit's, no fix round."""
    verdict = evaluate_ci([job("always-red", "failed"), job("lint", "success")], [job("always-red", "failed")])
    assert verdict == CiVerdict("preexisting", (), (job("always-red", "failed"),))


def test_new_red_job_returns_to_verifying():
    """SCN-ARC-14: red on H and green on the base."""
    verdict = evaluate_ci([job("test", "failed"), job("always-red", "failed")], [job("test", "success"),
                                                                              job("always-red", "failed")])  # fmt: skip
    assert verdict.status == "failed"
    assert [j.name for j in verdict.failed] == ["test"] and [j.name for j in verdict.preexisting] == ["always-red"]


def test_a_running_pipeline_is_not_a_failure():
    for state in ("created", "waiting_for_resource", "preparing", "pending", "running", "scheduled"):
        assert evaluate_ci([job("test", "failed"), job("build", state)], []).status == "running"
    assert evaluate_ci([job("build", "running")], []).failed == ()


def test_the_l4_job_itself_is_ignored():
    assert evaluate_ci([job("l4", "failed"), job("test", "success")], []).status == "green"
    assert evaluate_ci([job("l4", "running"), job("test", "success")], []).status == "green"  # not even as unfinished
    assert evaluate_ci([job("l4", "failed")], [], ignore=()).status == "failed"
    assert evaluate_ci([job("harness", "failed")], [], ignore=("harness",)).status == "green"


def test_allow_failure_manual_and_canceled_jobs_are_not_red():
    jobs = [
        job("soft", "failed", allow_failure=True), job("gate", "manual"), job("old", "canceled"),
        job("skip", "skipped"), job("fine", "success"),
    ]  # fmt: skip
    assert evaluate_ci(jobs, []) == CiVerdict("green", (), ())
    assert evaluate_ci([], []).status == "green"  # no job at all: nothing red


def test_a_job_absent_on_the_base_counts():
    """No base pipeline, or none with this job: the job counts as new (a unit should not hand off red)."""
    assert evaluate_ci([job("test", "failed")], []).status == "failed"
    assert evaluate_ci([job("test", "failed")], [job("lint", "success")]).status == "failed"
    assert evaluate_ci([job("test", "failed")], [job("test", "failed", allow_failure=True)]).status == "failed"


def test_a_running_base_pipeline_defers():
    verdict = evaluate_ci([job("test", "failed")], [job("test", "running")])
    assert verdict.status == "running" and verdict.failed == ()
    assert evaluate_ci([job("test", "success")], [job("test", "running")]).status == "green"  # the base is not asked


def test_only_the_base_jobs_red_on_h_can_defer():
    """A base job that H's red jobs do not name (a slow deploy, a pages job) says nothing about them."""
    verdict = evaluate_ci([job("test", "failed")], [job("test", "success"), job("deploy", "running")])
    assert verdict.status == "failed" and [j.name for j in verdict.failed] == ["test"]
