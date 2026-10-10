import os
import sys
import threading
import time
from pathlib import Path

import pytest

from l4.agents.proc import ProcRunner


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
