"""A transient push failure is tried again in `Git._push`, once, for every push (L4-LCK-001, SCN-LCK-10..13)."""

import logging
import signal
from collections.abc import Callable
from pathlib import Path

import pytest

from l4 import cancel
from l4.vcs.git import BOT_IDENTITY, Git, GitError
from l4.vcs.push import PushRejected

BRANCH = "l4/openspec/x"
REF = f"refs/heads/{BRANCH}"
LOCK = "refs/l4/locks/openspec/x"
ARCHIVED = "refs/l4/archived/openspec/x/r-1"
TRANSIENT = "fatal error in commit_refs_rules"
RULE = "GitLab: Push rule: commit message does not follow the pattern"
TRANSIENT_STDERR = (
    f"remote: {TRANSIENT}\nTo https://github.com/o/r\n ! [remote rejected] HEAD -> {BRANCH} (failure)\n"
    "error: failed to push some refs to 'https://github.com/o/r'\n"
)


class Clock:
    """Each call returns the next value; the last one repeats."""

    def __init__(self, *values: float) -> None:
        self.values = list(values)

    def __call__(self) -> float:
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


@pytest.fixture(autouse=True)
def _warnings_reach_caplog(monkeypatch):
    monkeypatch.setattr(logging.getLogger("l4"), "propagate", True)  # `configure_logging` of another test turns it off


@pytest.fixture
def world(make_repo, git_environ, raw, trailers) -> Callable[..., "World"]:
    def make(*, clock: Callable[[], float] | None = None) -> World:
        repo = make_repo(remote=True)
        sleeps: list[float] = []
        git = Git(repo, environ=git_environ, sleep=sleeps.append, monotonic=clock or Clock(0.0))
        git.run("checkout", "-q", "-b", BRANCH)
        (repo / "a.txt").write_text("a\n")
        git.run("add", "-A")
        git.commit("one", trailers, BOT_IDENTITY)
        return World(repo, repo.parent / "repo-origin.git", git, sleeps, raw)

    return make


class World:
    def __init__(self, repo: Path, origin: Path, git: Git, sleeps: list[float], raw: Callable[..., str]) -> None:
        self.repo, self.origin, self.git, self.sleeps, self._raw = repo, origin, git, sleeps, raw

    @property
    def calls(self) -> int:
        counter = self.origin / "calls"
        return int(counter.read_text()) if counter.exists() else 0

    def hook(self, message: str, *, failures: int) -> None:
        """The first `failures` pushes print `message` and are refused, the rest are accepted; every call is counted."""
        calls = self.origin / "calls"
        path = self.origin / "hooks" / "pre-receive"
        path.write_text(
            f"#!/bin/sh\nn=$(cat {calls} 2>/dev/null || echo 0)\nn=$((n+1))\necho $n > {calls}\n"
            f'if [ "$n" -le {failures} ]; then echo "{message}" >&2; exit 1; fi\nexit 0\n'
        )
        path.chmod(0o755)

    def head(self) -> str:
        return self._raw(self.repo, "rev-parse", "HEAD").strip()

    def remote(self, ref: str = REF) -> str:
        out = self._raw(self.repo, "ls-remote", "origin", ref).split()
        return out[0] if out else ""

    def pushes(self) -> list[list[str]]:
        return [argv for argv in self.git.history if "push" in argv]


def push_then_fail(monkeypatch, *, times: int = 1, ls_remote_fails: int = 0) -> dict[str, int]:
    """The first `times` pushes really run (so they land) and then report a server error, as a response that was lost on
    the way back would; the first `ls_remote_fails` calls of `ls-remote` fail."""
    real = Git.run
    seen = {"push": 0, "ls-remote": 0}

    def run(self, *args, **kw):
        if args and args[0] in seen:
            seen[args[0]] += 1
        if args and args[0] == "push":
            done = real(self, *args, **kw)
            if seen["push"] <= times:
                raise GitError(["git", *args], 1, TRANSIENT_STDERR)
            return done
        if args and args[0] == "ls-remote" and seen["ls-remote"] <= ls_remote_fails:
            raise GitError(["git", *args], 128, "fatal: unable to access: Could not resolve host: h")
        return real(self, *args, **kw)

    monkeypatch.setattr(Git, "run", run)
    return seen


def test_a_server_error_is_tried_again_and_the_branch_holds_head(world, caplog):
    """SCN-LCK-11."""
    w = world()
    w.hook(TRANSIENT, failures=1)
    with caplog.at_level(logging.WARNING):
        w.git.push("origin", [f"HEAD:{REF}"])
    assert w.remote() == w.head()
    assert w.sleeps == [5.0] and w.calls == 2
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "push" in warnings[0].getMessage().lower()


def test_the_unit_branch_push_with_a_lease_is_tried_again(world):
    w = world()
    w.hook(TRANSIENT, failures=1)
    w.git.push_branch("origin", BRANCH)
    assert w.remote() == w.head() and w.sleeps == [5.0] and w.calls == 2


def test_three_failures_raise_the_error_after_three_tries(world):
    w = world()
    w.hook(TRANSIENT, failures=9)
    with pytest.raises(GitError) as caught:
        w.git.push("origin", [f"HEAD:{REF}"])
    assert not isinstance(caught.value, PushRejected) and TRANSIENT in caught.value.stderr
    assert w.calls == 3 and w.sleeps == [5.0, 15.0] and w.remote() == ""


def test_no_try_starts_more_than_60_seconds_after_the_first(world):
    clock = Clock(0.0, 61.0)
    w = world(clock=clock)
    w.hook(TRANSIENT, failures=9)
    with pytest.raises(GitError):
        w.git.push("origin", [f"HEAD:{REF}"])
    assert w.calls == 1 and w.sleeps == []


def test_the_second_wait_must_fit_in_the_budget_too(world):
    w = world(clock=Clock(0.0, 10.0, 50.0))  # 10 + 5 fits, 50 + 15 does not
    w.hook(TRANSIENT, failures=9)
    with pytest.raises(GitError):
        w.git.push("origin", [f"HEAD:{REF}"])
    assert w.calls == 2 and w.sleeps == [5.0]


def test_a_push_rule_runs_once_and_does_not_wait(world):
    """SCN-LCK-10."""
    w = world()
    w.hook(RULE, failures=9)
    with pytest.raises(GitError) as caught:
        w.git.push("origin", [f"HEAD:{REF}"])
    assert not isinstance(caught.value, PushRejected) and RULE in caught.value.stderr
    assert w.calls == 1 and w.sleeps == []


def test_a_permission_marker_wins_over_a_server_error_in_the_same_message(world):
    w = world()
    w.hook(f"{TRANSIENT} permission denied", failures=9)
    with pytest.raises(GitError):
        w.git.push("origin", [f"HEAD:{REF}"])
    assert w.calls == 1 and w.sleeps == []


def test_a_non_fast_forward_is_raised_at_once(world, raw, tmp_path):
    w = world()
    human = tmp_path / "human"
    raw(tmp_path, "clone", "-q", str(w.origin), str(human))
    raw(human, "checkout", "-q", "-b", BRANCH)
    (human / "h.txt").write_text("h\n")
    raw(human, "add", "-A")
    raw(human, "commit", "-q", "-m", "human")
    raw(human, "push", "-q", "origin", BRANCH)
    with pytest.raises(PushRejected):
        w.git.push("origin", [f"HEAD:{REF}"])
    assert len(w.pushes()) == 1 and w.sleeps == []


def test_a_push_that_landed_is_not_pushed_twice_by_plain_refspec(world, monkeypatch):
    """SCN-LCK-12."""
    w = world()
    seen = push_then_fail(monkeypatch)
    w.git.push("origin", [f"HEAD:{REF}"])
    assert seen["push"] == 1 and seen["ls-remote"] == 1 and w.sleeps == [5.0]
    assert w.remote() == w.head()


def test_a_push_that_landed_is_not_refused_by_its_own_lease(world, monkeypatch):
    """SCN-LCK-12: pushing again under the lease of the first push would be refused."""
    w = world()
    seen = push_then_fail(monkeypatch)
    done = w.git.push_branch("origin", BRANCH)
    assert seen["push"] == 1 and seen["ls-remote"] == 1 and done.returncode == 0
    assert w.remote() == w.head()
    assert w.git._branch_seen[BRANCH] == w.head()


def test_a_delete_that_landed_is_found_by_the_ref_being_absent(world, monkeypatch):
    w = world()
    w.git.push("origin", [f"HEAD:{REF}"])
    sha = w.head()
    seen = push_then_fail(monkeypatch)
    w.git.push_delete("origin", BRANCH, sha)
    assert seen["push"] == 1 and seen["ls-remote"] == 1 and w.remote() == ""


def test_an_atomic_retire_that_landed_needs_every_ref_to_match(world, monkeypatch):
    w = world()
    sha = w.head()
    w.git.push_lease("origin", sha, LOCK, "")
    seen = push_then_fail(monkeypatch)
    w.git.retire_lock_ref("origin", sha, LOCK, ARCHIVED)
    assert seen["push"] == 1 and seen["ls-remote"] == 1
    assert w.remote(ARCHIVED) == sha and w.remote(LOCK) == ""


def test_a_keep_ref_that_landed_is_not_pushed_twice(world, monkeypatch):
    w = world()
    ref = "refs/l4/merged/openspec/x"
    seen = push_then_fail(monkeypatch)
    w.git.push_keep("origin", w.head(), ref)
    assert seen["push"] == 1 and w.remote(ref) == w.head()


def test_a_restart_that_landed_is_not_pushed_twice(world, monkeypatch):
    w = world()
    sha = w.head()
    w.git.push_lease("origin", sha, LOCK, "")
    seen = push_then_fail(monkeypatch)
    w.git.restart_push("origin", BRANCH, "", (LOCK, sha, "refs/l4/attempts/openspec/x/1"))
    assert seen["push"] == 1 and seen["ls-remote"] == 1
    assert w.remote() == sha and w.remote(LOCK) == "" and w.remote("refs/l4/attempts/openspec/x/1") == sha


def test_an_ls_remote_that_fails_counts_as_not_landed(world, monkeypatch):
    w = world()
    seen = push_then_fail(monkeypatch, ls_remote_fails=9)
    w.git.push("origin", [f"HEAD:{REF}"])  # the second push finds nothing to do and succeeds
    assert seen["push"] == 2 and seen["ls-remote"] == 1 and w.sleeps == [5.0]


def test_a_lease_refusal_after_a_server_error_is_checked_against_the_remote(world, monkeypatch):
    """The first push lands and reports a server error, the first `ls-remote` fails, and the second push is refused by
    the lease (a server that checks it itself); the second `ls-remote` finds the ref at HEAD, so the push is done."""
    w = world()
    real = Git.run
    seen = {"push": 0, "ls-remote": 0}

    def run(self, *args, **kw):
        seen[args[0]] = seen.get(args[0], 0) + 1
        if args[0] == "push":
            if seen["push"] == 1:
                real(self, *args, **kw)
                raise GitError(["git", *args], 1, TRANSIENT_STDERR)
            raise GitError(["git", *args], 1, f" ! [rejected]        HEAD -> {BRANCH} (stale info)\n")
        if args[0] == "ls-remote" and seen["ls-remote"] == 1:
            raise GitError(["git", *args], 128, "fatal: unable to access: Could not resolve host: h")
        return real(self, *args, **kw)

    monkeypatch.setattr(Git, "run", run)
    done = w.git.push_branch("origin", BRANCH)
    assert done.returncode == 0 and seen["push"] == 2 and seen["ls-remote"] == 2
    assert w.remote() == w.head() and w.git._branch_seen[BRANCH] == w.head()


def test_a_lease_refusal_after_a_server_error_is_a_rejection_when_it_did_not_land(world, monkeypatch, raw, tmp_path):
    w = world()
    human = tmp_path / "human"
    raw(tmp_path, "clone", "-q", str(w.origin), str(human))
    raw(human, "checkout", "-q", "-b", BRANCH)
    (human / "h.txt").write_text("h\n")
    raw(human, "add", "-A")
    raw(human, "commit", "-q", "-m", "human")
    raw(human, "push", "-q", "origin", BRANCH)
    theirs = raw(human, "rev-parse", "HEAD").strip()
    real = Git.run
    pushes = {"n": 0}

    def run(self, *args, **kw):
        if args and args[0] == "push":
            pushes["n"] += 1
            if pushes["n"] == 1:
                raise GitError(["git", *args], 1, TRANSIENT_STDERR)  # nothing landed
        return real(self, *args, **kw)

    monkeypatch.setattr(Git, "run", run)
    with pytest.raises(PushRejected):
        w.git.push_branch("origin", BRANCH)
    assert pushes["n"] == 2 and w.remote() == theirs and w.sleeps == [5.0]


def test_a_lease_refusal_without_an_earlier_server_error_is_not_looked_up(world, monkeypatch, raw, tmp_path):
    w = world()
    w.git.push("origin", [f"HEAD:{REF}"])
    w.git.run("update-ref", "-d", f"refs/remotes/origin/{BRANCH}")
    raw(w.repo, "commit", "-q", "--allow-empty", "-m", "two")  # so that the lease, which expects no branch, is refused
    real = Git.run
    seen: list[str] = []

    def run(self, *args, **kw):
        seen.append(args[0])
        return real(self, *args, **kw)

    monkeypatch.setattr(Git, "run", run)
    with pytest.raises(PushRejected):  # the lease expects the branch absent, and it exists
        w.git.push_branch("origin", BRANCH)
    assert "ls-remote" not in seen and w.sleeps == []


def test_a_cancel_stops_the_run_before_the_next_try(world):
    w = world()
    w.hook(TRANSIENT, failures=9)
    w.git._sleep = lambda seconds: cancel.request(signal.SIGTERM)  # the signal arrives while the harness waits
    try:
        with pytest.raises(cancel.RunCancelled):
            w.git.push("origin", [f"HEAD:{REF}"])
    finally:
        cancel.reset()
    assert w.calls == 1
