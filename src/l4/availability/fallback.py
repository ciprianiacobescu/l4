"""Selection over a role's chain (SPEC 8.4, L4-FAC-006, L4-AVL-003...010) and `l4 probe`.

`FallbackSelector.select` walks the chain in order. For each profile: does its adapter serve this role, do the
caller's constraints accept it, is it cooling (skipped with no request), is a fresh probe cached, else run the ladder.
The first usable profile wins. Every considered profile gets one console line (SPEC 8.4), a limit seen by a probe
starts a cool-down, and a chain with nothing usable raises `WaitingCapacity` (required roles) or `RoleUnavailable`.
"""

import hashlib
import json
import tempfile
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import click

from l4.agents.base import AgentAdapter, EventSink, LimitSignal, ProbeCtx, ProbeResult
from l4.agents.gate import ConcurrencyGate, GateBusy, busy_detail, login_key, slots_for
from l4.availability.cooldown import (
    AvailabilityStore,
    Clock,
    Cooldown,
    SystemClock,
    cooldown_key,
    identity_hash,
)
from l4.availability.cooldown import iso_utc as iso
from l4.availability.errors import RoleUnavailable, Unready, WaitingCapacity
from l4.availability.probes import LadderReport, ProbeLadder
from l4.availability.steps import SLOW_STEP_MS
from l4.availability.vendor import RoutedSet
from l4.config.defaults import cache_root
from l4.config.redaction import load_app_config
from l4.config.schema import AvailabilityCfg, L4Config, Profile, RolesCfg, duration_seconds
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.proc import run_process

# returns why a profile must not be used for this selection, or None (the verifier's independence rule is one)
Constraint = Callable[[str, Profile], str | None]


def probe_identity(profile: Profile, cfg: AvailabilityCfg, environ: Mapping[str, str], pin: str | None = None) -> str:
    """The key a cached ladder outcome is valid for: who the profile acts as (`identity_hash`) and every setting that
    changes what a probe concludes (version floor, reserve, model, options, the ladder, the hello prompt, and the
    effective `pin` when given: L4-PRV-046). A changed reserve or override must not be answered by a result judged
    against the old one."""
    timing = {
        "cache_ttl",
        "auth_failure_ttl",
        "probe_timeout",
        "probe_step_timeout",
        "default_cooldown",
        "credits_cooldown",
    }
    settings = {
        "profile": profile.model_dump(mode="json", exclude={"max_concurrency", "vendor"}),
        "availability": cfg.model_dump(mode="json", exclude=timing),
    }
    if pin is not None:
        settings["pin"] = pin
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
    return f"{identity_hash(profile, environ)}-{digest}"


def minute_stamp(moment: datetime) -> str:
    """`2026-10-03T14:32Z`, the form of the SPEC 8.4 console lines."""
    return iso(moment)[:-4] + "Z"


@dataclass
class Skipped:
    """A profile that was considered and not used. `step` is a probe step, or `serves`, `constraint`, `cooling`."""

    profile: str
    step: str
    reason: str
    kind: str | None = None  # the limit kind of a cool-down
    used_percent: float | None = None
    window_minutes: int | None = None
    resets_at: datetime | None = None
    cooldown_recorded: bool = False
    cached: bool = False  # the failure is a remembered one (L4-AVL-005), not one this run just saw
    age_s: float | None = None  # how long ago it was learned, for a remembered failure

    def to_event(self) -> dict[str, Any]:
        reason = "usage window exhausted" if self.step == "quota" and self.window_minutes is not None else self.reason
        event: dict[str, Any] = {"profile": self.profile, "step": self.step, "reason": reason}
        if self.used_percent is not None:
            event["used_percent"] = self.used_percent
        if self.window_minutes is not None:
            event["window_minutes"] = self.window_minutes
        if self.resets_at is not None:
            event["resets_at"] = iso(self.resets_at)
        if self.cached:
            event["cached"] = True
            event["age_s"] = int(self.age_s or 0)
        return event


@dataclass
class Selection:
    """The availability-side result of a selection: `Factory.for_role` turns it into a `Selected` with the adapter."""

    profile_name: str
    profile: Profile
    impl: AgentAdapter
    fallback_index: int
    skipped: list[Skipped]
    report: LadderReport
    cached: bool
    probed: dict[str, tuple[Profile, LadderReport]] = field(default_factory=dict)  # skipped profiles that were probed

    @property
    def probes(self) -> dict[str, dict[str, Any]]:
        return {name: dict(result.detail) for name, result in self.report.steps.items()}

    @property
    def quota_window(self) -> str | None:
        window = self.report.steps.get("quota")
        return window.detail.get("quota_window") if window else None


def _step_text(profile: Profile, name: str, result: ProbeResult) -> str:
    detail = result.detail
    if result.skipped:
        return f"{name} skipped"
    if name == "binary":
        if not detail.get("version"):
            return "binary ok"
        drift = detail.get("pin") not in (None, detail["version"])
        return f"binary {detail['version']} (pinned {detail['pin']})" if drift else f"binary {detail['version']}"
    if name == "auth":
        text = f"auth {profile.auth or detail.get('auth_method') or 'ok'}"
        if (routed := RoutedSet.from_detail(detail.get("routed"))) is not None:  # a profile on `auto` (D14)
            text += f" · auto: {', '.join(routed.vendors)} ({routed.source})"
        return text
    if name == "quota":
        if "quota_used_percent" in detail:
            return f"quota {detail['quota_used_percent']:g}% used ({detail.get('quota_window', 'window')})"
        return "quota ok"
    if name == "hello":
        return f"hello {detail['ms'] / 1000:.1f}s" if "ms" in detail else "hello ok"
    return f"{name} ok"


def _timed_text(profile: Profile, step: str, result: ProbeResult) -> str:
    text = _step_text(profile, step, result)
    ms = result.detail.get("step_ms")
    if step != "hello" and isinstance(ms, int) and ms >= SLOW_STEP_MS:  # the hello shows its own time
        text += f" {ms / 1000:.1f}s"
    return text


def _ok_text(name: str, profile: Profile, report: LadderReport, cached: bool) -> str:
    parts = [_timed_text(profile, step, result) for step, result in report.steps.items()]
    if cached:
        parts.append("cached")
    return f"{name} ok ({' · '.join(parts)})"


def format_selected_line(role: str, selection: Selection, escalated_from: str | None = None) -> str:
    line = f"[l4] {role}: {_ok_text(selection.profile_name, selection.profile, selection.report, selection.cached)}"
    line += " → selected"
    if escalated_from is not None:
        return f"{line}, escalated from {escalated_from}"
    return line + (f", fallback #{selection.fallback_index}" if selection.fallback_index >= 1 else "")


def format_skipped_line(role: str, skipped: Skipped) -> str:
    head = f"[l4] {role}: {skipped.profile} skipped — "
    if skipped.step == "cooling":
        until = minute_stamp(skipped.resets_at) if skipped.resets_at else "an unknown time"
        return f"{head}cooling until {until} ({skipped.kind}); no probe sent"
    text = f"{skipped.step}: {skipped.reason}" if skipped.step in _PROBE_STEPS else skipped.reason
    if skipped.resets_at is not None:
        text += f" (resets {minute_stamp(skipped.resets_at)})"
    line = head + text + ("; cool-down recorded" if skipped.cooldown_recorded else "")
    if skipped.cached:
        line += f" (cached {int((skipped.age_s or 0) // 60)}m ago; l4 probe --no-cache re-probes)"
    return line


_PROBE_STEPS = ("binary", "auth", "quota", "hello", "mcp", "custom")


def to_event(selection: Selection, fallback_from: str | None, escalated_from: str | None = None) -> dict[str, Any]:
    """The `availability.selected` payload (SPEC 8.4). `probes` is keyed by profile and covers the selected profile
    and every skipped one that was probed. The unit is the ledger envelope's."""
    probes: dict[str, dict[str, Any]] = {}
    reports = {**selection.probed, selection.profile_name: (selection.profile, selection.report)}
    for name, (profile, report) in reports.items():
        entry: dict[str, Any] = {}
        for step, result in report.steps.items():
            if step == "binary" and result.detail.get("version"):
                entry["binary"] = result.detail["version"]
                if result.detail.get("pin") not in (None, result.detail["version"]):
                    entry["binary_pinned"] = result.detail["pin"]
            elif step == "auth" and result.ok:
                if auth := profile.auth or result.detail.get("auth_method"):
                    entry["auth"] = auth
            elif step == "quota" and "quota_used_percent" in result.detail:
                entry["quota_used_percent"] = result.detail["quota_used_percent"]
                entry["quota_window"] = result.detail["quota_window"]
                if "credits_used" in result.detail:  # Kiro `/usage`, labelled: the streams meter differently
                    for key in ("credits_used", "credits_included", "credits_source"):
                        entry[key] = result.detail[key]
            elif step == "hello" and "ms" in result.detail:
                entry["hello_ms"] = result.detail["ms"]
        slow = {
            step: result.detail["step_ms"]
            for step, result in report.steps.items()
            if step != "hello"
            and isinstance(result.detail.get("step_ms"), int)
            and result.detail["step_ms"] >= SLOW_STEP_MS
        }
        if slow:
            entry["step_ms"] = slow
        probes[name] = entry
    event: dict[str, Any] = {
        "selected": selection.profile_name, "fallback_index": selection.fallback_index,
        "skipped": [s.to_event() for s in selection.skipped], "probes": probes, "cached": selection.cached,
        "quota_window": selection.quota_window,
    }  # fmt: skip
    if fallback_from is not None:
        event["fallback_from"] = fallback_from
    if escalated_from is not None:
        event["escalated_from"] = escalated_from
    return event


def cooldown_until(limit: LimitSignal, cfg: AvailabilityCfg, now: datetime) -> datetime:
    """The end of the cool-down a limit starts: its reset time; for credits (no reset) `credits_cooldown`; otherwise
    `default_cooldown` (also when the reset is unknown or already past)."""
    if limit.resets_at is not None and limit.resets_at > now:
        return limit.resets_at
    seconds = duration_seconds(cfg.credits_cooldown if limit.kind == "credits" else cfg.default_cooldown)
    return now + timedelta(seconds=seconds)


@dataclass
class ProfileProbe:
    """What `l4 probe` found for one profile."""

    profile: str
    adapter: str | None
    model: str | None
    status: Literal["ok", "failed", "cooling", "unsupported"]
    report: LadderReport | None = None
    cached: bool = False
    age_s: float | None = None  # how old the cached result is
    cooldown: Cooldown | None = None  # the live cool-down of a cooling profile
    reason: str | None = None
    cleared: bool = False  # a passing ladder ended the profile's cool-down


@dataclass
class _Walk:
    """The state of one pass over a chain."""

    role: str
    escalated_from: str | None = None
    record_unavailable: bool = True
    skipped: list[Skipped] = field(default_factory=list)
    probed: dict[str, tuple[Profile, LadderReport]] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    keys: list[tuple[str, str | None]] = field(default_factory=list)
    busy: list[tuple[int, str, Profile, int]] = field(default_factory=list)
    unready: dict[str, Unready] = field(default_factory=dict)  # by profile: not cooling, so probed again next run
    # (index, name, profile) of a profile skipped on a remembered auth refusal: probed once more if the role is needed
    refused: list[tuple[int, str, Profile]] = field(default_factory=list)

    def mark_unready(self, name: str, profile: Profile, step: str, reason: str) -> None:
        self.unready[name] = Unready(name, profile.adapter, profile.auth, step, reason)

    def add(self, skipped: Skipped, reason: str) -> None:
        self.skipped.append(skipped)
        self.reasons.append(reason)

    def forget(self, name: str) -> None:
        """A profile that is about to be probed afresh: what the remembered answer said about it is no longer true."""
        self.skipped[:] = [s for s in self.skipped if s.profile != name]
        self.reasons[:] = [r for r in self.reasons if not r.startswith(f"profile {name} failed the ")]
        self.unready.pop(name, None)

    def drop(self, name: str) -> None:
        """A profile that was busy and then freed up: its busy entry is no longer a reason."""
        self.skipped[:] = [s for s in self.skipped if not (s.profile == name and s.step == "concurrency")]
        self.reasons[:] = [r for r in self.reasons if not r.startswith(f"profile {name} is busy")]
        self.unready.pop(name, None)


class FallbackSelector:
    def __init__(
        self,
        cfg: L4Config,
        ctx: ProbeCtx,
        build: Callable[[Profile], AgentAdapter],
        store: AvailabilityStore,
        clock: Clock,
        *,
        events: EventSink | None = None,
        run_id: str | None = None,
        say: Callable[[str, str], None] | None = None,
        gate: ConcurrencyGate | None = None,
    ) -> None:
        self._cfg = cfg
        self._ctx = ctx
        self._build = build
        self._store = store
        self._clock = clock
        self._events = events
        self._run_id = run_id
        self._say = say or (lambda role, line: None)
        self._gate = gate
        self._ladder = ProbeLadder(ctx, cfg.availability.default_ladder)

    def select(
        self,
        role: str,
        chain: Sequence[str],
        *,
        required: bool,
        serves: Collection[str] | None = None,
        constraints: Sequence[Constraint] = (),
        after: str | None = None,
        record_unavailable: bool = True,
    ) -> Selection:
        """`after`: an escalation (escalate-and-note D5), only the profiles behind it are considered, `index` stays
        the position in `chain`, and the selected line ends `escalated from <after>`. `record_unavailable` False: a
        selection that finds nothing raises without writing `availability.unavailable`."""
        walk = _Walk(role, escalated_from=after, record_unavailable=record_unavailable)
        start = chain.index(after) + 1 if after is not None and after in chain else 0
        for index, name in enumerate(chain):
            if index < start:
                continue
            profile = self._cfg.profiles.get(name)
            if profile is None:
                raise L4Exit(ExitCode.USAGE_ERROR, f"roles.{role} names {name}, which is not defined under profiles")
            key = cooldown_key(name, profile)
            veto = self._veto(name, profile, key, serves, constraints)
            if veto is None or veto[0].step == "cooling":  # a profile excluded anyway does not set the retry time
                walk.keys.append(key)
            if veto is not None:
                walk.add(veto[0], veto[1])
                if veto[0].step != "cooling":
                    walk.mark_unready(name, profile, veto[0].step, veto[0].reason)
                self._say(role, format_skipped_line(role, veto[0]))
            elif (slots := self._busy(profile)) is not None:
                busy = Skipped(name, "concurrency", f"concurrency: max_concurrency {slots} busy")
                walk.add(busy, f"profile {name} is busy (max_concurrency {slots})")
                walk.busy.append((index, name, profile, slots))
                walk.mark_unready(name, profile, "concurrency", busy.reason)
                self._say(role, format_skipped_line(role, busy))
            elif (chosen := self._probe(walk, index, name, profile)) is not None:
                return chosen
        # nothing else is usable: a busy profile is waited for (it is then probed like any other)
        for index, name, profile, slots in walk.busy:
            assert self._gate is not None
            wait_s = self._lock_wait_s()
            if self._gate.wait_free(profile.adapter or "", login_key(profile, self._ctx.environ), slots, wait_s=wait_s):
                walk.drop(name)
                if (chosen := self._probe(walk, index, name, profile, wait=True)) is not None:
                    return chosen
            else:
                self._still_busy(walk, name, profile, wait_s)
        # a required role with nothing usable looks again, once per profile and once per call, at a remembered auth
        # refusal (L4-AVL-005): a person fixes those, and the cache must not outlast the fix while a unit is parked
        if required:
            for index, name, profile in walk.refused:
                walk.forget(name)
                self._say(
                    role,
                    f"[l4] {role}: {name} was refused at its last hello and nothing else is usable, probing again",
                )
                if (chosen := self._probe(walk, index, name, profile, fresh=True)) is not None:
                    return chosen
        return self._nothing_usable(role, walk, required)

    def _veto(
        self,
        name: str,
        profile: Profile,
        key: tuple[str, str | None],
        serves: Collection[str] | None,
        constraints: Sequence[Constraint],
    ) -> tuple[Skipped, str] | None:
        """Why this profile is not even considered: it cannot serve the role, a constraint refuses it, or it is
        cooling (no request is sent to it)."""
        if serves is not None and profile.adapter not in serves:
            what = f"adapter {profile.adapter}" if profile.adapter else "a backend profile"
            why = f"{what} cannot serve a tool-less call here"
            return Skipped(name, "serves", why), f"profile {name} is {why}"
        for constraint in constraints:
            if (why := constraint(name, profile)) is not None:
                return Skipped(name, "constraint", why), f"profile {name}: {why}"
        if (cooling := self._store.cooldowns.cooling(key, self._clock.now())) is not None:
            skipped = Skipped(name, "cooling", "cooling", cooling.kind, resets_at=cooling.until)
            return skipped, f"profile {name} is cooling until {minute_stamp(cooling.until)}"
        return None

    def _busy(self, profile: Profile) -> int | None:
        """The slot count of a profile whose login is in use by another run, else None."""
        slots = slots_for(profile)
        if self._gate is None or slots is None:
            return None
        try:
            busy = self._gate.is_busy(profile.adapter or "", login_key(profile, self._ctx.environ), slots)
        except OSError:  # no private lock directory: better no run than an unserialised one on a refreshable login
            busy = True
        return slots if busy else None

    def _lock_wait_s(self) -> float:
        return float(duration_seconds(self._cfg.availability.login_lock_wait))

    def _ladder_run(self, impl: AgentAdapter, profile: Profile, *, wait_s: float) -> LadderReport | None:
        """The ladder with the profile's login lock held for all of it (every step spawns the CLI against the stored
        login, and `auth`/`quota`/`hello` may refresh it). None: the login stayed taken for `wait_s` (0: not
        waited for) or the lock could not be made, and nothing was spawned."""
        slots = slots_for(profile)
        if self._gate is None or slots is None:
            return self._ladder.run(impl, profile)
        try:
            with self._gate.acquire(profile.adapter or "", login_key(profile, self._ctx.environ), slots, wait_s=wait_s):
                return self._ladder.run(impl, profile)
        except (GateBusy, OSError):
            return None

    def _still_busy(self, walk: "_Walk", name: str, profile: Profile, waited_s: float) -> None:
        """A busy login that did not free up in time: the skip now says so (SPEC L4-FAC-008)."""
        reason = busy_detail(profile.adapter or "")
        for entry in walk.skipped:
            if entry.profile == name and entry.step == "concurrency":
                entry.reason = reason
        walk.reasons[:] = [
            f"profile {name} is busy: {reason}" if r.startswith(f"profile {name} is busy") else r for r in walk.reasons
        ]
        self._say(walk.role, f"[l4] {walk.role}: {name} {reason} (waited {waited_s:g}s)")

    def _probe(
        self, walk: "_Walk", index: int, name: str, profile: Profile, *, fresh: bool = False, wait: bool = False
    ) -> Selection | None:
        """Cached probe, else the ladder (`fresh`: the ladder, whatever is cached). The selection when the profile
        passes; otherwise it is skipped (and a limit starts a cool-down) and None is returned. The ladder holds the
        login lock; `wait` waits for it (the last candidate), else a login taken in the meantime is skipped as busy."""
        ttl = float(duration_seconds(self._cfg.availability.cache_ttl))
        impl = self._build(profile)
        identity = probe_identity(
            profile, self._cfg.availability, self._ctx.environ, self._ctx.pins.get(profile.adapter)
        )
        hit = None if fresh else self._store.probes.get_aged(name, identity, ttl, self._clock.now())
        payload, age = (hit[0], hit[1]) if hit is not None else (None, None)
        if payload is not None:
            report: LadderReport | None = LadderReport.from_json(payload)
        else:
            wait_s = self._lock_wait_s() if wait else 0.0
            report = self._ladder_run(impl, profile, wait_s=wait_s)
            if report is None:  # another process took the login between the check and the probe
                slots = slots_for(profile) or 1
                busy = Skipped(name, "concurrency", f"concurrency: max_concurrency {slots} busy")
                walk.add(busy, f"profile {name} is busy (max_concurrency {slots})")
                if wait:
                    self._still_busy(walk, name, profile, wait_s)
                else:
                    walk.busy.append((index, name, profile, slots))
                    self._say(walk.role, format_skipped_line(walk.role, busy))
                walk.mark_unready(name, profile, "concurrency", busy.reason)
                return None
        assert report is not None
        walk.probed[name] = (profile, report)
        if payload is None:
            self._remember(name, identity, report, reprobed=fresh)
        failed = report.failed
        if failed is None:
            others = {n: pr for n, pr in walk.probed.items() if n != name}
            chosen = Selection(name, profile, impl, index, walk.skipped, report, payload is not None, others)
            self._say(walk.role, format_selected_line(walk.role, chosen, walk.escalated_from))
            return chosen
        step = next(n for n, r in report.steps.items() if r is failed)
        entry = Skipped(name, step, failed.reason or "no reason", failed.limit.kind if failed.limit else None)
        entry.cached, entry.age_s = payload is not None, age
        if failed.limit is not None:
            entry.used_percent, entry.window_minutes = failed.limit.used_percent, failed.limit.window_minutes
            entry.resets_at = failed.limit.resets_at
            if payload is None:
                self.record_cooldown(name, profile, failed.limit, walk.role)
                entry.cooldown_recorded = True
        walk.add(entry, f"profile {name} failed the {step} probe: {failed.reason or 'no reason'}")
        if failed.limit is None:
            walk.mark_unready(name, profile, step, failed.reason or "no reason")
        if payload is not None and step == "hello" and failed.failure_class == "auth" and not payload.get("reprobed"):
            walk.refused.append((index, name, profile))
        self._say(walk.role, format_skipped_line(walk.role, entry))
        return None

    def check(self, name: str, profile: Profile, *, refresh: bool) -> ProfileProbe:
        """`l4 probe` for one profile. Normally a cooling profile is not probed and a fresh cached result is used;
        `refresh` (`--no-cache`) probes it anyway, and a passing ladder ends its cool-down: the operator's way to
        undo a forced or stale one."""
        found = ProfileProbe(name, profile.adapter, profile.model, "failed")
        key = cooldown_key(name, profile)
        now = self._clock.now()
        if not refresh and (cooling := self._store.cooldowns.cooling(key, now)) is not None:
            found.status, found.cooldown = "cooling", cooling
            return found
        try:
            impl = self._build(profile)
        except L4Exit as exc:
            found.status, found.reason = "unsupported", str(exc)
            return found
        ttl = float(duration_seconds(self._cfg.availability.cache_ttl))
        identity = probe_identity(
            profile, self._cfg.availability, self._ctx.environ, self._ctx.pins.get(profile.adapter)
        )
        hit = None if refresh else self._store.probes.get_aged(name, identity, ttl, now)
        payload = hit[0] if hit is not None else None
        found.cached = payload is not None
        found.age_s = hit[1] if hit is not None else None
        found.report = LadderReport.from_json(payload) if payload is not None else None
        if found.report is None:
            found.report = self._ladder_run(impl, profile, wait_s=self._lock_wait_s())
            if found.report is None:
                found.reason = busy_detail(profile.adapter or "")
                return found
        if payload is None:
            self._remember(name, identity, found.report)
        failed = found.report.failed
        if failed is None:
            found.status = "ok"
            found.cleared = refresh and self._store.cooldowns.clear(key)
        else:
            found.reason = failed.reason
            if failed.limit is not None and payload is None:
                self.record_cooldown(name, profile, failed.limit, "probe")
        return found

    def _remember(self, name: str, identity: str, report: LadderReport, *, reprobed: bool = False) -> None:
        """Caches an outcome that cost something to learn: a success, or a failed `hello` (a model request). A
        failure of a free step (binary, auth, quota) is probed again each time, so that installing or logging in
        takes effect at once, and a limit is the cool-down registry's to remember: a cached failure would outlive a
        cool-down that ended sooner than the TTL. A failed hello is remembered by its class (L4-AVL-005): `other` for
        `cache_ttl`, `auth` for `auth_failure_ttl`, `transient` and `unsupported_version` not at all (installing the
        right major takes effect at the next probe, L4-OCG-003)."""
        failed = report.failed
        if failed is None:
            self._store.probes.put(name, identity, report.to_json(), self._clock.now())
        elif failed is report.steps.get("hello") and failed.limit is None:
            kind = failed.failure_class or "other"
            if kind == "other":  # the model answered, wrongly: remembered as long as a success
                self._store.probes.put(name, identity, report.to_json(), self._clock.now())
            elif kind == "auth":  # a human fixes a refusal, so it is looked at again soon
                ttl = float(duration_seconds(self._cfg.availability.auth_failure_ttl))
                payload = {**report.to_json(), "reprobed": True} if reprobed else report.to_json()  # not asked again
                self._store.probes.put(name, identity, payload, self._clock.now(), ttl_s=ttl)
            # transient (a timeout, a 5xx, no result) and unsupported_version are never remembered: the next run asks
        if self._events is not None:
            for step, result in report.steps.items():
                if result.detail.get("quota_unrecognised"):
                    self._events.append(
                        "availability.quota_unrecognised", profile=name, step=step, note=result.detail.get("quota_note")
                    )

    def record_cooldown(self, name: str, profile: Profile, limit: LimitSignal, role: str) -> Cooldown:
        now = self._clock.now()
        tool, model = cooldown_key(name, profile)
        # only a limit that names the very model the profile pins cools that model; a served id the profile does not
        # name (an alias, no model) would key an entry the profile never matches, so the profile's own key is used
        key = (tool, limit.model if limit.model is not None and limit.model == model else model)
        entry = self._store.cooldowns.record(
            name, key, cooldown_until(limit, self._cfg.availability, now), limit.kind, limit.source, self._run_id, now
        )
        if self._events is not None:
            self._events.append(
                "availability.cooldown", role=role, profile=name, tool=entry.tool, model=entry.model,
                until=iso(entry.until), kind=entry.kind, source=entry.source,
            )  # fmt: skip
        return entry

    def _unavailable(self, role: str, walk: "_Walk", required: bool, retry: datetime | None) -> None:
        """`availability.unavailable` (L4-AVL-008): the failed choice is as visible as a successful one (live job 5561:
        the ledger held nothing about the judge that failed its login probe)."""
        if self._events is not None and walk.record_unavailable:
            self._events.append(
                "availability.unavailable", role=role, required=required,
                skipped=[s.to_event() for s in walk.skipped], retry_after=iso(retry) if retry else None,
            )  # fmt: skip

    def _nothing_usable(self, role: str, walk: "_Walk", required: bool) -> Selection:
        now = self._clock.now()
        text = "; ".join(walk.reasons)
        if not required:
            self._unavailable(role, walk, required, None)
            raise RoleUnavailable(role, text)
        # the earliest end of a cool-down in the chain; with none cooling every failure was binary, auth, hello, a
        # constraint or `serves`, which nothing but a fix can end, so the next run probes again (L4-AVL-007)
        retry = self._store.cooldowns.earliest_reset(walk.keys, now) or now
        self._unavailable(role, walk, required, retry)
        raise WaitingCapacity(role, f"{text} (retry after {minute_stamp(retry)})", retry, tuple(walk.unready.values()))


def format_probe_line(found: ProfileProbe, profile: Profile) -> str:
    """The `l4 probe` line of one profile, in the SPEC 8.4 style under the role name `probe`."""
    if found.status == "ok" and found.report is not None:
        line = f"[l4] probe: {_ok_text(found.profile, profile, found.report, found.cached)}"
        return line + (" · cool-down cleared" if found.cleared else "")
    if found.status == "cooling" and found.cooldown is not None:
        skipped = Skipped(found.profile, "cooling", "cooling", found.cooldown.kind, resets_at=found.cooldown.until)
        return format_skipped_line("probe", skipped)
    if found.status == "unsupported":
        return f"[l4] probe: {found.profile} unsupported — {found.reason}"
    failed = found.report.failed if found.report else None
    step = next((n for n, r in found.report.steps.items() if r is failed), "probe") if found.report else "probe"
    entry = Skipped(found.profile, step, found.reason or "no reason", cached=found.cached, age_s=found.age_s)
    if failed is not None and failed.limit is not None:
        entry.resets_at, entry.cooldown_recorded = failed.limit.resets_at, not found.cached
    return format_skipped_line("probe", entry)


def probe_targets(cfg: L4Config, profiles: Sequence[str], role: str | None) -> list[str]:
    """The profiles to probe: those named, else the chain of `--role`, else every profile any role uses (in role
    order), else every profile that is defined."""
    if profiles:
        chosen = list(dict.fromkeys(profiles))
    elif role is not None:
        if role not in RolesCfg.model_fields:
            raise L4Exit(ExitCode.USAGE_ERROR, f"probe: {role!r} is not a role ({', '.join(RolesCfg.model_fields)})")
        chosen = list(dict.fromkeys(getattr(cfg.roles, role)))
    else:
        used = [n for r in RolesCfg.model_fields for n in getattr(cfg.roles, r)]
        chosen = list(dict.fromkeys(used or cfg.profiles))
    unknown = [n for n in chosen if n not in cfg.profiles]
    if unknown:
        raise L4Exit(ExitCode.USAGE_ERROR, f"probe: no such profile: {', '.join(unknown)}")
    return chosen


def run_probe(app: AppContext, *, profiles: Sequence[str], role: str | None, as_json: bool, no_cache: bool) -> ExitCode:
    """`l4 probe [PROFILE...] [--role R] [--json] [--no-cache]` (SPEC 2.1). Exit 0 when every probed profile is
    usable, 12 when one is failing or cooling. `--no-cache` ignores the probe cache and any cool-down, and a ladder
    that passes ends the profile's cool-down."""
    from l4.agents.factory import Factory

    app, cfg = load_app_config(app)
    targets = probe_targets(cfg, profiles, role)
    clock = SystemClock()
    store = AvailabilityStore(cache_root(app.environ, repo=app.repo), clock=clock)
    with tempfile.TemporaryDirectory(prefix="l4-probe-") as scratch:
        if app.repo.resolve() in Path(scratch).resolve().parents:
            raise L4Exit(ExitCode.USAGE_ERROR, "the system temp directory is inside the repository; set TMPDIR")
        ctx = ProbeCtx(app.environ, Path(scratch), run_process, forbid=(app.repo,))
        found = Factory(cfg, ctx, availability=store, clock=clock).probe_all(targets, refresh=no_cache)
    now = clock.now()
    cooldowns = store.cooldowns.entries(now)
    if as_json:
        document = {
            "schema": "l4/probe@1", "availability_file": str(store.path),
            "profiles": [_probe_json(f) for f in found],
            "cooldowns": [c.to_json() for c in cooldowns],
        }  # fmt: skip
        text = json.dumps(document, indent=2, ensure_ascii=False)
    else:
        lines = [format_probe_line(f, cfg.profiles[f.profile]) for f in found]
        lines += [
            f"[l4] probe: cooling {c.tool}|{c.model or '*'} until {minute_stamp(c.until)} ({c.kind}, {c.profile})"
            for c in cooldowns
        ]
        lines.append(f"[l4] probe: availability file {store.path}")
        text = "\n".join(lines)
    click.echo(app.redactor.redact_text(text))
    return ExitCode.OK if all(f.status == "ok" for f in found) else ExitCode.WAITING_CAPACITY


def _probe_json(found: ProfileProbe) -> dict[str, Any]:
    steps = []
    if found.report is not None:
        steps = [
            {"step": n, "ok": r.ok, "skipped": r.skipped, "reason": r.reason, "detail": r.detail}
            for n, r in found.report.steps.items()
        ]
    return {
        "profile": found.profile, "adapter": found.adapter, "model": found.model, "status": found.status,
        "cached": found.cached, "age_s": found.age_s, "reason": found.reason, "steps": steps,
        "cooling_until": iso(found.cooldown.until) if found.cooldown else None, "cooldown_cleared": found.cleared,
    }  # fmt: skip
