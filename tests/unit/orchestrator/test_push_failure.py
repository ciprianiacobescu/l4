"""Live failure (job 5420): a refused push ended as two chained tracebacks, `internal error` and exit 1."""

import pytest

from l4.vcs.git import Git, GitError
from l4.vcs.push import PushRejected

from ..forge.conftest import TOKEN
from ..implementer.conftest import green_step, red_step
from .conftest import BRANCH

DENIED = "remote: You are not allowed to push code to this project.\nfatal: unable to access 'https://h/p.git/': 403"


class Refusal(list):
    """Every push fails the way the forge said it; the list holds the refspecs of each attempt."""

    stderr = DENIED
    rejected = False


@pytest.fixture
def refused(monkeypatch: pytest.MonkeyPatch) -> Refusal:
    attempts = Refusal()

    def fail(self, remote, branch, *, config=()):
        attempts.append([branch])
        raise (PushRejected if attempts.rejected else GitError)(["git", "push"], 128, attempts.stderr)

    monkeypatch.setattr(Git, "push_branch", fail)
    return attempts


def test_a_denied_push_is_one_clean_exit_3_and_the_final_push_is_not_retried(run_l4, refused, capsys):
    run = run_l4([red_step(), green_step()])
    err = capsys.readouterr().err
    assert run.code == 3
    assert len(refused) == 1  # the red checkpoint; the final ledger push is not attempted again
    assert "Traceback" not in err
    assert f"push of {BRANCH} to origin failed: remote: You are not allowed to push code to this project." in err
    assert "write_repository" in err and TOKEN not in err


def test_another_push_failure_is_exit_1_and_still_one_line(run_l4, refused, capsys):
    refused.stderr = "fatal: unable to access 'https://h/p.git/': Could not resolve host: h"
    run = run_l4([red_step(), green_step()])
    err = capsys.readouterr().err
    assert run.code == 1 and "Traceback" not in err and "Could not resolve host" in err
    assert "internal error" not in err


def test_a_rejected_push_says_nothing_is_forced(run_l4, refused, capsys):
    refused.stderr, refused.rejected = " ! [rejected] HEAD -> x (non-fast-forward)", True
    run = run_l4([red_step(), green_step()])
    assert run.code == 1 and "never forces" in capsys.readouterr().err


def test_a_failing_final_ledger_push_does_not_mask_the_original_error(run_l4, monkeypatch, capsys):
    real = Git.push_branch
    state = {"calls": 0}

    def flaky(self, remote, branch, *, config=()):
        state["calls"] += 1
        if state["calls"] >= 1:  # every push is refused, the final ledger push included
            raise GitError(["git", "push"], 128, DENIED)
        return real(self, remote, branch, config=config)

    def crash(git, protected, base, **kwargs):
        raise RuntimeError("the original failure")

    monkeypatch.setattr(Git, "push_branch", flaky)
    monkeypatch.setattr("l4.implementer.tdd.revert_protected", crash)
    run = run_l4([red_step()])
    err = capsys.readouterr().err
    assert run.code == 1  # the crash, not the push
    assert "the original failure" in err and "could not push the final ledger" in err and "Traceback" not in err
