"""SPEC-001, SPEC-002 and SPEC-004: the spec frameworks of the repository and the Kiro units (L4-DET-001, L4-KSP-003).

Everything is read from files. SPEC-002 covers Kiro units only (OpenSpec's `validate --all` is M1: spec-providers 1.31
and SPEC-003, -005, -006, -007 with it). Spec Kit is named in SPEC-001's message and never driven.
"""

from l4.doctor.context import DoctorContext
from l4.doctor.registry import CONFIG_SCOPES, Check, CheckResult, register
from l4.implementer.prompt import WINDOW_SHARE, PromptContext, render_prompt
from l4.implementer.tasks import select_next_step
from l4.implementer.unit_context import (
    NOT_READ,
    budget_advice,
    effective_budget,
    model_window,
    prompt_inputs,
    safe_label,
)
from l4.specs.base import Framework, SpecError, SpecProvider, UnitRef
from l4.specs.detect import active_frameworks, detect_for
from l4.specs.kiro import KiroProvider
from l4.specs.providers import providers_for

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


LINK_FIX = "add a `_Requirements: N.M_` line under each leaf, or tag the task with an exempt kind such as [docs]"
WINDOW_FIX = "lower the budget, or state a larger context_window for the profile"


def _units(ctx: DoctorContext) -> list[tuple[SpecProvider, UnitRef]]:
    """Every unit of every active framework (OpenSpec too, L4-IMP-054), or the `--unit` one."""
    try:
        providers = providers_for(ctx.cfg, ctx.repo, ctx.env)
        pairs = [(p, u) for p in providers for u in p.list_units()]
    except (SpecError, OSError):
        return []
    return [(p, u) for p, u in pairs if ctx.unit is None or u.id == ctx.unit]


def _prompt_cuts(ctx: DoctorContext) -> tuple[list[str], list[str], list[str]]:
    """(what the next task's prompt of each unit would cut, the advice for it): L4-IMP-054. The prompt's context is
    planned by the builder of the run, with no changed files and the head implementer profile."""
    names = ctx.cfg.roles.implementer
    head = (names[0], ctx.cfg.profiles[names[0]]) if names and names[0] in ctx.cfg.profiles else (None, None)
    found, advice, over = [], [], []
    for provider, unit in _units(ctx):
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
                    max_criteria_per_test=ctx.cfg.verifier.max_criteria_per_test,
                    source_files=inputs.source_files,
                    conventions=inputs.conventions,
                    task_block=inputs.task_block,
                    unit_rel=inputs.unit_rel,
                    context_budget_tokens=inputs.budget_tokens,
                    budget_source=inputs.budget_source,
                    window_tokens=inputs.window_tokens,
                ),
            )
        except (SpecError, OSError, ValueError):  # SPEC-002 reports an unreadable unit
            continue
        if rendered.over_window:
            over.append(
                f"{unit.id} task {safe_label(task.key)}: the criteria, the task and the contract alone exceed 60% of "
                f"the model window of profile {safe_label(head[0] or '?')}"
            )
        for cut in rendered.cuts:
            where = safe_label(cut.path.removeprefix(f"{inputs.unit_rel}/"))
            who = f"{unit.id} task {safe_label(task.key)}: {where}"
            if cut.reason in NOT_READ:
                found.append(f"{who} not read ({cut.reason})")
            elif cut.reason == "oversize":
                found.append(f"{who} {cut.total_bytes} bytes, the first part read")
            else:
                found.append(f"{who} {cut.shown_chars} of {cut.total_chars} characters shown")
            if (text := _fix_for(rendered.budget_source)) not in advice:
                advice.append(text)
    return found, advice, over


def _fix_for(source: str) -> str:
    """SCN-IMP-289's fix text, naming the key that set the budget."""
    if source == "implementer":
        return "shorten the file, or raise implementer.context_budget_tokens"
    if source.startswith("profile:"):
        return (
            f"shorten the file, or raise profiles.{safe_label(source.removeprefix('profile:'))}.context_budget_tokens"
        )
    return budget_advice(source)


def _window_warnings(ctx: DoctorContext) -> list[str]:
    """A configured budget above 60 % of its profile's stated model window: `render_prompt` caps it at run time."""
    found = []
    for name in ctx.cfg.roles.implementer:
        profile = ctx.cfg.profiles.get(name)
        window = model_window(profile)
        if profile is None or window is None:
            continue
        budget, _ = effective_budget(ctx.cfg, name, profile)
        if budget > int(window * WINDOW_SHARE):
            found.append(
                f"profile {safe_label(name)}: context_budget_tokens {budget} exceeds 60% of its model window "
                f"({window} tokens)"
            )
    return found


def _spec_004(ctx: DoctorContext) -> CheckResult:
    kiro = _kiro_units(ctx)
    loose: list[str] = []
    if not isinstance(kiro, CheckResult):
        provider, kiro_units = kiro
        loose = [
            f"{unit.id}: {', '.join(t.key for t in tasks)}"
            for unit in kiro_units
            if (tasks := provider.leaves_without_requirements(unit))
        ]
    cuts, advice, over = _prompt_cuts(ctx)
    windows = [*_window_warnings(ctx), *over]
    if isinstance(kiro, CheckResult) and not cuts and not windows:
        return kiro  # no Kiro unit to look at, and nothing cut elsewhere
    if loose or cuts or windows:
        message = "; ".join(
            [
                *(["leaves without `_Requirements:_`: " + _shown(loose)] if loose else []),
                *([_shown(cuts)] if cuts else []),
                *windows,
            ]
        )
        fix = "; ".join([*([LINK_FIX] if loose else []), *advice, *([WINDOW_FIX] if windows else [])])
        return CheckResult("fail", message, fix)
    return CheckResult("pass", f"{len(kiro[1])} Kiro unit(s): every leaf cites a requirement")  # type: ignore[index]


SPEC_001 = register(Check("SPEC-001", "A supported spec framework", "error", _spec_001, CONFIG_SCOPES))
SPEC_002 = register(Check("SPEC-002", "Kiro units validate", "error", _spec_002, CONFIG_SCOPES, unit_aware=True))
SPEC_004 = register(
    Check("SPEC-004", "Kiro leaves cite requirements", "warn", _spec_004, CONFIG_SCOPES, unit_aware=True)
)
