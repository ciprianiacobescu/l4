"""`l4.proc.run_process` never waits on a pipe that a process outside its reach holds (L4-AVL-012, SCN-AVL-21)."""

import contextlib
import os
import signal
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from l4 import proc as proc_mod
from l4.doctor.context import CmdResult
from l4.proc import run_process


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _script(tmp_path: Path, body: str) -> list[str]:
    path = tmp_path / "child.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(path)]


def _timed_run(argv, tmp_path, timeout, limit=20.0) -> tuple[CmdResult, float]:
    """Run in a thread so that a hang fails the test instead of hanging the suite."""
    box: dict = {}

    def target() -> None:
        started = time.monotonic()
        box["result"] = run_process(argv, tmp_path, dict(os.environ), timeout)
        box["elapsed"] = time.monotonic() - started

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(limit)
    assert not thread.is_alive(), "run_process is still waiting"
    return box["result"], box["elapsed"]


def _kill_pid_file(pid_file: Path) -> None:
    with contextlib.suppress(FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        os.kill(int(pid_file.read_text()), signal.SIGKILL)


def _spawner(pid_file: Path, *, session: bool, quiet: bool, child_sleep: float, grand_sleep: float) -> str:
    stdio = "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, " if quiet else ""
    return f"""
        import subprocess, sys, time
        g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep({grand_sleep})"],
                             {stdio}start_new_session={session})
        open({str(pid_file)!r}, "w").write(str(g.pid))
        print("1.18.34", flush=True)
        time.sleep({child_sleep})
    """


def test_a_helper_in_its_own_session_holding_stdout_does_not_hang(tmp_path):  # SCN-AVL-21
    pid_file = tmp_path / "pid"
    argv = _script(tmp_path, _spawner(pid_file, session=True, quiet=False, child_sleep=0, grand_sleep=60))
    try:
        result, elapsed = _timed_run(argv, tmp_path, 10)
        assert result == CmdResult(0, "1.18.34\n", "") and elapsed < 4
    finally:
        _kill_pid_file(pid_file)


def test_a_timeout_with_an_escaped_helper_still_returns(tmp_path):
    pid_file = tmp_path / "pid"
    argv = _script(tmp_path, _spawner(pid_file, session=True, quiet=False, child_sleep=60, grand_sleep=60))
    try:
        result, elapsed = _timed_run(argv, tmp_path, 1)
        assert result == CmdResult(124, "", "timed out") and elapsed < 1 + 2 + 1
    finally:
        _kill_pid_file(pid_file)


def test_a_helper_in_the_group_holding_the_pipe_is_killed_after_the_grace(tmp_path):
    pid_file = tmp_path / "pid"
    argv = _script(tmp_path, _spawner(pid_file, session=False, quiet=False, child_sleep=0, grand_sleep=60))
    try:
        result, elapsed = _timed_run(argv, tmp_path, 10)
        assert result.returncode == 0 and result.stdout == "1.18.34\n" and elapsed < 2 + 2
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 1
        while _alive(pid) and time.monotonic() < deadline:
            with contextlib.suppress(ChildProcessError):
                os.waitpid(pid, os.WNOHANG)  # not our child: harmless
            time.sleep(0.02)
        assert not _alive(pid)
    finally:
        _kill_pid_file(pid_file)


def test_a_child_that_exited_before_the_deadline_is_never_a_timeout(tmp_path):
    """Review finding MINOR-5: the child printed and exited 0, a helper holds the pipe, the timeout is shorter than the
    grace: the child's own return code and output come back."""
    pid_file = tmp_path / "pid"
    argv = _script(tmp_path, _spawner(pid_file, session=False, quiet=False, child_sleep=0, grand_sleep=60))
    try:
        result, elapsed = _timed_run(argv, tmp_path, 1.0)
        assert result == CmdResult(0, "1.18.34\n", "") and elapsed < 2.5
    finally:
        _kill_pid_file(pid_file)


def test_a_normal_exit_leaves_a_background_process_with_closed_output_alone(tmp_path):
    pid_file = tmp_path / "pid"
    argv = _script(tmp_path, _spawner(pid_file, session=False, quiet=True, child_sleep=0, grand_sleep=5))
    try:
        result, elapsed = _timed_run(argv, tmp_path, 10)
        assert result == CmdResult(0, "1.18.34\n", "") and elapsed < 2
        assert _alive(int(pid_file.read_text()))
    finally:
        _kill_pid_file(pid_file)


def test_output_past_the_cap_is_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(proc_mod, "MAX_STREAM_BYTES", 1000)
    argv = _script(tmp_path, 'import sys; sys.stdout.write("x" * 5000); sys.stdout.flush()')
    result, _ = _timed_run(argv, tmp_path, 10)
    assert result.returncode == 0 and len(result.stdout) == 1000


@pytest.mark.parametrize("name", ["EOF_GRACE_S", "MAX_STREAM_BYTES"])
def test_the_bounds_are_named_constants(name):
    assert hasattr(proc_mod, name)
