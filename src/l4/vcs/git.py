"""The only way the harness runs git (L4-SEC-006): hooks and fsmonitor off, no inherited repository redirection."""

import contextlib
import logging
import os
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from l4 import cancel
from l4.exitcodes import ExitCode, L4Exit
from l4.safepath import resolve_tool, safe_path
from l4.vcs.errors import GitError
from l4.vcs.push import (
    PushRejected,
    build_branch_push_args,
    build_delete_args,
    build_keep_args,
    build_lease_push_args,
    build_push_args,
    build_restart_args,
    build_retire_args,
    is_lost_lease,
    is_non_fast_forward,
    is_transient_push_failure,
)
from l4.vcs.trailers import CommitTrailers, render

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

    def push_branch(self, remote: str, branch: str, *, config: Sequence[tuple[str, str]] = ()) -> GitResult:
        """Push HEAD to the unit branch under a lease on the last value this checkout saw of it (W-D2): a branch a
        person deleted is not recreated and one a person moved is not overwritten, both `PushRejected`. The value is
        the remote-tracking ref, or, when a fetch pruned that, what this object pushed last. Fast-forward only."""
        tracking = f"refs/remotes/{remote}/{branch}"
        expected = self.rev_parse(tracking) or self._branch_seen.get(branch, "")
        argv = build_branch_push_args(remote, branch, expected)
        if expected and self.run("merge-base", "--is-ancestor", expected, "HEAD", check=False).returncode != 0:
            raise PushRejected(  # git would force this once the lease holds, so it is refused here
                ["git", *argv], 1, f" ! [rejected]        HEAD -> {branch} (non-fast-forward)\n"
                "the local branch does not contain the remote one",
            )  # fmt: skip
        done = self._push(argv, config, is_lost_lease)
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
        for attempt in range(1, PUSH_TRIES + 1):
            try:
                return self.run(*args, config=config)
            except GitError as exc:
                exc.tries = attempt
                if moved(exc.stderr):
                    if transient is not None and self._landed(args, config):
                        log.info("the push landed although git reported a server error")
                        return GitResult(0, "", transient)
                    rejected = PushRejected(exc.argv, exc.returncode, exc.stderr)
                    rejected.tries = attempt
                    raise rejected from None
                if not is_transient_push_failure(exc.stderr) or attempt == PUSH_TRIES:
                    raise
                wait = PUSH_WAITS[attempt - 1]
                if self._monotonic() - started + wait > PUSH_BUDGET:
                    raise
                transient = exc.stderr
                log.warning(
                    "the push failed on the forge's side (%s); trying again in %gs (try %d of %d)",
                    _first_line(exc.stderr), wait, attempt + 1, PUSH_TRIES,
                )  # fmt: skip
                self._sleep(wait)
                cancel.check()
                if self._landed(args, config):
                    log.info("the push landed although git reported a server error")
                    return GitResult(0, "", transient)
        raise AssertionError("unreachable")  # pragma: no cover - the last try returns or raises

    def _landed(self, args: Sequence[str], config: Sequence[tuple[str, str]]) -> bool:
        """Whether every ref of the push `args` already holds the value pushed on the remote (absent for a delete).
        `args` is one of the argv shapes of `l4.vcs.push`: options, `--`, the remote, then `src:dst` refspecs. Any
        error, or a refspec of another shape, is "not known to have landed"."""
        if "--" not in args:
            return False
        remote, *specs = args[list(args).index("--") + 1 :]
        wanted: dict[str, str] = {}
        for spec in specs:
            src, colon, dst = spec.partition(":")
            if not colon or not dst.startswith("refs/"):
                return False
            if src:
                if (sha := self.rev_parse(src)) is None:
                    return False
                wanted[dst] = sha
            else:
                wanted[dst] = ""
        if not wanted:
            return False
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
