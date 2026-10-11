"""`l4 ci watch` on GitHub (github-parity 4.2, L4-GHP-012, SCN-GHP-19) against a fake of the GitHub API."""

import pytest

from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.redact import Redactor

from ..setup.fake_github import REPO, TOKEN, FakeGitHub


def job(jid: int, name: str, conclusion: str | None, status: str = "completed") -> dict:
    return {"id": jid, "name": name, "status": status, "conclusion": conclusion}


@pytest.fixture
def github() -> FakeGitHub:
    gh = FakeGitHub()
    gh.add_run(500)
    return gh


@pytest.fixture
def app(tmp_path, git_environ, raw):
    repo = tmp_path / "adopter"
    repo.mkdir()
    raw(repo, "init", "-q")
    raw(repo, "remote", "add", "origin", f"https://github.com/{REPO}.git")
    return AppContext(
        repo=repo, config_path=None, log_format="human", verbosity=0, run_id="r-20261011T1000Z-0001",
        environ={**git_environ, "GH_TOKEN": TOKEN}, redactor=Redactor({}),
    )  # fmt: skip


def watch(app, gh, capsys, **options):
    from l4.ci.watch import run_ci_watch

    options = {"sleep": lambda s: None, "transport": gh.transport(), **options}
    try:
        code = run_ci_watch(app, **options)
    except L4Exit as exc:
        out = capsys.readouterr()
        return int(exc.code), out.out + out.err + str(exc)
    out = capsys.readouterr()
    return int(code), out.out + out.err


def test_a_failed_job_shows_its_conclusion_and_the_tail_of_its_log(github, app, capsys):
    """SCN-GHP-19"""
    github.script = [("completed", "failure")]
    github.jobs[500] = [job(7, "l4", "failure"), job(8, "lint", "success")]
    github.logs[7] = "\n".join(f"log line {n}" for n in range(1, 11))
    code, out = watch(app, github, capsys, ref="main", tail=3)
    assert code == 1
    assert "l4" in out and "failure" in out and "lint" in out and "success" in out
    assert "log line 10" in out and "log line 8" in out and "log line 7" not in out
    assert "log line" not in out.split("lint")[1].split("success")[0]  # the passing job has no log


def test_success_exits_zero(github, app, capsys):
    github.script = [("queued", None), ("in_progress", None), ("completed", "success")]
    github.jobs[500] = [job(7, "l4", "success")]
    code, out = watch(app, github, capsys, ref="main")
    assert code == 0
    assert "success" in out and "log" not in out.lower().replace("l4", "")


def test_polls_until_completed_with_the_injected_clock(github, app, capsys):
    github.script = [("queued", None), ("in_progress", None), ("in_progress", None), ("completed", "success")]
    github.jobs[500] = [job(7, "l4", "success")]
    sleeps: list[float] = []
    now = [0.0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    code, _ = watch(app, github, capsys, ref="main", interval="15s", sleep=sleep, clock=lambda: now[0])
    assert code == 0 and sleeps == [15.0, 15.0, 15.0]


def test_a_run_that_never_completes_times_out_with_exit_one(github, app, capsys):
    github.script = [("in_progress", None)]
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    code, out = watch(app, github, capsys, ref="main", interval="15s", timeout="1m", sleep=sleep, clock=lambda: now[0])
    assert code == 1 and "timed out" in out


def test_the_newest_run_of_the_ref_is_followed(github, app, capsys):
    github.runs[0]["conclusion"] = "failure"
    github.script = [("completed", "success")]
    newer = github.add_run(501)
    github.add_run(502, ref="other")
    github.jobs[501] = [job(9, "l4", "success")]
    code, out = watch(app, github, capsys, ref="main")
    assert code == 0 and "#501" in out and newer["status"] == "completed"
    assert any(p.endswith("/runs") for _, p in github.requests)


def test_api_url_with_a_path_prefix_and_foreign_link_headers(app, capsys):
    """A credential broker adds a path prefix; nothing is requested from another host."""
    broker = FakeGitHub(base="http://localhost:8000/v1/call/svc_1")
    broker.add_run(500)
    broker.script = [("completed", "failure")]
    broker.jobs[500] = [job(7, "l4", "failure")]
    broker.logs[7] = "boom"
    code, out = watch(app, broker, capsys, repo=REPO, ref="main", api_url=broker.base, tail=5)
    assert code == 1 and "boom" in out
    assert not broker.strays
    assert ("GET", f"/repos/{REPO}/actions/jobs/7/logs") in broker.requests


def test_the_token_never_appears(github, app, capsys):
    github.token = "another-token"
    code, out = watch(app, github, capsys, ref="main")
    assert code != 0 and TOKEN not in out


def test_the_run_the_setup_dispatched_is_followed_not_an_older_one(github, app, capsys):
    from l4.ci.watch import watch_github_run
    from l4.forge.github import GitHubForge
    from l4.setup.github import GhApi

    github.script = [("completed", "success")]
    api = GhApi("https://api.github.com", TOKEN, github.transport())
    forge = GitHubForge(REPO, TOKEN, transport=github.transport())
    lines: list[str] = []
    github.jobs[501] = [job(9, "l4", "success")]
    calls = {"n": 0}

    def sleep(seconds: float) -> None:  # the dispatched run shows up while the watcher waits
        calls["n"] += 1
        if calls["n"] == 1:
            github.add_run(501)

    result = watch_github_run(api, forge, REPO, "main", after=500, say=lines.append, sleep=sleep)
    assert result.run_id == 501 and result.exit_code == 0 and calls["n"] >= 1


def test_setup_watch_follows_the_dispatched_run(github, app, capsys, tmp_path):
    from l4.setup.github import run_setup_github

    github.script = [("queued", None), ("in_progress", None), ("completed", "success")]
    github.jobs[501] = [job(9, "l4", "success")]
    code = run_setup_github(app, watch=True, sleep=lambda s: None, transport=github.transport())
    out = capsys.readouterr().out
    assert code == ExitCode.OK and "success" in out, out
