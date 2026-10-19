"""Run an external tool from an argv list: no shell, no stdin, a timeout that kills the whole process group."""

import contextlib
import os
import selectors
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from l4.doctor.context import CmdResult

# (argv, cwd, env, timeout) -> CmdResult; tests inject a fake
Runner = Callable[[Sequence[str], Path, Mapping[str, str], float], CmdResult]

EOF_GRACE_S = 2.0  # after the direct child exits, how long its output may stay open
MAX_STREAM_BYTES = 16 * 1024 * 1024  # per stream; the rest is read and dropped
_WAIT_AFTER_KILL_S = 5.0
_POLL_S = 0.05


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)


def run_process(argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: float) -> CmdResult:
    """A child that outlives `timeout` is killed together with everything it started (own session and process group):
    agent CLIs spawn helpers, and a probe must not leave them running. Output is read until the direct child has exited
    and both pipes are closed, or `EOF_GRACE_S` after its exit; the group is then killed. Nothing waits on a pipe that a
    process outside the group holds (L4-AVL-012)."""
    try:
        proc = subprocess.Popen(
            list(argv), cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True, close_fds=True,
        )  # fmt: skip
    except OSError as exc:
        return CmdResult(127, "", type(exc).__name__)
    chunks: dict[str, bytearray] = {"out": bytearray(), "err": bytearray()}
    deadline = time.monotonic() + timeout
    exited_at: float | None = None
    timed_out = False
    sel = selectors.DefaultSelector()
    try:
        assert proc.stdout is not None and proc.stderr is not None
        sel.register(proc.stdout, selectors.EVENT_READ, "out")
        sel.register(proc.stderr, selectors.EVENT_READ, "err")
        while True:
            now = time.monotonic()
            if proc.poll() is not None and exited_at is None:
                exited_at = now
            if not sel.get_map() and exited_at is not None:
                break  # both pipes closed and the child gone: the normal end
            if now >= deadline:
                timed_out = True
                break
            if exited_at is not None and now - exited_at >= EOF_GRACE_S:
                _kill_group(proc.pid)  # output is held by something that outlived the child
                break
            wait = min(_POLL_S, deadline - now)
            for key, _ in sel.select(wait) if sel.get_map() else _sleep(wait):
                data = os.read(key.fd, 65536)
                if not data:
                    sel.unregister(key.fileobj)
                    continue
                buf = chunks[key.data]
                room = MAX_STREAM_BYTES - len(buf)
                if room > 0:
                    buf += data[:room]
        if timed_out:
            _kill_group(proc.pid)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=_WAIT_AFTER_KILL_S)
    finally:
        sel.close()
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                with contextlib.suppress(OSError):
                    pipe.close()
    if timed_out:
        return CmdResult(124, "", "timed out")
    return CmdResult(
        proc.returncode if proc.returncode is not None else 124,
        chunks["out"].decode("utf-8", "replace"),
        chunks["err"].decode("utf-8", "replace"),
    )


def _sleep(seconds: float) -> list:
    time.sleep(seconds)
    return []
