"""A cancelled CI job stops the run (SPEC L4-CLI-003, W-D2).

GitLab cancels a job by signalling the process group it started, but a runner that starts the job through `su` has put
the job into another session, so the signal can miss `l4` (wave D: the cancelled job's `l4 run` lived on, kept the unit
lock, and would have pushed the unit branch its owner had deleted). Three layers close that:

1. SIGTERM, SIGHUP and SIGINT set one process-wide flag and raise `RunCancelled` (a `BaseException`, so no cleanup
   `except Exception` swallows it). From then on nothing is committed or pushed and no forge write is sent
   (`check()` guards every write); the lease is released.
2. A watchdog thread, only inside GitLab CI, asks the forge whether the job still runs (`GET /job` with the job
   token, which stops being valid when the job ends) and whether the job's session leader is still alive; either
   answer "gone" signals this process with SIGTERM.
3. `vcs.git` refuses to recreate a deleted unit branch (see `Git.push_branch`).
"""

import contextlib
import json
import logging
import os
import signal
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from typing import Any

log = logging.getLogger("l4.cancel")

CANCELLED_EXIT = 16  # ExitCode.CANCELLED
POLL_S = 30.0  # how often the watchdog asks; `L4_CANCEL_POLL_S` overrides it (the harness's own tests)
_SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
_DEAD_STATUSES = ("canceled", "canceling", "failed", "success", "skipped")
_event = threading.Event()
_state: dict[str, int] = {"signum": 0}
_local_probe: dict[str, Callable[[], bool] | None] = {"probe": None}  # set while a watchdog runs (see `check`)
_warned: dict[str, bool] = {"api": False}


class RunCancelled(BaseException):  # noqa: N818 - like KeyboardInterrupt: it must pass `except Exception`
    def __init__(self, signum: int = signal.SIGTERM) -> None:
        super().__init__(f"run cancelled by signal {int(signum)}")
        self.signum = int(signum)
        self.exit_code = CANCELLED_EXIT


def is_cancelled() -> bool:
    return _event.is_set()


def signum() -> int:
    return _state["signum"]


def request(sig: int = signal.SIGTERM) -> None:
    """Mark the run cancelled (the handlers and tests call this)."""
    if not _event.is_set():
        _state["signum"] = int(sig)
    _event.set()


def reset() -> None:
    _event.clear()
    _state["signum"] = 0
    _local_probe["probe"] = None
    _warned["api"] = False


def check() -> None:
    """Raise `RunCancelled` when the run was cancelled: put it before a push or a forge write. While a watchdog runs,
    it also asks the job's session leader (one local syscall), so a write between two polls cannot slip through."""
    probe = _local_probe["probe"]
    if not _event.is_set() and probe is not None and not probe():
        log.error("the CI job's session is gone: stopping the run before it writes")
        request(signal.SIGTERM)
    if _event.is_set():
        raise RunCancelled(_state["signum"] or signal.SIGTERM)


def _handle(num: int, _frame: object) -> None:
    if _event.is_set():  # cleanup is already running; a second signal must not interrupt it half way
        return
    request(num)
    raise RunCancelled(num)


@contextlib.contextmanager
def handlers() -> Iterator[None]:
    """Install the cancel handlers for the block (main thread only; elsewhere a no-op) and restore the old ones."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = {sig: signal.signal(sig, _handle) for sig in _SIGNALS}
    try:
        yield
    finally:
        for sig, old in previous.items():
            signal.signal(sig, old)


# --- the job watchdog -------------------------------------------------------------------------------------------

Fetch = Callable[[str, str], tuple[int, Any]]


def _fetch(url: str, token: str) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers={"JOB-TOKEN": token, "Accept": "application/json"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=15) as response:  # noqa: S310 - the CI server's own https URL
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def job_alive_verdict(environ: Mapping[str, str], *, fetch: Fetch = _fetch) -> bool:
    """False only when the forge says the job is over: a refused job token (the token is valid only while the job
    runs) or a status other than running. No CI, no token or any network trouble is "alive" (fail open)."""
    token, api = environ.get("CI_JOB_TOKEN"), environ.get("CI_API_V4_URL")
    if environ.get("GITLAB_CI") != "true" or not token or not api:
        return True
    try:
        status, body = fetch(f"{api.rstrip('/')}/job", token)
    except Exception as exc:  # noqa: BLE001 - a lost connection is not a cancel
        _warn_once(f"the job API could not be asked ({exc})")
        return True
    if status in (401, 403):
        return False
    if status == 200 and isinstance(body, dict):
        return body.get("status", "running") not in _DEAD_STATUSES
    _warn_once(f"the job API answered HTTP {status}")
    return True


def _warn_once(what: str) -> None:
    """Failing open is silent otherwise: say once that only the session check watches this job."""
    if not _warned["api"]:
        _warned["api"] = True
        log.warning("%s; only the session check watches whether this CI job still runs", what)


def session_alive(sid: int | None = None) -> bool:
    """Whether the session leader of this process still exists. A runner that starts jobs through `su` makes the
    job's shell the leader; when the runner kills it, the leader goes and this process is an orphan."""
    leader = os.getsid(0) if sid is None else sid
    if leader == os.getpid():
        return True
    try:
        os.kill(leader, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def poll_seconds(environ: Mapping[str, str]) -> float:
    try:
        value = float(environ.get("L4_CANCEL_POLL_S") or POLL_S)
    except ValueError:
        return POLL_S
    return value if value > 0 else POLL_S


def start_watchdog(
    environ: Mapping[str, str],
    *,
    poll_s: float | None = None,
    alive: Callable[[Mapping[str, str]], bool] | None = None,
    on_dead: Callable[[], None] | None = None,
    grace_s: float | None = 120.0,
    sid: int | None = -1,
) -> Callable[[], None] | None:
    """Inside GitLab CI, check at once and then every `poll_s` (default `poll_seconds`) until the job is over, then
    call `on_dead` (default: SIGTERM to this process; if the process is still here `grace_s` later, `os._exit`: the
    kernel drops the unit lock). While it runs, `check()` asks the session leader too. Returns the stop function."""
    if environ.get("GITLAB_CI") != "true":
        return None
    if not environ.get("CI_JOB_TOKEN"):  # say so: silence would prove the missing watchdog only by absence (F4)
        log.info(
            "not watching CI job %s (job API not used: no CI_JOB_TOKEN; only a signal stops this run)",
            environ.get("CI_JOB_ID") or "?",
        )
        return None
    interval = poll_seconds(environ) if poll_s is None else poll_s
    leader = os.getsid(0) if sid == -1 else sid
    check_alive = alive or (lambda env: job_alive_verdict(env) and (leader is None or session_alive(leader)))
    stop = threading.Event()
    probe = (lambda: session_alive(leader)) if alive is None and leader is not None else None
    _local_probe["probe"] = probe
    api = (
        f"job API every {interval:g}s"
        if environ.get("CI_API_V4_URL")
        else "job API not used: no CI_API_V4_URL"  # never the token itself
    )
    session = f"job session {leader}" if leader is not None else "no job session check"
    log.info("watching CI job %s (%s + %s)", environ.get("CI_JOB_ID") or "?", api, session)

    def fire() -> None:
        log.error("the CI job is over (cancelled or its session is gone): stopping the run")
        if on_dead is not None:
            on_dead()
            return
        os.kill(os.getpid(), signal.SIGTERM)
        if grace_s is not None and not stop.wait(grace_s):
            os._exit(CANCELLED_EXIT)

    def watch() -> None:
        while True:  # at once first: an orphaned shell may start this run after the job is already over
            if not check_alive(environ):
                fire()
                return
            if stop.wait(interval):
                return

    def stop_watching() -> None:
        stop.set()
        if _local_probe["probe"] is probe:
            _local_probe["probe"] = None

    threading.Thread(target=watch, name="l4-job-watchdog", daemon=True).start()
    return stop_watching
