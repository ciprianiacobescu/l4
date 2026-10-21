import json
import logging
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from l4.redact import Redactor
from l4.state.ledger import LedgerWriter, read_ledger
from l4.vcs.locks import Busy, LocalFileLease, acquire_for_run, release_for_run
from l4.vcs.names import UnitNames

RUN_A, RUN_B = "r-20261003T1312Z-aaaa", "r-20261003T1313Z-bbbb"


@pytest.fixture
def names(tmp_path: Path) -> UnitNames:
    return UnitNames.for_unit("openspec:x", branch_prefix="l4/", cache=tmp_path / "cache", repo_key="proj-0123456789")


def lease(names: UnitNames, run_id: str = RUN_A) -> LocalFileLease:
    return LocalFileLease(names.flock_path, unit=names.unit_id, run_id=run_id)


def test_second_lease_gets_busy_with_the_holder_and_release_frees_it(names: UnitNames):
    first, second = lease(names, RUN_A), lease(names, RUN_B)
    first.acquire()
    assert names.flock_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(Busy) as busy:
        second.acquire()
    assert busy.value.holder["run_id"] == RUN_A and busy.value.holder["unit"] == "openspec:x"
    with pytest.raises(RuntimeError, match="already held"):
        first.acquire()
    first.release()
    second.acquire()  # released
    assert json.loads(names.flock_path.read_text())["run_id"] == RUN_B
    second.release()
    second.release()  # idempotent
    assert names.flock_path.read_text() == ""  # no stale diagnostics after release


def test_second_process_gets_busy_and_sigkill_releases(names: UnitNames):
    code = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from l4.vcs.locks import LocalFileLease\n"
        f"l = LocalFileLease(Path({str(names.flock_path)!r}), unit='openspec:x', run_id={RUN_A!r})\n"
        "l.acquire()\n"
        "print('held', flush=True)\n"
        "time.sleep(60)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout is not None and child.stdout.readline().strip() == "held"
        with pytest.raises(Busy) as busy:
            lease(names, RUN_B).acquire()
        assert busy.value.holder["run_id"] == RUN_A
        child.send_signal(signal.SIGKILL)  # no release(): the kernel drops the lock with the process
        child.wait(timeout=10)
        taken = lease(names, RUN_B)
        taken.acquire()
        taken.release()
    finally:
        child.kill()
        child.wait()


def test_busy_unit_is_skipped_with_exit_zero_and_not_touched(names: UnitNames, tmp_path: Path, caplog):
    unit_dir = tmp_path / "repo" / "openspec" / "changes" / "x"
    holder = lease(names, RUN_A)
    holder.acquire()
    opened: list[str] = []

    def open_writer() -> LedgerWriter:
        opened.append("writer")
        return LedgerWriter.open(unit_dir, "openspec:x", RUN_B, redactor=Redactor({}))

    with caplog.at_level(logging.INFO, logger="l4.lock"):
        assert acquire_for_run(lease(names, RUN_B), open_writer) is None
    assert opened == [] and not unit_dir.exists()  # the unit was not touched, not even by a ledger file
    assert "lock.busy" in caplog.text and RUN_A in caplog.text
    holder.release()


def test_acquired_run_records_lock_events(names: UnitNames, tmp_path: Path):
    unit_dir = tmp_path / "repo" / "openspec" / "changes" / "x"
    mine = lease(names, RUN_B)
    writer = acquire_for_run(mine, lambda: LedgerWriter.open(unit_dir, "openspec:x", RUN_B, redactor=Redactor({})))
    assert writer is not None
    release_for_run(mine, writer)
    writer.finish(0)
    types = [e.type for e in read_ledger(unit_dir).events]
    assert types == ["run.started", "lock.acquired", "lock.released", "run.finished"]
    lease(names, RUN_A).acquire()  # and the lock really is free again


def test_the_lease_records_the_ci_job_and_pid_of_its_holder(tmp_path):
    """W-D2: a busy lock names the CI job that holds it, so an orphan of a cancelled job can be told from a live one."""
    import json

    from l4.vcs.locks import Busy, LocalFileLease

    path = tmp_path / "u.lock"
    held = LocalFileLease(path, unit="openspec:u", run_id="r-1", job="6051")
    held.acquire()
    try:
        assert json.loads(path.read_text())["job"] == "6051" and json.loads(path.read_text())["pid"].isdigit()
        other = LocalFileLease(path, unit="openspec:u", run_id="r-2")
        with pytest.raises(Busy) as busy:
            other.acquire()
        assert busy.value.holder["job"] == "6051"
    finally:
        held.release()
