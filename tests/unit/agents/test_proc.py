import contextlib
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from l4 import deadline
from l4.agents.proc import ProcRunner
from l4.availability.cooldown import SystemClock


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def run(tmp_path: Path, code: str, **kw):
    kw.setdefault("timeout_s", 30)
    return ProcRunner().run(py(code), {"PATH": os.environ["PATH"]}, tmp_path, stdout_path=tmp_path / "out", **kw)


def test_stdout_lines_stream_to_the_file_and_the_callback(tmp_path):
    seen: list[str] = []
    done = run(tmp_path, "print('a'); print('b')", on_line=lambda line: seen.append(line))
    assert done.returncode == 0 and not done.timed_out
    assert seen == ["a", "b"] and (tmp_path / "out").read_text() == "a\nb\n"


def test_stderr_goes_to_its_own_file_and_stdin_reaches_the_child_then_eof(tmp_path):
    code = "import sys; d = sys.stdin.read(); sys.stderr.write('e'); print(len(d))"
    done = run(tmp_path, code, stdin="x" * 3_000_000, stderr_path=tmp_path / "err")
    assert done.returncode == 0 and (tmp_path / "out").read_text() == "3000000\n"
    assert (tmp_path / "err").read_text() == "e"


def test_no_stdin_means_the_child_sees_eof(tmp_path):
    assert run(tmp_path, "import sys; print(repr(sys.stdin.read()))").returncode == 0
    assert (tmp_path / "out").read_text() == "''\n"


def test_the_environment_is_exactly_what_was_given(tmp_path):
    os.environ["L4_TEST_LEAK"] = "leaked"
    try:
        run(tmp_path, "import os; print(sorted(os.environ))")
    finally:
        del os.environ["L4_TEST_LEAK"]
    assert "L4_TEST_LEAK" not in (tmp_path / "out").read_text()


GRANDCHILD = (
    "import subprocess, sys, time\n"
    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "print(p.pid, flush=True)\n"
    "time.sleep(60)\n"
)


def pid_of_grandchild(tmp_path: Path) -> int:
    return int((tmp_path / "out").read_text().split()[0])


def test_timeout_kills_process_group(tmp_path):
    started = time.monotonic()
    done = run(tmp_path, GRANDCHILD, timeout_s=1)
    assert done.timed_out and time.monotonic() - started < 15
    pid = pid_of_grandchild(tmp_path)
    for _ in range(50):
        if not alive(pid):
            break
        time.sleep(0.1)
    assert not alive(pid)


def test_stall_watchdog_kills_a_silent_child(tmp_path):
    done = run(tmp_path, "import time; print('hi', flush=True); time.sleep(60)", stall_timeout_s=1)
    assert done.stalled and not done.timed_out


def test_a_callback_can_abort_the_run(tmp_path):
    done = run(tmp_path, "import time\nprint('stop', flush=True)\ntime.sleep(60)", on_line=lambda line: True)
    assert done.aborted and done.returncode != 0


def _wait_for(path: Path, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)


def test_interrupt_sends_sigint_then_the_run_ends(tmp_path):
    interrupt = threading.Event()
    ready = tmp_path / "ready"  # interrupt only once the child is inside `try`: interpreter start-up time varies
    threading.Thread(target=lambda: (_wait_for(ready), interrupt.set()), daemon=True).start()
    code = (
        f"import time\ntry:\n    open({str(ready)!r}, 'w').close()\n    time.sleep(60)\n"
        "except KeyboardInterrupt:\n    print('got-int')\n"
    )
    # a generous timeout: on a loaded machine the interpreter's start-up alone can pass the default 30 s, and the run
    # would end as timed out (SIGKILL) before the interrupt is ever sent
    done = run(tmp_path, code, interrupt=interrupt, timeout_s=300)
    assert done.interrupted and not done.timed_out and (tmp_path / "out").read_text() == "got-int\n"


def test_a_missing_executable_is_an_error_not_a_hang(tmp_path):
    with pytest.raises(FileNotFoundError):
        ProcRunner().run(["/no/such/binary"], {}, tmp_path, stdout_path=tmp_path / "out", timeout_s=5)


def test_run_process_timeout_kills_the_whole_group(tmp_path):
    from l4.proc import run_process

    marker = tmp_path / "pid"
    script = (
        "import subprocess, sys, time\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(marker)!r}, 'w').write(str(p.pid))\n"
        "time.sleep(60)\n"
    )
    done = run_process([sys.executable, "-c", script], tmp_path, {"PATH": os.environ["PATH"]}, 1.0)
    assert done.returncode == 124
    pid = int(marker.read_text())
    for _ in range(50):
        if not alive(pid):
            break
        time.sleep(0.1)
    assert not alive(pid)


def test_a_grandchild_holding_stdout_open_cannot_leave_the_file_unfinished(tmp_path):
    code = (
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print('done', flush=True)\n"
    )
    started = time.monotonic()
    done = run(tmp_path, code)
    assert done.returncode == 0 and time.monotonic() - started < 30
    assert (tmp_path / "out").read_text() == "done\n"


def test_an_escaped_helper_holding_stdout_does_not_hang_the_run(tmp_path, caplog):  # SCN-AVL-24
    pid_file = tmp_path / "helper.pid"
    code = (
        "import subprocess, sys\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)\n"
        f"open({str(pid_file)!r}, 'w').write(str(g.pid))\n"
        "print('done', flush=True)\n"
    )
    started = time.monotonic()
    try:
        with caplog.at_level("WARNING"):
            done = run(tmp_path, code)
        assert done.returncode == 0 and time.monotonic() - started < 5 + 5 + 2
        assert (tmp_path / "out").read_text() == "done\n"
        assert (
            "a process outside the agent's process group still holds its output: the raw events end here" in caplog.text
        )
    finally:
        if pid_file.exists():
            with contextlib.suppress(ProcessLookupError, ValueError):
                os.kill(int(pid_file.read_text()), 9)


class FakeWatch:
    """A stand-in with the watch's methods (the real `ActivityWatch` is another unit)."""

    def __init__(self, open_call: bool = False) -> None:
        self.open_call = open_call
        self.started: list[tuple[float, object]] = []
        self.lines: list[str] = []
        self.ticks = 0
        self.stopped_idle_s: float | None = None

    def start(self, now, reader) -> None:
        self.started.append((now, reader))

    def line(self, text: str) -> None:
        self.lines.append(text)

    def tick(self, now: float) -> None:
        self.ticks += 1

    def has_open_call(self) -> bool:
        return self.open_call


def test_a_watch_is_started_fed_each_line_and_ticked_while_the_child_runs(tmp_path):
    watch = FakeWatch()
    reader = object()
    done = run(tmp_path, "import time; print('a', flush=True); time.sleep(0.5); print('b')", watch=watch, reader=reader)
    assert done.returncode == 0
    assert len(watch.started) == 1 and watch.started[0][1] is reader
    assert watch.lines == ["a", "b"] and watch.ticks >= 3 and watch.stopped_idle_s is None


def test_a_stall_sends_sigint_before_the_kill(tmp_path):
    marker = tmp_path / "marker"
    code = (
        "import time\ntry:\n    print('hi', flush=True)\n    time.sleep(60)\n"
        f"except KeyboardInterrupt:\n    open({str(marker)!r}, 'w').write('int')\n"
    )
    done = run(tmp_path, code, stall_timeout_s=4, timeout_s=300)
    assert done.stalled and not done.timed_out and marker.read_text() == "int"


def test_an_open_call_holds_the_stall_rule(tmp_path):
    watch = FakeWatch(open_call=True)
    started = time.monotonic()
    done = run(tmp_path, "import time; print('start', flush=True); time.sleep(2.5)", stall_timeout_s=0.5, watch=watch)
    assert done.returncode == 0 and not done.stalled and time.monotonic() - started >= 2.4
    assert watch.stopped_idle_s is None


def test_a_silent_child_with_no_open_call_is_stopped_and_the_silence_is_recorded(tmp_path):
    watch = FakeWatch(open_call=False)
    done = run(tmp_path, "import time; print('hi', flush=True); time.sleep(60)", stall_timeout_s=1, watch=watch)
    assert done.stalled and watch.stopped_idle_s is not None and watch.stopped_idle_s >= 1


def test_the_stall_kill_follows_after_the_grace_even_when_the_agent_prints_on_sigint(tmp_path, monkeypatch):
    import l4.agents.proc as proc

    monkeypatch.setattr(proc, "INTERRUPT_GRACE_S", 1.0)
    code = (
        "import signal, time\n"
        "def h(*a):\n    print('late line', flush=True)\n"
        "signal.signal(signal.SIGINT, h)\n"
        "print('hi', flush=True)\n"
        "while True:\n    time.sleep(0.1)\n"
    )
    watch = FakeWatch()
    started = time.monotonic()
    done = run(tmp_path, code, stall_timeout_s=4, watch=watch, timeout_s=300)
    assert done.stalled and not done.timed_out and "late line" in (tmp_path / "out").read_text()
    assert time.monotonic() - started < 60


# --- the run deadline (L4-IMP-068, D4 of run-continuation) ----------------------------------------------------------


def _arm_deadline() -> deadline.RunDeadline:
    """A run deadline that no timer fires: the test calls `fire()`."""
    clock = SystemClock()
    dl = deadline.RunDeadline(at=clock.now(), clock=clock, event=threading.Event())

    class Never:
        daemon = False

        def __init__(self, seconds, function) -> None:
            pass

        def start(self) -> None:
            pass

        def cancel(self) -> None:
            pass

    dl.event.clear()
    deadline.arm(dl, timer=Never)
    return dl


def _fire_when_ready(dl: deadline.RunDeadline, ready: Path, after_s: float, stamp: list[float]) -> None:
    def go() -> None:
        _wait_for(ready)
        time.sleep(after_s)
        stamp.append(time.monotonic())
        dl.fire()

    threading.Thread(target=go, daemon=True).start()


def _kill_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    if pid_file.exists():
        with contextlib.suppress(ProcessLookupError, PermissionError, ValueError):
            os.killpg(int(pid_file.read_text()), 9)


def test_the_deadline_stops_a_running_process_with_sigint_then_sigkill(tmp_path):
    """A child that ignores SIGINT is killed after the 5 s grace, and its pid is gone."""
    dl = _arm_deadline()
    ready, stamp = tmp_path / "ready", []
    _fire_when_ready(dl, ready, 0.5, stamp)
    code = (
        "import os, signal, time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        f"open({str(tmp_path / 'pid')!r}, 'w').write(str(os.getpid()))\n"
        f"open({str(ready)!r}, 'w').close()\ntime.sleep(60)\n"
    )
    try:
        done = run(tmp_path, code, timeout_s=300)
        ended = time.monotonic()
        assert done.interrupted and done.deadline and not done.timed_out and not done.stalled
        assert 4.5 <= ended - stamp[0] <= 5 + 2.5  # SIGINT ignored: the group is killed after the grace
        assert not alive(int((tmp_path / "pid").read_text()))
    finally:
        _kill_group(tmp_path)


def test_a_child_that_exits_on_sigint_ends_before_the_grace(tmp_path):
    dl = _arm_deadline()
    ready, stamp = tmp_path / "ready", []
    _fire_when_ready(dl, ready, 0.2, stamp)
    code = f"import time\nopen({str(ready)!r}, 'w').close()\ntime.sleep(60)\n"
    done = run(tmp_path, code, timeout_s=300)
    assert done.deadline and done.interrupted
    assert time.monotonic() - stamp[0] < 2


def test_a_process_started_after_the_deadline_is_stopped_at_once(tmp_path):
    dl = _arm_deadline()
    dl.fire()
    started = time.monotonic()
    done = run(tmp_path, "import time; time.sleep(60)", timeout_s=300)
    assert done.deadline and done.interrupted
    assert time.monotonic() - started < 10  # the interpreter's start-up, not the 60 s


def test_the_deadline_wins_over_the_idle_rule_and_the_time_limit(tmp_path, monkeypatch):
    """SCN-IMP-362."""
    import l4.agents.proc as proc

    monkeypatch.setattr(proc, "INTERRUPT_GRACE_S", 2.0)
    # (a) the idle rule has fired and its grace runs when the deadline fires: the second SIGINT ends the child
    dl = _arm_deadline()
    ready, stamp = tmp_path / "ready", []
    code = (
        "import signal, sys, time\nhits = []\n"
        "def h(*a):\n    hits.append(1)\n    if len(hits) > 1:\n        sys.exit(0)\n"
        f"signal.signal(signal.SIGINT, h)\nopen({str(ready)!r}, 'w').close()\nwhile True:\n    time.sleep(0.05)\n"
    )
    watch = FakeWatch(open_call=False)
    _fire_when_ready(dl, ready, 1.0, stamp)  # the idle rule (0.2 s of silence) fired well before
    done = run(tmp_path, code, stall_timeout_s=0.2, watch=watch, timeout_s=300)
    assert done.deadline and done.interrupted and not done.stalled and not done.timed_out
    assert watch.stopped_idle_s is None
    # (b) the time limit and the deadline in the same poll: the deadline fired before the process started
    dl2 = _arm_deadline()
    dl2.fire()
    watch2 = FakeWatch(open_call=False)
    done = run(tmp_path, "import time; time.sleep(60)", stall_timeout_s=0, watch=watch2, timeout_s=0)
    assert done.deadline and done.interrupted and not done.stalled and not done.timed_out
    assert watch2.stopped_idle_s is None


def test_without_a_deadline_nothing_changes(tmp_path):
    assert deadline.current() is None
    done = run(tmp_path, "print('x')")
    assert not done.deadline and not done.interrupted and done.returncode == 0
