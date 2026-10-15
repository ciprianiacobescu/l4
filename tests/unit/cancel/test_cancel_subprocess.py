"""W-D2 (SAFETY) end to end: `l4 run` as a real child process, cancelled the ways a GitLab shell runner cancels a job.

Job 6051: the runner (service started with `--user`) runs the job as `su -s /bin/bash gitlab-runner -c "bash -l"`, and
`su` puts that shell in a session of its own. On cancel the runner signals its own process group (SIGTERM, then SIGKILL
after its graceful timeout); `su` passes on only a SIGTERM and, 2 s later, a SIGKILL to its child shell. `l4 run`
below that shell got no signal, lived on with the unit lock, and would have pushed. Each test here starts `l4 run` under
a `/bin/sh` that leads its own session, lets the real command-adapter agent start (a child process that sleeps), cancels
the job one way, and checks: the run ends with exit 16, the agent process is gone, nothing reached `origin`, and the
unit lock can be taken again.
"""

import http.server
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from l4.config.defaults import openspec_entrypoint
from l4.vcs.locks import LocalFileLease
from l4.vcs.names import UnitNames

from ..conftest import UNIT, TddRepo

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX sessions and signals")

AGENT = """\
import json, os, sys, time
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"pid": os.getpid()}))
time.sleep(600)
"""
START_S = 120.0  # setup, the base gate and the first agent start
STOP_S = 30.0  # the watchdog polls every 0.2 s here; cleanup kills the agent and writes the ledger


def _alive(pid: int) -> bool:
    """Running, not a zombie (an orphan's new parent may reap it late; a zombie answers kill(pid, 0) too)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False)
    return not state.stdout.strip().startswith("Z")


def _wait_until(predicate, timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout:g}s waiting for {what}")
        time.sleep(0.1)


class Job:
    def __init__(self, tdd: TddRepo, tmp_path: Path, extra_env: dict[str, str]) -> None:
        self.tdd = tdd
        agent = tmp_path / "agent.py"
        agent.write_text(AGENT)
        self.marker = tmp_path / "agent.json"
        tdd.write_config(
            profiles={"impl": {"adapter": "command", "vendor": "fakeco",
                               "options": {"argv": [sys.executable, str(agent), str(self.marker)]}}},
            clarifier={"enabled": False},
        )  # fmt: skip
        config = tdd.repo / ".l4" / "config.yaml"
        data = yaml.safe_load(config.read_text())
        data["forge"] = {"type": "local"}  # no forge API: the CI variables below only switch the watchdog on
        config.write_text(yaml.safe_dump(data))
        node = tmp_path / "fake-bin" / "node"  # the intake validates the unit (L4-ADO-007): a node that says "valid"
        node.parent.mkdir()
        node.write_text('#!/bin/sh\necho \'{"items":[{"id":"add-discount-codes","valid":true,"issues":[]}]}\'\n')
        node.chmod(0o755)
        entry = openspec_entrypoint(tdd.environ)
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text("// fake\n")
        path = f"{node.parent}{os.pathsep}{tdd.environ['PATH']}"
        env = {**tdd.environ, "PATH": path, "GITLAB_CI": "true", "CI_JOB_TOKEN": "job-token", "CI_JOB_ID": "6051",
               "L4_CANCEL_POLL_S": "0.2", **extra_env}  # fmt: skip
        l4 = [sys.executable, "-m", "l4", "run", "--unit", UNIT, "--repo", str(tdd.repo)]
        self.log = tmp_path / "job.log"
        with self.log.open("wb") as sink:
            # `cmd; echo` keeps the shell as a separate process (no exec): it leads the session, `l4` is its child
            self.shell = subprocess.Popen(
                ["/bin/sh", "-c", f'{shlex.join(l4)}; echo "l4 exit $?"'], cwd=tdd.repo, env=env,
                stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT, start_new_session=True,
            )  # fmt: skip
        self.names = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=tdd.cache, repo_key=tdd.key)
        _wait_until(lambda: self.marker.exists() or self.shell.poll() is not None, START_S, "the agent to start")
        assert self.marker.exists(), self.output()
        self.agent_pid = json.loads(self.marker.read_text())["pid"]
        holder = json.loads(self.names.flock_path.read_text())
        self.l4_pid = int(holder["pid"])
        assert os.getsid(self.l4_pid) == self.shell.pid  # the shell leads the session, as `su`'s `bash -l` did
        assert _alive(self.agent_pid) and _alive(self.l4_pid)
        self.refs_before = self.origin_refs()

    def output(self) -> str:
        return self.log.read_text(errors="replace")[-4000:]

    def origin_refs(self) -> str:
        done = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname) %(objectname)"], cwd=self.tdd.origin, env=self.tdd.environ,
            capture_output=True, text=True, check=True,
        )  # fmt: skip
        return done.stdout

    def outcome(self) -> dict:
        return json.loads((self.tdd.repo / ".l4-out" / "outcome.json").read_text())

    def local_events(self, event_type: str) -> list[dict]:
        files = sorted((self.names.worktree / "openspec/changes/add-discount-codes/.l4/ledger").glob("*.jsonl"))
        events = [json.loads(line) for f in files for line in f.read_text().splitlines()]
        return [e for e in events if e["type"] == event_type]

    def assert_stopped_cleanly(self) -> None:
        _wait_until(lambda: not _alive(self.l4_pid), STOP_S, f"l4 run (pid {self.l4_pid}) to end\n{self.output()}")
        _wait_until(lambda: not _alive(self.agent_pid), 10, f"the agent (pid {self.agent_pid}) to end")
        assert self.outcome()["exit_code"] == 16, self.output()
        assert self.local_events("run.cancelled"), self.output()
        assert self.origin_refs() == self.refs_before  # nothing was pushed: no unit branch, no lock ref
        lease = LocalFileLease(self.names.flock_path, unit=UNIT, run_id="r-next")
        lease.acquire()  # the next job takes the unit lock (job 6059 found it busy and skipped)
        lease.release()

    def kill_everything(self) -> None:
        for pid in (self.l4_pid, self.agent_pid):
            if _alive(pid):
                os.kill(pid, signal.SIGKILL)
        if self.shell.poll() is None:
            os.killpg(self.shell.pid, signal.SIGKILL)
            self.shell.wait()


@pytest.fixture
def job(tdd_repo: TddRepo, tmp_path: Path) -> Iterator:
    started: list[Job] = []

    def start(**extra_env: str) -> Job:
        started.append(Job(tdd_repo, tmp_path, extra_env))
        return started[-1]

    yield start
    for one in started:
        one.kill_everything()


@pytest.mark.parametrize("first", [signal.SIGTERM, signal.SIGKILL], ids=["sigterm-then-sigkill", "sigkill-only"])
def test_su_kills_only_the_job_shell_and_the_orphaned_run_stops_itself(job, first):
    """What `su` does on the runner's SIGTERM: SIGTERM to its child shell, 2 s later SIGKILL, and it reaps it (or the
    shell is SIGKILLed at once). The run gets no signal; its session leader is gone, which the watchdog sees."""
    run = job()
    os.kill(run.shell.pid, first)
    time.sleep(0.5)
    if run.shell.poll() is None:
        os.kill(run.shell.pid, signal.SIGKILL)
    run.shell.wait()  # su reaps its child: a zombie leader would still answer kill(pid, 0)
    assert _alive(run.l4_pid)  # orphaned, exactly as pid 829181 was
    run.assert_stopped_cleanly()


def test_the_runner_group_sigterm_reaches_the_run_and_it_ends_before_the_sigkill(job):
    """A runner that starts the job without `su`: SIGTERM to the job's process group, SIGKILL after the graceful
    timeout. The run must end on the SIGTERM; its agent runs in a session of its own and is killed by the run."""
    run = job()
    os.killpg(run.shell.pid, signal.SIGTERM)
    try:
        run.assert_stopped_cleanly()
    finally:
        if run.shell.poll() is None:
            os.killpg(run.shell.pid, signal.SIGKILL)  # the runner's force kill; the run must not have needed it
        run.shell.wait()


class _JobApi(http.server.BaseHTTPRequestHandler):
    over = threading.Event()

    def do_GET(self) -> None:  # noqa: N802 - the stdlib's name
        if self.path != "/api/v4/job" or self.headers.get("JOB-TOKEN") != "job-token":
            self.send_response(404)
            self.end_headers()
            return
        if self.over.is_set():  # GitLab refuses the job token once the job is over
            self.send_response(401)
            self.end_headers()
            return
        body = b'{"status": "running"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


def test_a_job_the_forge_reports_over_stops_the_run_while_its_session_lives(job):
    """No signal and a live session leader (a runner that signals nobody): the job token is refused, so the run ends."""
    _JobApi.over = threading.Event()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _JobApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        run = job(CI_API_V4_URL=f"http://127.0.0.1:{server.server_address[1]}/api/v4")
        time.sleep(1.0)
        assert _alive(run.l4_pid)  # a running job keeps its run
        _JobApi.over.set()
        run.assert_stopped_cleanly()
        assert run.shell.wait(10) == 0  # the shell lived on and saw `l4` exit (it prints the code)
        assert "l4 exit 16" in run.output()
    finally:
        server.shutdown()
