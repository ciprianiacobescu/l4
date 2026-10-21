"""W-D2 (SAFETY): a signal during a run stops it where it is. Nothing is committed or pushed afterwards, the unit
lock is free again, and the exit code is 16 (job 6051: the cancelled job's `l4 run` lived on and would have pushed)."""

import signal

import pytest

from l4 import cancel
from l4.agents.fake import FakeAdapter
from l4.cancel import RunCancelled
from l4.vcs.git import Git

from ..implementer.conftest import green_step, red_step
from .conftest import BRANCH


@pytest.fixture(autouse=True)
def _clean_flag():
    cancel.reset()
    yield
    cancel.reset()


def _cancel_on_call(monkeypatch: pytest.MonkeyPatch, nth: int, on_cancel=None) -> None:
    real, calls = FakeAdapter.run, {"n": 0}

    def run(self, req):
        calls["n"] += 1
        if calls["n"] == nth:
            if on_cancel is not None:
                on_cancel()
            cancel.request(signal.SIGTERM)
            raise RunCancelled(signal.SIGTERM)
        return real(self, req)

    monkeypatch.setattr(FakeAdapter, "run", run)


def test_a_cancel_during_the_green_step_pushes_nothing_after_it(run_l4, tdd_repo, raw, monkeypatch):
    """Every push goes through `Git._push` (the unit branch, the lock ref, the pending ledger, a retire): count them
    all, and what `origin` holds, at the moment of the cancel and at the end of the run."""
    pushes: list[list[str]] = []
    real_push = Git._push

    def spy(self, args, config, moved):
        pushes.append(list(args))
        return real_push(self, args, config, moved)

    def origin_refs() -> str:
        return raw(tdd_repo.origin, "for-each-ref", "--format=%(refname) %(objectname)")

    at_cancel: dict[str, object] = {}

    def snapshot() -> None:
        at_cancel.update(pushes=len(pushes), refs=origin_refs())

    monkeypatch.setattr(Git, "_push", spy)
    _cancel_on_call(monkeypatch, 2, snapshot)  # the red step ran and was checkpointed; the green step is cancelled
    run = run_l4([red_step(), green_step()])
    assert run.code == 16
    assert at_cancel["pushes"] >= 1 and BRANCH in str(at_cancel["refs"])  # the red checkpoint reached origin
    assert len(pushes) == at_cancel["pushes"], pushes[at_cancel["pushes"] :]  # and nothing after the cancel
    assert origin_refs() == at_cancel["refs"]
    assert run.outcome["exit_code"] == 16
    assert run.local_events("run.cancelled")
    assert run.local_events("lock.released")


def test_a_cancel_before_any_push_leaves_the_remote_without_the_branch(run_l4, monkeypatch):
    _cancel_on_call(monkeypatch, 1)
    run = run_l4([red_step(), green_step()])
    assert run.code == 16
    assert run.raw(run.tdd.origin, "for-each-ref", f"refs/heads/{BRANCH}").strip() == ""


def test_the_lock_is_free_after_a_cancel(run_l4, monkeypatch):
    _cancel_on_call(monkeypatch, 1)
    first = run_l4([red_step(), green_step()])
    assert first.code == 16
    from l4.vcs.locks import LocalFileLease
    from l4.vcs.names import UnitNames

    from ..conftest import UNIT

    names = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=first.tdd.cache, repo_key=first.tdd.key)
    lease = LocalFileLease(names.flock_path, unit=UNIT, run_id="r-next")
    lease.acquire()  # free at once, not only when the process ends
    lease.release()
    cancel.reset()
    monkeypatch.undo()
    second = run_l4([red_step(), green_step()])
    assert second.code != 0 or second.outcome["units"]  # it ran (no `lock.busy` skip): the unit has a phase now
    assert "lock.busy" not in str(second.outcome)


def test_push_refuses_once_cancelled(run_l4, monkeypatch):
    from l4.orchestrator import Orchestrator

    cancel.request(signal.SIGTERM)
    with pytest.raises(RunCancelled):
        Orchestrator.push(object.__new__(Orchestrator))
