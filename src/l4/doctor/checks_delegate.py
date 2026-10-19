"""DLG-001 and DLG-002 (delegate-answers L4-DLG-012; SCN-DLG-33, SCN-DLG-34, SCN-DLG-34a): the delegate's configuration
is sound and a delegate profile is usable. Both pass silently while `delegate.enabled` is false. `--live` adds the
`hello` of the delegate chain to LIVE-001 (checks_agents), at warn weight. Registered at import (via
`l4.doctor.registry.CHECK_MODULES`)."""

from pathlib import Path

from l4.agents.base import ProbeCtx
from l4.agents.factory import Factory
from l4.config.schema import DELEGATE_KINDS, L4Config, duration_seconds
from l4.delegate.independence import DELEGATE_SERVES, Asker, delegate_constraint
from l4.doctor.checks_agents import scratch_dir
from l4.doctor.context import DoctorContext
from l4.doctor.registry import CONFIG_SCOPES, DEFAULT_SCOPES, Check, CheckResult, register
from l4.exitcodes import L4Exit
from l4.proc import run_process

OFF = "the delegate is off (delegate.enabled is false)"
ADAPTERS_THAT_SERVE = ("claude-code", "codex")  # the adapters whose read-only tool mode L4 defines (design D2)
# a role of `roles` whose profiles ask or judge the questions the delegate answers: (role, what it is called, the
# questions of its that would escalate)
MINDS = (("implementer", "implementer"), ("judges", "judge"))
MAX_LISTED = 6


def _listed(problems: list[str]) -> str:
    more = f" (+{len(problems) - MAX_LISTED} more)" if len(problems) > MAX_LISTED else ""
    return "; ".join(problems[:MAX_LISTED]) + more


def _shape_problems(cfg: L4Config) -> tuple[list[str], list[str]]:
    """What is wrong with the chain and the settings, and the chain's profiles that can serve the role."""
    problems: list[str] = []
    chain = cfg.roles.delegate
    if not chain:
        problems.append("roles.delegate is empty (name at least one claude-code or codex profile)")
    serving: list[str] = []
    for name in chain:
        profile = cfg.profiles.get(name)
        if profile is None:
            problems.append(f"roles.delegate names {name}, which is not defined under profiles")
        elif profile.adapter not in ADAPTERS_THAT_SERVE:
            what = f"a {profile.adapter} profile" if profile.adapter else "a backend profile"
            problems.append(f"profile {name} is {what}; only claude-code and codex profiles serve the delegate")
        else:
            serving.append(name)
    settings = cfg.delegate
    if not settings.kinds:
        problems.append("delegate.kinds is empty (name the kinds of question it may answer)")
    problems += [
        f"delegate.kinds names {kind}, which is not a question kind"
        for kind in settings.kinds
        if kind not in DELEGATE_KINDS
    ]
    limits = {
        "max_attempts_per_question": settings.max_attempts_per_question,
        "max_answers_per_task": settings.max_answers_per_task,
        "max_questions_per_run": settings.max_questions_per_run,
        "max_cost_usd_per_answer": settings.max_cost_usd_per_answer,
        "max_cost_usd_per_unit": settings.max_cost_usd_per_unit,
        "plan_cost_share": settings.plan_cost_share,
    }
    problems += [f"delegate.{key} must be positive" for key, value in limits.items() if value <= 0]
    problems += _budget_problems(cfg)
    if settings.independence == "model":
        problems += [
            f"profile {name} has no model (delegate.independence: model cannot show it is not the asker's model)"
            for name in serving
            if not cfg.profiles[name].model
        ]
    return problems, serving


def _budget_problems(cfg: L4Config) -> list[str]:
    """A call that cannot finish before the soft deadline is deferred, and every pass would defer it (review F1): the
    budget known here must leave room for one call. `auto` is the runner's, which this check cannot see."""
    ci = cfg.ci
    if ci.time_budget == "auto":
        return []
    room = duration_seconds(ci.time_budget) - duration_seconds(ci.soft_deadline_margin)
    if duration_seconds(cfg.delegate.timeout) < room:
        return []
    return [
        f"delegate.timeout ({cfg.delegate.timeout}) is not less than ci.time_budget ({ci.time_budget}) minus "
        f"ci.soft_deadline_margin ({ci.soft_deadline_margin}): no delegate call would fit before the soft deadline"
    ]


def _independence_problems(cfg: L4Config, serving: list[str]) -> list[str]:
    """Every implementer and judge profile needs a delegate profile that is not it (by `delegate.independence`): else
    the questions it raises escalate to a person, and `merge: auto` waits on them."""
    problems: list[str] = []
    for role, noun in MINDS:
        for name in dict.fromkeys(getattr(cfg.roles, role)):
            mind = cfg.profiles.get(name)
            if mind is None:
                continue  # CFG-002 names a profile that does not exist
            if cfg.delegate.independence == "model" and not mind.model:
                problems.append(
                    f"{noun} profile {name} has no model: the delegate cannot be shown to be another model than it"
                )
                continue
            asker = Asker(name, mind.model, "judged" if noun == "judge" else "asked")
            check = delegate_constraint((asker,), cfg.delegate.independence, profiles=cfg.profiles)
            if any(check(candidate, cfg.profiles[candidate]) is None for candidate in serving):
                continue
            model = f" ({mind.model})" if mind.model else ""
            questions = "verdict" if noun == "judge" else "technical, product, ambiguous and harness"
            problems.append(
                f"no delegate profile is independent of {noun} profile {name}{model}: its {questions} questions "
                "would escalate"
            )
    if not problems:
        problems += _joint_problems(cfg, serving)
    return problems


def _joint_problems(cfg: L4Config, serving: list[str]) -> list[str]:
    """A verdict question has the judges AND the implementers as askers (F9): one profile must be independent of all of
    them at once, or every verdict question escalates."""
    judges = list(dict.fromkeys(n for n in cfg.roles.judges if n in cfg.profiles))
    coders = list(dict.fromkeys(n for n in cfg.roles.implementer if n in cfg.profiles))
    if not judges or not coders:
        return []
    found = tuple(
        [Asker(n, cfg.profiles[n].model, "judged") for n in judges]
        + [Asker(n, cfg.profiles[n].model, "asked") for n in coders]
    )
    check = delegate_constraint(found, cfg.delegate.independence, profiles=cfg.profiles)
    if any(check(candidate, cfg.profiles[candidate]) is None for candidate in serving):
        return []
    return [
        f"no delegate profile is independent of both the judges ({', '.join(judges)}) and the implementers "
        f"({', '.join(coders)}): its verdict questions would escalate"
    ]


def _dlg_001(ctx: DoctorContext) -> CheckResult:
    cfg = ctx.cfg
    if not cfg.delegate.enabled:
        return CheckResult("pass", OFF)
    problems, serving = _shape_problems(cfg)
    problems += _independence_problems(cfg, serving) if serving else []
    if problems:
        return CheckResult(
            "fail",
            _listed(problems),
            "name a claude-code or codex profile on another model than the implementers and judges under "
            "roles.delegate (for example delegate-sol), or set delegate.independence: profile",
        )
    return CheckResult(
        "pass", f"roles.delegate: {', '.join(serving)}; every implementer and judge has an independent one"
    )


DLG_001 = register(Check("DLG-001", "The delegate is configured and independent", "error", _dlg_001, CONFIG_SCOPES))


def _without_hello(cfg: L4Config) -> L4Config:
    """The configuration with the probe ladder that spends no tokens: `--live` spends the `hello` (LIVE-001)."""
    ladder = [step for step in cfg.availability.default_ladder if step != "hello"]
    return cfg.model_copy(update={"availability": cfg.availability.model_copy(update={"default_ladder": ladder})})


def _alias_notes(cfg: L4Config) -> list[str]:
    """Profiles of the delegate, the implementers and the judges whose `model` has no digit (`opus`, `sonnet`): an alias
    the CLI resolves to a full id the configuration never names, so `independence: model` cannot be shown from the
    configuration alone (the model a step reports is what counts, D3)."""
    if cfg.delegate.independence != "model":
        return []
    names = dict.fromkeys([*cfg.roles.delegate, *cfg.roles.implementer, *cfg.roles.judges])
    return [
        f"profile {name} (model {profile.model})"
        for name in names
        if (profile := cfg.profiles.get(name)) is not None
        and profile.model
        and not any(ch.isdigit() for ch in profile.model)
    ]


def _dlg_002(ctx: DoctorContext) -> CheckResult:
    cfg = ctx.cfg
    if not cfg.delegate.enabled:
        return CheckResult("pass", OFF)
    if not cfg.roles.delegate:
        return CheckResult("fail", "roles.delegate is empty: no delegate profile can be used", "see DLG-001")
    with scratch_dir(ctx.repo) as scratch:
        probe_ctx = ProbeCtx(environ=ctx.env, cwd=Path(scratch), run=run_process, forbid=(ctx.repo,))
        try:
            picked = Factory(_without_hello(cfg), probe_ctx).for_role("delegate", "doctor", serves=DELEGATE_SERVES)
        except L4Exit as exc:
            return CheckResult(
                "fail",
                str(exc),
                "log in or install the CLI as the runner user (docs/runner/README.md); until then the delegate "
                "escalates its questions to a person",
            )
    if aliases := _alias_notes(cfg):
        return CheckResult(
            "fail",
            f"delegate profile {picked.profile_name} is usable, but {', '.join(aliases)} is a model alias: the served "
            "model can be another than the configured one, and delegate.independence: model compares full ids",
            "set the model to a full model id (for example claude-opus-5-5), or delegate.independence: profile",
        )
    return CheckResult("pass", f"delegate profile {picked.profile_name} is usable (binary, auth and quota)")


DLG_002 = register(Check("DLG-002", "A delegate profile is usable now", "warn", _dlg_002, DEFAULT_SCOPES))

__all__ = ["DLG_001", "DLG_002"]
