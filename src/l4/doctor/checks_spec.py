"""SPEC-001, SPEC-002 and SPEC-004: the spec frameworks of the repository and the Kiro units (L4-DET-001, L4-KSP-003).

Everything is read from files. SPEC-002 covers Kiro units only (OpenSpec's `validate --all` is M1: spec-providers 1.31
and SPEC-003, -005, -006, -007 with it). Spec Kit is named in SPEC-001's message and never driven.
"""

from l4.doctor.context import DoctorContext
from l4.doctor.registry import CONFIG_SCOPES, Check, CheckResult, register
from l4.implementer.prompt import PromptContext, render_prompt
from l4.implementer.tasks import select_next_step
from l4.implementer.unit_context import prompt_inputs
from l4.specs.base import Framework, SpecError, UnitRef
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


CUT_FIX = "shorten the file, or raise implementer.context_budget_tokens"
LINK_FIX = "add a `_Requirements: N.M_` line under each leaf, or tag the task with an exempt kind such as [docs]"


def _prompt_cuts(ctx: DoctorContext, provider: KiroProvider, units: list[UnitRef]) -> list[str]:
    """For each unit with a pending task, what the next task's prompt would cut (L4-IMP-054): the prompt's context is
    planned by the builder of the run, with no changed files and the head implementer profile."""
    names = ctx.cfg.roles.implementer
    head = (names[0], ctx.cfg.profiles[names[0]]) if names and names[0] in ctx.cfg.profiles else (None, None)
    found = []
    for unit in units:
        try:
            tasks = provider.tasks(unit)
            task = select_next_step(tasks)
            if task is None:
                continue
            inputs = prompt_inputs(
                root=ctx.repo, provider=provider, ref=unit, task=task, tasks=tasks, changed=[], cfg=ctx.cfg,
                profile_name=head[0], profile=head[1],
            )  # fmt: skip
            rendered = render_prompt(
                "red",
                PromptContext(
                    unit_id=unit.id,
                    adapter="",
                    task_key=task.key,
                    task_title=task.title,
                    task_links=task.links,
                    criteria=inputs.criteria,
                    own_criteria=inputs.own_criteria,
                    source_files=inputs.source_files,
                    conventions=inputs.conventions,
                    task_block=inputs.task_block,
                    unit_rel=inputs.unit_rel,
                    context_budget_tokens=inputs.budget_tokens,
                ),
            )
        except (SpecError, OSError, ValueError):  # SPEC-002 reports an unreadable unit
            continue
        for cut in rendered.cuts:
            where = cut.path.removeprefix(f"{inputs.unit_rel}/")
            if cut.reason in ("symlink", "not_regular"):
                found.append(f"{unit.id} task {task.key}: {where} not read ({cut.reason})")
            elif cut.reason == "oversize":
                found.append(f"{unit.id} task {task.key}: {where} {cut.total_bytes} bytes, the first part read")
            else:
                found.append(
                    f"{unit.id} task {task.key}: {where} {cut.shown_chars} of {cut.total_chars} characters shown"
                )
    return found


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
    cuts = _prompt_cuts(ctx, provider, units)
    if loose or cuts:
        message = "; ".join(
            [
                *(["leaves without `_Requirements:_`: " + _shown(loose)] if loose else []),
                *([_shown(cuts)] if cuts else []),
            ]
        )
        fix = "; ".join([*([LINK_FIX] if loose else []), *([CUT_FIX] if cuts else [])])
        return CheckResult("fail", message, fix)
    return CheckResult("pass", f"{len(units)} Kiro unit(s): every leaf cites a requirement")


SPEC_001 = register(Check("SPEC-001", "A supported spec framework", "error", _spec_001, CONFIG_SCOPES))
SPEC_002 = register(Check("SPEC-002", "Kiro units validate", "error", _spec_002, CONFIG_SCOPES, unit_aware=True))
SPEC_004 = register(
    Check("SPEC-004", "Kiro leaves cite requirements", "warn", _spec_004, CONFIG_SCOPES, unit_aware=True)
)
