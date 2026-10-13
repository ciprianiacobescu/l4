"""One stdio JSON-RPC session with a child process, for the zero-token `codex app-server` probes.

The messages are written up front (the runner recording of 2026-10-04 shows `codex app-server` answers them in order
while stdin stays open); the session ends as soon as every request id has an answer, or at the deadline. The child
runs in its own process group and is always killed. No shell, no inherited environment.
"""

import contextlib
import json
import os
import selectors
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def run_rpc_session(
    argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout_s: float, messages: Sequence[Mapping[str, Any]]
) -> dict[int, Any]:
    """The response (or error) object of each request, by id. Notifications (no `id`) are ignored. Requests that
    got no answer in time are absent; a child that cannot start gives an empty result."""
    wanted = {m["id"] for m in messages if isinstance(m.get("id"), int)}
    try:
        proc = subprocess.Popen(
            list(argv), cwd=cwd, env=dict(env), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
        )  # fmt: skip
    except OSError:
        return {}
    answers: dict[int, Any] = {}
    assert proc.stdin is not None and proc.stdout is not None
    try:
        try:
            for message in messages:
                proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            proc.stdin.flush()
        except OSError:
            return answers  # the child closed its end: nothing more will come
        deadline = time.monotonic() + timeout_s
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        buffer = b""
        while wanted - answers.keys() and (left := deadline - time.monotonic()) > 0:
            if not selector.select(timeout=left):
                break
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                break
            buffer += chunk
            *lines, buffer = buffer.split(b"\n")
            for line in lines:
                try:
                    reply = json.loads(line)
                except ValueError:
                    continue
                if isinstance(reply, dict) and isinstance(reply.get("id"), int) and reply["id"] in wanted:
                    answers[reply["id"]] = reply
        return answers
    finally:
        with contextlib.suppress(OSError):
            proc.stdin.close()
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
