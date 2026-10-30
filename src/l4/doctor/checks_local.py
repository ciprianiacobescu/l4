"""LOCAL-001 (SPEC L4-SEC-041, local-doctor): a person's own computer cannot sandbox, so `l4 run` and `l4 verify`
will refuse here. Registered at import, in the `local` scope only: `l4 doctor --ci` never runs it, so it never changes
a CI job's exit code, and it is a warning, so it never changes the exit code of `l4 doctor` either.

It asks the preflight the commands ask (`l4.sandbox.select.sandbox_refusal`), with the doctor's own runner, so the
row and the refusal cannot disagree. SANDBOX-001 (the full credential and isolation probe of L4-SEC-005) is a separate
change and stays unregistered; this row does less and has its own id.
"""

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from l4.doctor.context import CmdResult, DoctorContext
from l4.doctor.registry import Check, CheckResult, register
from l4.exitcodes import L4Exit
from l4.sandbox.select import sandbox_refusal

REFUSES = "l4 run/l4 verify will refuse on this computer: "
NOT_BUILT = ("user", "container")  # `select_sandbox` exits 2 for these; the row says so instead of crashing


def _local_001(ctx: DoctorContext, platform: str | None = None) -> CheckResult:
    """`platform` is for tests; it defaults to this machine's, as in `sandbox_refusal`."""
    sandbox = ctx.cfg.sandbox
    if sandbox.mode in NOT_BUILT:
        return CheckResult(
            "fail", f"{REFUSES}sandbox.mode: {sandbox.mode} is not built yet", "use sandbox.mode: auto or bwrap"
        )

    def runner(argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: float) -> CmdResult:
        return ctx.run(argv, timeout=timeout, env=env)  # the doctor's seam; the preflight's own timeout stays

    try:
        reason = sandbox_refusal(
            sandbox, ctx.env, ctx.repo, platform or sys.platform, command="l4 run/l4 verify", runner=runner
        )
    except L4Exit as exc:  # a bwrap inside the repository
        reason = str(exc)
    if reason:
        return CheckResult("fail", REFUSES + reason)
    if sandbox.mode == "none":
        return CheckResult("pass", "sandbox.mode: none with allow_none: a run would use no sandbox (none)")
    return CheckResult("pass", "a run would use the bwrap sandbox (bwrap)")


LOCAL_001 = register(Check("LOCAL-001", "A local run can sandbox", "warn", _local_001, frozenset({"local"})))
