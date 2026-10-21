"""HB-10: `run.started` says which runner and which tool versions the run had (L4-STA-001)."""

import subprocess

from l4.state.environment import run_environment


def fake_run(table: dict[str, str]):
    def run(argv, **kw):
        out = table.get(argv[0])
        if out is None:
            raise FileNotFoundError(argv[0])
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    return run


def test_the_runner_and_the_tool_versions_are_recorded():
    env = {"CI_RUNNER_ID": "12", "CI_RUNNER_DESCRIPTION": "runner-2", "PATH": "/x"}
    facts = run_environment(
        env,
        which=lambda name, path=None: f"/bin/{name}",
        run=fake_run({"/bin/git": "git version 2.43.0\n", "/bin/bwrap": "bubblewrap 0.9.0\n"}),
    )
    assert facts["runner"] == {"id": "12", "description": "runner-2"}
    assert facts["tools"]["git"] == "2.43.0" and facts["tools"]["bwrap"] == "0.9.0"
    assert facts["tools"]["python"].count(".") == 2


def test_a_tool_that_is_missing_or_prints_no_version_is_left_out_not_an_error():
    facts = run_environment({"PATH": "/x"}, which=lambda name, path=None: None, run=fake_run({}))
    assert "runner" not in facts
    assert set(facts["tools"]) == {"python"}


def test_a_failing_version_command_never_stops_the_run():
    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 5)

    facts = run_environment({}, which=lambda name, path=None: "/bin/" + name, run=boom)
    assert set(facts["tools"]) == {"python"}


def _ci(env):
    return run_environment(env, which=lambda name, path=None: None).get("ci_url")


_GH = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "owner/repo",
    "GITHUB_RUN_ID": "123",
}


def test_github_run_url_without_an_attempt_or_with_the_first():
    assert _ci(_GH) == "https://github.com/owner/repo/actions/runs/123"
    assert _ci({**_GH, "GITHUB_RUN_ATTEMPT": "1"}) == "https://github.com/owner/repo/actions/runs/123"


def test_github_run_url_with_an_attempt_above_one():
    assert _ci({**_GH, "GITHUB_RUN_ATTEMPT": "2"}) == "https://github.com/owner/repo/actions/runs/123/attempts/2"


def test_gitlab_job_url():
    env = {"GITLAB_CI": "true", "CI_JOB_URL": "https://gitlab.example.com/g/p/-/jobs/9"}
    assert _ci(env) == "https://gitlab.example.com/g/p/-/jobs/9"


def test_no_ci_has_no_ci_url():
    assert _ci({}) is None
    assert _ci({"GITHUB_SERVER_URL": "https://github.com"}) is None


def test_a_bad_part_leaves_the_key_out():
    assert _ci({**_GH, "GITHUB_REPOSITORY": "../x"}) is None
    assert _ci({**_GH, "GITHUB_RUN_ID": "12a"}) is None
    assert _ci({**_GH, "GITHUB_RUN_ATTEMPT": "x"}) is None
    assert _ci({**_GH, "GITHUB_SERVER_URL": "http://github.com"}) is None
    assert _ci({"GITLAB_CI": "true", "CI_JOB_URL": "not a url"}) is None


def test_a_server_url_with_a_user_part_leaves_the_key_out():
    assert _ci({**_GH, "GITHUB_SERVER_URL": "https://user:pw@github.com"}) is None
    assert _ci({"GITLAB_CI": "true", "CI_JOB_URL": "https://tok@gitlab.example.com/j/1"}) is None
