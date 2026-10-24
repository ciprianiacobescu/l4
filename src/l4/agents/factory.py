"""`Factory.for_role` (SPEC L4-FAC-006) and `Factory.on_limit` (L4-AVL-006): the role's chain is walked in order by
`l4.availability.fallback.FallbackSelector` (cool-downs, probe cache, the ladder), every decision is logged as the
SPEC 8.4 console lines and one `availability.selected` event, and a limit hit in the middle of a run records a
cool-down and selects the next profile.

A required role (`REQUIRED_ROLES`) with nothing usable raises `WaitingCapacity` (a `RoleUnavailable`, exit 12, with a
`retry_after`); an optional role raises plain `RoleUnavailable`. No LLM backends yet (M1: agent-factory 1.13-1.15).
"""

import contextlib
import dataclasses
import logging
import time
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from l4 import recordedversions
from l4.agents.base import AgentAdapter, EventSink, LimitSignal, ProbeCtx, RunResult
from l4.agents.claude_code import ClaudeCodeAdapter
from l4.agents.codex import CodexAdapter
from l4.agents.command import CommandAdapter
from l4.agents.copilot_cli import CopilotCliAdapter
from l4.agents.fake import FakeAdapter
from l4.agents.gate import ConcurrencyGate, GatedAdapter, login_key, slots_for
from l4.agents.kiro_cli import KiroCliAdapter
from l4.agents.opencode import OpenCodeAdapter
from l4.agents.opencode_v2 import OpenCodeV2Adapter
from l4.availability.cooldown import AvailabilityStore, Clock, SystemClock, iso_utc
from l4.availability.errors import REQUIRED_ROLES, RoleUnavailable, WaitingCapacity
from l4.availability.fallback import Constraint, FallbackSelector, ProfileProbe, to_event
from l4.availability.probes import LadderReport
from l4.availability.vendor import RoutedSet, built_in_routed, resolve_vendor
from l4.config.schema import L4Config, Profile, RolesCfg, duration_seconds
from l4.exitcodes import ExitCode, L4Exit
from l4.provision.catalog import effective_pins, profile_cli

__all__ = [
    "ADAPTERS",
    "REQUIRED_ROLES",
    "Factory",
    "RoleUnavailable",
    "Selected",
    "SelectionRequest",
    "WaitingCapacity",
]

ADAPTERS: dict[str, Callable[[], AgentAdapter]] = {
    "codex": CodexAdapter,
    "claude-code": ClaudeCodeAdapter,
    "opencode": OpenCodeAdapter,
    "kiro-cli": KiroCliAdapter,
    "copilot-cli": CopilotCliAdapter,
    "command": CommandAdapter,
    "fake": lambda: FakeAdapter([]),
}
# the adapter of a profile whose CLI is not its adapter's default one (`catalog.profile_cli` key): `opencode` with
# `options.cli_major: 2` is a second class under the same adapter name (L4-OCV-001, amendment E5)
CLI_ADAPTERS: dict[str, Callable[[], AgentAdapter]] = {"opencode2": OpenCodeV2Adapter}


def recorded_routed(store: AvailabilityStore, name: str) -> tuple[RoutedSet, datetime] | None:
    """The set the latest probe of this profile recorded in the `auth` step, with the moment it was stored; None when
    there is none or it is malformed (a record is never believed blindly)."""
    kept = store.probes.latest_routed(name)
    if kept is not None and (found := RoutedSet.from_detail(kept[1])) is not None:
        return found, kept[0]
    stored = store.probes.latest_at(name)  # a file written before the set was kept apart
    if stored is None:
        return None
    try:
        auth = LadderReport.from_json(stored[1]).steps.get("auth")
    except (KeyError, TypeError, ValueError):
        return None
    if auth is None or (found := RoutedSet.from_detail(auth.detail.get("routed"))) is None:
        return None
    return found, stored[0]


@dataclass(frozen=True)
class SelectionRequest:
    """What was asked, so that `Factory.on_limit` can ask again."""

    role: str
    unit: str
    serves: Collection[str] | None = None
    constraints: tuple[Constraint, ...] = ()


@dataclass
class Selected:
    profile_name: str
    profile: Profile
    impl: AgentAdapter
    fallback_index: int = 0
    skipped: list[dict[str, Any]] = field(default_factory=list)
    probes: dict[str, dict[str, Any]] = field(default_factory=dict)  # step -> detail, of the selected profile
    cached: bool = False
    fallback_from: str | None = None  # `chain[0]`, whenever `fallback_index` >= 1
    vendor: str | None = None  # the profile's vendor and where that claim comes from (for_role fills both)
    provenance: Literal["served", "tool", "declared", "routed", "unknown"] = "unknown"
    request: SelectionRequest | None = None


class Factory:
    """`adapters` replaces registry entries by adapter name (tests inject a `FakeAdapter` with a script).
    `availability` is the runner's cool-down and probe-cache file (in memory when omitted); `clock` is the one
    source of time for every cool-down and cache decision."""

    def __init__(
        self,
        cfg: L4Config,
        ctx: ProbeCtx,
        *,
        events: EventSink | None = None,
        adapters: Mapping[str, AgentAdapter] | None = None,
        availability: AvailabilityStore | None = None,
        clock: Clock | None = None,
        gate: ConcurrencyGate | None = None,
    ) -> None:
        self._cfg = cfg
        self._clock = clock or SystemClock()
        self._ctx = dataclasses.replace(
            ctx,
            timeout_s=float(duration_seconds(cfg.availability.probe_timeout)),
            step_timeout_s=float(duration_seconds(cfg.availability.probe_step_timeout)),
            hello_prompt=cfg.availability.hello_prompt,
            min_remaining_percent=cfg.availability.min_remaining_percent,
            min_remaining_usd=cfg.availability.min_remaining_usd,
            now=self._clock.now,
            pins={adapter: version for adapter, (version, _) in effective_pins(cfg).items()},
            pin_sources={adapter: source for adapter, (_, source) in effective_pins(cfg).items()},
        )
        self._events = events
        self._adapters = dict(adapters or {})
        self._store = availability or AvailabilityStore(None)
        self._noted_experimental: set[str] = set()
        # one lock directory per OS user, never under $L4_CACHE: a process with another cache takes the same lock
        self._gate = gate or ConcurrencyGate.for_user(self._ctx.environ)
        if self._gate.observe is None:
            self._gate.observe = self._login_waited

    def with_config(self, cfg: L4Config) -> "Factory":
        """The same probes, adapters, cool-down registry, clock, login gate and event sink over another configuration:
        the delegate's chain and profiles are the base branch's, not this run's (L4-DLG-001)."""
        return Factory(
            cfg,
            self._ctx,
            events=self._events,
            adapters=self._adapters,
            availability=self._store,
            clock=self._clock,
            gate=self._gate,
        )

    def now(self) -> datetime:
        return self._clock.now()

    def sleep(self, seconds: float) -> None:
        """Wait on the factory's clock (a test clock moves on instead of blocking)."""
        sleeper = getattr(self._clock, "sleep", None)
        (sleeper or time.sleep)(seconds)

    def _login_waited(self, fact: dict[str, Any]) -> None:
        """A wait for another process's login is printed and ledgered (SPEC L4-FAC-008)."""
        tool = fact["tool"]
        _console(
            "login",
            f"[l4] login: waited {fact['waited_s']:g}s for another process to finish with the {tool} login "
            f"({fact['outcome']})",
        )
        if self._events is not None:
            self._events.append("availability.login_wait", **fact)

    @property
    def availability(self) -> AvailabilityStore:
        return self._store

    def build(self, profile: Profile) -> AgentAdapter:
        if profile.adapter is None:
            raise L4Exit(ExitCode.USAGE_ERROR, "backend profiles are not supported in M0 (M1: agent-factory 3.x)")
        cli = profile_cli(profile)[0]  # the adapter's name, or `opencode2` for an opencode profile of cli_major 2
        for injected in (cli, profile.adapter):  # a test's adapter for `opencode` serves both majors unless v2 has one
            if injected in self._adapters:
                return self._adapters[injected]
        if profile.adapter not in ADAPTERS:
            known = ", ".join(ADAPTERS)
            raise L4Exit(ExitCode.USAGE_ERROR, f"adapter {profile.adapter} is not available (known: {known})")
        return CLI_ADAPTERS.get(cli, ADAPTERS[profile.adapter])()

    def routed(self, name: str, profile: Profile) -> RoutedSet:
        """The possible vendors of a profile on `auto` (kiro-judge D14): the set its latest probe recorded in the
        availability cache, whatever the age of that record, else the built-in set of its adapter."""
        found = recorded_routed(self._store, name)
        return found[0] if found is not None else built_in_routed(name, profile)

    def _selector(self) -> FallbackSelector:
        return FallbackSelector(
            self._cfg, self._ctx, self.build, self._store, self._clock, events=self._events,
            run_id=getattr(self._events, "run_id", None), say=_console, gate=self._gate,
        )  # fmt: skip

    def for_role(
        self, role: str, unit: str, *, serves: Collection[str] | None = None, constraints: Sequence[Constraint] = ()
    ) -> Selected:
        """The first usable profile of the role's chain. `serves`: the adapters that can do this role's work; a
        profile outside it (a backend profile, an adapter that cannot run tool-less) is skipped and the walk goes on,
        so an optional role degrades (L4-AVL-010) instead of failing the run. `constraints` can veto a profile
        (the verifier's independence rule)."""
        if role not in RolesCfg.model_fields:
            raise ValueError(f"{role!r} is not a role")
        chain: list[str] = getattr(self._cfg.roles, role)
        if not chain:
            raise RoleUnavailable(role, "no profile is configured for it under roles")
        picked = self._selector().select(
            role, chain, required=role in REQUIRED_ROLES, serves=serves, constraints=constraints
        )
        fallback_from = chain[0] if picked.fallback_index >= 1 else None
        if self._events is not None:
            self._events.append("availability.selected", role=role, **to_event(picked, fallback_from))
            self._note_adapter(role, picked.profile_name, picked.profile, picked.impl, picked.report)
        return Selected(
            picked.profile_name, picked.profile, self._gated(picked.profile, picked.impl), picked.fallback_index,
            [s.to_event() for s in picked.skipped], picked.probes, picked.cached, fallback_from,
            vendor=resolve_vendor(picked.profile)[0], provenance=resolve_vendor(picked.profile)[1],
            request=SelectionRequest(role, unit, serves, tuple(constraints)),
        )  # fmt: skip

    def next_profile(self, role: str, unit: str, after: str, *, constraints: Sequence[Constraint] = ()) -> Selected:
        """The first usable profile of the role's chain after `after` (escalate-and-note D5): never parks the unit,
        records no cool-down. Raises `RoleUnavailable` when there is none."""
        if role not in RolesCfg.model_fields:
            raise ValueError(f"{role!r} is not a role")
        chain: list[str] = getattr(self._cfg.roles, role)
        if after not in chain or after == chain[-1]:
            why = "is the last profile of" if after in chain else "is not in"
            raise RoleUnavailable(role, f"no profile is left after {after}: it {why} roles.{role}")
        picked = self._selector().select(
            role, chain, required=False, constraints=constraints, after=after, record_unavailable=False
        )
        if self._events is not None:
            self._events.append("availability.selected", role=role, **to_event(picked, None, after))
            self._note_adapter(role, picked.profile_name, picked.profile, picked.impl, picked.report)
        return Selected(
            picked.profile_name, picked.profile, self._gated(picked.profile, picked.impl), picked.fallback_index,
            [s.to_event() for s in picked.skipped], picked.probes, picked.cached, None,
            vendor=resolve_vendor(picked.profile)[0], provenance=resolve_vendor(picked.profile)[1],
            request=SelectionRequest(role, unit, None, tuple(constraints)),
        )  # fmt: skip

    def _note_adapter(
        self, role: str, name: str, profile: Profile, impl: AgentAdapter, report: LadderReport | None = None
    ) -> None:
        """What this adapter cannot promise, said at selection (SPEC 8.1, 8.3): the served model is not reported, so
        independence rests on the profile's declared vendor; an experimental adapter is announced once."""
        assert self._events is not None
        if getattr(impl, "model_unverified", False):
            self._events.append(
                "availability.model_unverified", role=role, profile=name, model=profile.model, vendor=profile.vendor
            )
        version = report.steps["binary"].detail.get("version") if report and "binary" in report.steps else None
        known = recordedversions.unrecorded(profile.adapter or "", version) if version else None
        if known is not None:
            self._events.append(
                "availability.unrecorded_version", role=role, profile=name, adapter=profile.adapter,
                version=version, recorded=known,
            )  # fmt: skip
        if getattr(impl, "experimental", False) and name not in self._noted_experimental:
            self._noted_experimental.add(name)
            self._events.append("agent.experimental", profile=name, adapter=profile.adapter)

    def probe_all(self, names: Sequence[str], *, refresh: bool) -> list[ProfileProbe]:
        """The ladder (or the cache, or the cool-down) for each named profile, for `l4 probe`."""
        selector = self._selector()
        return [selector.check(name, self._cfg.profiles[name], refresh=refresh) for name in names]

    @contextlib.contextmanager
    def holding_login(self, profile: Profile) -> Iterator[None]:
        """The profile's login lock, for a caller that spawns its CLI itself (a readiness probe): waits up to
        `availability.login_lock_wait`; `GateBusy` (or `OSError`, no private lock directory) when it cannot get it."""
        slots = slots_for(profile)
        if slots is None:
            yield
            return
        wait_s = float(duration_seconds(self._cfg.availability.login_lock_wait))
        with self._gate.acquire(profile.adapter or "", login_key(profile, self._ctx.environ), slots, wait_s=wait_s):
            yield

    def _gated(self, profile: Profile, impl: AgentAdapter) -> AgentAdapter:
        """The adapter holding a gate slot around each run, when the profile's login is shared (L4-FAC-008)."""
        slots = slots_for(profile)
        if slots is None:
            return impl
        wait_s = float(duration_seconds(self._cfg.availability.login_lock_wait))
        return GatedAdapter(
            impl, self._gate, profile.adapter or "", login_key(profile, self._ctx.environ), slots,
            wait_s=wait_s, now=self._clock.now,
        )  # fmt: skip

    def cool_down(self, selected: Selected, kind: Literal["model_mismatch"], detail: str) -> None:
        """Cool a profile that answered, but not as configured (another model served): selecting it again would only
        buy another discarded answer, so it rests for `default_cooldown`."""
        if selected.request is None:
            raise ValueError("cool_down needs a Selected that for_role returned")
        profile = selected.profile
        signal = LimitSignal(profile.adapter or "unknown", profile.model, kind, None, kind, detail)
        self._selector().record_cooldown(selected.profile_name, profile, signal, selected.request.role)

    def on_limit(self, selected: Selected, run: RunResult | LimitSignal) -> Selected:
        """A run hit a limit: record the cool-down (the limit's reset, else the configured default), drop the cached
        probe, log it, and select again; the limited profile is now cooling, so the next one in the chain is chosen
        (`WaitingCapacity` when there is none). Nothing here waits."""
        if selected.request is None:
            raise ValueError("on_limit needs a Selected that for_role returned")
        profile = selected.profile
        reason = ""
        if isinstance(run, LimitSignal):  # a limit seen outside a run (an audit writer's reply carries no RunResult)
            limit = run
        else:
            reason = run.status if run.limit is None else ""  # no limit seen: say what the run ended with
            limit = run.limit or LimitSignal(
                profile.adapter or "unknown", profile.model, "auth" if run.status == "auth" else "rate_limit", None,
                f"run.{run.status}", run.detail or "",
            )  # fmt: skip
        cooldown = self._selector().record_cooldown(selected.profile_name, profile, limit, selected.request.role)
        self._store.probes.invalidate(selected.profile_name)
        request = selected.request
        chosen = self.for_role(request.role, request.unit, serves=request.serves, constraints=request.constraints)
        if chosen.profile_name == selected.profile_name:  # never hand back the profile that just hit its limit
            raise WaitingCapacity(
                request.role, f"profile {chosen.profile_name} hit a limit and is still selectable", cooldown.until
            )
        if self._events is not None:
            self._events.append(
                "availability.fallback", role=request.role, **{"from": selected.profile_name},
                to=chosen.profile_name, reason=reason or limit.kind, resets_at=iso_utc(cooldown.until),
            )  # fmt: skip
        return chosen


def _console(role: str, line: str) -> None:
    """One SPEC 8.4 line on stderr through the `l4.<role>` logger, which adds the `[l4] <role>:` prefix itself."""
    logging.getLogger(f"l4.{role}").info(line.removeprefix(f"[l4] {role}: "))
