"""What a human still has to do for each agent profile (L4-PRV-007..009): three states, printed steps, no secrets.

`ready` means an auth signal exists, not that the credential works; that is `doctor --live`. Nothing here logs in:
`HUMAN_STEPS` is text. The auth signal comes from the adapter's own `probe(profile, "auth", ctx)`, which parses the
CLI's output itself and keeps e-mail addresses out (`l4.availability.probes`); `sanitize_status` is the second fence.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from l4.agents.base import ProbeCtx
from l4.agents.factory import Factory
from l4.agents.gate import GateBusy, busy_detail
from l4.config.schema import Profile
from l4.exitcodes import L4Exit

_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_. -]{1,40}$")


class AdapterState(StrEnum):
    READY = "ready"
    INSTALLED_NOT_AUTHENTICATED = "installed-not-authenticated"
    MISSING = "missing"
    BUSY = "login-busy"  # another process is using the login (L4-FAC-008): not asked, so neither ready nor refused


# (adapter, auth) -> what only a human can do. Codex's `login --device-auth` is listed by `codex login --help`
# in 0.160.0 [V]; `claude setup-token` is [V, research/02]; `kiro-cli login` is [U].
HUMAN_STEPS: dict[tuple[str, str], tuple[str, ...]] = {
    ("claude-code", "subscription"): (
        "run `claude setup-token` on a machine with a browser",
        "store the printed token as the masked CI variable CLAUDE_CODE_OAUTH_TOKEN",
    ),
    ("claude-code", "api_key"): ("store your key as the masked CI variable ANTHROPIC_API_KEY",),
    ("opencode", "subscription"): ("store your OpenRouter key as the masked CI variable OPENROUTER_API_KEY",),
    ("opencode", "api_key"): ("store your OpenRouter key as the masked CI variable OPENROUTER_API_KEY",),
    ("codex", "subscription"): (
        "on the runner VM, as the runner user, run `codex login --device-auth` and finish it in a browser",
    ),
    ("codex", "api_key"): ("store your key as the masked CI variable CODEX_API_KEY",),
    ("kiro-cli", "subscription"): ("on the runner VM, as the runner user, run `kiro-cli login`",),
    ("kiro-cli", "api_key"): ("store your key as the masked CI variable KIRO_API_KEY",),
}


def steps_for(adapter: str, auth: str | None) -> tuple[str, ...]:
    return HUMAN_STEPS.get((adapter, auth or "subscription"), ())


def provider_steps(profile: Profile) -> tuple[str, ...]:
    """A profile that declares its own provider names its own key variable (never a value)."""
    options = profile.opencode_options()
    if options is None or options.provider is None:
        return ()
    return (
        f"provide the provider key as {options.provider.api_key_env} in the harness environment "
        "(a masked CI variable on a runner); it is passed to the agent as a 0600 file, never as a variable",
    )


def sanitize_status(raw: dict[str, Any]) -> dict[str, Any]:
    """Only `logged_in`, `auth_method` and `plan`, and only values that look like words (an e-mail has an `@`)."""

    def word(*keys: str) -> str | None:
        for key in keys:
            value = raw.get(key)
            if isinstance(value, str) and _SAFE_VALUE.match(value):
                return value
        return None

    logged_in = raw.get("logged_in", raw.get("loggedIn"))
    return {
        "logged_in": logged_in if isinstance(logged_in, bool) else False,
        "auth_method": word("auth_method", "authMethod"),
        "plan": word("plan", "subscriptionType"),
    }


@dataclass(frozen=True)
class AdapterReadiness:
    profile: str
    adapter: str
    state: AdapterState
    steps: tuple[str, ...] = ()  # only for installed-not-authenticated
    status: dict[str, Any] = field(default_factory=dict)  # sanitized

    def line(self) -> str:
        return f"{self.profile} {self.adapter} {self.state.value}"


def adapter_readiness(name: str, profile: Profile, factory: Factory, ctx: ProbeCtx) -> AdapterReadiness:
    """binary, then auth. An adapter this build does not know counts as missing."""
    adapter = profile.adapter or "backend"
    try:
        impl = factory.build(profile)
    except L4Exit:
        return AdapterReadiness(name, adapter, AdapterState.MISSING)
    if not impl.probe(profile, "binary", ctx).ok:
        return AdapterReadiness(name, adapter, AdapterState.MISSING)
    try:
        with factory.holding_login(profile):  # `auth` may refresh the stored login: one process at a time
            auth = impl.probe(profile, "auth", ctx)
    except (GateBusy, OSError):
        return AdapterReadiness(name, adapter, AdapterState.BUSY, status={"note": busy_detail(adapter)})
    if auth.ok:
        return AdapterReadiness(name, adapter, AdapterState.READY, status=sanitize_status(auth.detail))
    return AdapterReadiness(
        name,
        adapter,
        AdapterState.INSTALLED_NOT_AUTHENTICATED,
        provider_steps(profile) or steps_for(adapter, profile.auth),
    )
