"""Configuration errors that only show once the environment is known, found before a run takes the lease, creates a
worktree or probes an agent: all of them are usage errors (exit 2), none echoes a configured value."""

from l4.config.defaults import cache_root
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import require_forge_target, require_token_in_ci
from l4.llm.system_one import ENGINES
from l4.sandbox.caches import cache_dir


def preflight_run_config(app: AppContext, cfg: L4Config) -> None:
    require_token_in_ci(cfg, app.environ)  # exit 3
    require_forge_target(cfg, app.environ)  # exit 2
    root = cache_root(app.environ, repo=app.repo).resolve()  # exit 2: relative, or inside the repository
    for name, cache in cfg.sandbox.caches.items():
        try:
            cache_dir(cache, root, "unit/unit")
        except ValueError:
            message = f"sandbox.caches.{name}: the path must stay inside the runner cache"
            raise L4Exit(ExitCode.USAGE_ERROR, message) from None
    for role in ("implementer", "judges"):
        chain = getattr(cfg.roles, role)
        if not chain:
            raise L4Exit(ExitCode.USAGE_ERROR, f"roles.{role} is empty: a run needs at least one profile for it")
        for profile in chain:
            if profile not in cfg.profiles:
                raise L4Exit(ExitCode.USAGE_ERROR, f"roles.{role} names a profile that is not defined under profiles")
    # optional roles: an empty chain is fine, an undefined name is not
    for role in ("clarifier", "s1_judge", "verifier_agent"):
        if any(profile not in cfg.profiles for profile in getattr(cfg.roles, role)):
            raise L4Exit(ExitCode.USAGE_ERROR, f"roles.{role} names a profile that is not defined under profiles")
    if cfg.clarifier.s1_standin == "llm_boolean" and not cfg.roles.s1_judge:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            "clarifier.s1_standin is llm_boolean but roles.s1_judge is empty: it needs a profile (an adapter profile "
            "is enough for the stand-in; verifier step 8 runs only for a `backend: system-one` profile there)",
        )
    e2e = cfg.gates.e2e
    if e2e.command.strip():  # step 3 runs the gate, so a half-configured one is refused before any agent works
        missing = [n for n, value in (("serve.command", e2e.serve.command.strip()), ("serve.ready_url",
                   e2e.serve.ready_url.strip()), ("reports", e2e.reports)) if not value]  # fmt: skip
        if missing:
            raise L4Exit(ExitCode.USAGE_ERROR, f"gates.e2e.command is set: gates.e2e.{', '.join(missing)} is empty")
        if e2e.format != "junit":
            raise L4Exit(ExitCode.USAGE_ERROR, "gates.e2e.format: only junit is supported yet")
        if cfg.verifier.playwright.enabled is not False and not cfg.roles.verifier_agent:
            # step 5 would have no test writer ("auto" follows the command)
            message = "gates.e2e.command is set and Playwright is on: roles.verifier_agent is empty"
            raise L4Exit(ExitCode.USAGE_ERROR, message)
    for name, profile in cfg.profiles.items():
        if profile.backend != "system-one":
            continue
        if profile.engine not in ENGINES:
            raise L4Exit(ExitCode.USAGE_ERROR, f"profiles.{name}.engine must be one of {', '.join(ENGINES)}")
        if profile.engine == "remote" and not profile.base_url:
            raise L4Exit(ExitCode.USAGE_ERROR, f"profiles.{name}.base_url is required for a remote engine")
        if profile.engine == "jev" and not profile.api_key_env:
            raise L4Exit(ExitCode.USAGE_ERROR, f"profiles.{name}.api_key_env is required for the jev engine")
    for name in cfg.verifier.s1.shadow:  # M1.6: record-only engines; a typo would silently shadow nothing
        if name not in cfg.profiles:
            raise L4Exit(
                ExitCode.USAGE_ERROR, f"verifier.s1.shadow names a profile that is not defined under profiles: {name}"
            )
        if cfg.profiles[name].backend != "system-one":
            raise L4Exit(ExitCode.USAGE_ERROR, f"verifier.s1.shadow: {name} is not a backend: system-one profile")
