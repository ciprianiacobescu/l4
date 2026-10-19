"""Where a profile's vendor comes from (SPEC 10.1): the input of the verifier's independence rule, recorded on every
`Selected` so that a caller of `Factory.for_role` need not recompute it.

The vendor comes from the tool, never from the operator's say-so, wherever the tool can tell:
- a model id the adapter reported as served (`claude-*` anthropic, `gpt-*`/`o<digit>` openai, `gemini-*` google);
- a single-vendor CLI (codex, claude-code): the vendor of the tool (`TOOL_VENDORS`);
- a kiro-cli profile: the vendor of its model's family (`MODEL_FAMILIES`), `unknown` when it has no model or `auto`;
- only an adapter that can run any vendor's model (opencode, kiro-cli, command, acp) falls back to `vendor:`, and the
  result is `declared`.
"""

import re
from typing import Literal

from l4.config.schema import TOOL_VENDORS, Profile

Provenance = Literal["served", "tool", "declared", "unknown"]
TOOL_VENDOR_ADAPTERS = frozenset(TOOL_VENDORS)
UNKNOWN = "unknown"

MODEL_FAMILIES = (  # (pattern on the lowercased model id after its last `/`, the vendor that makes the family)
    (re.compile(r"^(?:(?:[a-z]+\.)?anthropic\.)?claude-"), "anthropic"),  # Bedrock: `us.anthropic.claude-…`
    (re.compile(r"^(gpt-|o\d)"), "openai"),
    (re.compile(r"^gemini-"), "google"),
    (re.compile(r"^deepseek-"), "deepseek"),
    (re.compile(r"^glm-"), "zhipu"),
    (re.compile(r"^minimax-"), "minimax"),
    (re.compile(r"^qwen"), "alibaba"),
    (re.compile(r"^kimi-"), "moonshot"),
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


def resolve_vendor(profile: Profile, served_model: str | None = None) -> tuple[str | None, Provenance]:
    """`(vendor, provenance)` of this profile. `served_model` is what the adapter reported, when it does."""
    if served_model:
        vendor = served_vendor(served_model)
        return (vendor, "served") if vendor != UNKNOWN else (UNKNOWN, "unknown")
    if tool := TOOL_VENDORS.get(profile.adapter or ""):
        return tool, "tool"
    if profile.adapter == "kiro-cli":  # Kiro hosts the models of many vendors: the model's family says whose it is
        model = (profile.model or "").strip().lower()
        if not model or model == "auto":  # Kiro picks: any vendor may answer, whatever `vendor:` says
            return UNKNOWN, "unknown"
        if family := family_vendor(model):
            return family, "declared"
    declared = (profile.vendor or "").strip().lower()  # `OpenAI` and `openai` are one vendor
    if not declared or declared == UNKNOWN:
        return (declared or None), "unknown"
    return declared, "declared"


def vendor_provenance(profile: Profile, served_model: str | None = None) -> Provenance:
    return resolve_vendor(profile, served_model)[1]
