"""YOLO-001 (yolo-mode L4-YOLO-008, SCN-YOLO-17): `forge.merge_policy: auto` merges nothing unless a plan with
`merge: auto` is active, so without one the setting has no effect. A warning, never an error. It reads the plan refs
this checkout already has (`l4.yolo.commands.auto_merge_plan_active`): no network. Registered at import (via
`l4.doctor.registry.CHECK_MODULES`)."""

from l4.doctor.context import DoctorContext
from l4.doctor.registry import CONFIG_SCOPES, Check, CheckResult, register
from l4.exitcodes import L4Exit
from l4.vcs.errors import GitError
from l4.vcs.git import Git

MESSAGE = "forge.merge_policy: auto has no effect without an active plan with merge: auto (L4-YOLO-008)"


def _yolo_001(ctx: DoctorContext) -> CheckResult:
    if ctx.cfg.forge.merge_policy != "auto":
        return CheckResult("skip", "forge.merge_policy is human")
    from l4.yolo.commands import auto_merge_plan_active  # here: the plan commands import much of the harness

    try:
        active = auto_merge_plan_active(ctx.repo, Git(ctx.repo, environ=ctx.env))
    except (GitError, L4Exit):
        active = False  # no git, not a repository, or refs that cannot be read (ENV rows say so): the warning stands
    if active:
        return CheckResult("pass", "a plan with merge: auto is active")
    return CheckResult(
        "fail",
        MESSAGE,
        "activate a plan with merge: auto (l4 yolo activate), or set forge.merge_policy: human",
    )


YOLO_001 = register(Check("YOLO-001", "merge_policy: auto has a plan that uses it", "warn", _yolo_001, CONFIG_SCOPES))
