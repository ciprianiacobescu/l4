"""SKL-003: an installed `l4` skill older than the running `l4` (L4-SKL-003). Registered at import (via
l4.doctor.run)."""

from pathlib import Path

from l4 import __version__, skills_cli
from l4.doctor.context import DoctorContext
from l4.doctor.registry import Check, CheckResult, register


def _skl_003(ctx: DoctorContext) -> CheckResult:
    home = Path(ctx.env["HOME"]) if ctx.env.get("HOME") else Path.home()
    root = ctx.repo if (ctx.repo / ".git").exists() else None  # project folders only inside a repository
    copies = skills_cli.installed_copies(home, root)
    if not copies:
        return CheckResult("skip", "no l4 skill installed by `l4 skills install`")
    old = [c for c in copies if skills_cli.compare(c.version) == "old"]
    if not old:
        return CheckResult("pass", f"{len(copies)} installed l4 skill(s), none older than l4 {__version__}")
    listed = "; ".join(f"{c.path} is {c.version or 'unknown'}" for c in old)
    return CheckResult(
        "fail",
        f"the installed l4 skill is older than l4 {__version__}: {listed}",
        "run `l4 skills install` (add --project for the copy in the repository)",
    )


SKL_003 = register(Check("SKL-003", "The installed l4 skill matches this l4", "warn", _skl_003))
