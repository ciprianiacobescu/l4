"""Run one agent process (SPEC L4-FAC-001, L4-AVL-006): its own process group, a wall-clock timeout, a stall watchdog,
SIGINT on `interrupt`. The child gets exactly the environment it is given, never the parent's."""

import contextlib
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from l4.agents.activity import ActivityWatch, StreamReader

POLL_S = 0.05
INTERRUPT_GRACE_S = 5.0


@dataclass(frozen=True)
class ProcOutcome:
    returncode: int
    timed_out: bool = False
    stalled: bool = False
    interrupted: bool = False
    aborted: bool = False  # `on_line` asked to stop


def _signal_group(pgid: int, sig: signal.Signals) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, sig)


class ProcRunner:
    def run(
        self,
        argv: Sequence[str],
        env: Mapping[str, str],
        cwd: Path,
        *,
        stdout_path: Path,
        timeout_s: float,
        stdin: str | None = None,
        stderr_path: Path | None = None,
        interrupt: threading.Event | None = None,
        on_line: Callable[[str], bool | None] | None = None,
        stall_timeout_s: float | None = None,
        watch: ActivityWatch | None = None,
        reader: StreamReader | None = None,
    ) -> ProcOutcome:
        """stdout is copied line by line to `stdout_path`; `on_line` returning True aborts the run. `stdin` is written
        in full, then closed (EOF), from a thread, so a prompt larger than the pipe buffer cannot deadlock."""
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.ExitStack() as stack:
            err_target = stack.enter_context(stderr_path.open("wb")) if stderr_path else subprocess.DEVNULL
            proc = subprocess.Popen(
                list(argv), cwd=cwd, env=dict(env), stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=err_target, start_new_session=True, close_fds=True,
            )  # fmt: skip
            pgid = proc.pid
            state = {"last": time.monotonic(), "aborted": False}
            if watch is not None:
                watch.start(state["last"], reader)
            threads = [
                threading.Thread(target=self._pump, args=(proc, stdout_path, on_line, state, watch), daemon=True)
            ]
            if stdin is not None:
                threads.append(threading.Thread(target=self._feed, args=(proc, stdin), daemon=True))
            for thread in threads:
                thread.start()
            try:
                outcome = self._wait(proc, pgid, timeout_s, interrupt, stall_timeout_s, state, watch)
            except BaseException:  # RunCancelled, KeyboardInterrupt: never leave the agent or the gate running
                _signal_group(pgid, signal.SIGKILL)
                with contextlib.suppress(Exception):
                    proc.wait(timeout=5)
                raise
            for thread in threads:
                thread.join(timeout=5)
            if any(thread.is_alive() for thread in threads):
                # a grandchild still holds the pipe: end it, so the raw events file is complete before anyone parses it
                _signal_group(pgid, signal.SIGKILL)
                for thread in threads:
                    thread.join()
            return outcome

    @staticmethod
    def _feed(proc: subprocess.Popen[bytes], text: str) -> None:
        assert proc.stdin is not None
        with contextlib.suppress(BrokenPipeError, OSError):
            proc.stdin.write(text.encode("utf-8"))
        with contextlib.suppress(BrokenPipeError, OSError):
            proc.stdin.close()

    @staticmethod
    def _pump(
        proc: subprocess.Popen[bytes],
        path: Path,
        on_line: Callable[[str], bool | None] | None,
        state: dict,
        watch: ActivityWatch | None = None,
    ) -> None:
        assert proc.stdout is not None
        with path.open("wb") as sink:
            for raw in proc.stdout:
                sink.write(raw)
                sink.flush()
                state["last"] = time.monotonic()
                text = raw.decode("utf-8", "replace").rstrip("\r\n")
                if watch is not None:
                    with contextlib.suppress(Exception):  # the watch never stops the pump: the pipe must drain
                        watch.line(text)
                if on_line is not None and on_line(text):
                    state["aborted"] = True

    def _wait(
        self,
        proc: subprocess.Popen[bytes],
        pgid: int,
        timeout_s: float,
        interrupt: threading.Event | None,
        stall_timeout_s: float | None,
        state: dict,
        watch: ActivityWatch | None = None,
    ) -> ProcOutcome:
        deadline = time.monotonic() + timeout_s
        flags = {"timed_out": False, "stalled": False, "interrupted": False, "aborted": False}
        interrupted_at: float | None = None
        stalled_at: float | None = None  # a latch: once the rule fired, lines in the grace do not undo it
        while proc.poll() is None:
            now = time.monotonic()
            if watch is not None:
                with contextlib.suppress(Exception):
                    watch.tick(now)
            silent_s = now - state["last"]
            idle = stalled_at is None and stall_timeout_s is not None and silent_s >= stall_timeout_s
            if idle and (watch is None or not watch.has_open_call()):
                stalled_at = now
                if watch is not None:
                    watch.stopped_idle_s = silent_s
                _signal_group(pgid, signal.SIGINT)
            if now >= deadline:
                flags["timed_out"] = True
            elif stalled_at is not None:
                flags["stalled"] = True
                if now - stalled_at < INTERRUPT_GRACE_S:
                    time.sleep(POLL_S)
                    continue
            elif state["aborted"]:
                flags["aborted"] = True
            elif interrupt is not None and interrupt.is_set():
                flags["interrupted"] = True
                if interrupted_at is None:
                    interrupted_at = now
                    _signal_group(pgid, signal.SIGINT)
                if now - interrupted_at < INTERRUPT_GRACE_S:
                    time.sleep(POLL_S)
                    continue
            else:
                time.sleep(POLL_S)
                continue
            _signal_group(pgid, signal.SIGKILL)  # the whole group: agents start shells, shells start test runs
            break
        returncode = proc.wait()
        return ProcOutcome(returncode, **flags)
