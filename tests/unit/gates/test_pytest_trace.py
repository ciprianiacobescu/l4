"""M13-G2: the harness-owned pytest plugin `l4_trace` and the env that loads it into every gate run."""

import ast
import subprocess
import sys
import time
from pathlib import Path

import pytest

from l4.gates.junit import parse_junit
from l4.gates.trace import PLUGIN_MODULE, plugin_dir, trace_env

TESTS = (
    "import pytest\n\n\n"
    "@pytest.mark.l4('C-aaaaaaaa', 'C-bbbbbbbb')\n"
    "def test_tagged():\n    assert True\n\n\n"
    "def test_plain():\n    assert True\n"
)


def run_pytest(tmp_path: Path, family: str, *args: str, ini: str = "") -> Path:
    (tmp_path / "test_x.py").write_text(TESTS)
    (tmp_path / "pytest.ini").write_text("[pytest]\n" + ini)
    report = tmp_path / "junit.xml"
    env = {"PATH": "/usr/bin:/bin", **trace_env()}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", f"junit_family={family}",
         f"--junitxml={report}", *args],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    return report


@pytest.mark.parametrize("family", ["xunit1", "xunit2"])
def test_marker_reaches_junit_through_the_gate_env(tmp_path: Path, family: str):
    tests = parse_junit(run_pytest(tmp_path, family)).tests
    assert tests["test_x::test_tagged"].criteria == ("C-aaaaaaaa", "C-bbbbbbbb")
    assert tests["test_x::test_plain"].criteria == ()


def test_marker_registered_under_strict_markers(tmp_path: Path):
    report = run_pytest(tmp_path, "xunit2", "--strict-markers")
    assert parse_junit(report).tests["test_x::test_tagged"].criteria


def test_plugin_dir_holds_only_the_plugin():
    names = {p.name for p in plugin_dir().iterdir() if p.name != "__pycache__"}
    assert names == {f"{PLUGIN_MODULE}.py"}
    assert trace_env() == {"PYTEST_ADDOPTS": f"-p {PLUGIN_MODULE}", "PYTHONPATH": str(plugin_dir())}


def test_plugin_imports_nothing_from_the_harness():
    tree = ast.parse((plugin_dir() / f"{PLUGIN_MODULE}.py").read_text())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported - set(sys.stdlib_module_names) == {"pytest"}


# --- W-D1: one hung test is named, not the whole gate ----------------------------------------------------------------

HANGING = (
    "import socket\n\n\n"
    "def test_fine():\n    assert True\n\n\n"
    "def test_hangs():\n    a, b = socket.socketpair()\n    a.recv(1)\n\n\n"
    "def test_after():\n    assert True\n"
)
DEAF = (
    "import signal, socket\n\n\n"
    "def test_hangs_deaf():\n"
    "    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})\n"
    "    a, b = socket.socketpair()\n    a.recv(1)\n"
)


def run_hanging(tmp_path: Path, source: str, timeout: str | None, *extra: str, grace: str = "1"):
    (tmp_path / "test_h.py").write_text(source)
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    env = {"PATH": "/usr/bin:/bin", **trace_env(), "L4_TEST_HANG_GRACE_S": grace}
    if timeout is not None:
        env["L4_TEST_TIMEOUT_S"] = timeout
    started = time.monotonic()
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "junit_family=xunit1",
         f"--junitxml={tmp_path / 'junit.xml'}", *extra],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    return done, time.monotonic() - started


def test_a_hung_test_fails_by_name_and_the_others_still_run(tmp_path: Path):
    done, took = run_hanging(tmp_path, HANGING, "1")
    tests = parse_junit(tmp_path / "junit.xml").tests
    assert tests["test_h::test_hangs"].status == "failed"
    assert "l4-test-timeout:" in tests["test_h::test_hangs"].message
    assert tests["test_h::test_fine"].status == "passed" and tests["test_h::test_after"].status == "passed"
    assert done.returncode == 1 and took < 20


def test_no_limit_means_no_timer(tmp_path: Path):
    done, _ = run_hanging(tmp_path, "def test_a():\n    assert True\n", None)
    assert done.returncode == 0


def test_a_test_that_blocks_the_soft_limit_is_named_on_the_real_stderr_and_ends_the_run(tmp_path: Path):
    done, took = run_hanging(tmp_path, DEAF, "1", grace="1")
    assert done.returncode == 70, done.stdout + done.stderr
    assert "L4_TEST_HANG: test_h.py::test_hangs_deaf" in done.stderr
    assert "test_hangs_deaf" in done.stderr.split("L4_TEST_HANG:", 1)[1] and took < 30


def test_a_project_with_pytest_timeout_keeps_its_own_limit(tmp_path: Path):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "timeout.py").write_text("")  # registered under the name pytest-timeout has
    (tmp_path / "test_slow.py").write_text("import time\n\n\ndef test_a():\n    time.sleep(2)\n")
    env = {"PATH": "/usr/bin:/bin", **trace_env(), "L4_TEST_TIMEOUT_S": "1"}
    env["PYTHONPATH"] += f":{plugins}"
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "timeout"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr


# --- review: a slow but correct test passes; the limit is safe off the main thread; an idle pytest-timeout -----------

SLOW_BUT_CORRECT = (
    "import time\n\nimport pytest\n\n\n"
    "@pytest.fixture\ndef slow_setup():\n    time.sleep(1.2)\n    yield\n\n\n"
    "def test_one(slow_setup):\n    time.sleep(1.2)\n\n\n"
    "def test_two():\n    time.sleep(1.2)\n\n\n"
    "def test_three():\n    time.sleep(1.2)\n"
)


def test_slow_but_correct_tests_under_the_limit_pass_and_the_limit_is_per_test(tmp_path: Path):
    """Each test (and each of its setup, call and teardown) gets the whole limit: four seconds of sleeps under a
    two-second limit all pass, so the timer is re-armed per phase, never a budget for the session."""
    done, _ = run_hanging(tmp_path, SLOW_BUT_CORRECT, "2")
    tests = parse_junit(tmp_path / "junit.xml").tests
    assert done.returncode == 0, done.stdout + done.stderr
    assert {t.status for t in tests.values()} == {"passed"} and len(tests) == 3


def test_the_limit_is_safe_off_the_main_thread(monkeypatch: pytest.MonkeyPatch):
    """pytest-xdist workers on execnet's thread model run the hooks off the main thread, where `signal.signal` raises
    ValueError and an ITIMER with no handler would kill the worker: the soft limit stands aside there and the hard
    deadline still holds, so no test breaks because of the plugin."""
    import importlib
    import threading

    monkeypatch.syspath_prepend(str(plugin_dir()))
    plugin = importlib.import_module(PLUGIN_MODULE)
    monkeypatch.setitem(plugin._limit, "s", 5.0)
    seen: dict[str, object] = {}

    def drive() -> None:
        try:
            hook = plugin._wrapped()
            next(hook)
            seen["deadline"] = plugin._current["deadline"]
            seen["itimer"] = __import__("signal").getitimer(__import__("signal").ITIMER_REAL)[0]
            with pytest.raises(StopIteration):
                next(hook)
        except BaseException as exc:  # noqa: BLE001 - the assertion below shows it
            seen["error"] = exc

    thread = threading.Thread(target=drive)
    thread.start()
    thread.join()
    assert "error" not in seen, seen.get("error")
    assert isinstance(seen["deadline"], float)  # the hard limit is armed
    assert seen["itimer"] == 0.0  # and no SIGALRM timer whose handler could not be installed
    assert plugin._current["deadline"] is None


FAKE_TIMEOUT_PLUGIN = (
    "def pytest_addoption(parser):\n"
    "    parser.addoption('--timeout', type=float, default=None, dest='timeout')\n"
    "    parser.addini('timeout', 'the per-test limit')\n"
)


def run_with_fake_pytest_timeout(tmp_path: Path, source: str, *args: str, env_extra: dict | None = None):
    plugins = tmp_path / "plugins"
    plugins.mkdir(exist_ok=True)
    (plugins / "timeout.py").write_text(FAKE_TIMEOUT_PLUGIN)  # registered under the name pytest-timeout has
    (tmp_path / "test_h.py").write_text(source)
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    env = {"PATH": "/usr/bin:/bin", **trace_env(), "L4_TEST_TIMEOUT_S": "1", "L4_TEST_HANG_GRACE_S": "1",
           **(env_extra or {})}  # fmt: skip
    env["PYTHONPATH"] += f":{plugins}"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "timeout", "-o", "junit_family=xunit1",
         f"--junitxml={tmp_path / 'junit.xml'}", *args],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )  # fmt: skip


def test_an_installed_pytest_timeout_that_sets_no_limit_does_not_switch_the_limit_off(tmp_path: Path):
    """pytest-timeout is often installed and idle (no `timeout` anywhere): standing aside then would leave the gate
    with no per-test limit at all, which is W-D1 again."""
    done = run_with_fake_pytest_timeout(tmp_path, HANGING)
    tests = parse_junit(tmp_path / "junit.xml").tests
    assert tests["test_h::test_hangs"].status == "failed", done.stdout + done.stderr
    assert "l4-test-timeout:" in tests["test_h::test_hangs"].message


@pytest.mark.parametrize(
    ("args", "env"),
    [(("--timeout=30",), {}), (("-o", "timeout=30"), {}), ((), {"PYTEST_TIMEOUT": "30"})],
    ids=["option", "ini", "env"],
)
def test_a_pytest_timeout_that_sets_a_limit_keeps_its_own(tmp_path: Path, args, env):
    done = run_with_fake_pytest_timeout(tmp_path, "import time\n\n\ndef test_a():\n    time.sleep(2)\n", *args,
                                        env_extra=env)  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_test_with_its_own_timeout_marker_is_left_to_pytest_timeout(tmp_path: Path):
    source = "import time\n\nimport pytest\n\n\n@pytest.mark.timeout(30)\ndef test_a():\n    time.sleep(2)\n"
    done = run_with_fake_pytest_timeout(tmp_path, source, "-p", "no:warnings")
    assert done.returncode == 0, done.stdout + done.stderr
