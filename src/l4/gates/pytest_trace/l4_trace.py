"""The harness-owned pytest plugin that carries `@pytest.mark.l4("C-...")` into the JUnit report (M13-G2).

Without it the marker never reaches the report [spike 03]: each id becomes one `("l4", id)` user property, which pytest
9 writes as a `<property>` of the testcase in both junit families (recorded: tests/fixtures/recorded/pytest). The
module imports nothing from `l4`: it runs inside the project's own environment, with only pytest available.

It also bounds one test (W-D1). With `L4_TEST_TIMEOUT_S=<seconds>` a test that runs longer fails with
`l4-test-timeout: ...` (a SIGALRM handler raises into the test, which interrupts a blocking `recv`), so the JUnit report
names the hung test instead of the whole gate being killed after its 30 minutes with no name. A test that ignores the
soft limit (a handler that is blocked, a C call) is reported on the *original* stderr as `L4_TEST_HANG: <nodeid>` with
every thread's traceback, 30 s later, and the process ends with exit 70. It does nothing when the limit is unset, or
when the project's pytest-timeout sets a limit of its own (`--timeout`, `PYTEST_TIMEOUT` or the `timeout` ini value:
its limit wins); an installed pytest-timeout that sets none leaves only the tests with a `timeout` marker to it. Off the
main thread (an xdist worker on execnet's thread model) there is no SIGALRM, only the hard limit.

With `L4_COLLECT_ONLY=<path>[<os.pathsep><path>...]` set (the verifier's audit run, design D15) it collects only those
Python files, relative to the directory pytest runs in: every other `.py` file except a `conftest.py` is ignored, and a
directory never is. An empty value collects no Python file.
"""

import contextlib
import faulthandler
import json
import os
import signal
import threading
import time
from pathlib import Path

import pytest

HANG_MARKER = "L4_TEST_HANG: "
TIMEOUT_MARKER = "l4-test-timeout:"
HARD_GRACE_S = 30.0  # `L4_TEST_HANG_GRACE_S` overrides it (the harness's own tests)
HARD_EXIT = 70
_REAL_STDERR = os.dup(2) if hasattr(os, "dup") else -1  # taken at import, before pytest's capture redirects fd 2
_limit: dict[str, float] = {"s": 0.0, "grace": HARD_GRACE_S}
_current: dict[str, object] = {"nodeid": None, "deadline": None}
_state: dict[str, bool] = {"watchdog": False, "defer_marked": False}


def _write_real_stderr(text: str) -> None:
    with contextlib.suppress(OSError):
        os.write(_REAL_STDERR, text.encode("utf-8", "replace"))


_OUTCOME_FD: list[int] = []


def _open_record() -> None:
    """Open the outcome record once. `L4_OUTCOME_FILE` names it; the variable is dropped from the environment at once,
    so code the tests import cannot find where the record is, and the descriptor stays append-only."""
    path = os.environ.pop("L4_OUTCOME_FILE", "")
    if path and not _OUTCOME_FD:
        with contextlib.suppress(OSError):
            _OUTCOME_FD.append(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600))


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """One line per test phase, written and flushed at once: what pytest judged, whatever the report file says later."""
    if _OUTCOME_FD:
        row = {"id": report.nodeid, "when": report.when, "outcome": report.outcome}
        with contextlib.suppress(OSError):
            os.write(_OUTCOME_FD[0], (json.dumps(row) + "\n").encode("utf-8"))


def pytest_configure(config: pytest.Config) -> None:
    _open_record()
    config.addinivalue_line("markers", "l4(*ids): the acceptance criteria (C-xxxxxxxx) this test checks")
    raw = os.environ.get("L4_TEST_TIMEOUT_S", "")
    try:
        limit = float(raw) if raw else 0.0
    except ValueError:
        limit = 0.0
    if limit > 0 and not _pytest_timeout_limits(config) and hasattr(signal, "SIGALRM"):
        _limit["s"] = limit
        _state["defer_marked"] = config.pluginmanager.hasplugin("timeout")
        with contextlib.suppress(ValueError):
            _limit["grace"] = float(os.environ.get("L4_TEST_HANG_GRACE_S", "") or HARD_GRACE_S)
        if not _state["watchdog"]:  # one per process, whichever thread configures pytest
            _state["watchdog"] = True
            threading.Thread(target=_watchdog, name="l4-test-hang-watchdog", daemon=True).start()


def _pytest_timeout_limits(config: pytest.Config) -> bool:
    """Whether the project's pytest-timeout sets a limit for every test (in its own order: option, environment, ini).
    Loaded but unreadable counts as a limit: its own settings are not ours to second-guess."""
    if not config.pluginmanager.hasplugin("timeout"):
        return False
    try:
        value = config.getoption("timeout")
        if value is None:
            value = os.environ.get("PYTEST_TIMEOUT") or config.getini("timeout")
        return float(value or 0) > 0
    except (ValueError, TypeError):
        return True


def _watchdog() -> None:
    while True:
        time.sleep(0.2)
        deadline, nodeid = _current["deadline"], _current["nodeid"]
        if isinstance(deadline, float) and time.monotonic() > deadline:
            _write_real_stderr(f"\n{HANG_MARKER}{nodeid}\n")
            try:
                faulthandler.dump_traceback(file=_REAL_STDERR, all_threads=True)
            finally:
                os._exit(HARD_EXIT)


def _on_alarm(signum: int, frame: object) -> None:
    pytest.fail(f"{TIMEOUT_MARKER} the test ran longer than {_limit['s']:g}s")  # the traceback shows the wait


def _arm(soft: bool) -> None:
    _current["deadline"] = time.monotonic() + _limit["s"] + _limit["grace"]
    # the C-level backstop: it needs no GIL, so it fires even when the interpreter is stuck
    faulthandler.dump_traceback_later(_limit["s"] + 2 * _limit["grace"] + 1, exit=True, file=_REAL_STDERR)
    if soft:
        signal.setitimer(signal.ITIMER_REAL, _limit["s"])


def _disarm(soft: bool) -> None:
    if soft:
        signal.setitimer(signal.ITIMER_REAL, 0)
    faulthandler.cancel_dump_traceback_later()
    _current["deadline"] = None


def _collect_only() -> set[str] | None:
    raw = os.environ.get("L4_COLLECT_ONLY")
    if raw is None:
        return None
    return {os.path.realpath(p) for p in raw.split(os.pathsep) if p}


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    only = _collect_only()
    if only is None or collection_path.suffix != ".py" or collection_path.name == "conftest.py":
        return None
    bases = {Path.cwd(), config.invocation_params.dir, config.rootpath}
    listed = {os.path.realpath(b / p) for b in bases for p in os.environ["L4_COLLECT_ONLY"].split(os.pathsep) if p}
    listed |= {p for p in only if os.path.isabs(p)}
    return None if os.path.realpath(collection_path) in listed else True


def pytest_runtest_logstart(nodeid: str, location: object) -> None:
    _current["nodeid"] = nodeid


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item: pytest.Item):
    yield from _wrapped(item)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item):
    yield from _wrapped(item)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item: pytest.Item):
    yield from _wrapped(item)


def _wrapped(item: pytest.Item | None = None):
    marked = item is not None and _state["defer_marked"] and item.get_closest_marker("timeout") is not None
    if _limit["s"] <= 0 or marked:  # a test with its own pytest-timeout marker keeps that limit
        yield
        return
    soft = threading.current_thread() is threading.main_thread()  # signal handlers exist only there
    previous = signal.signal(signal.SIGALRM, _on_alarm) if soft else None
    _arm(soft)
    try:
        yield
    finally:
        _disarm(soft)
        if soft:
            signal.signal(signal.SIGALRM, previous)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        seen: set[str] = set()
        for mark in item.iter_markers("l4"):
            for criterion in mark.args:
                if isinstance(criterion, str) and criterion not in seen:
                    seen.add(criterion)
                    item.user_properties.append(("l4", criterion))
