"""Where a profile's vendor comes from (SPEC 10.1): the input of the verifier's independence rule, recorded on every
`Selected` so that a caller of `Factory.for_role` need not recompute it.

The vendor comes from the tool, never from the operator's say-so, wherever the tool can tell:
- a model id the adapter reported as served (`claude-*` anthropic, `gpt-*`/`o<digit>` openai, `gemini-*` google);
- a single-vendor CLI (codex, claude-code): the vendor of the tool (`TOOL_VENDORS`);
- a kiro-cli or copilot-cli profile (`ROUTED_ADAPTERS`): the vendor of its model's family (`MODEL_FAMILIES`); with no
  model or `auto` it is `routed`: no single vendor, the possible vendors of the models the CLI may route it to
  (`RoutedSet`, kiro-judge D14, L4-FAC-020);
- only an adapter that can run any vendor's model (opencode, kiro-cli, copilot-cli, command, acp) falls back to
  `vendor:`, and the result is `declared`.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from l4.config.schema import TOOL_VENDORS, Profile

Provenance = Literal["served", "tool", "declared", "routed", "unknown"]
TOOL_VENDOR_ADAPTERS = frozenset(TOOL_VENDORS)
UNKNOWN = "unknown"

MODEL_FAMILIES = (  # (pattern on the lowercased model id after its last `/`, the vendor that makes the family)
    (re.compile(r"^(?:(?:[a-z][a-z0-9-]*\.)?anthropic\.)?claude-"), "anthropic"),  # Bedrock: `us.anthropic.claude-…`
    (re.compile(r"^(gpt-|o\d)"), "openai"),
    (re.compile(r"^gemini-"), "google"),
    (re.compile(r"^deepseek-"), "deepseek"),
    (re.compile(r"^glm-"), "zhipu"),
    (re.compile(r"^minimax-"), "minimax"),
    (re.compile(r"^qwen"), "alibaba"),
    (re.compile(r"^kimi-"), "moonshot"),
    (re.compile(r"^grok-"), "xai"),
    (re.compile(r"^mai-"), "microsoft"),
)
_DATE_SUFFIX = re.compile(r"-\d{8}$")
_BRACKET_SUFFIX = re.compile(r"\[[^\]]*\]$")
_DOT_BETWEEN_DIGITS = re.compile(r"(?<=\d)\.(?=\d)")


def family_vendor(model: str | None) -> str | None:
    """The vendor that makes this model's family, else None (`auto`, an empty id or a family not in the table)."""
    name = (model or "").strip().lower().rsplit("/", 1)[-1]
    return next((vendor for pattern, vendor in MODEL_FAMILIES if pattern.match(name)), None)


def served_vendor(model: str) -> str:
    """The vendor named by a served model id; an id of no known family is `unknown`."""
    return family_vendor(model) or UNKNOWN


def normalise_model(model: str) -> str:
    """Case, a `[1m]` context suffix, a trailing date and a `.` between digits do not make another model:
    `claude-sonnet-4.5`, `claude-sonnet-4-5` and `claude-sonnet-4-5-20250929` are one."""
    name = _DATE_SUFFIX.sub("", _BRACKET_SUFFIX.sub("", model.strip().lower()))
    return _DOT_BETWEEN_DIGITS.sub("-", name)


def same_model(requested: str, served: str) -> bool:
    return normalise_model(requested) == normalise_model(served)


EXPERIMENTAL_WORDS = ("experimental", "preview", "excluded model")  # a listed model Auto never routes to (R19)


@dataclass(frozen=True)
class RoutedSet:
    """What a kiro-cli profile on `auto` may be served by: the makers of the Active models (`vendors`, sorted; `unknown`
    for a model of no known family), those models (`models`, normalised, sorted), where the set comes from (`listed`:
    the profile's own model listing, widened by the built-in set; `built-in`) and, for `built-in`, why."""

    vendors: tuple[str, ...]
    models: tuple[str, ...]
    source: Literal["listed", "built-in"] = "built-in"
    reason: str | None = None

    def to_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {"source": self.source, "vendors": list(self.vendors), "models": list(self.models)}
        if self.reason:
            detail["reason"] = self.reason
        return detail

    @classmethod
    def from_detail(cls, detail: object) -> "RoutedSet | None":
        """The set a probe recorded, else None (a missing or malformed record is never believed)."""
        if not isinstance(detail, Mapping):
            return None
        vendors, models, source = detail.get("vendors"), detail.get("models"), detail.get("source")
        if source not in ("listed", "built-in") or not isinstance(vendors, list) or not isinstance(models, list):
            return None
        if not vendors or not all(isinstance(v, str) and v for v in vendors):
            return None
        if not all(isinstance(m, str) for m in models):
            return None
        reason = detail.get("reason")
        return cls(tuple(sorted(vendors)), tuple(sorted(models)), source, reason if isinstance(reason, str) else None)


def _built_in() -> RoutedSet:
    """The Active models of the kiro-cli 2.32.0 listing of 2026-10-19 (design R18)."""
    models = (
        "claude-sonnet-5.5", "claude-opus-5", "claude-sonnet-5", "claude-opus-4.8", "claude-opus-4.7",
        "claude-opus-4.6", "claude-sonnet-4.6", "claude-opus-4.5", "claude-sonnet-4.5", "claude-haiku-4.5",
        "minimax-m2.5", "glm-5",
    )  # fmt: skip
    return RoutedSet(("anthropic", "minimax", "zhipu"), tuple(sorted(normalise_model(m) for m in models)))


def _copilot_built_in() -> RoutedSet:
    """The model ids that `copilot help config` lists for 1.0.102 (`tests/fixtures/recorded/copilot-cli/
    1.0.102-notoken/help-config.txt`, task 0.1). Every id has a known family: an id of none must stop the change, not
    put `unknown` into the set (L4-FAC-020)."""
    models = (
        "claude-sonnet-5.5", "claude-sonnet-5", "claude-fable-5.1", "claude-fable-5", "claude-opus-5.5",
        "claude-opus-5", "claude-opus-4.8", "claude-opus-4.8-fast", "claude-sonnet-4.6", "claude-haiku-5.5",
        "claude-haiku-4.5",
        "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
        "gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5-mini", "mai-code-1.1-flash", "gemini-4-argon",
        "gemini-3.8-flash", "gemini-3.7-flash", "grok-4.7", "grok-4.6", "grok-4.5", "kimi-k3",
    )  # fmt: skip
    vendors = {vendor for m in models if (vendor := family_vendor(m)) is not None}
    assert len(vendors) and all(family_vendor(m) for m in models), "a listed Copilot model has no known family"
    return RoutedSet(tuple(sorted(vendors)), tuple(sorted(normalise_model(m) for m in models)))


ROUTED_DEFAULT = _built_in()
COPILOT_ROUTED_DEFAULT = _copilot_built_in()
ROUTED_ADAPTERS = ("kiro-cli", "copilot-cli")  # the CLIs whose `auto` picks the model (and so the vendor) itself
ROUTED_DEFAULTS: dict[str, RoutedSet] = {"kiro-cli": ROUTED_DEFAULT, "copilot-cli": COPILOT_ROUTED_DEFAULT}
RoutedLookup = Callable[[str, Profile], RoutedSet]  # (profile name, profile) -> its possible vendors and models


def built_in_routed(name: str, profile: Profile) -> RoutedSet:
    """The built-in possible vendors and models of `profile`'s adapter on `auto` (kiro-cli's, else copilot-cli's)."""
    return ROUTED_DEFAULTS.get(profile.adapter or "", ROUTED_DEFAULT)


def is_routed(profile: Profile) -> bool:
    """A kiro-cli or copilot-cli profile with no model, `auto` in any letter case, or a blank model."""
    return profile.adapter in ROUTED_ADAPTERS and (profile.model or "").strip().lower() in ("", "auto")


def active_model_ids(listing: object) -> list[str] | None:
    """The Active model ids of a `chat --list-models --format json` answer, in listed order; None when it is not an
    object with a `models` list or holds no Active model. `auto` is skipped; a model whose description says
    experimental, preview or excluded model is Experimental; every other one, one with no description included, is
    Active (a missing description adds a vendor, never removes one)."""
    entries = listing.get("models") if isinstance(listing, Mapping) else None
    if not isinstance(entries, list):
        return None
    found: list[str] = []
    for entry in entries:
        model = entry.get("model_id") if isinstance(entry, Mapping) else None
        if not isinstance(model, str) or not model.strip() or model.strip().lower() == "auto":
            continue
        description = entry.get("description")
        if isinstance(description, str) and any(w in description.lower() for w in EXPERIMENTAL_WORDS):
            continue
        found.append(model.strip())
    return found or None


def routed_from_listing(listing: object) -> RoutedSet | None:
    """The possible vendors of `auto` from a listing: the makers of its Active models, widened by the built-in set
    (the owner's decision of 2026-10-19: the union, so that a vendor Kiro dropped from the list or a restricted
    listing never shrinks the set). None when the listing holds no Active model."""
    ids = active_model_ids(listing)
    if ids is None:
        return None
    vendors = {served_vendor(m) for m in ids} | set(ROUTED_DEFAULT.vendors)
    models = {normalise_model(m) for m in ids} | set(ROUTED_DEFAULT.models)
    return RoutedSet(tuple(sorted(vendors)), tuple(sorted(models)), "listed")


def built_in_with_reason(reason: str) -> RoutedSet:
    return RoutedSet(ROUTED_DEFAULT.vendors, ROUTED_DEFAULT.models, "built-in", reason)


def resolve_vendor(profile: Profile, served_model: str | None = None) -> tuple[str | None, Provenance]:
    """`(vendor, provenance)` of this profile. `served_model` is what the adapter reported, when it does."""
    if served_model:
        vendor = served_vendor(served_model)
        return (vendor, "served") if vendor != UNKNOWN else (UNKNOWN, "unknown")
    if tool := TOOL_VENDORS.get(profile.adapter or ""):
        return tool, "tool"
    if profile.adapter in ROUTED_ADAPTERS:  # these CLIs host many vendors' models: the model's family says whose it is
        if is_routed(profile):  # the CLI picks: any vendor of the possible set may answer, whatever `vendor:` says
            return None, "routed"
        if family := family_vendor(profile.model or ""):
            return family, "declared"
    declared = (profile.vendor or "").strip().lower()  # `OpenAI` and `openai` are one vendor
    if not declared or declared == UNKNOWN:
        return (declared or None), "unknown"
    return declared, "declared"


def vendor_provenance(profile: Profile, served_model: str | None = None) -> Provenance:
    return resolve_vendor(profile, served_model)[1]
