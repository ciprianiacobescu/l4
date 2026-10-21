"""`l4 ci watch` (M1.8 A13): follow a GitLab pipeline to its end, with an injected clock and sleep."""

import httpx
import pytest

from l4.ci.watch import watch_pipeline
from l4.forge.gitlab_admin import AdminApi

from ..setup.conftest import API, MAINTAINER, FakeGitLab  # the fake server of the setup tests


@pytest.fixture
def gitlab() -> FakeGitLab:  # this module's own fake: the one conftest.py provides is the forge's, not setup's
    return FakeGitLab()


def job(jid: int, name: str, status: str, *, stage: str = "test", allow_failure: bool = False) -> dict:
    return {
        "id": jid, "name": name, "stage": stage, "status": status, "allow_failure": allow_failure,
        "runner": {"id": 12, "description": "l4-runner"},
    }  # fmt: skip


class Clock:
    """Time that only moves when the watcher sleeps; each sleep also applies the next scripted state."""

    def __init__(self, gitlab: FakeGitLab, pipeline_id: int, script: list[tuple[str, list[dict]]]) -> None:
        self.now, self.gl, self.pid, self.script, self.sleeps = 0.0, gitlab, pipeline_id, list(script), []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        if self.script:
            self.apply(self.script.pop(0))

    def apply(self, state: tuple[str, list[dict]]) -> None:
        status, jobs = state
        next(p for p in self.gl.pipelines if p["id"] == self.pid)["status"] = status
        self.gl.jobs[self.pid] = jobs


@pytest.fixture
def watched(gitlab):
    gitlab.pipelines.append({"id": 77, "status": "pending", "ref": "main", "web_url": "https://x.test/p/77"})

    def start(first: tuple[str, list[dict]], *rest: tuple[str, list[dict]]):
        clock = Clock(gitlab, 77, list(rest))
        clock.apply(first)
        api = AdminApi(API, MAINTAINER, transport=gitlab.transport())
        lines: list[str] = []

        def watch(**kw):
            options = {"interval": 15.0, "timeout": 5400.0, "tail": 0, "sleep": clock.sleep, "clock": clock.monotonic}
            return watch_pipeline(api, "119", 77, say=lines.append, **{**options, **kw})

        return watch, lines, clock

    return start


def test_one_line_per_status_change(watched):
    watch, lines, clock = watched(
        ("pending", [job(1, "test", "pending"), job(2, "l4", "created", stage=".post")]),
        ("running", [job(1, "test", "running"), job(2, "l4", "created", stage=".post")]),
        ("running", [job(1, "test", "running"), job(2, "l4", "created", stage=".post")]),  # nothing changed
        ("running", [job(1, "test", "success"), job(2, "l4", "running", stage=".post")]),
        ("success", [job(1, "test", "success"), job(2, "l4", "success", stage=".post")]),
    )
    result = watch()
    assert result.ok and result.status == "success"
    changes = [line for line in lines if line.startswith("job ")]
    assert changes == [
        "job 1 test (test) pending — runner #12 l4-runner",
        "job 2 l4 (.post) created — runner #12 l4-runner",
        "job 1 test (test) running — runner #12 l4-runner",
        "job 1 test (test) success — runner #12 l4-runner",
        "job 2 l4 (.post) running — runner #12 l4-runner",
        "job 2 l4 (.post) success — runner #12 l4-runner",
    ]
    assert clock.sleeps == [15.0] * 4  # one sleep between two polls, the interval
    assert any(line.startswith("pipeline #77") and "success" in line for line in lines)


def test_allowed_failure_is_success(watched):
    watch, lines, _ = watched(
        ("success", [job(1, "test", "success"), job(2, "l4", "failed", stage=".post", allow_failure=True)])
    )
    result = watch()
    assert result.ok and result.exit_code == 0
    assert any("job 2 l4 (.post) failed (allowed)" in line for line in lines)  # the line says it was allowed
    table = [line for line in lines if line.startswith("  ")]
    assert any("l4" in row and "failed (allowed)" in row for row in table)


def test_a_failed_pipeline_exits_1_and_a_real_failure_is_not_allowed(watched):
    watch, lines, _ = watched(("failed", [job(1, "test", "failed"), job(2, "l4", "skipped", stage=".post")]))
    result = watch()
    assert not result.ok and result.exit_code == 1
    assert any("job 1 test (test) failed — " in line and "(allowed)" not in line for line in lines)


def test_timeout_exits_1(watched):
    watch, lines, clock = watched(
        ("running", [job(1, "test", "running")]), *[("running", [job(1, "test", "running")])] * 50
    )
    result = watch(timeout=60.0, interval=20.0)
    assert not result.ok and result.exit_code == 1 and result.status == "timeout"
    assert clock.now == 60.0 and any("timed out after 60 s" in line for line in lines)


def test_tail_prints_the_failed_jobs_trace_tail_only(watched, gitlab):
    gitlab.traces[1] = "\n".join(f"\x1b[31mline {n}\x1b[0m" for n in range(100))
    gitlab.traces[2] = "the passing job's trace must not appear"
    watch, lines, _ = watched(("failed", [job(1, "test", "failed"), job(2, "lint", "success")]))
    watch(tail=5)
    shown = [line for line in lines if line.startswith("    | ")]
    assert [line.removeprefix("    | ") for line in shown] == [f"line {n}" for n in range(95, 100)]  # ANSI stripped
    assert not any("passing job" in line for line in lines)
    watch2, lines2, _ = watched(("failed", [job(1, "test", "failed")]))
    watch2(tail=0)
    assert not any(line.startswith("    | ") for line in lines2)


def test_a_missing_pipeline_is_an_error(gitlab):
    api = AdminApi(API, MAINTAINER, transport=gitlab.transport())
    from l4.forge.gitlab_admin import AdminError

    with pytest.raises(AdminError):
        watch_pipeline(api, "119", 4040, say=lambda line: None, sleep=lambda s: None)


def test_transport_errors_are_retried_not_fatal(gitlab):
    gitlab.pipelines.append({"id": 78, "status": "success", "ref": "main", "web_url": "x"})
    gitlab.jobs[78] = [job(1, "test", "success")]
    calls = {"n": 0}
    inner = gitlab.transport()

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("blip")
        return inner.handle_request(request)

    api = AdminApi(API, MAINTAINER, transport=httpx.MockTransport(flaky))
    result = watch_pipeline(api, "119", 78, say=lambda line: None, sleep=lambda s: None)
    assert result.ok and calls["n"] > 1


# --- the command ---------------------------------------------------------------------------------------------------


@pytest.fixture
def cli(gitlab, tmp_path, git_environ, monkeypatch, capsys):
    from l4.cli import main
    from l4.setup import gitlab as module

    monkeypatch.setattr(module, "TRANSPORT", gitlab.transport())
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args: str, **env: str) -> tuple[int, str]:
        environ = {**git_environ, "GITLAB_TOKEN": MAINTAINER, **env}
        code = main(["ci", "watch", "--repo", str(repo), "--api-base", API, *args], environ=environ)
        out = capsys.readouterr()
        return code, out.out + out.err

    return run


def test_the_command_follows_a_pipeline_and_exits_0_or_1(gitlab, cli):
    gitlab.pipelines.append({"id": 90, "status": "success", "ref": "main", "web_url": "u"})
    gitlab.jobs[90] = [job(1, "test", "success")]
    code, out = cli("--project", "example-group/sample-consumer", "--pipeline", "90", "--interval", "1s")
    assert code == 0 and "pipeline #90 success -> exit 0" in out and MAINTAINER not in out
    gitlab.pipelines.append({"id": 91, "status": "failed", "ref": "main", "web_url": "u"})
    gitlab.jobs[91] = [job(1, "test", "failed")]
    gitlab.traces[1] = "a\nb\nc"
    code, out = cli("--project", "119", "--ref", "main", "--tail", "2")  # the latest pipeline of main
    assert code == 1 and "pipeline #91 failed" in out and "    | b" in out and "    | a" not in out


def test_the_default_branch_is_used_without_a_ref_and_none_found_is_exit_1(gitlab, cli):
    code, out = cli("--project", "119")
    assert code == 1 and "no pipeline found on main" in out
    gitlab.pipelines.append({"id": 92, "status": "success", "ref": "main", "web_url": "u"})
    gitlab.jobs[92] = [job(1, "test", "success")]
    assert cli("--project", "119")[0] == 0


def test_usage_errors_are_exit_2(gitlab, cli):
    assert cli("--project", "119", "--pipeline", "1", GITLAB_TOKEN="")[0] == 2
    assert cli("--project", "119", "--pipeline", "1", "--timeout", "soon")[0] == 2
    assert cli("--project", "a//b")[0] == 2
    code, out = cli("--project", "119", "--pipeline", "4040")
    assert code == 1 and "HTTP 404" in out


def test_watch_outlives_a_token_expiry_with_a_refresh(gitlab):
    """M1.8 live F2: the Mintkey wrapper's JWT lives 600 s and the check pipeline can run longer. After the 600 s of
    the fake clock the server answers 401; the watch refreshes the credential once and ends `success`."""
    gitlab.pipelines.append({"id": 77, "status": "pending", "ref": "main", "web_url": "https://x.test/p/77"})
    states = [("running", [job(1, "test", "running")])] * 4 + [("success", [job(1, "test", "success")])]
    clock = Clock(gitlab, 77, states)
    clock.apply(("pending", [job(1, "test", "pending")]))
    issued = {"jwt-1": 600.0}  # credential -> the fake-clock time it stops working
    refreshed: list[float] = []

    def server(request: httpx.Request) -> httpx.Response:
        token = request.headers["PRIVATE-TOKEN"]
        if token not in issued or clock.now >= issued[token]:
            return httpx.Response(401, json={"message": "401 Unauthorized"})
        request.headers["PRIVATE-TOKEN"] = MAINTAINER  # the fake GitLab knows the maintainer's value only
        return gitlab.handle(request)

    def refresh() -> str:
        refreshed.append(clock.now)
        issued[f"jwt-{len(issued) + 1}"] = clock.now + 600.0
        return f"jwt-{len(issued)}"

    api = AdminApi(API, "jwt-1", transport=httpx.MockTransport(server), refresh=refresh)
    lines: list[str] = []
    result = watch_pipeline(
        api, "119", 77, say=lines.append, interval=200.0, timeout=5400.0, sleep=clock.sleep, clock=clock.monotonic
    )
    assert result.ok and result.status == "success" and lines[-1].endswith("-> exit 0")
    assert len(refreshed) == 1 and refreshed[0] >= 600.0  # one refresh, when the first JWT ran out
    assert not any("jwt-" in line for line in lines)  # a credential never appears in a line
