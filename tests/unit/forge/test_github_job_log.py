"""`GitHubForge.job_log`: the failing step's excerpt and its name (ci-evidence D2; L4-VER-061)."""

from pathlib import Path

import pytest
from tests.unit.forge._github_helpers import API, REPO, TOKEN, FakeGitHub

from l4.forge.github import GitHubForge

SHA = "a" * 40
LOG = (Path(__file__).resolve().parents[2] / "fixtures" / "ci_logs" / "github-pytest-failure.log").read_text(
    encoding="utf-8"
)
STEPS = [
    {"name": "Set up job", "conclusion": "success", "started_at": "2026-10-20T10:00:00.000Z"},
    {"name": "Run actions/checkout@v4", "conclusion": "success", "started_at": "2026-10-20T10:00:05.000Z"},
    {"name": "tests", "conclusion": "failure", "started_at": "2026-10-20T10:00:19.000Z"},
    {"name": "Post Run actions/checkout@v4", "conclusion": "success", "started_at": "2026-10-20T10:04:04.000Z"},
]


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def forge(github: FakeGitHub) -> GitHubForge:
    return GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)


def job_reads(github: FakeGitHub) -> list[str]:
    return [
        p for m, p, _, _ in github.requests if m == "GET" and p.endswith(f"/actions/jobs/{github.check_runs[0]['id']}")
    ]


def test_job_log_is_the_failing_steps_excerpt_and_names_it(github, forge):
    run = github.add_check_run(SHA, "tests", "completed", "failure", log=LOG, steps=STEPS)
    result = forge.job_log(run["id"])
    assert result.step is None and result.failed_step == "tests"
    assert result.tail.split("\n")[0] == "Run uv run pytest -q"
    assert "FAILED tests/test_cli.py::test_help" in result.tail
    assert result.tail.endswith("Error: Process completed with exit code 1.")
    assert "Post job cleanup." not in result.tail and "Node.js 20" not in result.tail
    assert forge.job_log_tail(run["id"]) == result.tail


def test_the_steps_are_read_with_the_token_and_the_log_without_it(github, forge):
    run = github.add_check_run(SHA, "tests", "completed", "failure", log=LOG, steps=STEPS)
    forge.job_log(run["id"])
    assert ("api.github.test", True) in github.hosts_seen and ("logs.example.test", False) in github.hosts_seen
    assert len(job_reads(github)) == 1


@pytest.mark.parametrize("status", [403, 500])
def test_a_refused_steps_read_keeps_the_log(github, forge, status):
    run = github.add_check_run(SHA, "tests", "completed", "failure", log=LOG, steps=STEPS)
    github.jobs_status = status
    result = forge.job_log(run["id"])
    assert result.tail.split("\n")[0] == "Run uv run pytest -q"
    assert result.failed_step == "Run uv run pytest -q"  # the header, the API gave no name
    assert "FAILED tests/test_cli.py::test_help" in result.tail


def test_no_log_reads_no_steps(github, forge):
    github.add_check_run(SHA, "tests", "completed", "failure", steps=STEPS)  # a job without a log
    result = forge.job_log(github.check_runs[0]["id"])
    assert result.tail == "" and result.failed_step is None
    assert job_reads(github) == []
    assert forge.job_log(999999).tail == ""


def test_steps_listed_with_the_run_jobs_are_not_read_again(github, forge):
    run = github.add_check_run(
        SHA, "tests", "completed", "failure", suite=11, log=LOG, steps=STEPS, app="github-actions"
    )
    github.add_workflow_run(SHA, "ci.yml", "push", suite=11, run_id=900)
    github.add_job(900, run)
    github.list_steps = True
    forge.list_pipeline_jobs(SHA)
    result = forge.job_log(run["id"])
    assert result.failed_step == "tests"
    assert job_reads(github) == []
    # a listing without steps falls back to the read
    other = FakeGitHub()
    again = GitHubForge(REPO, TOKEN, api_url=API, transport=other.transport(), sleep=lambda s: None)
    run2 = other.add_check_run(
        SHA, "tests", "completed", "failure", suite=11, log=LOG, steps=STEPS, app="github-actions"
    )
    other.add_workflow_run(SHA, "ci.yml", "push", suite=11, run_id=900)
    other.add_job(900, run2)
    again.list_pipeline_jobs(SHA)
    assert again.job_log(run2["id"]).failed_step == "tests"
    assert len([p for m, p, _, _ in other.requests if p.endswith(f"/actions/jobs/{run2['id']}")]) == 1
