"""The local lease (SPEC 12.2): a non-blocking flock on `$L4_CACHE/locks/<key>/<fw>/<name>.lock`
(`<key>`: the repository key, `l4.vcs.repokey`).

Correct on one runner, which is the M0 setup (GitLab `resource_group` serialises jobs; the flock covers a manual run
racing a pipeline job). The kernel drops the lock when the process dies, so a SIGKILL needs no cleanup.
M1: state-vcs-locks 1.25 (PushCoordinator), M2 remote lease refs and fencing.
"""

import fcntl
import json
import logging
import os
import secrets
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from l4.exitcodes import ExitCode, L4Exit
from l4.state.ledger import LedgerClosed, LedgerWriter

log = logging.getLogger("l4.lock")


class Busy(Exception):
    def __init__(self, holder: dict[str, Any]) -> None:
        self.holder = holder
        super().__init__(f"unit is locked by run {holder.get('run_id', 'unknown')}")


class LocalFileLease:
    def __init__(
        self, path: Path, *, unit: str, run_id: str, holder: str | None = None, job: str | None = None
    ) -> None:
        self._path = path
        self._payload = {
            "unit": unit,
            "run_id": run_id,
            "holder": holder or f"{socket.gethostname()}:{os.getpid()}",
            "nonce": secrets.token_hex(8),
            "pid": str(os.getpid()),
            **({"job": job} if job else {}),  # the CI job: a busy lock whose job is over is an orphan (W-D2)
        }
        self._fd: int | None = None

    @property
    def payload(self) -> dict[str, str]:
        return dict(self._payload)

    def acquire(self) -> None:
        if self._fd is not None:
            raise RuntimeError("lease already held by this object")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = self._read_holder(fd)
            os.close(fd)
            raise Busy(holder) from None
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        payload = {**self._payload, "acquired_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps(payload).encode("utf-8"))

    def release(self) -> None:
        if self._fd is None:
            return
        os.ftruncate(self._fd, 0)  # the diagnostics describe a holder; there is none now
        os.close(self._fd)  # closing the descriptor drops the flock
        self._fd = None

    @staticmethod
    def _read_holder(fd: int) -> dict[str, Any]:
        try:
            raw = os.pread(fd, 4096, 0)
            holder = json.loads(raw)
        except (OSError, ValueError):
            return {}
        return holder if isinstance(holder, dict) else {}


def acquire_for_run(lease: LocalFileLease, open_writer: Callable[[], LedgerWriter]) -> LedgerWriter | None:
    """Take the lease, then open the run's ledger and record `lock.acquired`. A busy unit returns None before
    anything is written: the unit is skipped with exit 0 and its files are not touched (SCN-LCK-01)."""
    try:
        lease.acquire()
    except Busy as busy:
        job = busy.holder.get("job")
        log.info("lock.busy: %s%s", busy, f" (CI job {job}, pid {busy.holder.get('pid', '?')})" if job else "")
        return None
    try:
        writer = open_writer()
        writer.append("lock.acquired", holder=lease.payload["holder"], nonce=lease.payload["nonce"])
    except BaseException:
        lease.release()
        raise
    return writer


def release_for_run(lease: LocalFileLease, writer: LedgerWriter) -> None:
    try:
        writer.append("lock.released")
    except LedgerClosed:
        pass  # the run already finished its ledger; the lock is still released below
    finally:
        lease.release()


def run_unlock(app: object, **options: object) -> None:
    """The `l4 unlock` handler named in `commands.HANDLERS`; this module exists before the command does."""
    raise L4Exit(ExitCode.USAGE_ERROR, "unlock: not yet implemented (M1: state-vcs-locks)")
