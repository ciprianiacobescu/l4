"""SPEC-001, SPEC-002 and SPEC-004: the spec frameworks of the repository and the Kiro units (L4-DET-001, L4-KSP-003).

Everything is read from files. SPEC-002 covers Kiro units only (OpenSpec's `validate --all` is M1: spec-providers 1.31
and SPEC-003, -005, -006, -007 with it). Spec Kit is named in SPEC-001's message and never driven.
"""

from l4.doctor.context import DoctorContext
from l4.doctor.registry import CONFIG_SCOPES, Check, CheckResult, register
from l4.specs.base import Framework, UnitRef
from l4.specs.detect import active_frameworks, detect_for
from l4.specs.kiro import KiroProvider

MAX_LISTED = 5
SPECKIT_NOTE = "Spec Kit: detected, not driven"


def _kiro(ctx: DoctorContext) -> KiroProvider | None:
    if Framework.KIRO not in active_frameworks(ctx.cfg, ctx.repo):
        return None
    cfg = ctx.cfg
    return KiroProvider(
        ctx.repo, root=cfg.spec.kiro.root, enforce=cfg.sdd.enforce, exempt_kinds=cfg.tdd.exempt_task_kinds
    )


def _kiro_units(ctx: DoctorContext) -> tuple[KiroProvider, list[UnitRef]] | CheckResult:
    """The Kiro units to look at: all of them, or the `--unit` one. A skip when there is nothing to look at."""
    provider = _kiro(ctx)
    if provider is None:
        return CheckResult("skip", "Kiro is not active in this repository")
    units = provider.list_units()
    if ctx.unit is not None:
        units = [u for u in units if u.id == ctx.unit]
        if not units:
            return CheckResult("skip", f"{ctx.unit} is not a Kiro unit")
    return provider, units


def _shown(items: list[str]) -> str:
    return "; ".join(items[:MAX_LISTED]) + (f" (+{len(items) - MAX_LISTED} more)" if len(items) > MAX_LISTED else "")


def _spec_001(ctx: DoctorContext) -> CheckResult:
    found = detect_for(ctx.cfg, ctx.repo)
    active = active_frameworks(ctx.cfg, ctx.repo)
    notes = [SPECKIT_NOTE] if found.speckit else []
    if found.legacy_openspec:
        return CheckResult(
            "fail", "; ".join(["OpenSpec < 1.0 layout; run the OpenSpec migration", *notes]),
            "migrate with the OpenSpec CLI (`openspec migrate`)",
        )  # fmt: skip
    if not active:
        message = "; ".join(["no spec framework (OpenSpec or Kiro) was found", *notes])
        return CheckResult("fail", message, "run `l4 init` or create a spec under .kiro/specs/<name>/")
    return CheckResult("pass", "; ".join([", ".join(f.value for f in active), *notes]))


def _spec_002(ctx: DoctorContext) -> CheckResult:
    picked = _kiro_units(ctx)
    if isinstance(picked, CheckResult):
        return picked
    provider, units = picked
    errors = []
    for unit in units:
        for issue in provider.validate(unit).issues:
            if issue.level == "ERROR":
                where = f"{issue.path}:{issue.line}" if issue.line else issue.path
                errors.append(f"{unit.id} {where}: {issue.message}")
    if errors:
        return CheckResult("fail", _shown(errors), "fix the Kiro spec files named above")
    return CheckResult("pass", f"{len(units)} Kiro unit(s) validate")


def _spec_004(ctx: DoctorContext) -> CheckResult:
    picked = _kiro_units(ctx)
    if isinstance(picked, CheckResult):
        return picked
    provider, units = picked
    loose = [
        f"{unit.id}: {', '.join(t.key for t in tasks)}"
        for unit in units
        if (tasks := provider.leaves_without_requirements(unit))
    ]
    if loose:
        return CheckResult(
            "fail", "leaves without `_Requirements:_`: " + _shown(loose),
            "add a `_Requirements: N.M_` line under each leaf, or tag the task with an exempt kind such as [docs]",
        )  # fmt: skip
    return CheckResult("pass", f"{len(units)} Kiro unit(s): every leaf cites a requirement")


SPEC_001 = register(Check("SPEC-001", "A supported spec framework", "error", _spec_001, CONFIG_SCOPES))
SPEC_002 = register(Check("SPEC-002", "Kiro units validate", "error", _spec_002, CONFIG_SCOPES, unit_aware=True))
SPEC_004 = register(
    Check("SPEC-004", "Kiro leaves cite requirements", "warn", _spec_004, CONFIG_SCOPES, unit_aware=True)
)
