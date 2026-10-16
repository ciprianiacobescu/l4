"""Which judge may verify a unit (L4-VER-001, SPEC 10.1) and how sure the harness is that it is independent.

A judge is independent when its vendor (or model, with `different_model`) differs from that of every implementer
profile that authored commits in the unit. Where that vendor comes from is recorded as its provenance:
- `served`: the adapter reported the model that answered (claude-code `modelUsage`);
- `tool`: a CLI that only runs one vendor's models (codex, claude-code): the vendor is the tool's, and a `vendor:` that
  contradicts it is rejected at config load;
- `declared`: an adapter that can run any vendor's model and reports none (opencode, kiro-cli, command, acp): the
  operator's `vendor:` counts, and the verdict says `declared (unverified)`;
- `unknown`: no `vendor:`, or `vendor: unknown`. Never independent of anything (SCN-AVL-19).
Any `declared` party makes the verdict's independence `declared (unverified)` (decision Q9). A judge whose served
model is of an implementer's vendor, or of no known vendor, is `not independent`: its verdict is dropped.
"""

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from l4.agents.factory import Factory, Selected, WaitingCapacity
from l4.availability.fallback import Constraint
from l4.availability.vendor import Provenance, resolve_vendor
from l4.config.schema import L4Config, Profile
from l4.llm.agent_judge import JUDGE_ADAPTERS

NO_INDEPENDENT_VERIFIER = "no independent verifier"

_FULL_CLAUDE_ID = re.compile(r"^claude-[a-z0-9.-]*\d")
_BRACKET_SUFFIX = re.compile(r"\[[^\]]*\]$")
_DATE_SUFFIX = re.compile(r"-\d{8}$")


def is_full_model_id(model: str | None) -> bool:
    """A Claude model id that names one model (`claude-haiku-4-5-20251001`), not an alias (`haiku`, `sonnet`)."""
    return bool(model) and _FULL_CLAUDE_ID.match(model.lower()) is not None  # type: ignore[union-attr]


def normalise_model(model: str) -> str:
    """Case, a `[1m]` context suffix and a trailing date do not make another model."""
    return _DATE_SUFFIX.sub("", _BRACKET_SUFFIX.sub("", model.strip().lower()))


def same_model(requested: str, served: str) -> bool:
    return normalise_model(requested) == normalise_model(served)


def independence_constraint(cfg: L4Config, implementer_profiles: Sequence[str]) -> Constraint:
    """The veto `Factory.for_role` applies to each judge: the reason it is not independent, else None. Every
    implementer profile of the unit counts, not only the first, and an unknown vendor on either side is a veto."""
    mode = cfg.verifier.independence
    key = "vendor" if mode == "different_vendor" else "model"

    def known(profile: Profile | None) -> str | None:
        return resolve_vendor(profile or Profile())[0] if key == "vendor" else getattr(profile, key, None)

    def check(name: str, profile: Profile) -> str | None:
        if mode == "none":
            return None
        mine = known(profile)
        if not mine or mine == "unknown":
            return f"judge profile {name} has no known {key}"
        for other in implementer_profiles:
            theirs = known(cfg.profiles.get(other))
            if not theirs or theirs == "unknown":
                return f"implementer profile {other} has no known {key}"
            if theirs == mine:
                return f"judge profile {name} and implementer profile {other} share the {key}"
        return None

    return check


def independence_keeper(cfg: L4Config, implementers: Sequence[str]) -> Constraint:
    """The veto an escalation applies to each next implementer profile: it must not take away the last independent
    judge (escalate-and-note D6)."""
    raise NotImplementedError("escalate-and-note 1.6")


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
    left is `WaitingCapacity` with the reason `no independent verifier`, and no judge has been called."""
    independent = independence_constraint(cfg, implementer_profiles)

    def allowed(name: str, profile: Profile) -> str | None:
        return "its verdict was discarded earlier in this round" if name in skip else independent(name, profile)

    try:
        selected = factory.for_role(role, unit, serves=JUDGE_ADAPTERS, constraints=(allowed,))
    except WaitingCapacity as exc:
        raise no_independent_verifier(role, exc) from None
    return selected


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
    return JudgeSeat(model if reports and is_full_model_id(model) else None, reports)


@dataclass(frozen=True)
class Party:
    profile: str
    vendor: str | None
    model: str | None
    provenance: Provenance
    served: str | None = None

    def text(self) -> str:
        how = f"served {self.served}" if self.provenance == "served" and self.served else self.provenance
        return f"{self.profile} {self.vendor or 'unknown'} ({how})"


@dataclass(frozen=True)
class Independence:
    """The record of the check behind a verdict: who judged, who implemented, and how the vendors are known."""

    mode: str
    judge: Party
    implementers: tuple[Party, ...]

    @property
    def verified(self) -> bool:
        return all(p.provenance != "declared" for p in (self.judge, *self.implementers))

    @property
    def independent(self) -> bool:
        """Whether the judge differs from every implementer; an unknown vendor is never independent."""
        if self.mode == "none":
            return True
        key = (lambda p: p.vendor) if self.mode == "different_vendor" else (lambda p: p.model)
        mine = key(self.judge)
        if not mine or mine == "unknown":
            return False
        return all((theirs := key(p)) and theirs != "unknown" and theirs != mine for p in self.implementers)

    @property
    def status(self) -> str:
        if self.mode == "none":
            return "not checked (independence: none)"
        if not self.independent:  # a served model of an implementer's vendor, or of none known
            return f"not independent ({self.mode})"
        return f"verified ({self.mode})" if self.verified else "declared (unverified)"

    def line(self) -> str:
        parties = ", ".join(p.text() for p in (self.judge, *self.implementers))
        return f"independence: {self.status}: {parties}"

    def to_json(self) -> dict[str, object]:
        def party(p: Party) -> dict[str, object]:
            return {"profile": p.profile, "vendor": p.vendor, "model": p.model, "provenance": p.provenance,
                    "served": p.served}  # fmt: skip

        return {
            "mode": self.mode, "status": self.status, "verified": self.verified, "judge": party(self.judge),
            "implementers": [party(p) for p in self.implementers],
        }  # fmt: skip


def assess_independence(
    cfg: L4Config, implementer_profiles: Sequence[str], judge: str, *, served_model: str | None = None
) -> Independence:
    """`served_model` only for an adapter that reports one (the caller knows); it makes the judge's provenance
    `served`."""

    def party(name: str, served: str | None = None) -> Party:
        profile = cfg.profiles.get(name) or Profile()
        vendor, provenance = resolve_vendor(profile, served)
        return Party(name, vendor, profile.model, provenance, served)

    return Independence(
        cfg.verifier.independence, party(judge, served_model), tuple(party(n) for n in implementer_profiles)
    )
