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
   A leader that is already gone at the start is a runner that starts jobs that way (its starter exits at once): the
   session check is then dropped for the run (with one warning) and only the job API watches.
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

from l4.redact import url_job_token

log = logging.getLogger("l4.cancel")

CANCELLED_EXIT = 16  # ExitCode.CANCELLED
POLL_S = 30.0  # how often the watchdog asks; `L4_CANCEL_POLL_S` overrides it (the harness's own tests)
_SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
_DEAD_STATUSES = ("canceled", "canceling", "failed", "success", "skipped")
_event = threading.Event()
_state: dict[str, int] = {"signum": 0}
_local_probe: dict[str, Callable[[], bool] | None] = {"probe": None}  # set while a watchdog runs (see `check`)
_warned: dict[str, bool] = {"api": False, "token": False}


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
    _warned["token"] = False


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


def job_token(environ: Mapping[str, str]) -> str:
    """The token the job API wants. `CI_JOB_TOKEN`, unless a CI/CD variable of that name overrides the predefined one:
    then the token inside `CI_REPOSITORY_URL` is the job's (one warning per process; never a token value)."""
    token, from_url = environ.get("CI_JOB_TOKEN") or "", url_job_token(environ)
    if from_url and from_url != token:
        if not _warned["token"]:
            _warned["token"] = True
            log.warning(
                "CI_JOB_TOKEN is not this job's token (a CI/CD variable named CI_JOB_TOKEN of the project, its group "
                "or the instance overrides it); the job API uses the job token in CI_REPOSITORY_URL. Rename that "
                "variable: the project's own jobs get its value instead of the job token too."
            )
        return from_url
    return token


def job_over(environ: Mapping[str, str], *, fetch: Fetch = _fetch) -> str | None:
    """Why the forge says the job is over: `token refused` (the token is valid only while the job runs) or the status
    other than running; None when it runs. No CI, no token or any network trouble is "alive" (fail open)."""
    api = environ.get("CI_API_V4_URL")
    if environ.get("GITLAB_CI") != "true" or not api:
        return None
    token = job_token(environ)
    if not token:
        return None
    try:
        status, body = fetch(f"{api.rstrip('/')}/job", token)
    except Exception as exc:  # noqa: BLE001 - a lost connection is not a cancel
        _warn_once(f"the job API could not be asked ({exc})")
        return None
    if status in (401, 403):
        return "token refused"
    if status == 200 and isinstance(body, dict):
        got = str(body.get("status", "running"))
        return got if got in _DEAD_STATUSES else None
    _warn_once(f"the job API answered HTTP {status}")
    return None


def job_alive_verdict(environ: Mapping[str, str], *, fetch: Fetch = _fetch) -> bool:
    """False only when the forge says the job is over (see `job_over`)."""
    return job_over(environ, fetch=fetch) is None


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
    fetch: Fetch = _fetch,
) -> Callable[[], None] | None:
    """Inside GitLab CI, check at once and then every `poll_s` (default `poll_seconds`) until the job is over, then
    call `on_dead` (default: SIGTERM to this process; if the process is still here `grace_s` later, `os._exit`: the
    kernel drops the unit lock). While it runs, `check()` asks the session leader too. Returns the stop function."""
    if environ.get("GITLAB_CI") != "true":
        return None
    if not job_token(environ):  # say so: silence would prove the missing watchdog only by absence (F4)
        log.info(
            "not watching CI job %s (job API not used: no CI_JOB_TOKEN; only a signal stops this run)",
            environ.get("CI_JOB_ID") or "?",
        )
        return None
    interval = poll_seconds(environ) if poll_s is None else poll_s
    leader = os.getsid(0) if sid == -1 else sid
    leader_gone = leader is not None and not session_alive(leader)
    if leader_gone:  # a runner whose job session leader exits right away: the job API alone watches (hotfix 0.4.23)
        log.warning(
            "the CI job's session leader %s is not running at the start (this runner starts jobs that way); "
            "only the job API watches this CI job",
            leader,
        )
        leader = None
    api_used = bool(environ.get("CI_API_V4_URL"))
    if leader is None and not api_used:
        log.warning(
            "the job API cannot be used here (no CI_API_V4_URL) and the session check is off; "
            "only a signal stops this run"
        )

    asked = {"api": 0, "off": 0}  # the job API: how often asked, and whether it is left out for this run

    def why_over() -> str | None:
        if alive is not None:  # a test double stands in for both checks
            return None if alive(environ) else "the check says it is over"
        got = None if asked["off"] else job_over(environ, fetch=fetch)
        first = asked["api"] == 0 and not asked["off"]
        asked["api"] += 1
        if got == "token refused" and first and leader is not None:
            # the session check is in use and the job runs (its leader was alive at the start): a refusal at once is
            # a token that was never the job's, not a job that is over
            asked["off"] = 1
            log.warning(
                "the job API refused the job token at the start while the job's session runs (is CI_JOB_TOKEN "
                "overridden by a CI/CD variable?); only the job session watches this CI job"
            )
            got = None
        if got:
            return f"the job API says {got}"
        if leader is not None and not session_alive(leader):
            return f"its session leader {leader} is gone"
        return None

    stop = threading.Event()
    probe = (lambda: session_alive(leader)) if alive is None and leader is not None else None
    _local_probe["probe"] = probe
    api = f"job API every {interval:g}s" if api_used else "job API not used: no CI_API_V4_URL"  # never the token itself
    session = (
        f"job session {leader}"
        if leader is not None
        else "no job session check: its leader was gone at the start"
        if leader_gone
        else "no job session check"
    )
    log.info(
        "watching CI job %s (%s%s%s)",
        environ.get("CI_JOB_ID") or "?",
        api,
        " + " if leader is not None or not leader_gone else "; ",
        session,
    )

    def fire(reason: str) -> None:
        log.error("the CI job is over (%s): stopping the run", reason)
        if on_dead is not None:
            on_dead()
            return
        os.kill(os.getpid(), signal.SIGTERM)
        if grace_s is not None and not stop.wait(grace_s):
            os._exit(CANCELLED_EXIT)

    def watch() -> None:
        while True:  # at once first: an orphaned shell may start this run after the job is already over
            reason = why_over()
            if reason:
                fire(reason)
                return
            if stop.wait(interval):
                return

    def stop_watching() -> None:
        stop.set()
        if _local_probe["probe"] is probe:
            _local_probe["probe"] = None

    threading.Thread(target=watch, name="l4-job-watchdog", daemon=True).start()
    return stop_watching
