"""Run an external tool from an argv list: no shell, no stdin, a timeout that kills the whole process group."""

import contextlib
import os
import signal
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from l4.doctor.context import CmdResult

# (argv, cwd, env, timeout) -> CmdResult; tests inject a fake
Runner = Callable[[Sequence[str], Path, Mapping[str, str], float], CmdResult]


def run_process(argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: float) -> CmdResult:
    """A child that outlives `timeout` is killed together with everything it started (own session and process group):
    agent CLIs spawn helpers, and a probe must not leave them running."""
    try:
        proc = subprocess.Popen(
            list(argv), cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", start_new_session=True,
            close_fds=True,
        )  # fmt: skip
    except OSError as exc:
        return CmdResult(127, "", type(exc).__name__)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return CmdResult(124, "", "timed out")
    return CmdResult(proc.returncode, stdout, stderr)
