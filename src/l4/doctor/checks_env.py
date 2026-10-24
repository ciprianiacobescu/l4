"""ENV-001..004: the toolchain the harness itself needs; ENV-015: each agent CLI against its pin.
Registered at import."""

import re

from l4.config.defaults import copilot_env, openspec_entrypoint, openspec_env, openspec_prefix
from l4.config.schema import RolesCfg
from l4.doctor.context import DoctorContext
from l4.doctor.registry import Check, CheckResult, Severity, register
from l4.provision.catalog import (
    ADAPTER_BINARIES,
    ADAPTER_PINS,
    SUPPORTED_MAJORS,
    adapters_in_use,
    effective_pins,
    gate_pin,
    major_no_version_text,
    major_problem,
    manual_command,
    profile_cli,
    reported_version,
    required_tools,
)
from l4.provision.runner import Paths, detect_platform
from l4.versions import parse_version, version_at_least

MIN_PYTHON = (3, 11)
MIN_GIT = (2, 34)  # SPEC 15 (the change docs still say 2.40)
MIN_NODE = (20, 19)

_VERSION = re.compile(r"(\d+)\.(\d+)")


def _major_minor(text: str) -> tuple[int, int] | None:
    match = _VERSION.search(text)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _fmt(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def _env_001(ctx: DoctorContext) -> CheckResult:
    if ctx.python_version[:2] < MIN_PYTHON:
        return CheckResult("fail", f"Python {_fmt(ctx.python_version)} found, {_fmt(MIN_PYTHON)} or newer is required")
    if not ctx.which("uv"):
        return CheckResult("fail", "uv not found on PATH", "install uv (https://docs.astral.sh/uv/)")
    return CheckResult("pass", f"Python {_fmt(ctx.python_version)}, uv present")


def _env_002(ctx: DoctorContext) -> CheckResult:
    git = ctx.which("git")
    if not git:
        return CheckResult("fail", f"git not found on PATH (need {_fmt(MIN_GIT)} or newer)")
    out = ctx.run([git, "--version"])
    version = _major_minor(out.stdout) if out.returncode == 0 else None
    if version is None:
        return CheckResult("fail", "could not parse the output of `git --version`")
    if version < MIN_GIT:
        return CheckResult("fail", f"git {_fmt(version)} found, {_fmt(MIN_GIT)} or newer is required")
    return CheckResult("pass", f"git {_fmt(version)}")


def openspec_active(ctx: DoctorContext) -> bool:
    frameworks = ctx.cfg.spec.frameworks
    if frameworks == "auto":
        return (ctx.repo / ctx.cfg.spec.openspec.root).is_dir()
    return "openspec" in frameworks


def _env_003(ctx: DoctorContext) -> CheckResult:
    if not openspec_active(ctx):
        return CheckResult("skip", "OpenSpec is not active in this repository")
    pin = ctx.cfg.spec.openspec.version
    entry = openspec_entrypoint(ctx.env)
    hint = f"npm install --prefix {openspec_prefix(ctx.env)} --save-exact {ctx.cfg.spec.openspec.package}@{pin}"
    # the node checked here is the node the provider will run (L4-OSP-001)
    node = ctx.which("node")
    if not node:
        return CheckResult("fail", f"node not found on PATH (need {_fmt(MIN_NODE)} or newer)")
    node_version = _major_minor(ctx.run([node, "--version"]).stdout)
    if node_version is None or node_version < MIN_NODE:
        found = _fmt(node_version) if node_version else "unknown"
        return CheckResult("fail", f"node {found} at {node}, {_fmt(MIN_NODE)} or newer is required")
    if not entry.is_file():
        return CheckResult("fail", f"OpenSpec {pin} is not installed: {entry} is missing", hint)
    out = ctx.run([node, str(entry), "--version"], timeout=60.0, env=openspec_env(ctx.env, forbid=(ctx.repo,)))
    found = out.stdout.strip()
    if out.returncode != 0 or found != pin:
        return CheckResult("fail", f"OpenSpec reports {found or 'no version'}, the pinned version is {pin}", hint)
    return CheckResult("pass", f"OpenSpec {pin} via {node}")


ENV_001 = register(Check("ENV-001", "Python and uv", "error", _env_001))
ENV_002 = register(Check("ENV-002", "git", "error", _env_002))
ENV_003 = register(Check("ENV-003", "Node and the pinned OpenSpec", "error", _env_003))


HEAD_ROLES = ("implementer", "judges")  # an unusable first profile of these stops the run (SCN-DOC-02)


def version_env(ctx: DoctorContext, binary: str) -> dict[str, str] | None:
    """The environment of a `--version` read: `claude` gets `DISABLE_AUTOUPDATER=1` and never `DISABLE_UPDATES`, which
    blocks `claude install` (L4-PRV-044); `copilot` gets the L4 package cache and no auto-update (L4-PRV-048). Any other
    binary keeps the default (None)."""
    if binary == "copilot":
        return {**ctx.env, **copilot_env(ctx.env)}
    if binary != "claude":
        return None
    return {**{k: v for k, v in ctx.env.items() if k != "DISABLE_UPDATES"}, "DISABLE_AUTOUPDATER": "1"}


def _cli_problem(ctx: DoctorContext, binary: str, minimum: str | None, key: str | None = None) -> str | None:
    """Why `binary` is unusable (missing, too old, or of another major than `key` runs), or None. `key` is the CLI's
    gate key (`profile_cli`): the adapter, or `opencode2` for a `cli_major: 2` profile."""
    exe = ctx.which(binary)
    if exe is None:
        return f"{binary} not found"
    gated = key in SUPPORTED_MAJORS
    if not minimum and not gated:
        return None
    found = ctx.run([exe, "--version"], env=version_env(ctx, binary)).stdout
    if gated and key is not None:  # the major first, whatever min_version says (L4-OCG-001)
        if (wrong := major_problem(key, binary, found, gate_pin(ctx.cfg, key))) is not None:
            return wrong
        if reported_version(found) is None:  # fail closed: a gated CLI whose major cannot be read is not accepted
            return major_no_version_text(key, binary)
        if not minimum:
            return None
    meets = version_at_least(found, minimum)
    if meets is None:
        return f"{binary} reports no version that can be compared with {minimum}"
    if not meets:
        return f"{binary} {_fmt(parse_version(found) or ())} found, {minimum} or newer is required"
    return None


def _env_004(ctx: DoctorContext) -> CheckResult:
    """The CLI of every profile in every role chain resolves on the harness path and meets its `min_version`. A failing
    profile is a warning while another profile of its chain is usable (the fallback decides, SPEC 22 Q9); it is an
    error only when no profile of an implementer or judge chain is usable. Other roles never stop the run."""
    problems: dict[str, str] = {}  # profile -> its problem, one probe per profile
    checked: set[str] = set()
    messages: list[str] = []
    severity: Severity = "warn"
    for role in RolesCfg.model_fields:
        chain = list(getattr(ctx.cfg.roles, role))
        usable: list[str] = []
        failing: list[tuple[int, str]] = []
        for index, name in enumerate(chain):
            profile = ctx.cfg.profiles.get(name)
            if profile is None or profile.adapter not in ADAPTER_BINARIES:
                usable.append(name)  # no agent CLI to check: nothing that can fail here
                continue
            if name not in checked:
                checked.add(name)
                key, binary = profile_cli(profile)
                problem = _cli_problem(ctx, binary, profile.min_version, key)
                if problem:
                    problems[name] = problem
            if name in problems:
                failing.append((index, name))
            else:
                usable.append(name)
        if not failing:
            continue
        parts = [
            f"{role} head `{name}`: {problems[name]}" if index == 0 and role in HEAD_ROLES
            else f"{role} fallback `{name}`: {problems[name]}"
            for index, name in failing
        ]  # fmt: skip
        if usable:
            parts.append(f"usable fallback `{usable[0]}`")
        else:
            parts.append(f"no usable profile in the {role} chain")
            if role in HEAD_ROLES:
                severity = "error"
        messages.append("; ".join(parts))
    if not checked:
        return CheckResult("skip", "no profile in a role chain uses an agent CLI")
    if not messages:
        return CheckResult("pass", f"{len(checked)} agent CLI(s) present")
    return CheckResult(
        "fail", " | ".join(dict.fromkeys(messages)), "`l4 doctor --fix` installs agent CLIs user-locally (L4-DOC-002)",
        severity=severity,
    )  # fmt: skip


ENV_004 = register(Check("ENV-004", "Agent CLIs of every role chain", "error", _env_004))


def _home_relative(path: str, home: str) -> str:
    return "~" + path[len(home) :] if home and path.startswith(home.rstrip("/") + "/") else path


def _env_015(ctx: DoctorContext) -> CheckResult:
    """Each agent CLI a role chain uses runs its effective pin (L4-PRV-046): the catalog's, or the version
    `ci.cli_versions` holds. A drift names the CLI, its path and both versions and the fix; a missing CLI or a wrong
    major is ENV-004's finding and left to it. One `--version` read per CLI in use."""
    pins = effective_pins(ctx.cfg)
    used = adapters_in_use(ctx.cfg)
    at_pin: list[str] = []
    held: list[str] = []
    drifts: list[str] = []
    fixes: list[str] = []
    tools = {t.adapter: t for t in required_tools(ctx.cfg, openspec_active=False) if t.kind == "agent"}
    for adapter, binary in ADAPTER_BINARIES.items():
        if adapter not in used:
            continue
        exe = ctx.which(binary)
        if exe is None:
            continue
        text = ctx.run([exe, "--version"], env=version_env(ctx, binary)).stdout
        found = parse_version(text)
        pin, source = pins[adapter]
        if found is None or major_problem(adapter, binary, text, pin) is not None:
            continue
        shown = ".".join(map(str, found))
        if shown != pin:
            where = _home_relative(exe, ctx.env.get("HOME", ""))
            drifts.append(
                f"{binary} {shown} at {where}, pinned {pin}" + (f" ({source})" if source != "catalog" else "")
            )
            fixes.append(manual_command(tools[adapter], detect_platform(), str(Paths.from_env(ctx.env).l4_home)))
        elif source != "catalog":
            catalog_pin = ADAPTER_PINS[adapter]
            note = f"{binary} {shown} held by ci.cli_versions; L4 pins {catalog_pin}"
            held.append(note + ("; the override equals the pin: remove it" if catalog_pin == pin else ""))
        else:
            at_pin.append(f"{binary} {shown}")
    if not used:
        return CheckResult("skip", "no profile in a role chain uses an agent CLI")
    if drifts:
        hint = "in CI l4 doctor --ci --fix installs the pins; on this machine: " + "; ".join(fixes)
        return CheckResult("fail", "; ".join(drifts), hint)
    parts = [f"{', '.join(at_pin)} at {'its pin' if len(at_pin) == 1 else 'their pins'}"] if at_pin else []
    message = "; ".join([*parts, *held]) or "no agent CLI to compare with its pin"
    return CheckResult("pass", message)


ENV_015 = register(Check("ENV-015", "Agent CLIs run their pins", "warn", _env_015))
