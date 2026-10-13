"""ENV-001..004: the toolchain the harness itself needs. Registered at import."""

import re

from l4.config.defaults import openspec_entrypoint, openspec_env, openspec_prefix
from l4.config.schema import RolesCfg
from l4.doctor.context import DoctorContext
from l4.doctor.registry import Check, CheckResult, Severity, register
from l4.provision.catalog import ADAPTER_BINARIES
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


def _cli_problem(ctx: DoctorContext, binary: str, minimum: str | None) -> str | None:
    exe = ctx.which(binary)
    if exe is None:
        return f"{binary} not found"
    if not minimum:
        return None
    found = ctx.run([exe, "--version"]).stdout
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
                problem = _cli_problem(ctx, ADAPTER_BINARIES[profile.adapter], profile.min_version)
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
