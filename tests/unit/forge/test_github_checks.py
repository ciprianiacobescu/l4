"""The check runs of a commit are the jobs of the project's own CI on GitHub (forge-and-ci 2.9 check-run part)."""

import logging

import pytest

from l4.ci.repo_ci import red_jobs
from l4.forge.base import JobResult
from l4.forge.github import GitHubForge

from ._github_helpers import API, REPO, TOKEN, FakeGitHub

SHA = "a" * 40


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def forge(github) -> GitHubForge:
    return GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)


def test_check_runs_of_sha_become_job_results(github, forge):
    github.page_size = 2
    github.add_check_run(SHA, "lint", "completed", "success")
    github.add_check_run(SHA, "test", "completed", "failure", suite=77)
    github.add_check_run(SHA, "build", "in_progress", None)
    github.add_check_run(SHA, "docs", "queued", None)
    github.add_check_run(SHA, "deploy", "completed", "cancelled")
    github.add_check_run(SHA, "optional", "completed", "neutral")
    github.add_check_run(SHA, "gate", "completed", "timed_out")
    github.add_check_run(SHA, "approve", "completed", "action_required")
    github.add_check_run("b" * 40, "other", "completed", "failure")
    github.add_check_run(SHA, "test", "completed", "success", suite=78)  # a rerun: the newest check run of a name wins
    jobs = {j.name: j for j in forge.list_pipeline_jobs(SHA)}
    assert {n: j.status for n, j in jobs.items()} == {
        "lint": "success", "test": "success", "build": "running", "docs": "pending", "deploy": "canceled",
        "optional": "skipped", "gate": "failed", "approve": "manual",
    }  # fmt: skip
    assert jobs["test"].pipeline_id == 78 and jobs["test"].allow_failure is False and jobs["test"].stage == ""
    assert isinstance(jobs["lint"], JobResult) and jobs["lint"].web_url.startswith("https://github.test/")
    assert github.writes() == []
    assert forge.list_pipeline_jobs("c" * 40) == []


def test_log_redirect_is_followed_without_the_token(github, forge):
    log = "\x1b[31mboom\x1b[0m\n" + "x\n" * 100 + "FAILED"
    run = github.add_check_run(SHA, "test", "completed", "failure", log=log)
    tail = forge.job_log_tail(run["id"], 20)
    assert tail.splitlines()[-1] == "FAILED" and len(tail.splitlines()) == 20 and "\x1b" not in tail
    hosts = github.hosts_seen
    assert ("api.github.test", True) in hosts and ("logs.example.test", False) in hosts  # the token stayed home
    assert forge.job_log_tail(999999, 20) == ""  # no logs (expired, or not an Actions job): no evidence
    github.redirect_to = "http://logs.example.test/plain"  # a downgrade is never followed
    assert forge.job_log_tail(run["id"], 20) == ""


def test_settled_reads_every_check_run_and_keeps_the_newest_finished_one(github, forge):
    github.add_check_run(SHA, "test", "completed", "failure", suite=10)
    github.add_check_run(SHA, "test", "in_progress", None, suite=11)
    github.add_check_run(SHA, "build", "queued", None, suite=11)
    assert {j.name: j.status for j in forge.list_pipeline_jobs(SHA)} == {"test": "running", "build": "pending"}
    settled = {j.name: j for j in forge.list_pipeline_jobs(SHA, settled=True)}
    assert {n: j.status for n, j in settled.items()} == {"test": "failed", "build": "pending"}
    assert settled["test"].pipeline_id == 10
    assert github.requests[-1][2].get("filter") == "all"  # not only the latest run of each check suite


def _tests_and_docs(github: FakeGitHub) -> None:
    """On SHA, `build` of tests.yml fails (suite 1) and `build` of docs.yml passes (suite 2, the newer check run)."""
    github.add_workflow_run(SHA, "tests.yml", "push", suite=1)
    github.add_workflow_run(SHA, "docs.yml", "push", suite=2)
    github.add_check_run(SHA, "build", "completed", "failure", suite=1, app="github-actions")
    github.add_check_run(SHA, "build", "completed", "success", suite=2, app="github-actions")


@pytest.mark.parametrize("new_suite", [False, True])
def test_a_rerun_collapses_whether_or_not_it_has_a_new_suite(github, forge, new_suite):
    """SCN-CI-052: attempt 1 failed, attempt 2 passed; one job `tests.yml / test`, the newest attempt."""
    if new_suite:
        github.add_workflow_run(SHA, "tests.yml", "push", suite=32, run_id=900, attempts=(31,))
        github.add_check_run(SHA, "test", "completed", "failure", suite=31, app="github-actions")
        github.add_check_run(SHA, "test", "completed", "success", suite=32, app="github-actions")
    else:
        github.add_workflow_run(SHA, "tests.yml", "push", suite=31, run_id=900, attempts=(31,))
        github.add_check_run(SHA, "test", "completed", "failure", suite=31, app="github-actions")
        github.add_check_run(SHA, "test", "completed", "success", suite=31, app="github-actions")
    (job,) = forge.list_pipeline_jobs(SHA)
    assert job.key == "tests.yml / test" and job.status == "success"


def test_a_failed_job_is_not_hidden_behind_the_same_name_of_another_workflow(github, forge):
    """SCN-CI-051 at the forge: two jobs, and the red one is `tests.yml / build`."""
    _tests_and_docs(github)
    jobs = forge.list_pipeline_jobs(SHA)
    assert {j.key for j in jobs} == {"tests.yml / build", "docs.yml / build"}
    assert [j.key for j in red_jobs(jobs)] == ["tests.yml / build"]


def test_push_and_pull_request_runs_are_two_jobs(github, forge):
    """SCN-CI-053"""
    github.add_workflow_run(SHA, "tests.yml", "push", suite=41)
    github.add_workflow_run(SHA, "tests.yml", "pull_request", suite=42)
    github.add_check_run(SHA, "build", "completed", "success", suite=41, app="github-actions")
    github.add_check_run(SHA, "build", "completed", "failure", suite=42, app="github-actions")
    jobs = forge.list_pipeline_jobs(SHA)
    assert [j.key for j in jobs] == ["tests.yml / build", "tests.yml / build"]
    assert {j.event for j in jobs} == {"push", "pull_request"}
    (red,) = red_jobs(jobs)
    assert red.event == "pull_request"


def test_a_check_run_of_another_app_is_keyed_by_its_slug(github, forge):
    """SCN-CI-054"""
    github.add_workflow_run(SHA, "tests.yml", "push", suite=1)
    github.add_check_run(SHA, "build", "completed", "failure", suite=9, app="codecov")
    github.add_check_run(SHA, "build", "completed", "success", suite=1, app="github-actions")
    jobs = forge.list_pipeline_jobs(SHA)
    assert {j.key for j in jobs} == {"codecov / build", "tests.yml / build"}
    (red,) = red_jobs(jobs)
    assert red.key == "codecov / build"


def test_an_unreadable_workflow_listing_keys_actions_runs_by_suite(github, forge, caplog):
    """SCN-CI-055"""
    _tests_and_docs(github)
    github.workflow_runs_status = 403
    with caplog.at_level(logging.WARNING):
        jobs = forge.list_pipeline_jobs(SHA)
    assert {j.workflow for j in jobs} == {"suite-1", "suite-2"}
    assert [j.status for j in red_jobs(jobs)] == ["failed"]
    assert sum("could not be read" in r.getMessage() for r in caplog.records) == 1


def test_an_actions_check_run_whose_workflow_is_not_found_is_keyed_by_its_suite(github, forge):
    github.add_workflow_run(SHA, "tests.yml", "push", suite=1)
    github.add_check_run(SHA, "build", "completed", "success", suite=1, app="github-actions")
    github.add_check_run(SHA, "build", "completed", "failure", suite=7, app="github-actions")
    assert {j.workflow for j in forge.list_pipeline_jobs(SHA)} == {"tests.yml", "suite-7"}


def test_an_unreadable_attempt_drops_only_its_suite(github, forge):
    """An attempt read that gives 403 leaves that attempt's check runs keyed by suite (fail closed)."""
    github.add_workflow_run(SHA, "tests.yml", "push", suite=32, run_id=900, attempts=(31,))
    github.add_check_run(SHA, "test", "completed", "failure", suite=31, app="github-actions")
    github.add_check_run(SHA, "test", "completed", "success", suite=32, app="github-actions")
    github.attempts_status = 403
    assert {j.workflow for j in forge.list_pipeline_jobs(SHA)} == {"suite-31", "tests.yml"}
