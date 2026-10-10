"""The check runs of a commit are the jobs of the project's own CI on GitHub (forge-and-ci 2.9 check-run part)."""

import pytest

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
