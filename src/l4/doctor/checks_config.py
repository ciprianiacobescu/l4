"""CFG-005 (M1.8, A6): an explicitly set list that drops defaults.

CFG-002 (reduced): role chains reference defined profiles, the roles M0 runs (implementer, judges) are not empty,
and no profile has both adapter and backend. Registered at import. A typo or an empty chain would otherwise surface only
when the first agent is selected (`Factory.for_role` exits 12)."""

from l4.config import defaults as d
from l4.doctor.context import DoctorContext
from l4.doctor.registry import CONFIG_SCOPES, Check, CheckResult, register

REQUIRED_ROLES = ("implementer", "judges")


def _cfg_002(ctx: DoctorContext) -> CheckResult:
    problems = [
        f"roles.{role} names a profile that is not defined under profiles"
        for role, chain in ctx.cfg.roles
        if any(name not in ctx.cfg.profiles for name in chain)
    ]
    problems += [
        f"roles.{role} is empty; `l4 run` needs at least one profile there"
        for role in REQUIRED_ROLES
        if not getattr(ctx.cfg.roles, role)
    ]
    problems += [
        f"profiles.{name} sets both adapter and backend"
        for name, profile in ctx.cfg.profiles.items()
        if profile.adapter and profile.backend
    ]
    if problems:
        return CheckResult("fail", "; ".join(problems), "fix the paths named above in .l4/config.yaml")
    return CheckResult("pass", "role chains and profiles are consistent")


CFG_002 = register(Check("CFG-002", "Role chains reference existing profiles", "error", _cfg_002, CONFIG_SCOPES))


# (section, list key, its `extra_` key, the defaults): a list that is set replaces its defaults (L4-CFG-001)
_LISTS = (
    ("tdd", "test_globs", "extra_test_globs", d.TEST_GLOBS),
    ("tdd", "test_support_globs", "extra_test_support_globs", d.TEST_SUPPORT_GLOBS),
    ("odd", "forbidden_paths", "extra_forbidden_paths", d.FORBIDDEN_PATHS),
)
MAX_SHOWN = 4


def _cfg_005(ctx: DoctorContext) -> CheckResult:
    dropped: list[str] = []
    hints: list[str] = []
    for section, key, extra, defaults in _LISTS:
        model = getattr(ctx.cfg, section)
        if key not in model.model_fields_set:
            continue
        missing = [entry for entry in defaults if entry not in getattr(model, key)]
        if not missing:
            continue
        shown = ", ".join(missing[:MAX_SHOWN]) + (
            f" (+{len(missing) - MAX_SHOWN} more)" if len(missing) > MAX_SHOWN else ""
        )
        dropped.append(f"{section}.{key} drops {len(missing)} default(s): {shown}")
        hints.append(f"{section}.{extra}")
    if not dropped:
        return CheckResult("pass", "no explicitly set list drops a default")
    return CheckResult(
        "fail", "; ".join(dropped),
        f"to add entries instead of replacing the defaults, use {', '.join(hints)}; or list the dropped defaults too",
    )  # fmt: skip


CFG_005 = register(
    Check("CFG-005", "Explicit lists keep the defaults they replace", "warn", _cfg_005, scopes=CONFIG_SCOPES)
)
