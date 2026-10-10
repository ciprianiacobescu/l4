"""Where a profile's vendor comes from (SPEC 10.1): the input of the verifier's independence rule, recorded on every
`Selected` so that a caller of `Factory.for_role` need not recompute it.

The vendor comes from the tool, never from the operator's say-so, wherever the tool can tell:
- a model id the adapter reported as served (`claude-*` anthropic, `gpt-*`/`o<digit>` openai, `gemini-*` google);
- a single-vendor CLI (codex, claude-code): the vendor of the tool (`TOOL_VENDORS`);
- only an adapter that can run any vendor's model (opencode, kiro-cli, command, acp) falls back to `vendor:`, and the
  result is `declared`.
"""

import re
from typing import Literal

from l4.config.schema import TOOL_VENDORS, Profile

Provenance = Literal["served", "tool", "declared", "unknown"]
TOOL_VENDOR_ADAPTERS = frozenset(TOOL_VENDORS)
UNKNOWN = "unknown"

_SERVED_VENDORS = (
    (re.compile(r"^(?:(?:[a-z]+\.)?anthropic\.)?claude-"), "anthropic"),  # Bedrock: `us.anthropic.claude-…`
    (re.compile(r"^(gpt-|o\d)"), "openai"),
    (re.compile(r"^gemini-"), "google"),
)


def served_vendor(model: str) -> str:
    """The vendor named by a served model id; an id of no known family is `unknown`."""
    name = model.strip().lower().rsplit("/", 1)[-1]
    return next((vendor for pattern, vendor in _SERVED_VENDORS if pattern.match(name)), UNKNOWN)


def resolve_vendor(profile: Profile, served_model: str | None = None) -> tuple[str | None, Provenance]:
    """`(vendor, provenance)` of this profile. `served_model` is what the adapter reported, when it does."""
    if served_model:
        vendor = served_vendor(served_model)
        return (vendor, "served") if vendor != UNKNOWN else (UNKNOWN, "unknown")
    if tool := TOOL_VENDORS.get(profile.adapter or ""):
        return tool, "tool"
    declared = (profile.vendor or "").strip().lower()  # `OpenAI` and `openai` are one vendor
    if not declared or declared == UNKNOWN:
        return (declared or None), "unknown"
    return declared, "declared"


def vendor_provenance(profile: Profile, served_model: str | None = None) -> Provenance:
    return resolve_vendor(profile, served_model)[1]
