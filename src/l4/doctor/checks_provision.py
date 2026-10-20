"""PRV-001, PRV-002 and the user-local provisioning fix of ENV-001, ENV-003 and ENV-004 (L4-DOC-002, runner-provisioning
1.9). Logins and root-only steps are printed, never run; `--ci --fix` applies this fix and no other (L4-PRV-010)."""

from collections.abc import Sequence
from pathlib import Path

import l4.doctor.checks_env as checks_env  # noqa: F401  (the checks a fix hangs on are registered first)
from l4.agents.base import ProbeCtx
from l4.agents.factory import Factory
from l4.agents.opencode_provider import provider_host, reachable
from l4.doctor.checks_agents import scratch_dir
from l4.doctor.context import DoctorContext
from l4.doctor.registry import Check, CheckResult, Fix, attach_fix, register
from l4.forge.urls import origin_url
from l4.proc import Runner as CommandRunner
from l4.proc import run_process
from l4.provision.catalog import adapters_in_use
from l4.provision.install import install_planned
from l4.provision.readiness import AdapterState, adapter_readiness
from l4.provision.runner import (
    Fetcher,
    FixAction,
    GuardedCommandRunner,
    HttpxFetcher,
    Paths,
    detect_platform,
    plan_fixes,
    plan_root_prereqs,
    resolve_self_provision,
)

OS_RELEASE = Path("/etc/os-release")


def _os_release() -> str:
    try:
        return OS_RELEASE.read_text(encoding="utf-8")
    except OSError:
        return ""


def _fetcher() -> Fetcher:
    return HttpxFetcher()


def _runner() -> CommandRunner:
    return GuardedCommandRunner(run_process)


def fix_provision(ctx: DoctorContext) -> Sequence[FixAction]:
    return install_planned(
        ctx.cfg, Paths.from_env(ctx.env), ctx.env, detect_platform(),
        openspec_active=checks_env.openspec_active(ctx), fetcher=_fetcher(), run=_runner(),
        os_release=_os_release(), allow_install=resolve_self_provision(ctx.cfg, ctx.env),
        replace_present=ctx.ci,
    )  # fmt: skip


def survey_provision(ctx: DoctorContext) -> Sequence[FixAction]:
    """What `fix_provision` would do, without doing it: a healthy runner answers `already present` for every tool."""
    return plan_fixes(
        ctx.cfg, Paths.from_env(ctx.env), ctx.env, detect_platform(),
        openspec_active=checks_env.openspec_active(ctx), run=_runner(), os_release=_os_release(),
        allow_install=resolve_self_provision(ctx.cfg, ctx.env), replace_present=ctx.ci,
    )  # fmt: skip


def _provider_notes(ctx: DoctorContext, names: Sequence[str]) -> list[str]:
    """Host reachability of each custom provider, as a note: the machine behind it may sleep, which makes the profile
    unavailable (the chain falls back), not the runner unhealthy. Host and port only: no path, no key."""
    notes = []
    for name in sorted(names):
        options = ctx.cfg.profiles[name].opencode_options()
        if options is None or options.provider is None:
            continue
        up, _ = reachable(options.provider.base_url)
        host = provider_host(options.provider.base_url)
        notes.append(f"{name} provider {host} {'reachable' if up else 'unreachable (optional: the chain falls back)'}")
    return notes


def _prv_001(ctx: DoctorContext) -> CheckResult:
    names = [name for profiles in adapters_in_use(ctx.cfg).values() for name in profiles]
    if not names:
        return CheckResult("skip", "no profile in a role chain uses an agent CLI")
    with scratch_dir(ctx.repo) as scratch:
        probe_ctx = ProbeCtx(environ=ctx.env, cwd=Path(scratch), run=run_process, forbid=(ctx.repo,))
        factory = Factory(ctx.cfg, probe_ctx)
        origin = origin_url(ctx.repo, ctx.env)  # `ci.platform: auto` words the steps for the forge (L4-GHP-009)
        rows = [
            adapter_readiness(name, ctx.cfg.profiles[name], factory, probe_ctx, cfg=ctx.cfg, origin=origin)
            for name in sorted(names)
        ]
    unset = [row.detail for row in rows if row.detail]  # L4-PRV-024: the variable that would authenticate the profile
    message = "; ".join([*(row.line() for row in rows), *unset, *_provider_notes(ctx, names)])
    if all(row.state in (AdapterState.READY, AdapterState.BUSY) for row in rows):
        return CheckResult("pass", message)
    steps = [step for row in rows for step in row.steps]
    return CheckResult("fail", message, " | ".join(dict.fromkeys(steps)) or "run `l4 doctor --fix` for missing CLIs")


def _prv_002(ctx: DoctorContext) -> CheckResult:
    missing = plan_root_prereqs(Paths.from_env(ctx.env), ctx.env, detect_platform(), _os_release())
    if not missing:
        return CheckResult("pass", "no root-only prerequisite is missing")
    return CheckResult(
        "fail", "; ".join(f"{a.tool}: {a.message}" for a in missing),
        "a person with root runs the line above; the harness never does (L4-PRV-006)",
    )  # fmt: skip


PRV_001 = register(Check("PRV-001", "Agent CLI readiness", "warn", _prv_001))
PRV_002 = register(Check("PRV-002", "Root-only prerequisites", "warn", _prv_002))
INSTALL_FIX = Fix("install", "provision", fix_provision, survey_provision)
for _check_id in ("ENV-001", "ENV-003", "ENV-004"):
    attach_fix(_check_id, INSTALL_FIX)
