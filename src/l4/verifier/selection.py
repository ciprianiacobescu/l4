"""Which judge may verify a unit (L4-VER-001, SPEC 10.1) and how sure the harness is that it is independent.

A judge is independent when its vendor (or model, with `different_model`) differs from that of every implementer
profile that authored commits in the unit. Where that vendor comes from is recorded as its provenance:
- `served`: the adapter reported the model that answered (claude-code `modelUsage`);
- `tool`: a CLI that only runs one vendor's models (codex, claude-code): the vendor is the tool's, and a `vendor:` that
  contradicts it is rejected at config load;
- `declared`: an adapter that can run any vendor's model and reports none (opencode, kiro-cli, command, acp): the
  operator's `vendor:` counts, and the verdict says `declared (unverified)`;
- `routed`: a kiro-cli profile on `auto`. It has no single vendor but a set of them, the makers of the models Kiro may
  route it to (`RoutedSet`); it is independent only of a vendor outside that set, and the verdict says
  `routed (unverified)` (kiro-judge D14);
- `unknown`: no `vendor:`, or `vendor: unknown`. Never independent of anything (SCN-AVL-19).
Any `declared` party makes the verdict's independence `declared (unverified)` (decision Q9). A judge whose served
model is of an implementer's vendor, or of no known vendor, is `not independent`: its verdict is dropped.
"""

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from l4.agents.factory import Factory, Selected, WaitingCapacity
from l4.availability.fallback import Constraint
from l4.availability.vendor import (
    Provenance,
    RoutedLookup,
    RoutedSet,
    built_in_routed,
    is_routed,
    normalise_model,
    resolve_vendor,
)
from l4.availability.vendor import same_model as same_model  # re-exported: the judge imports it from here
from l4.config.schema import L4Config, Profile
from l4.llm.agent_judge import JUDGE_ADAPTERS

NO_INDEPENDENT_VERIFIER = "no independent verifier"

_FULL_CLAUDE_ID = re.compile(r"^claude-[a-z0-9.-]*\d")


def is_full_model_id(model: str | None) -> bool:
    """A Claude model id that names one model (`claude-haiku-4-5-20251001`), not an alias (`haiku`, `sonnet`)."""
    return bool(model) and _FULL_CLAUDE_ID.match(model.lower()) is not None  # type: ignore[union-attr]


UNKNOWN = "unknown"


@dataclass(frozen=True)
class Side:
    """One party of the independence rule: the vendors that may have made its model (one, or a routed party's set),
    its model normalised, and for a routed party the normalised models it may be served by."""

    vendors: frozenset[str]
    model: str | None = None
    models: frozenset[str] = frozenset()
    routed: bool = False


def side_of(name: str, profile: Profile | None, routed: RoutedLookup, served: str | None = None) -> Side:
    profile = profile or Profile()
    vendor, provenance = resolve_vendor(profile, served)
    if provenance == "routed":
        found = routed(name, profile)
        return Side(frozenset(found.vendors), None, frozenset(found.models), True)
    model = profile.model or served
    return Side(frozenset({vendor or UNKNOWN}), normalise_model(model) if model else None)


def judge_unknown(mode: str, judge: Side) -> bool:
    """A judge of no known vendor (or, with `different_model`, of no model) is never independent."""
    if mode == "different_vendor" or judge.routed:
        return UNKNOWN in judge.vendors
    return not judge.model


def clash(mode: str, judge: Side, other: Side) -> str | None:
    """Why `judge` is not independent of `other`: `share` (a vendor or model in common), or `other-unknown` /
    `judge-unknown` (no known vendor, or with `different_model` no known model); `*-vendor-unknown` is the vendor being
    the reason under `different_model`, where a routed side is judged by vendor. The judge's own unknown before any
    comparison is `judge_unknown`. Never called for `independence: none`."""
    if mode == "different_vendor":
        if UNKNOWN in other.vendors:
            return "other-unknown"
        return "share" if judge.vendors & other.vendors else None
    if judge.routed or other.routed:  # a routed side is known by the models it may be served by
        if UNKNOWN in other.vendors:
            return "other-vendor-unknown"
        if judge.routed and other.routed:
            return "share"  # two auto sides: both may be served by the same model
        routed_side, plain = (judge, other) if judge.routed else (other, judge)
        if UNKNOWN in plain.vendors:  # the other party's maker is not known, so it may be one of the routed models
            return "other-vendor-unknown" if plain is other else "judge-vendor-unknown"
        if plain.model is None:
            return "other-unknown" if plain is other else "judge-unknown"
        return "share" if plain.model.rsplit("/", 1)[-1] in routed_side.models else None
    if not other.model:
        return "other-unknown"
    return "share" if judge.model == other.model else None


def clash_text(mode: str, kind: str, judge: str, other: str | None = None) -> str:
    """The veto text: `judge profile J has no known vendor` and the other two forms of the rule."""
    key = "vendor" if mode == "different_vendor" or "-vendor-" in kind else "model"
    if kind.startswith("judge-"):
        return f"judge profile {judge} has no known {key}"
    if kind.startswith("other-"):
        return f"implementer profile {other} has no known {key}"
    return f"judge profile {judge} and implementer profile {other} share the {key}"


def independence_constraint(
    cfg: L4Config,
    implementer_profiles: Sequence[str],
    routed: RoutedLookup = built_in_routed,
    *,
    judge_sets: Mapping[str, RoutedSet] | None = None,
) -> Constraint:
    """The veto `Factory.for_role` applies to each judge: the reason it is not independent, else None. Every
    implementer profile of the unit counts, not only the first, and an unknown vendor on either side is a veto. A
    routed profile (kiro-cli on `auto`) counts with every vendor it may be served by (`routed`: the lookup of its
    set; `judge_sets`: sets that a judge's own probe recorded, which replace the lookup for that judge)."""
    mode = cfg.verifier.independence

    def check(name: str, profile: Profile) -> str | None:
        if mode == "none":
            return None
        own = (lambda _n, _p: judge_sets[name]) if judge_sets and name in judge_sets else routed
        mine = side_of(name, profile, own)
        if judge_unknown(mode, mine):
            return clash_text(mode, "judge-unknown", name)
        for other in implementer_profiles:
            if reason := clash(mode, mine, side_of(other, cfg.profiles.get(other), routed)):
                return clash_text(mode, reason, name, other)
        return None

    return check


def independence_keeper(
    cfg: L4Config, implementers: Sequence[str], routed: RoutedLookup = built_in_routed
) -> Constraint:
    """The veto an escalation applies to each next implementer profile: it must not take away the last independent
    judge (escalate-and-note D6). A profile P is refused when, for `roles.judges` and for a non-empty
    `roles.verifier_agent`, no judge-capable profile of that chain is independent of `[*implementers, P]`."""
    mode = cfg.verifier.independence

    def check(name: str, profile: Profile) -> str | None:
        if mode == "none":
            return None
        chain = [*implementers, name]
        for role in ("judges", "verifier_agent"):
            judges = [
                n for n in getattr(cfg.roles, role) if n in cfg.profiles and cfg.profiles[n].adapter in JUDGE_ADAPTERS
            ]
            if not judges:
                continue
            veto = independence_constraint(cfg, chain, routed)
            if all(veto(n, cfg.profiles[n]) is not None for n in judges):
                return f"no profile of roles.{role} would be independent of {name} (verifier.independence: {mode})"
        return None

    return check


def select_judge(
    factory: Factory,
    cfg: L4Config,
    unit: str,
    implementer_profiles: Sequence[str],
    *,
    role: str = "judges",
    skip: Collection[str] = (),
) -> Selected:
    """The first usable, independent profile of `roles.<role>`. `skip` names profiles to pass over (a judge whose
    served model did not match); the collection is read at every selection, so a caller may grow it later. Nothing
    left is `WaitingCapacity` with the reason `no independent verifier`, and no judge has been called.

    The walk checks a routed judge (kiro-cli on `auto`) against the set the factory knows before it probes it; the
    probe may then record another one, so the selected judge is checked again against its own probe and, when that set
    vetoes it, passed over (kiro-judge D14): a judge is never called on a set its own probe contradicts."""
    passed: set[str] = set()  # routed judges that their own probe vetoed

    def allowed(name: str, profile: Profile) -> str | None:
        if name in skip:
            return "its verdict was discarded earlier in this round"
        if name in passed:
            return "its own model listing shows a vendor that is not independent"
        return independence_constraint(cfg, implementer_profiles, factory.routed)(name, profile)

    while True:
        try:
            selected = factory.for_role(role, unit, serves=JUDGE_ADAPTERS, constraints=(allowed,))
        except WaitingCapacity as exc:
            raise no_independent_verifier(role, exc) from None
        found = RoutedSet.from_detail(selected.probes.get("auth", {}).get("routed"))
        if found is None or not is_routed(selected.profile):
            return selected
        veto = independence_constraint(
            cfg, implementer_profiles, factory.routed, judge_sets={selected.profile_name: found}
        )
        if veto(selected.profile_name, selected.profile) is None:
            return selected
        passed.add(selected.profile_name)


def no_independent_verifier(role: str, exc: WaitingCapacity) -> WaitingCapacity:
    reason = str(exc).removeprefix(f"role {role} is unavailable: ")
    return WaitingCapacity(role, f"{NO_INDEPENDENT_VERIFIER} ({reason})", exc.retry_after, exc.unready)


@dataclass(frozen=True)
class JudgeSeat:
    """What the harness can check about the judge that is answering: `expect_model` (a full model id, for an adapter
    that reports the served model) and whether a served model, if reported, is believed for provenance."""

    expect_model: str | None = None
    reports_served: bool = False


def seat_of(selected: Selected) -> JudgeSeat:
    reports = selected.impl.capabilities().served_model
    model = selected.profile.model
    if selected.profile.adapter == "kiro-cli":  # any pinned model is checked against the session file (L4-KJD-015)
        pinned = (model or "").strip()
        return JudgeSeat(pinned if reports and pinned and pinned.lower() != "auto" else None, reports)
    return JudgeSeat(model if reports and is_full_model_id(model) else None, reports)


@dataclass(frozen=True)
class Party:
    profile: str
    vendor: str | None
    model: str | None
    provenance: Provenance
    served: str | None = None
    vendors: tuple[str, ...] = ()  # a routed party's possible vendors (sorted); empty for any other
    routed_models: tuple[str, ...] = ()  # and the normalised models it may be served by

    def text(self) -> str:
        if self.provenance == "routed":
            return f"{self.profile} routed: {', '.join(self.vendors)} (auto)"
        how = f"served {self.served}" if self.provenance == "served" and self.served else self.provenance
        return f"{self.profile} {self.vendor or 'unknown'} ({how})"

    @property
    def side(self) -> Side:
        if self.provenance == "routed":
            return Side(frozenset(self.vendors), None, frozenset(self.routed_models), True)
        model = self.model or self.served
        return Side(frozenset({self.vendor or UNKNOWN}), normalise_model(model) if model else None)


@dataclass(frozen=True)
class Independence:
    """The record of the check behind a verdict: who judged, who implemented, and how the vendors are known."""

    mode: str
    judge: Party
    implementers: tuple[Party, ...]

    @property
    def verified(self) -> bool:
        return all(p.provenance not in ("declared", "routed") for p in (self.judge, *self.implementers))

    @property
    def routed(self) -> bool:
        return any(p.provenance == "routed" for p in (self.judge, *self.implementers))

    @property
    def independent(self) -> bool:
        """Whether the judge differs from every implementer; an unknown vendor is never independent."""
        if self.mode == "none":
            return True
        mine = self.judge.side
        if judge_unknown(self.mode, mine):
            return False
        return all(clash(self.mode, mine, p.side) is None for p in self.implementers)

    @property
    def status(self) -> str:
        if self.mode == "none":
            return "not checked (independence: none)"
        if not self.independent:  # a served model of an implementer's vendor, or of none known
            return f"not independent ({self.mode})"
        if self.routed:
            return "routed (unverified)"
        return f"verified ({self.mode})" if self.verified else "declared (unverified)"

    def line(self) -> str:
        parties = ", ".join(p.text() for p in (self.judge, *self.implementers))
        return f"independence: {self.status}: {parties}"

    def to_json(self) -> dict[str, object]:
        def party(p: Party) -> dict[str, object]:
            return {"profile": p.profile, "vendor": p.vendor, "model": p.model, "provenance": p.provenance,
                    "served": p.served, "vendors": list(p.vendors)}  # fmt: skip

        return {
            "mode": self.mode, "status": self.status, "verified": self.verified, "judge": party(self.judge),
            "implementers": [party(p) for p in self.implementers],
        }  # fmt: skip


def assess_independence(
    cfg: L4Config,
    implementer_profiles: Sequence[str],
    judge: str,
    *,
    served_model: str | None = None,
    routed: RoutedLookup = built_in_routed,
) -> Independence:
    """`served_model` only for an adapter that reports one (the caller knows); it makes the judge's provenance
    `served`. `routed` finds the possible vendors of a profile on `auto`."""

    def party(name: str, served: str | None = None) -> Party:
        profile = cfg.profiles.get(name) or Profile()
        vendor, provenance = resolve_vendor(profile, served)
        if provenance == "routed":
            found = routed(name, profile)
            return Party(name, None, profile.model, provenance, None, found.vendors, found.models)
        return Party(name, vendor, profile.model, provenance, served)

    return Independence(
        cfg.verifier.independence, party(judge, served_model), tuple(party(n) for n in implementer_profiles)
    )
