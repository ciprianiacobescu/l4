"""The runner's memory of who is exhausted and what was probed lately (SPEC L4-AVL-003, L4-AVL-005).

One file, `$L4_CACHE/availability.json`: `{"version": 1, "cooldowns": {...}, "probes": {...}}`. Every write is a
read-modify-write under `flock` on `availability.json.lock` and ends in an atomic replace, so concurrent jobs on one
runner cannot lose each other's entries. A corrupt file reads as empty (with a warning) and is rewritten: selection
must never fail because of it. Nothing stored here is a credential, an e-mail or raw CLI output.
"""

import fcntl
import hashlib
import json
import logging
import os
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from l4.config.defaults import CREDENTIAL_PATHS
from l4.config.schema import Profile
from l4.fsutil import atomic_write_bytes

log = logging.getLogger("l4.availability")

FILE_NAME = "availability.json"
WHOLE_TOOL = "*"
CooldownKey = tuple[str, str | None]  # (tool, model); model None: every model of the tool

# adapters whose profile never names a model: a cool-down for one must not cool the next (a fake or a command)
PROFILE_KEYED = ("fake", "command")

# environment variables that identify the account a profile acts as (names only; values are hashed, never stored)
IDENTITY_ENV = {
    "claude-code": ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CONFIG_DIR"),
    "codex": ("CODEX_API_KEY", "CODEX_HOME"),
    "opencode": ("OPENROUTER_API_KEY", "OPENCODE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"),
    "kiro-cli": ("KIRO_API_KEY",),
    "copilot-cli": ("COPILOT_GITHUB_TOKEN",),
}


class Clock(Protocol):
    def now(self) -> datetime: ...  # tz-aware UTC


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class FakeClock:
    """The one test clock of the harness: `FakeClock(start).advance(delta)`."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("a clock is timezone-aware (UTC)")
        self._now = start
        self.slept: list[float] = []

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta

    def sleep(self, seconds: float) -> None:
        """A wait takes no real time: the clock moves on and the call is remembered (`slept`)."""
        self.slept.append(seconds)
        self.advance(timedelta(seconds=seconds))


def cooldown_key(profile_name: str, profile: Profile) -> CooldownKey:
    """`(tool, model)` of a profile. A profile without a model is the whole tool, except for adapters that have no
    single tool behind them (L4-AVL-004: the key includes the model, so a sibling model is not cooled)."""
    tool = profile.adapter or (f"backend:{profile.backend}" if profile.backend else "unknown")
    if profile.model is None and profile.adapter in PROFILE_KEYED:
        return tool, f"profile:{profile_name}"
    return tool, profile.model


def _key_text(key: CooldownKey) -> str:
    return f"{key[0]}|{key[1] or WHOLE_TOOL}"


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parseiso_utc(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


class _JsonFile:
    """`path` None keeps the document in memory (a Factory built without a runner cache, as in unit tests)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._memory: dict[str, Any] = {}

    def read(self) -> dict[str, Any]:
        if self.path is None:
            return deepcopy(self._memory)
        try:
            doc = json.loads(self.path.read_bytes())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            log.warning("%s is unreadable (%s); treating it as empty", self.path, type(exc).__name__)
            return {}
        if not isinstance(doc, dict):
            log.warning("%s does not hold a JSON object; treating it as empty", self.path)
            return {}
        return doc

    @contextmanager
    def _locked(self) -> Iterator[None]:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path.with_name(self.path.name + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)  # closing releases the lock, also when the process dies

    def update(self, mutate: Callable[[dict[str, Any]], None]) -> None:
        if self.path is None:
            doc = deepcopy(self._memory)
            mutate(doc)
            self._memory = doc
            return
        with self._locked():
            doc = self.read()
            mutate(doc)
            atomic_write_bytes(self.path, json.dumps(doc, indent=1, sort_keys=True).encode("utf-8"))


def _section(doc: dict[str, Any], name: str) -> dict[str, Any]:
    doc.setdefault("version", 1)
    section = doc.get(name)
    if not isinstance(section, dict):
        section = doc[name] = {}
    return section


@dataclass(frozen=True)
class Cooldown:
    profile: str
    tool: str
    model: str | None
    until: datetime
    kind: str
    source: str
    recorded_by_run: str | None = None

    @property
    def key(self) -> CooldownKey:
        return self.tool, self.model

    def to_json(self) -> dict[str, Any]:
        return {
            "profile": self.profile, "tool": self.tool, "model": self.model, "until": iso_utc(self.until),
            "kind": self.kind, "source": self.source, "recorded_by_run": self.recorded_by_run,
        }  # fmt: skip

    @classmethod
    def from_json(cls, raw: object) -> "Cooldown | None":
        if not isinstance(raw, dict):
            return None
        until = _parseiso_utc(raw.get("until"))
        tool, profile, kind, source = raw.get("tool"), raw.get("profile"), raw.get("kind"), raw.get("source")
        model, run = raw.get("model"), raw.get("recorded_by_run")
        if until is None or not all(isinstance(v, str) for v in (tool, profile, kind, source)):
            return None
        return cls(
            str(profile), str(tool), model if isinstance(model, str) else None, until, str(kind), str(source),
            run if isinstance(run, str) else None,
        )  # fmt: skip


class CooldownRegistry:
    """Cool-downs keyed by `(tool, model)`; `(tool, None)` is the whole tool (L4-AVL-003, L4-AVL-004)."""

    def __init__(self, path: Path | None = None, *, clock: Clock | None = None) -> None:
        self._file = _JsonFile(path)
        self._clock = clock or SystemClock()

    @property
    def path(self) -> Path | None:
        return self._file.path

    def record(
        self, profile: str, key: CooldownKey, until: datetime, kind: str, source: str, run_id: str | None = None,
        now: datetime | None = None,
    ) -> Cooldown:  # fmt: skip
        """Never shortens an existing cool-down of the same key: `clear` is the way to end one early."""
        now = now or self._clock.now()
        entry = Cooldown(profile, key[0], key[1], until.astimezone(UTC), kind, source, run_id)

        def mutate(doc: dict[str, Any]) -> None:
            section = _section(doc, "cooldowns")
            for name in [n for n, raw in section.items() if (c := Cooldown.from_json(raw)) is None or c.until <= now]:
                del section[name]
            old = Cooldown.from_json(section.get(_key_text(key)))
            if old is not None and old.until > entry.until:
                return
            section[_key_text(key)] = entry.to_json()

        self._file.update(mutate)
        return entry

    def entries(self, now: datetime | None = None) -> list[Cooldown]:
        """The live cool-downs, soonest end first."""
        moment = now or self._clock.now()
        raw = _section(self._file.read(), "cooldowns")
        found = [c for c in (Cooldown.from_json(v) for v in raw.values()) if c is not None and c.until > moment]
        return sorted(found, key=lambda c: (c.until, c.tool, c.model or ""))

    def cooling(self, key: CooldownKey, now: datetime | None = None) -> Cooldown | None:
        """The live entry for `(tool, model)` or for the whole tool; the later one when both exist."""
        matching = [c for c in self.entries(now) if c.tool == key[0] and c.model in (key[1], None)]
        return max(matching, key=lambda c: c.until, default=None)

    def earliest_reset(self, keys: Iterable[CooldownKey] | None = None, now: datetime | None = None) -> datetime | None:
        """The soonest end among the live cool-downs (those that cool one of `keys`, when given)."""
        wanted = None if keys is None else list(keys)
        ends = [
            c.until
            for c in self.entries(now)
            if wanted is None or any(c.tool == tool and c.model in (model, None) for tool, model in wanted)
        ]
        return min(ends, default=None)

    def clear(self, key: CooldownKey) -> bool:
        """Removes what cools `key`: its own entry and the whole-tool one. True when something was removed."""
        names = {_key_text(key), _key_text((key[0], None))}
        removed = False

        def mutate(doc: dict[str, Any]) -> None:
            nonlocal removed
            section = _section(doc, "cooldowns")
            for name in names & set(section):
                del section[name]
                removed = True

        self._file.update(mutate)
        return removed


def _routed_of(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """The `routed` detail of the `auth` step of a stored ladder report, when it has one."""
    steps = payload.get("steps")
    for entry in steps if isinstance(steps, list) else ():
        if isinstance(entry, dict) and entry.get("name") == "auth":
            detail = entry.get("detail")
            routed = detail.get("routed") if isinstance(detail, dict) else None
            return dict(routed) if isinstance(routed, dict) else None
    return None


class ProbeCache:
    """Ladder outcomes per `(profile, identity hash)`; failures are cached too (a transient one is retried after the
    TTL, or at once with `l4 probe --no-cache`). A real-run failure calls `invalidate` (L4-AVL-005)."""

    def __init__(self, path: Path | None = None, *, clock: Clock | None = None) -> None:
        self._file = _JsonFile(path)
        self._clock = clock or SystemClock()

    @staticmethod
    def _name(profile: str, identity: str) -> str:
        return f"{profile}|{identity}"

    def get_aged(
        self, profile: str, identity: str, ttl_s: float, now: datetime | None = None
    ) -> tuple[dict[str, Any], float] | None:
        """The cached payload and its age in seconds. An entry that was stored with a shorter lifetime of its own
        (`put(..., ttl_s=)`: a failure that is remembered briefly) expires at that lifetime, whatever `ttl_s` says."""
        moment = now or self._clock.now()
        raw = _section(self._file.read(), "probes").get(self._name(profile, identity))
        if not isinstance(raw, dict):
            return None
        at, payload = _parseiso_utc(raw.get("at")), raw.get("payload")
        own = raw.get("ttl_s")
        limit = min(ttl_s, own) if isinstance(own, int | float) and not isinstance(own, bool) else ttl_s
        if at is None or not isinstance(payload, dict) or not (timedelta(0) <= moment - at < timedelta(seconds=limit)):
            return None
        return payload, (moment - at).total_seconds()

    def get(self, profile: str, identity: str, ttl_s: float, now: datetime | None = None) -> dict[str, Any] | None:
        found = self.get_aged(profile, identity, ttl_s, now)
        return found[0] if found else None

    def latest(self, profile: str) -> dict[str, Any] | None:
        """The payload of the newest entry stored for this profile under any identity, whatever its age or lifetime
        (data that outlives the TTL: the model set a probe recorded). None when there is none."""
        found = self.latest_at(profile)
        return found[1] if found else None

    def latest_at(self, profile: str) -> tuple[datetime, dict[str, Any]] | None:
        """`latest` with the moment the entry was stored."""
        found: tuple[datetime, dict[str, Any]] | None = None
        for name, raw in _section(self._file.read(), "probes").items():
            if not name.startswith(f"{profile}|") or not isinstance(raw, dict):
                continue
            at, payload = _parseiso_utc(raw.get("at")), raw.get("payload")
            if at is not None and isinstance(payload, dict) and (found is None or at > found[0]):
                found = (at, payload)
        return found

    def latest_routed(self, profile: str) -> tuple[datetime, dict[str, Any]] | None:
        """The model set a probe of this profile last recorded (the `routed` detail of its `auth` step), with the
        moment it was stored; it outlives the TTL, `invalidate` and the prune. None when there is none."""
        raw = _section(self._file.read(), "routed").get(profile)
        if not isinstance(raw, dict):
            return None
        at = _parseiso_utc(raw.get("at"))
        return (at, raw["routed"]) if at is not None and isinstance(raw.get("routed"), dict) else None

    def put(
        self,
        profile: str,
        identity: str,
        payload: Mapping[str, Any],
        now: datetime | None = None,
        *,
        ttl_s: float | None = None,
    ) -> None:
        moment = now or self._clock.now()

        def mutate(doc: dict[str, Any]) -> None:
            section = _section(doc, "probes")
            entry: dict[str, Any] = {"at": iso_utc(moment), "payload": dict(payload)}
            if ttl_s is not None:
                entry["ttl_s"] = ttl_s
            section[self._name(profile, identity)] = entry
            if (routed := _routed_of(payload)) is not None:  # kept apart: a limit or the prune below leaves it be
                _section(doc, "routed")[profile] = {"at": iso_utc(moment), "routed": routed}
            horizon = moment - timedelta(days=2)  # old entries are useless at any sane TTL
            stale = [
                n
                for n, v in section.items()
                if not isinstance(v, dict) or (_parseiso_utc(v.get("at")) or horizon) < horizon
            ]
            for name in stale:
                del section[name]

        self._file.update(mutate)

    def invalidate(self, profile: str) -> None:
        def mutate(doc: dict[str, Any]) -> None:
            section = _section(doc, "probes")
            for name in [n for n in section if n.startswith(f"{profile}|")]:
                del section[name]

        self._file.update(mutate)


class AvailabilityStore:
    """The runner's `availability.json`: cool-downs and the probe cache over one file. `root` None: in memory."""

    def __init__(self, root: Path | None = None, *, clock: Clock | None = None) -> None:
        path = None if root is None else root / FILE_NAME
        self.path = path
        self.cooldowns = CooldownRegistry(path, clock=clock)
        self.probes = ProbeCache(path, clock=clock)


def identity_hash(profile: Profile, environ: Mapping[str, str]) -> str:
    """Who this profile acts as: tool, auth, the credential directories and the account's token variables. The
    values are hashed and cut to 16 hex digits; no part of one is ever stored (L4-AVL-005)."""
    tool = profile.adapter or profile.backend or ""
    home = environ.get("HOME", "")
    parts = [tool, profile.auth or "", profile.base_url or ""]
    parts += [str(Path(p.replace("~", home, 1))) for p in CREDENTIAL_PATHS.get(tool, ())]
    names = sorted({*IDENTITY_ENV.get(tool, ()), *([profile.api_key_env] if profile.api_key_env else [])})
    parts += [f"{name}={environ[name]}" for name in names if environ.get(name)]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
