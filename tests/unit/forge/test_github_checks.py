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
        "optional": "skipped", "gate": "failed", "approve": "manual",  # action_required: held for a person (m6)
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
    listings = [query for _, path, query, _ in github.requests if path.endswith("/check-runs")]
    assert listings[-1].get("filter") == "all"  # not only the latest run of each check suite


def _tests_and_docs(github: FakeGitHub) -> None:
    """On SHA, `build` of tests.yml fails (suite 1) and `build` of docs.yml passes (suite 2, the newer check run)."""
    github.add_workflow_run(SHA, "tests.yml", "push", suite=1)
    github.add_workflow_run(SHA, "docs.yml", "push", suite=2)
    github.add_check_run(SHA, "build", "completed", "failure", suite=1, app="github-actions")
    github.add_check_run(SHA, "build", "completed", "success", suite=2, app="github-actions")


def test_a_rerun_collapses_to_its_newest_attempt(github, forge):
    """SCN-CI-052: attempt 1 failed, attempt 2 passed in the same check suite (a re-run keeps its suite): one job."""
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


@pytest.mark.parametrize(
    ("conclusion", "status"),
    [
        ("success", "success"), ("neutral", "skipped"), ("skipped", "skipped"),
        ("failure", "failed"), ("timed_out", "failed"), ("startup_failure", "failed"),
        ("action_required", "manual"), ("stale", "failed"), ("cancelled", "canceled"),
    ],
)  # fmt: skip
def test_a_conclusion_is_a_pass_a_failure_or_a_cancellation(github, forge, conclusion, status):
    """F1 (L4-CI-013): only success, neutral and skipped pass; a conclusion that did not pass is red, a cancellation
    is its own status; the reader never calls a job that did not pass green."""
    github.add_check_run(SHA, "test", "completed", conclusion, suite=1, app="github-actions")
    (job,) = forge.list_pipeline_jobs(SHA)
    assert job.status == status


def test_a_workflow_run_that_is_not_completed_is_a_running_job_even_without_check_runs(github, forge):
    """F2 (SCN-CI-062, L4-CI-014): GitHub has not created the check runs of a queued run yet; the run itself is read."""
    github.add_workflow_run(SHA, "tests.yml", "push", suite=1, status="queued")
    (job,) = forge.list_pipeline_jobs(SHA)
    assert job.status == "pending" and job.workflow == "tests.yml" and job.event == "push"


def test_an_unfinished_workflow_run_is_running_though_its_created_jobs_passed(github, forge):
    """F2: a `needs:` job that is not created yet; the run's own status says the CI is not finished."""
    github.add_workflow_run(SHA, "tests.yml", "push", suite=1, status="in_progress")
    github.add_check_run(SHA, "build", "completed", "success", suite=1, app="github-actions")
    jobs = forge.list_pipeline_jobs(SHA)
    assert sorted(j.status for j in jobs) == ["running", "success"]


def test_the_harness_own_workflow_run_is_never_a_running_job(github, forge):
    """The sweep runs inside `l4.yml`: its own unfinished run must not hold the verdict back."""
    github.add_workflow_run(SHA, "l4.yml", "push", suite=1, status="in_progress")
    assert forge.list_pipeline_jobs(SHA) == []


def test_commit_statuses_are_jobs_except_the_harness_own(github, forge):
    """F5 (SCN-CI-066, L4-CI-015): a CI that reports commit statuses is read; `l4/*` contexts are the harness's own."""
    github.add_status(SHA, "ci/jenkins", "failure")
    github.add_status(SHA, "ci/lint", "success")
    github.add_status(SHA, "ci/slow", "pending")
    github.add_status(SHA, "ci/boom", "error")
    github.add_status(SHA, "l4/add-x", "pending")
    github.add_status("b" * 40, "ci/other", "failure")
    jobs = {j.key: j.status for j in forge.list_pipeline_jobs(SHA)}
    assert jobs == {
        "status / ci/jenkins": "failed", "status / ci/lint": "success", "status / ci/slow": "pending",
        "status / ci/boom": "failed",
    }  # fmt: skip


def test_same_name_check_runs_of_one_suite_that_are_not_attempts_stay_distinct(github, forge):
    """F6 (SCN-CI-068, L4-CI-010): a reporter's `Test Results` check runs are not jobs of the run; a failed one is not
    hidden by a passing one of the same name in the same suite."""
    run = github.add_workflow_run(SHA, "tests.yml", "push", suite=1)
    job = github.add_check_run(SHA, "test", "completed", "success", suite=1, app="github-actions")
    github.add_job(run["id"], job)
    github.add_check_run(SHA, "Test Results", "completed", "failure", suite=1, app="github-actions")
    github.add_check_run(SHA, "Test Results", "completed", "success", suite=1, app="github-actions")
    jobs = forge.list_pipeline_jobs(SHA)
    assert sorted(j.status for j in jobs) == ["failed", "success", "success"]
    assert [j.key for j in red_jobs(jobs)] == ["tests.yml / Test Results"]


def test_a_superseded_execution_of_a_job_is_dropped_by_the_latest_jobs_listing(github, forge):
    """F6: a re-run job's earlier execution is in `jobs?filter=all` but not in `filter=latest`."""
    run = github.add_workflow_run(SHA, "tests.yml", "push", suite=31, run_id=900, attempts=(31,))
    old = github.add_check_run(SHA, "test", "completed", "failure", suite=31, app="github-actions")
    new = github.add_check_run(SHA, "test", "completed", "success", suite=31, app="github-actions")
    github.add_job(run["id"], old, latest=False)
    github.add_job(run["id"], new)
    (job,) = forge.list_pipeline_jobs(SHA)
    assert job.status == "success" and job.job_id == new["id"]


def test_required_checks_come_from_the_rules_the_branch_and_the_classic_protection(github, forge):
    """F2, m2 (SCN-CI-064): the required status checks of the base branch from the three places GitHub keeps them."""
    github.rules = [
        {"type": "pull_request", "parameters": {}},
        {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "build"}]}},
    ]
    assert forge.required_checks("main") == (["build"], False)
    github.rules = None
    github.branch = {"protected": True, "protection": {"required_status_checks": {"contexts": ["lint"], "checks": [
        {"context": "lint"}, {"context": "test"}]}}}  # fmt: skip
    assert forge.required_checks("main") == (["lint", "test"], False)
    github.branch = None
    github.protection = {"contexts": ["unit"], "checks": [{"context": "unit"}]}
    assert forge.required_checks("main") == (["unit"], False)  # the classic endpoint when the branch read gives nothing
    github.protection = None
    assert forge.required_checks("main") == ([], False)  # nothing required, not an error


def test_required_checks_that_every_endpoint_refuses_are_reported_unreadable(github, forge):
    """m2: a 403 from every endpoint is not fatal, but the caller is told."""
    github.rules_status = 403
    github.branch_status = 403
    assert forge.required_checks("main") == ([], True)


def test_the_workflow_files_of_the_repository_are_listed(github, forge):
    github.workflows = ["l4.yml", "tests.yml"]
    assert forge.workflow_files() == ["l4.yml", "tests.yml"]
    github.workflows_status = 403
    assert forge.workflow_files() is None


@pytest.mark.parametrize(
    ("conclusion", "verdict"),
    [("cancelled", "blocked"), ("action_required", "blocked"), ("stale", "failed"), ("timed_out", "failed")],
)
def test_the_reader_does_not_call_a_job_that_did_not_pass_green(github, forge, conclusion, verdict):
    """The review's R1 (SCN-CI-061): the only project job was cancelled, needs action or went stale."""
    from l4.ci.handoff_ci import read_handoff_ci

    github.add_workflow_run(SHA, "tests.yml", "push", suite=1)
    github.add_check_run(SHA, "test", "completed", conclusion, suite=1, app="github-actions")
    assert read_handoff_ci(forge, SHA, "b" * 40, "github").status == verdict


def test_the_reader_waits_for_a_queued_run_a_run_in_progress_and_a_pending_status(github, forge):
    """The review's R2, R3 and R4 (SCN-CI-062, SCN-CI-063, SCN-CI-066)."""
    from l4.ci.handoff_ci import read_handoff_ci

    run = github.add_workflow_run(SHA, "tests.yml", "push", suite=1, status="queued")
    assert read_handoff_ci(forge, SHA, "b" * 40, "github").status == "running"  # R2
    run["status"] = "in_progress"
    github.add_check_run(SHA, "build", "completed", "success", suite=1, app="github-actions")
    assert read_handoff_ci(forge, SHA, "b" * 40, "github").status == "running"  # R3
    run["status"] = "completed"
    assert read_handoff_ci(forge, SHA, "b" * 40, "github").status == "green"
    github.add_status(SHA, "ci/jenkins", "failure")  # R4
    assert read_handoff_ci(forge, SHA, "b" * 40, "github").status == "failed"


def test_a_failed_job_named_l4_in_another_workflow_is_a_project_job(github, forge):
    """The review's R6 (SCN-CI-067): only `l4.yml`'s `l4` job is the harness's own."""
    from l4.ci.handoff_ci import read_handoff_ci

    github.add_workflow_run(SHA, "tests.yml", "push", suite=1)
    github.add_check_run(SHA, "l4", "completed", "failure", suite=1, app="github-actions")
    github.add_check_run(SHA, "lint", "completed", "success", suite=1, app="github-actions")
    assert read_handoff_ci(forge, SHA, "b" * 40, "github").status == "failed"
    github.check_runs.clear()
    github.workflow_runs.clear()
    github.add_workflow_run(SHA, "l4.yml", "push", suite=2)
    github.add_check_run(SHA, "l4", "completed", "failure", suite=2, app="github-actions")
    github.add_check_run(SHA, "lint", "completed", "success", suite=2, app="github-actions")
    assert read_handoff_ci(forge, SHA, "b" * 40, "github").status == "green"


def test_a_check_run_of_another_app_that_needs_action_blocks_and_opens_no_fix_round(github, forge):
    """m6 (L4-CI-013): action_required (a CLA, an app's approval) is a person's to do, not a code fix."""
    from l4.ci.handoff_ci import read_handoff_ci

    github.add_workflow_run(SHA, "tests.yml", "push", suite=1)
    github.add_check_run(SHA, "test", "completed", "success", suite=1, app="github-actions")
    github.add_check_run(SHA, "cla", "completed", "action_required", suite=9, app="cla-bot")
    read = read_handoff_ci(forge, SHA, "b" * 40, "github")
    assert read.status == "blocked" and [j.key for j in read.blocked] == ["cla-bot / cla"] and not read.failed


def test_check_runs_are_read_with_filter_all(github, forge):
    """m5: the default listing keeps one check run per name and suite and would hide a same-name twin."""
    github.add_check_run(SHA, "test", "completed", "success", suite=1)
    forge.list_pipeline_jobs(SHA)
    listings = [query for _, path, query, _ in github.requests if path.endswith("/check-runs")]
    assert listings[-1].get("filter") == "all"


def _quiet_base(github, l4_runs: int = 48) -> str:
    """H: one workflow with two jobs and the skipped `l4` run; the base: one CI run and a day of scheduled `l4.yml`
    runs (the review's N9)."""
    base = "b" * 40
    run = github.add_workflow_run(SHA, "tests.yml", "push", suite=1)
    for name in ("build", "test"):
        github.add_job(
            run["id"], github.add_check_run(SHA, name, "completed", "success", suite=1, app="github-actions")
        )
    ours = github.add_workflow_run(SHA, "l4.yml", "push", suite=2)
    github.add_job(ours["id"], github.add_check_run(SHA, "l4", "skipped", None, suite=2, app="github-actions"))
    there = github.add_workflow_run(base, "tests.yml", "push", suite=10)
    github.add_job(
        there["id"], github.add_check_run(base, "build", "completed", "success", suite=10, app="github-actions")
    )
    for i in range(l4_runs):
        r = github.add_workflow_run(base, "l4.yml", "schedule", suite=100 + i)
        github.add_job(
            r["id"], github.add_check_run(base, "l4", "completed", "success", suite=100 + i, app="github-actions")
        )
    github.rules = []
    return base


def test_one_ci_read_of_a_green_commit_makes_few_calls(github, forge):
    """M1 (SCN-CI-069): the jobs of `l4.yml` runs are never listed and the base is read only when H has a red job.
    The review counted 110 calls for this read."""
    from l4.ci.handoff_ci import read_handoff_ci

    base = _quiet_base(github)
    before = len(github.requests)
    read = read_handoff_ci(forge, SHA, base, "github", base_branch="main")
    calls = len(github.requests) - before
    assert read.status == "green" and calls <= 10, calls


def test_one_ci_read_with_a_red_job_is_bounded(github, forge):
    """M1: a red job makes the base comparison read the base too, still without the jobs of its `l4.yml` runs."""
    from l4.ci.handoff_ci import read_handoff_ci

    base = _quiet_base(github)
    github.add_check_run(SHA, "lint", "completed", "failure", suite=1, app="github-actions")
    github.add_job(github.workflow_runs[0]["id"], github.check_runs[-1])
    before = len(github.requests)
    read = read_handoff_ci(forge, SHA, base, "github", base_branch="main")
    calls = len(github.requests) - before
    assert read.status == "failed" and calls <= 20, calls


def _job_of(github, run, name, conclusion, suite, sha=SHA):
    check = github.add_check_run(sha, name, "completed", conclusion, suite=suite, app="github-actions")
    github.add_job(run["id"], check)


def test_a_cancelled_push_run_whose_pull_request_twin_was_skipped_is_not_run(github, forge):
    """X1 (SCN-CI-061): the double-run guard skips `build` on the PR run, a shared concurrency group cancels the push
    run: nothing ran `build`, so H is `not_run`, never green."""
    from l4.ci.handoff_ci import read_handoff_ci

    push = github.add_workflow_run(SHA, "tests.yml", "push", suite=1)
    pr = github.add_workflow_run(SHA, "tests.yml", "pull_request", suite=2)
    _job_of(github, push, "build", "cancelled", 1)
    _job_of(github, pr, "build", "skipped", 2)
    read = read_handoff_ci(forge, SHA, "b" * 40, "github", base_branch="main")
    assert read.status == "not_run" and not read.blocked


def test_a_cancelled_push_run_alone_still_blocks(github, forge):
    from l4.ci.handoff_ci import read_handoff_ci

    push = github.add_workflow_run(SHA, "tests.yml", "push", suite=1)
    _job_of(github, push, "build", "cancelled", 1)
    assert read_handoff_ci(forge, SHA, "b" * 40, "github", base_branch="main").status == "blocked"


def test_a_ci_app_on_the_base_keeps_the_window(github, forge):
    """X2 (SCN-CI-064): only `l4.yml` and nothing required, but a CI app reports on the base head."""
    from datetime import UTC, datetime, timedelta

    from l4.ci.handoff_ci import read_handoff_ci

    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    base = "b" * 40
    github.workflows = ["l4.yml"]
    github.add_check_run(base, "build", "completed", "success", suite=50, app="circleci-checks")
    read = read_handoff_ci(forge, SHA, base, "github", base_branch="main", ready_at=now - timedelta(minutes=1), now=now)
    assert read.status == "running"
    github.check_runs.clear()
    github.add_status(base, "ci/jenkins", "success")
    read = read_handoff_ci(forge, SHA, base, "github", base_branch="main", ready_at=now - timedelta(minutes=1), now=now)
    assert read.status == "running"
    github.statuses.clear()
    github.add_status(base, "l4/add-x", "pending")  # the harness's own status is no CI
    read = read_handoff_ci(forge, SHA, base, "github", base_branch="main", ready_at=now - timedelta(minutes=1), now=now)
    assert read.status == "not_run"


def test_a_required_check_with_no_job_at_all_blocks_after_the_window(github, forge):
    """X4 (SCN-CI-064): a push made with GITHUB_TOKEN started nothing and `build` is required."""
    from datetime import UTC, datetime, timedelta

    from l4.ci.handoff_ci import read_handoff_ci

    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    github.workflows = ["l4.yml", "tests.yml"]
    github.rules = [
        {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "build"}]}}
    ]
    read = read_handoff_ci(
        forge, SHA, "b" * 40, "github", base_branch="main", ready_at=now - timedelta(hours=1), now=now
    )
    assert read.status == "unreported" and read.reason == "build"
