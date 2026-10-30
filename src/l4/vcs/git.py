"""The only way the harness runs git (L4-SEC-006): hooks and fsmonitor off, no inherited repository redirection."""

import contextlib
import logging
import os
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from l4 import cancel
from l4.exitcodes import ExitCode, L4Exit
from l4.safepath import resolve_tool, safe_path
from l4.vcs.errors import GitError
from l4.vcs.push import (
    BranchGone,
    BranchMoved,
    BranchRewritten,
    PushRejected,
    build_branch_push_args,
    build_delete_args,
    build_keep_args,
    build_lease_push_args,
    build_plan_push_args,
    build_push_args,
    build_restart_args,
    build_retire_args,
    is_lost_lease,
    is_non_fast_forward,
    is_transient_push_failure,
)
from l4.vcs.trailers import CommitTrailers, render

if TYPE_CHECKING:
    from l4.vcs.race import AnswerMerge

__all__ = ["BOT_IDENTITY", "HARDENING", "Git", "GitError", "GitResult", "Identity"]

HARDENING = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "protocol.ext.allow=never")

# Inherited variables that would point git at a different repository, index or config than the one we mean, and the
# identity variables, which beat `-c user.name`: the harness's commits are the bot's, or they read as a person's
# (L4-ARC-008 (d), L4-SEC-004).
_SCRUBBED = frozenset(
    {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_PREFIX", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
        "GIT_EXEC_PATH", "GIT_EXTERNAL_DIFF",
        "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
    }
)  # fmt: skip
_SCRUBBED_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
DEFAULT_TIMEOUT = 120.0
# a push the forge failed on its side is tried up to PUSH_TRIES times, waiting PUSH_WAITS between the tries, and no
# try starts more than PUSH_BUDGET seconds after the first (L4-LCK-001)
PUSH_TRIES = 3
PUSH_WAITS = (5.0, 15.0)
PUSH_BUDGET = 60.0
TMP_REF_PREFIX = "refs/l4/tmp"  # under it, per process and branch, the head of a moved unit branch is fetched to

log = logging.getLogger("l4.git")


@dataclass(frozen=True)
class Identity:
    name: str
    email: str


# Commits are authored by the configured bot identity (L4-IMP-007); the forge-and-ci change binds the real account.
BOT_IDENTITY = Identity("l4-bot", "l4-bot@users.noreply.invalid")


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


def _git_env(environ: Mapping[str, str], forbid: Sequence[Path]) -> dict[str, str]:
    env = {k: v for k, v in environ.items() if k not in _SCRUBBED and not k.startswith(_SCRUBBED_PREFIXES)}
    env["PATH"] = safe_path(environ, forbid=forbid)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    return env


def _first_line(stderr: str) -> str:
    return next((line.strip() for line in stderr.splitlines() if line.strip()), "no message")


class Git:
    """Runs `git <HARDENING> <args>` in `repo`; `history` records every argv (tests assert on it).

    git is resolved once to an absolute path on a PATH without empty, relative or checkout entries, so a `git`
    planted in the repository or a worktree is never run (L4-SEC-006); `forbid` adds further checkouts.
    """

    def __init__(
        self,
        repo: Path,
        *,
        environ: Mapping[str, str] | None = None,
        forbid: Sequence[Path] = (),
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.repo = repo
        self._sleep, self._monotonic = sleep, monotonic  # the retry of a push waits through these (tests inject them)
        self.forbid = (*forbid, repo)
        source = os.environ if environ is None else environ
        self.env = _git_env(source, self.forbid)
        self.exe = resolve_tool("git", self.env, forbid=self.forbid)
        if self.exe is None:
            raise L4Exit(ExitCode.DOCTOR_FAILED, "git was not found on a safe PATH; run `l4 doctor`")
        self.history: list[list[str]] = []
        self.on_commit: Callable[[str, str], None] | None = None  # (sha, subject): the console progress trace
        self.on_push: Callable[[str, str | None, str], None] | None = None  # (branch, old sha or None, new sha)
        self._branch_seen: dict[str, str] = {}  # branch -> the sha this object pushed last (see `push_branch`)

    def at(self, repo: Path) -> "Git":
        other = Git(repo, environ=self.env, forbid=self.forbid, sleep=self._sleep, monotonic=self._monotonic)
        other.on_commit, other.on_push = self.on_commit, self.on_push
        return other

    def _argv(self, args: Sequence[str], config: Sequence[tuple[str, str]]) -> list[str]:
        assert self.exe is not None
        argv = [self.exe, *HARDENING, *(part for key, value in config for part in ("-c", f"{key}={value}")), *args]
        self.history.append(["git", *argv[1:]])
        return argv

    def run(
        self,
        *args: str,
        check: bool = True,
        input: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        config: Sequence[tuple[str, str]] = (),
    ) -> GitResult:
        argv = self._argv(args, config)
        try:
            done = subprocess.run(
                argv, cwd=self.repo, env=self.env, input=input, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout, check=False,
                stdin=subprocess.DEVNULL if input is None else None,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            raise GitError(argv, 124, "timed out") from None
        result = GitResult(done.returncode, done.stdout, done.stderr)
        if check and result.returncode != 0:
            raise GitError(argv, result.returncode, result.stderr)
        return result

    def repo_hooks_path(self) -> str:
        """Where the repository's own hooks are: `core.hooksPath` of the local, global or system configuration (the
        nearest wins, read per scope because `HARDENING` pins the merged value to /dev/null), else the common git
        directory's `hooks`. For the one call that must run the person's hooks, as a later `-c core.hooksPath=...`
        (the last `-c` wins over `HARDENING`'s)."""
        for scope in ("--local", "--global", "--system"):
            done = self.run("config", scope, "--get", "core.hooksPath", check=False)
            if done.returncode == 0 and done.stdout.strip():
                return done.stdout.strip()
        common = self.run("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        return str(Path(common) / "hooks")

    def run_bytes(self, *args: str, check: bool = True, timeout: float = DEFAULT_TIMEOUT) -> bytes:
        """stdout exactly as git wrote it. `run` decodes and may translate bytes (U+FFFD for invalid UTF-8), so
        anything that must match the file byte for byte (tasks.md, ledger lines) is read through here."""
        argv = self._argv(args, ())
        try:
            done = subprocess.run(
                argv, cwd=self.repo, env=self.env, capture_output=True, timeout=timeout, check=False,
                stdin=subprocess.DEVNULL,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            raise GitError(argv, 124, "timed out") from None
        if check and done.returncode != 0:
            raise GitError(argv, done.returncode, done.stderr.decode("utf-8", "replace"))
        return done.stdout if done.returncode == 0 else b""

    def run_input_bytes(
        self, *args: str, data: bytes, check: bool = True, timeout: float = DEFAULT_TIMEOUT
    ) -> GitResult:
        """`run` with `data` on standard input, byte for byte (`git apply -` of a binary patch)."""
        argv = self._argv(args, ())
        try:
            done = subprocess.run(
                argv, cwd=self.repo, env=self.env, input=data, capture_output=True, timeout=timeout, check=False
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            raise GitError(argv, 124, "timed out") from None
        result = GitResult(
            done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")
        )
        if check and result.returncode != 0:
            raise GitError(argv, result.returncode, result.stderr)
        return result

    def rev_parse(self, ref: str) -> str | None:
        done = self.run("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
        return done.stdout.strip() if done.returncode == 0 else None

    def fetch(
        self,
        remote: str,
        *,
        refspecs: Sequence[str] = (),
        prune: bool = False,
        config: Sequence[tuple[str, str]] = (),
    ) -> None:
        """Without `refspecs` the remote's configured ones. `--prune` removes only the local refs that the given
        (or configured) refspecs map from a ref the remote no longer has."""
        self.run("fetch", "--quiet", *(["--prune"] if prune else []), remote, *refspecs, config=config)

    def commit(
        self, message: str, trailers: CommitTrailers, identity: Identity = BOT_IDENTITY, *, allow_empty: bool = False
    ) -> str:
        """Commit what is staged. Never runs hooks or signs; refuses a missing mandatory trailer first."""
        rendered = render(trailers)
        args = ["commit", "--quiet", "--no-verify", "--no-gpg-sign", "-m", message]
        args += [part for key, value in rendered for part in ("--trailer", f"{key}: {value}")]
        if allow_empty:
            args.append("--allow-empty")
        self.run(*args, config=(("user.name", identity.name), ("user.email", identity.email)))
        sha = self.run("rev-parse", "HEAD").stdout.strip()
        if self.on_commit is not None:
            with contextlib.suppress(Exception):  # a console line never fails a commit
                self.on_commit(sha, message)
        return sha

    def push(self, remote: str, refspecs: Sequence[str], *, config: Sequence[tuple[str, str]] = ()) -> GitResult:
        """Fast-forward only: `+` refspecs and force options are refused before git runs (L4-RACE-001).

        `config` is for authentication (SPEC 16.3): `remote.<name>.pushurl` set to a credential-free URL, because a
        checkout's origin URL may embed a CI job token that git prefers over any helper, plus a `credential.helper`
        that reads L4_FORGE_TOKEN from the environment by name. The token itself never goes into argv.
        """
        cancel.check()  # W-D2: no git push after a cancel, whichever caller asks
        watched = self.on_push is not None
        targets = [r.split(":", 1) for r in refspecs if r.count(":") == 1 and ":refs/heads/" in r] if watched else []
        old = {dst: self.rev_parse(f"refs/remotes/{remote}/{dst.removeprefix('refs/heads/')}") for _, dst in targets}
        done = self._push(build_push_args(remote, refspecs), config, is_non_fast_forward)
        if self.on_push is not None:
            for src, dst in targets:
                new = self.rev_parse(src)
                if new is not None:
                    with contextlib.suppress(Exception):
                        self.on_push(dst.removeprefix("refs/heads/"), old[dst], new)
        return done

    def push_branch(
        self,
        remote: str,
        branch: str,
        *,
        config: Sequence[tuple[str, str]] = (),
        answers: "AnswerMerge | None" = None,
    ) -> GitResult:
        """Push HEAD to the unit branch under a lease on the last value this checkout saw of it (W-D2): a branch a
        person deleted is not recreated and one a person moved is not overwritten, both `PushRejected`. The value is
        the remote-tracking ref, or, when a fetch pruned that, what this object pushed last. Fast-forward only.

        A refused lease is told apart (`BranchGone`, `BranchMoved`, `BranchRewritten`, all `PushRejected`). With
        `answers`, a branch that moved forward by a person's answers only is merged and pushed again (L4-RACE-001,
        `l4.vcs.race`); without, it stays an error."""
        if answers is None:
            return self.push_branch_once(remote, branch, config=config)
        from l4.vcs.race import push_merging  # race imports this module

        return push_merging(self, remote, branch, answers, config=config)

    def lease_value(self, remote: str, branch: str) -> str:
        """What the unit branch's lease holds: the remote-tracking ref, else what this object pushed last, else ''."""
        return self.rev_parse(f"refs/remotes/{remote}/{branch}") or self._branch_seen.get(branch, "")

    def note_remote_head(self, remote: str, branch: str, sha: str) -> None:
        """The next lease on the unit branch is `sha`: the head this checkout fetched and merged."""
        self._branch_seen[branch] = sha
        with contextlib.suppress(GitError):
            self.run("update-ref", f"refs/remotes/{remote}/{branch}", sha)

    def pause(self, seconds: float) -> None:
        """Wait, through the clock this object was given (a test's does not sleep)."""
        self._sleep(seconds)

    def push_branch_once(self, remote: str, branch: str, *, config: Sequence[tuple[str, str]] = ()) -> GitResult:
        """One push of `push_branch`, with the refusal of the lease classified."""
        tracking = f"refs/remotes/{remote}/{branch}"
        expected = self.lease_value(remote, branch)
        argv = build_branch_push_args(remote, branch, expected)
        if expected and self.run("merge-base", "--is-ancestor", expected, "HEAD", check=False).returncode != 0:
            raise PushRejected(  # git would force this once the lease holds, so it is refused here
                ["git", *argv], 1, f" ! [rejected]        HEAD -> {branch} (non-fast-forward)\n"
                "the local branch does not contain the remote one",
            )  # fmt: skip
        try:
            done = self._push(argv, config, is_lost_lease)
        except PushRejected as rejected:
            raise self.classify_lease(remote, branch, rejected, config=config) from None
        if (new := self.rev_parse("HEAD")) is not None:
            self._branch_seen[branch] = new
            # git moves the tracking ref only when a configured fetch refspec covers the branch (not in a
            # `--single-branch` clone): without this the next push would lease on a stale value and be refused
            with contextlib.suppress(GitError):
                self.run("update-ref", tracking, new)
            if self.on_push is not None:
                with contextlib.suppress(Exception):
                    self.on_push(branch, expected or None, new)
        return done

    def classify_lease(
        self, remote: str, branch: str, rejected: PushRejected, *, config: Sequence[tuple[str, str]] = ()
    ) -> PushRejected:
        """Tell a refused lease of the unit branch apart with `git ls-remote` (L4-RACE-001): `BranchGone` (no such
        branch), `BranchMoved` (the lease value is an ancestor of the remote head, which is fetched to a private ref
        to read what changed there and removed again), `BranchRewritten` (it is not). `rejected` itself when the
        remote cannot be asked, or still holds the lease value (then the lease failed for another reason)."""
        ref, expected = f"refs/heads/{branch}", self.lease_value(remote, branch)
        try:
            listed = self.run("ls-remote", remote, ref, config=config).stdout
        except GitError:
            return rejected
        head = next((line.split("\t", 1)[0] for line in listed.splitlines() if line.endswith(f"\t{ref}")), None)
        if head is None:
            return BranchGone(rejected)
        if head == expected:
            return rejected
        if not expected:
            return BranchRewritten(rejected, head)
        look = f"{TMP_REF_PREFIX}/{os.getpid()}/{branch}"  # no other worktree or run of this clone shares it
        try:
            # `--refmap=` : the configured refspec must not move the tracking ref, which is the lease value
            self.run("fetch", "--quiet", "--no-tags", "--refmap=", remote, f"+{ref}:{look}", config=config)
            fetched = self.rev_parse(look)
        except GitError:
            return rejected
        finally:
            self.run("update-ref", "-d", look, check=False)
        if fetched is None:
            return rejected
        ancestry = self.run("merge-base", "--is-ancestor", expected, fetched, check=False).returncode
        if ancestry == 1:
            return BranchRewritten(rejected, fetched, expected)
        if ancestry != 0:
            return rejected
        paths, irregular = self._changes(expected, fetched)
        count = int(self.run("rev-list", "--count", f"{expected}..{fetched}").stdout.strip() or 0)
        return BranchMoved(rejected, fetched, paths, count, irregular=irregular)

    def _changes(self, old: str, new: str) -> tuple[list[str], list[str]]:
        """The paths the commits `old..new` change, commit by commit (a change that a later commit reverts still
        counts), and those among them that some commit did not leave a regular file: deleted, mode changed, a link, a
        submodule. A merge commit is read against each of its parents (`-m`)."""
        raw = self.run_bytes("log", "-m", "--raw", "-z", "--no-renames", "--format=", f"{old}..{new}")
        tokens = raw.split(b"\0")
        paths: set[str] = set()
        irregular: set[str] = set()
        for meta, name in zip(tokens, tokens[1:], strict=False):
            if not meta.startswith(b":"):
                continue
            fields = meta[1:].split()  # old mode, new mode, old sha, new sha, status
            path = os.fsdecode(name)
            paths.add(path)
            if len(fields) < 5 or fields[4] not in (b"A", b"M") or fields[1] != b"100644":
                irregular.add(path)
        return sorted(paths), sorted(irregular)

    def push_delete(
        self, remote: str, branch: str, expect: str, *, config: Sequence[tuple[str, str]] = ()
    ) -> GitResult:
        """Delete a branch on the remote only if it still holds `expect` (squash-and-delete D6); `PushRejected` when the
        lease is lost. git also removes the local remote-tracking ref."""
        return self._push(build_delete_args(remote, branch, expect), config, is_lost_lease)

    def push_keep(self, remote: str, sha: str, ref: str, *, config: Sequence[tuple[str, str]] = ()) -> GitResult:
        """Create `ref` (under `refs/l4/merged/`) at `sha`; `PushRejected` when it exists already."""
        return self._push(build_keep_args(remote, sha, ref), config, is_lost_lease)

    def restart_push(
        self,
        remote: str,
        branch: str,
        old_head: str,
        lock: tuple[str, str, str] | None = None,
        *,
        config: Sequence[tuple[str, str]] = (),
    ) -> GitResult:
        """`l4 restart` (L4-OPS-004): HEAD replaces the unit branch (leased on `old_head`, '' = absent) and the lock ref
        `lock = (ref, sha, archived)` moves to `archived`, one atomic push. `PushRejected` when any lease is lost, with
        nothing changed on the remote."""
        cancel.check()
        return self._push(build_restart_args(remote, branch, old_head, lock), config, is_lost_lease)

    def push_lease(
        self, remote: str, sha: str, ref: str, expected: str, *, config: Sequence[tuple[str, str]] = ()
    ) -> GitResult:
        """Push a commit to a lock ref under a lease: refused by the server when the ref is no longer `expected`
        (`''`: must not exist yet). Raises `PushRejected` for that, so the caller can read the new value and retry."""
        return self._push(build_lease_push_args(remote, sha, ref, expected), config, is_lost_lease)

    def push_plan(
        self, remote: str, sha: str, ref: str, expected: str, *, config: Sequence[tuple[str, str]] = ()
    ) -> GitResult:
        """Push a commit to a plan ref (`refs/l4/plans/<id>`) in one atomic push under a lease on `expected` (`''`: must
        not exist yet). `PushRejected` when the lease is lost, so the caller reads the plan again."""
        return self._push(build_plan_push_args(remote, sha, ref, expected), config, is_lost_lease)

    def retire_lock_ref(
        self, remote: str, sha: str, ref: str, archived: str, *, config: Sequence[tuple[str, str]] = ()
    ) -> GitResult:
        """Move a lock ref that still holds `sha` to `archived`, both ends under a lease and in one atomic push.
        Raises `PushRejected` when the lock ref moved or the archived name is taken."""
        return self._push(build_retire_args(remote, sha, ref, archived), config, is_lost_lease)

    def _push(self, args: Sequence[str], config: Sequence[tuple[str, str]], moved: Callable[[str], bool]) -> GitResult:
        """`moved` says whether a refusal means the ref moved on (`PushRejected`); every other refusal, a protected
        branch or a push rule included, stays a `GitError` for `explain_push_failure` (G12).

        A failure on the forge's side (`is_transient_push_failure`) is tried again, up to `PUSH_TRIES` tries with
        `PUSH_WAITS` between them and none starting more than `PUSH_BUDGET` seconds after the first (L4-LCK-001).
        Before each new try, and when a try after a transient one finds the ref moved, `_landed` asks the remote whether
        the earlier push went through although git reported an error: the lease of a push that landed would refuse the
        same push again."""
        cancel.check()  # W-D2: the lock ref, the pending ledger and the retire push too
        started = self._monotonic()
        transient: str | None = None  # git's message of the last transient failure
        last: GitError | None = None
        for attempt in range(1, PUSH_TRIES + 1):
            if last is not None and self._monotonic() - started > PUSH_BUDGET:
                break  # the wait and the check that followed it ended past the budget: no new try
            try:
                return self.run(*args, config=config)
            except GitError as exc:
                exc.tries = attempt
                if moved(exc.stderr):
                    if transient is not None and self._landed(args, config):
                        return self._landed_result(args, transient)
                    rejected = PushRejected(exc.argv, exc.returncode, exc.stderr)
                    rejected.tries = attempt
                    raise rejected from None
                if not is_transient_push_failure(exc.stderr):
                    raise
                transient, last = exc.stderr, exc
                wait = PUSH_WAITS[attempt - 1] if attempt < PUSH_TRIES else 0.0
                if attempt == PUSH_TRIES or self._monotonic() - started + wait > PUSH_BUDGET:
                    break  # the last try, or no time for another: but the push may have landed all the same
                log.warning(
                    "the push failed on the forge's side (%s); trying again in %gs (try %d of %d)",
                    _first_line(exc.stderr), wait, attempt + 1, PUSH_TRIES,
                )  # fmt: skip
                self._sleep(wait)
                cancel.check()
                if self._landed(args, config):
                    return self._landed_result(args, transient)
        assert last is not None and transient is not None
        if self._landed(args, config):
            return self._landed_result(args, transient)
        raise last

    def _landed_result(self, args: Sequence[str], stderr: str) -> GitResult:
        """The push went through although git reported an error: say so, and leave the remote-tracking refs as git does
        after a success (`refs/remotes/<remote>/<b>` at the pushed commit, or removed for a delete)."""
        log.info("the push landed although git reported a server error")
        if (expected := self._expected(args)) is not None:
            remote, wanted = expected
            for dst, sha in wanted.items():
                if dst.startswith("refs/heads/"):
                    tracking = f"refs/remotes/{remote}/{dst.removeprefix('refs/heads/')}"
                    with contextlib.suppress(GitError):
                        self.run(*(["update-ref", tracking, sha] if sha else ["update-ref", "-d", tracking]))
        return GitResult(0, "", stderr)

    def _expected(self, args: Sequence[str]) -> tuple[str, dict[str, str]] | None:
        """The remote of the push `args` and the value each destination ref should hold when it went through (`''`:
        absent, for a delete). `args` is one of the argv shapes of `l4.vcs.push`: options, `--`, the remote, then
        `src:dst` refspecs. None for any other shape or a source that git cannot resolve."""
        if "--" not in args:
            return None
        remote, *specs = args[list(args).index("--") + 1 :]
        wanted: dict[str, str] = {}
        for spec in specs:
            src, colon, dst = spec.partition(":")
            if not colon or not dst.startswith("refs/"):
                return None
            if src:
                if (sha := self.rev_parse(src)) is None:
                    return None
                wanted[dst] = sha
            else:
                wanted[dst] = ""
        return (remote, wanted) if wanted else None

    def _landed(self, args: Sequence[str], config: Sequence[tuple[str, str]]) -> bool:
        """Whether every ref of the push `args` already holds the value pushed on the remote (absent for a delete). Any
        error of `ls-remote`, or a push whose refs cannot be told, is "not known to have landed"."""
        if (expected := self._expected(args)) is None:
            return False
        remote, wanted = expected
        try:
            listed = self.run("ls-remote", remote, *wanted, config=config).stdout
        except GitError:
            return False
        held = {}
        for line in listed.splitlines():
            sha, _, name = line.partition("\t")
            held[name.strip()] = sha
        return all(held.get(dst, "") == sha for dst, sha in wanted.items())

    def stream_blob(self, blob: str, out_fd: int, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Copy the content of a blob to the open file `out_fd` in chunks, never holding it whole in memory."""
        argv = self._argv(("cat-file", "blob", blob), ())
        with subprocess.Popen(
            argv, cwd=self.repo, env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        ) as proc:  # fmt: skip
            assert proc.stdout is not None and proc.stderr is not None
            while chunk := proc.stdout.read(1 << 20):
                view = memoryview(chunk)
                while view:
                    view = view[os.write(out_fd, view) :]
            error = proc.stderr.read()
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                raise GitError(argv, 124, "timed out") from None
        if code != 0:
            raise GitError(argv, code, error.decode("utf-8", "replace"))

    def write_blob(self, data: bytes, *, timeout: float = DEFAULT_TIMEOUT) -> str:
        """Store `data` as a blob, byte for byte (no filters), and return its id; no index or worktree is involved."""
        argv = self._argv(("hash-object", "-w", "--no-filters", "--stdin"), ())
        try:
            done = subprocess.run(
                argv, cwd=self.repo, env=self.env, input=data, capture_output=True, timeout=timeout, check=False
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            raise GitError(argv, 124, "timed out") from None
        if done.returncode != 0:
            raise GitError(argv, done.returncode, done.stderr.decode("utf-8", "replace"))
        return done.stdout.decode("ascii").strip()
