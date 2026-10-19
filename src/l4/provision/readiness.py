"""What a human still has to do for each agent profile (L4-PRV-007..009): three states, printed steps, no secrets.

`ready` means an auth signal exists, not that the credential works; that is `doctor --live`. Nothing here logs in:
`HUMAN_STEPS` is text. The auth signal comes from the adapter's own `probe(profile, "auth", ctx)`, which parses the
CLI's output itself and keeps e-mail addresses out (`l4.availability.probes`); `sanitize_status` is the second fence.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from l4.agents.base import ProbeCtx
from l4.agents.credentials import OPENCODE_API_KEY, credential_in, profile_credential_variable
from l4.agents.factory import Factory
from l4.agents.gate import GateBusy, busy_detail
from l4.availability.steps import StepTimedOut
from l4.config.schema import L4Config, Profile
from l4.exitcodes import L4Exit
from l4.forge.base import forge_platform

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


_MASKED = re.compile(r"the masked CI variable (\w+)")


def secret_place(environment: str | None) -> str:
    """Where a credential is stored on GitHub (L4-GHP-009): a secret of the Actions environment the job runs in."""
    return f"a secret of the GitHub environment `{environment}`" if environment else "a repository secret"


def steps_for(
    adapter: str, auth: str | None, *, platform: str = "gitlab", environment: str | None = None
) -> tuple[str, ...]:
    """What a human does. On GitHub a key is `a secret of the GitHub environment <ci.github_environment>`, not `the
    masked CI variable`; the logins on the runner VM read the same on both."""
    steps = HUMAN_STEPS.get((adapter, auth or "subscription"), ())
    if platform != "github":
        return steps
    return tuple(_MASKED.sub(lambda m: f"{secret_place(environment)}: {m.group(1)}", step) for step in steps)


def provider_steps(profile: Profile, *, platform: str = "gitlab", environment: str | None = None) -> tuple[str, ...]:
    """A profile that declares its own provider names its own key variable (never a value)."""
    options = profile.opencode_options()
    if options is None or options.provider is None:
        if profile_credential_variable(profile) != OPENCODE_API_KEY:
            return ()
        if platform == "github":
            return (f"run `l4 setup github --secret {OPENCODE_API_KEY}=<ENV>` (the value comes from your environment)",)
        return (f"store your OpenCode key as the masked CI variable {OPENCODE_API_KEY}",)
    where = f"{secret_place(environment)}" if platform == "github" else "a masked CI variable on a runner"
    return (
        f"provide the provider key as {options.provider.api_key_env} in the harness environment "
        f"({where}); it is passed to the agent as a 0600 file, never as a variable",
    )


def platform_of(cfg: L4Config | None, environ: Mapping[str, str], origin: str | None = None) -> tuple[str, str | None]:
    """The CI platform and the GitHub environment name: `ci.platform`, else the forge type (`forge_platform`)."""
    if cfg is None:
        return "gitlab", None
    return forge_platform(cfg, environ, origin), cfg.ci.github_environment


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
    detail: str | None = None  # `<profile>: <VARIABLE> is not set` for a profile whose credential variable is unset

    def line(self) -> str:
        return f"{self.profile} {self.adapter} {self.state.value}"


def adapter_readiness(
    name: str,
    profile: Profile,
    factory: Factory,
    ctx: ProbeCtx,
    *,
    cfg: L4Config | None = None,
    origin: str | None = None,
) -> AdapterReadiness:
    """binary, then auth. An adapter this build does not know counts as missing. The human steps are worded for the
    platform of `cfg` (default: the factory's own config) and, when `ci.platform` is auto, of the `origin` URL."""
    platform, environment = platform_of(cfg or getattr(factory, "_cfg", None), ctx.environ, origin)
    adapter = profile.adapter or "backend"
    try:
        impl = factory.build(profile)
    except L4Exit:
        return AdapterReadiness(name, adapter, AdapterState.MISSING)
    try:
        if not impl.probe(profile, "binary", ctx).ok:
            return AdapterReadiness(name, adapter, AdapterState.MISSING)
    except StepTimedOut as exc:
        return AdapterReadiness(name, adapter, AdapterState.MISSING, detail=exc.reason)
    try:
        with factory.holding_login(profile):  # `auth` may refresh the stored login: one process at a time
            auth = impl.probe(profile, "auth", ctx)
    except StepTimedOut as exc:
        return AdapterReadiness(
            name, adapter, AdapterState.INSTALLED_NOT_AUTHENTICATED, detail=exc.reason,
            steps=provider_steps(profile, platform=platform, environment=environment)
            or steps_for(adapter, profile.auth, platform=platform, environment=environment),
        )  # fmt: skip
    except (GateBusy, OSError):
        return AdapterReadiness(name, adapter, AdapterState.BUSY, status={"note": busy_detail(adapter)})
    if auth.ok:
        return AdapterReadiness(name, adapter, AdapterState.READY, status=sanitize_status(auth.detail))
    variable = profile_credential_variable(profile)
    unset = variable if variable and credential_in(ctx.environ, variable) is None else None
    return AdapterReadiness(
        name,
        adapter,
        AdapterState.INSTALLED_NOT_AUTHENTICATED,
        provider_steps(profile, platform=platform, environment=environment)
        or steps_for(adapter, profile.auth, platform=platform, environment=environment),
        detail=f"{name}: {unset} is not set" if unset else None,
    )
