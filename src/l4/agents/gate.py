"""The concurrency gate for shared agent logins (SPEC L4-FAC-008).

Two processes must not drive one refreshable OAuth login at once: both refresh an expired token with the same
single-use refresh token and the loser clears the stored credentials (runner incident 2026-10-07, job 6045). So:

* the limit of a refreshable login (claude-code, codex, kiro-cli, and opencode with `auth: subscription`) is exactly
  1 slot, whatever `max_concurrency` says; a higher value applies only to an `api_key` login (`slots_for`);
* the lock key is the resolved credential directory (`login_key`), not the profile name, the model or `$L4_CACHE`;
* the lock files live in one directory per OS user (`lock_root`: `~/.cache/l4/locks` of the user the process runs as,
  or `$L4_LOCK_DIR`), created 0700 with 0600 files, so a process with another `$L4_CACHE`, HOME or entry point (a CI
  job, an `l4 eval`, `doctor --live`, a hand-run `l4 probe`) takes the same lock; it is not under the checkout or any
  directory an agent sandbox can write;
* a slot is held around the whole probe ladder of a profile and around each adapter run (`GatedAdapter`); the wait is
  bounded (`availability.login_lock_wait`), printed and ledgered (`observe`); no process holds two (`GateNested`);
* a flock dies with its process, and the lock descriptors are close-on-exec, so neither a crash nor a detached child
  leaks a slot.
"""

import contextlib
import fcntl
import hashlib
import os
import pwd
import re
import stat
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any

from l4.agents.base import AgentAdapter, AgentCaps, LimitSignal, ProbeCtx, ProbeResult, ProbeStep, RunRequest, RunResult
from l4.config.defaults import CREDENTIAL_PATHS
from l4.config.schema import Profile

WAIT_S = 1200.0  # `availability.login_lock_wait` default: longer than a judge call, shorter than a stuck unit
POLL_S = 2.0
BUSY_COOLDOWN_S = 120.0  # how long a profile whose login stayed busy is passed over (not a usage limit)
OAUTH_ADAPTERS = ("claude-code", "codex", "kiro-cli")  # a stored OAuth login that the CLI refreshes itself [I]
LOCK_DIR_ENV = "L4_LOCK_DIR"
# how many of `CREDENTIAL_PATHS` make the key: claude-code's `~/.claude.json` sibling holds settings, not the login
_LOGIN_ONLY = {"claude-code": 1}

_held = threading.local()


class GateBusy(Exception):
    """Every slot stayed taken for the whole wait."""


class GateNested(RuntimeError):
    """A thread asked for a second login lock while holding one: a bug (two CLIs at once, or a self-deadlock)."""


def held_keys() -> list[str]:
    """`tool/identity` of every login lock this thread holds through `acquire`."""
    return list(getattr(_held, "keys", []))


def refreshable_login(profile: Profile) -> bool:
    """The profile's login is an OAuth store that its CLI refreshes: a second process refreshing it races."""
    if profile.adapter in OAUTH_ADAPTERS:
        return profile.auth != "api_key" and not (profile.auth is None and profile.api_key_env)
    return profile.adapter == "opencode" and profile.auth == "subscription"


def lock_root(environ: Mapping[str, str]) -> Path:
    """The lock directory: the same for every process of one OS user, whatever its HOME, `$L4_CACHE` or
    `$XDG_*` (a CI job and a `sudo -u runner -H` shell differ in all of them). `$L4_LOCK_DIR` replaces it."""
    explicit = environ.get(LOCK_DIR_ENV) or os.environ.get(LOCK_DIR_ENV)
    if explicit:
        return Path(explicit)
    try:
        home = pwd.getpwuid(os.getuid()).pw_dir
    except KeyError:  # a container uid with no passwd entry
        home = environ.get("HOME") or str(Path.home())
    return Path(home) / ".cache" / "l4" / "locks"


def credential_homes(tool: str, environ: Mapping[str, str]) -> list[str]:
    """The resolved (symlinks followed) directories or files that hold the login of `tool` for this environment: the
    ones under HOME that the CLI the harness spawns uses. Every spawn environment is built from HOME (`probe_env`,
    `build_agent_env`) and never carries CLAUDE_CONFIG_DIR or CODEX_HOME, so an override in the host environment
    does not move the store the CLI drives and must not move the lock either."""
    home = environ.get("HOME") or str(Path.home())
    paths = CREDENTIAL_PATHS.get(tool, ())[: _LOGIN_ONLY.get(tool)]
    return [os.path.realpath(p.replace("~", home, 1)) for p in paths]


def login_key(profile: Profile, environ: Mapping[str, str]) -> str:
    """Who holds the lock: the credential store a refreshable profile logs in with, nothing else. Any other
    profile keeps its identity hash (probe and cool-down identity, L4-AVL-005)."""
    if not refreshable_login(profile):
        from l4.availability.cooldown import identity_hash

        return identity_hash(profile, environ)
    parts = [profile.adapter or "", *credential_homes(profile.adapter or "", environ)]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


class Slot:
    def __init__(self, fd: int, key: str | None = None, waited_s: float = 0.0) -> None:
        self._fd: int | None = fd
        self._key = key
        self.waited_s = waited_s

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)  # closing drops the flock
            self._fd = None
            if self._key is not None and self._key in getattr(_held, "keys", []):
                _held.keys.remove(self._key)

    def __enter__(self) -> "Slot":
        return self

    def __exit__(self, *exc: tuple[type[BaseException] | None, BaseException | None, TracebackType | None]) -> None:
        self.release()


def slots_for(profile: Profile) -> int | None:
    """Exactly 1 for a refreshable login. Otherwise `max_concurrency` when set, else 1 for a subscription login; an
    API key is not gated unless asked for."""
    if refreshable_login(profile):
        return 1
    if profile.max_concurrency is not None:
        return profile.max_concurrency
    return 1 if profile.auth == "subscription" else None


class ConcurrencyGate:
    """`root/locks` (or, for a per-user gate, `locks_dir` itself). `observe` is told about every acquisition that
    waited, and about each wait that ran out (`{"tool", "slots", "waited_s", "outcome": "acquired" | "timeout"}`),
    never about a free login; the factory turns it into a console line and an `availability.login_wait` event."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        locks_dir: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if locks_dir is None and root is None:
            raise ValueError("a gate needs a root or a locks_dir")
        self._dir = locks_dir if locks_dir is not None else Path(root or ".") / "locks"
        self._sleep, self._monotonic = sleep, monotonic
        self.observe: Callable[[dict[str, Any]], None] | None = None

    @classmethod
    def for_user(cls, environ: Mapping[str, str], **kw: Any) -> "ConcurrencyGate":
        """The gate every process of this OS user shares (`lock_root`)."""
        return cls(locks_dir=lock_root(environ), **kw)

    def _ensure_dir(self) -> None:
        self._dir.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(FileExistsError):
            self._dir.mkdir(mode=0o700)
        info = self._dir.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise OSError(f"{self._dir} is not a directory of this user: refusing to put login locks there")
        if info.st_mode & 0o077:  # an umask-widened or foreign-opened directory is closed again
            self._dir.chmod(0o700)

    def _path(self, tool: str, identity: str, index: int) -> Path:
        return self._dir / f"{re.sub(r'[^A-Za-z0-9._-]', '_', tool)}-{identity}-{index}.lock"

    def _try(self, tool: str, identity: str, slots: int, key: str | None) -> Slot | None:
        self._ensure_dir()
        for index in range(slots):
            fd = os.open(
                self._path(tool, identity, index), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
            )
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                    raise OSError("a login lock file that is not a regular file of this user")
                if info.st_mode & 0o077:
                    os.fchmod(fd, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                continue
            except BaseException:
                os.close(fd)
                raise
            if key is not None:
                if not hasattr(_held, "keys"):
                    _held.keys = []
                _held.keys.append(key)
            return Slot(fd, key)
        return None

    def try_acquire(self, tool: str, identity: str, slots: int) -> Slot | None:
        """A slot now, or None. Not counted by `held_keys` and never `GateNested`: it cannot wait."""
        return self._try(tool, identity, slots, None)

    def is_busy(self, tool: str, identity: str, slots: int) -> bool:
        slot = self.try_acquire(tool, identity, slots)
        if slot is None:
            return True
        slot.release()
        return False

    def _poll(self, tool: str, identity: str, slots: int, wait_s: float, poll_s: float, key: str | None) -> Slot:
        start = self._monotonic()
        deadline = start + wait_s
        slept = False
        while (slot := self._try(tool, identity, slots, key)) is None:
            if self._monotonic() >= deadline:
                if slept:
                    self._observed(tool, slots, self._monotonic() - start, "timeout")
                raise GateBusy(f"{tool}: all {slots} slot(s) busy for {wait_s:g}s")
            self._sleep(poll_s)
            slept = True
        slot.waited_s = self._monotonic() - start if slept else 0.0
        if slept:
            self._observed(tool, slots, slot.waited_s, "acquired")
        return slot

    def _observed(self, tool: str, slots: int, waited_s: float, outcome: str) -> None:
        if self.observe is not None and waited_s > 0:
            self.observe({"tool": tool, "slots": slots, "waited_s": round(waited_s, 1), "outcome": outcome})

    def acquire(self, tool: str, identity: str, slots: int, *, wait_s: float = WAIT_S, poll_s: float = POLL_S) -> Slot:
        """Waits up to `wait_s` for a slot and holds it until released. A thread holds one at a time: a second
        `acquire` (another CLI under the first) would deadlock or race, so it raises `GateNested` at once."""
        if held := held_keys():
            raise GateNested(f"{tool}: this thread already holds the login lock {held[0]} (one CLI at a time)")
        return self._poll(tool, identity, slots, wait_s, poll_s, f"{tool}/{identity}")

    def wait_free(
        self, tool: str, identity: str, slots: int, *, wait_s: float = WAIT_S, poll_s: float = POLL_S
    ) -> bool:
        """True when a slot freed up within `wait_s` (it is released again at once; the run takes its own)."""
        try:
            self._poll(tool, identity, slots, wait_s, poll_s, None).release()
        except (GateBusy, OSError):  # a lock directory that cannot be used is as good as a taken login: no run
            return False
        return True


def busy_detail(tool: str) -> str:
    return f"unavailable: another process holds the {tool} login"


class GatedAdapter:
    """Holds a gate slot around each `run`; everything else is the wrapped adapter's. A login that stays busy for
    the whole wait is a `rate_limited` result whose limit resets soon (`BUSY_COOLDOWN_S`): the caller records a
    short cool-down and falls back to the next profile, exactly as for a usage limit."""

    def __init__(
        self,
        inner: AgentAdapter,
        gate: ConcurrencyGate,
        tool: str,
        identity: str,
        slots: int,
        *,
        wait_s: float = WAIT_S,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._inner, self._gate = inner, gate
        self._tool, self._identity, self._slots, self._wait_s = tool, identity, slots, wait_s
        self._now = now or (lambda: datetime.now(UTC))
        self.name = inner.name

    def capabilities(self) -> AgentCaps:
        return self._inner.capabilities()

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        return self._inner.probe(profile, step, ctx)

    def run(self, req: RunRequest) -> RunResult:
        try:
            slot = self._gate.acquire(self._tool, self._identity, self._slots, wait_s=self._wait_s)
        except GateBusy:
            return busy_result(self._tool, req, self._now())
        except OSError as exc:  # no private lock directory: better no run than an unserialised one
            return RunResult("error", req.raw_events_path, detail=f"unavailable: login lock not usable ({exc})")
        with slot:
            return self._inner.run(req)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._inner, name)


def busy_result(tool: str, req: RunRequest, now: datetime) -> RunResult:
    detail = busy_detail(tool)
    limit = LimitSignal(
        tool, req.profile.model, "rate_limit", now + timedelta(seconds=BUSY_COOLDOWN_S), "gate.busy", detail
    )
    return RunResult("rate_limited", req.raw_events_path, detail=detail, limit=limit)
