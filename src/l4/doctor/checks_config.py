"""CFG-006 and CFG-007 (adoption-kit L4-ACT-004): the pin of an action-form workflow, and the local `l4`.

CFG-008 (adoption-lessons L4-ADO-005): the harness running in CI is the pin of the base's workflow.

CFG-012 (budget-guard L4-IMP-076, L4-IMP-077): a set `ci.time_budget` leaves room for one step after the margin, and
does not shorten the job by more than the margin.

CFG-004: `gates.test.command` is set. The run rejects every unit without it (no test oracle), so nothing else in
the configuration matters until it is.

CFG-005 (M1.8, A6): an explicitly set list that drops defaults.

CFG-002 (reduced): role chains reference defined profiles, the roles M0 runs (implementer, judges) are not empty,
and no profile has both adapter and backend. Registered at import. A typo or an empty chain would otherwise surface only
when the first agent is selected (`Factory.for_role` exits 12)."""

import re

from l4.buildinfo import harness_commit
from l4.ci.budget import job_timeout, read_workflow, shortens_job, too_short
from l4.ci.github import ACTION_PATH, WORKFLOW_RELPATH
from l4.ci.pin_guard import FIX, pin_check
from l4.config import defaults as d
from l4.config.schema import duration_seconds, effective_delivery
from l4.doctor.context import DoctorContext
from l4.doctor.registry import CONFIG_SCOPES, Check, CheckResult, register
from l4.init.action import read_pin

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
    ("tdd", "gate_config_globs", "extra_gate_config_globs", d.GATE_CONFIG_GLOBS),
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


def _cfg_004(ctx: DoctorContext) -> CheckResult:
    if ctx.cfg.gates.test.command.strip():
        return CheckResult("pass", "gates.test.command is set")
    return CheckResult(
        "fail",
        "gates.test.command is empty: every unit is rejected at run time (there is no test oracle)",
        "set gates.test.command in .l4/config.yaml, for example `pytest -q`",
    )


CFG_004 = register(Check("CFG-004", "gates.test.command is set", "error", _cfg_004, scopes=CONFIG_SCOPES))


_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_ACTION_FILE = f"{ACTION_PATH}/action.yml"
_PIN_HINT = "pin it with `l4 upgrade --harness-ref REF` (or `--harness-commit SHA`), which writes `@<sha> # <REF>`"


def _cfg_006(ctx: DoctorContext) -> CheckResult:
    """In action mode the workflow's `uses:` names a 40-hex sha and is the only pin. With a copy of the action
    (`uses: ./.github/actions/l4`) the `commit` input is the pin and must be 40 hex too; when a published action is
    also given `commit`, the two must be one sha (SCN-ACT-09)."""
    if effective_delivery(ctx.cfg) != "action":
        return CheckResult("skip", f"harness.delivery is {effective_delivery(ctx.cfg)}, not action")
    try:
        text = (ctx.repo / WORKFLOW_RELPATH).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return CheckResult("fail", f"{WORKFLOW_RELPATH} cannot be read", "run `l4 init --ci github --action --force`")
    found = read_pin(text)
    if found is None:
        return CheckResult(
            "fail",
            f"{WORKFLOW_RELPATH} has no step that uses {ACTION_PATH}",
            "run `l4 init --ci github --action --force`, or restore the step",
        )
    if found.local:
        commit = found.inputs.get("commit")
        if not isinstance(commit, str) or not _FULL_SHA.match(commit):
            return CheckResult(
                "fail",
                f"the copy of the action ({found.uses}) is pinned by its `commit` input, which is {commit!r}, "
                "not a full commit sha (40 lowercase hex digits)",
                _PIN_HINT,
            )
        if not (ctx.repo / _ACTION_FILE).is_file():
            return CheckResult("fail", f"{WORKFLOW_RELPATH} uses the copy {found.uses}, but {_ACTION_FILE} is missing")
        return CheckResult("pass", f"the copy of the action fetches the harness at {commit[:12]}")
    assert found.pin is not None
    if not _FULL_SHA.match(found.pin):
        return CheckResult(
            "fail",
            f"`uses: {found.uses}` is pinned to {found.pin!r}, not a full commit sha (40 lowercase hex digits): "
            "a tag or branch moves under the workflow",
            _PIN_HINT,
        )
    commit = found.inputs.get("commit")
    if found.inputs.get("source") == "repository" and commit is not None and commit != found.pin:
        return CheckResult(
            "fail",
            f"`uses:` names {found.pin} but the `commit` input is {commit}: the action and the harness it installs "
            "must be one commit",
            _PIN_HINT,
        )
    return CheckResult("pass", f"the setup action is pinned at {found.pin[:12]}")


CFG_006 = register(Check("CFG-006", "The action pin is a full commit sha", "error", _cfg_006, CONFIG_SCOPES))


def _cfg_007(ctx: DoctorContext) -> CheckResult:
    """Without `.l4/bin/l4` a local `l4` is whatever the person installed: say whether there is one."""
    if effective_delivery(ctx.cfg) != "action" or (ctx.repo / ".l4" / "bin" / "l4").exists():
        return CheckResult("skip", "not an action adoption without a shim")
    found = ctx.which("l4")
    if found:
        return CheckResult("pass", f"l4 on PATH: {found}")
    return CheckResult(
        "fail",
        "no .l4/bin/l4 and no l4 on PATH: only CI (through the setup action) can run the harness here",
        "install one: `uv tool install git+https://github.com/OWNER/REPO@<the sha of the uses: line>`",
    )


CFG_007 = register(Check("CFG-007", "A local l4 is on PATH (action adoption)", "info", _cfg_007, scopes=CONFIG_SCOPES))


def _cfg_008(ctx: DoctorContext) -> CheckResult:
    """In a CI job with `harness.delivery: action`, the harness that is running (`L4_HARNESS_COMMIT`, or the commit it
    was installed from) is the pin of `.github/workflows/l4.yml` on the checked-out base. A schedule runs the default
    branch's copy, so a base that moved on leaves a cron run on the old harness (L4-ADO-005); `l4 plan --sweep` and
    `l4 run` then do no work (`l4.ci.pin_guard`). A warning: the pin itself is CFG-006's."""
    check = pin_check(ctx.cfg, ctx.repo, ctx.env, harness_commit())
    if check.status == "mismatch":
        return CheckResult("fail", check.problem, FIX)
    return CheckResult(check.status, check.reason)


CFG_008 = register(
    Check("CFG-008", "The running harness is the base's pin", "warn", _cfg_008, scopes=frozenset({"ci"}))
)


def _cfg_009(ctx: DoctorContext) -> CheckResult:
    """An escalation that cannot act (escalate-and-note L4-IMP-018): `escalate_after` that is neither 0 nor below
    `max_task_attempts` on a chain of two or more profiles never moves a task, and two profiles with one adapter and one
    model are one model under two names. A chain of one profile passes."""
    chain = list(ctx.cfg.roles.implementer)
    if len(chain) < 2:
        return CheckResult("pass", "one implementer profile: a task that fails stays on it")
    impl = ctx.cfg.implementer
    problems: list[str] = []
    if impl.escalate_after != 0 and impl.escalate_after >= impl.max_task_attempts:
        problems.append(
            f"implementer.escalate_after ({impl.escalate_after}) is not below implementer.max_task_attempts "
            f"({impl.max_task_attempts}): no task moves to {chain[1]}"
        )
    seen: dict[tuple[str, str], str] = {}
    for name in chain:
        profile = ctx.cfg.profiles.get(name)
        if profile is None or not profile.adapter or not profile.model:
            continue
        key = (profile.adapter, profile.model)
        if key in seen:
            problems.append(
                f"profiles {seen[key]} and {name} run the same model ({profile.model}): "
                f"a move from {seen[key]} to {name} changes nothing"
            )
        else:
            seen[key] = name
    if problems:
        return CheckResult(
            "fail",
            "; ".join(problems),
            "set implementer.escalate_after below max_task_attempts, or 0 when you do not want escalation",
        )
    return CheckResult("pass", "the implementer chain can escalate")


CFG_009 = register(Check("CFG-009", "The implementer escalation can act", "warn", _cfg_009, scopes=CONFIG_SCOPES))


def _cfg_010(ctx: DoctorContext) -> CheckResult:
    """Shows `verifier.test_awareness_allow`: the production paths where code may name the test run. The verifier reads
    the key at the base branch, never from a unit's head (L4-VER-039)."""
    globs = ctx.cfg.verifier.test_awareness_allow
    if not globs:
        return CheckResult("pass", "verifier.test_awareness_allow is empty: no production path may name the test run")
    return CheckResult("pass", f"verifier.test_awareness_allow (read at the base branch): {', '.join(globs)}")


CFG_010 = register(
    Check("CFG-010", "Production paths that may name the test run", "info", _cfg_010, scopes=CONFIG_SCOPES)
)


KIRO_JUDGE_MIN_VERSION = "2.32.0"
_KIRO_LINE = "tool-less harness agent, prompt on stdin, no trust flag"


def _cfg_011(ctx: DoctorContext) -> CheckResult:
    """kiro-cli judge and clarifier profiles (kiro-judge L4-KJD-009, D9). A profile on `auto` passes, naming the vendors
    Kiro may route it to and where that set comes from; options.agent and a min_version below 2.32.0 warn; a `vendor:`
    on an `auto` profile of any role is noted as ignored, never failing."""
    from l4.agents.factory import recorded_routed
    from l4.availability.cooldown import AvailabilityStore
    from l4.availability.vendor import built_in_routed, is_routed, resolve_vendor
    from l4.config.defaults import cache_root
    from l4.versions import version_at_least

    profiles = ctx.cfg.profiles
    judging: list[str] = []
    for name in [*ctx.cfg.roles.judges, *ctx.cfg.roles.clarifier]:
        profile = profiles.get(name)
        if profile is not None and profile.adapter == "kiro-cli" and name not in judging:
            judging.append(name)
    store = AvailabilityStore(cache_root(ctx.env, repo=ctx.repo))
    lines: list[str] = []
    warnings: list[str] = []
    for name in judging:
        profile = profiles[name]
        if is_routed(profile):
            found = recorded_routed(store, name)
            routed = found[0] if found else built_in_routed(name, profile)
            if found and routed.source == "listed":
                source = f"listed {found[1].date().isoformat()}"
            else:  # doctor runs before any probe on a fresh runner: say so, or `built-in` reads as a failed listing
                source = "built-in" if found else "built-in (no listing recorded yet)"
            lines.append(
                f"{name}: {_KIRO_LINE}, model auto, routed to {', '.join(routed.vendors)} ({source}); "
                "a pinned model makes the served model checkable"
            )
        else:
            vendor, _ = resolve_vendor(profile)
            lines.append(f"{name}: {_KIRO_LINE}, model {profile.model} ({vendor or 'unknown'})")
        if profile.options.get("agent"):
            warnings.append(f"{name}: a judge always runs the harness's tool-less agent; options.agent is ignored here")
        if profile.min_version is None or version_at_least(profile.min_version, KIRO_JUDGE_MIN_VERSION) is not True:
            warnings.append(f"{name}: the judge invocation was measured on kiro-cli {KIRO_JUDGE_MIN_VERSION}")
    notes: list[str] = []
    seen: set[str] = set()
    for role in type(ctx.cfg.roles).model_fields:
        for name in getattr(ctx.cfg.roles, role):
            profile = profiles.get(name)
            if name in seen or profile is None or profile.adapter != "kiro-cli":
                continue
            seen.add(name)
            if is_routed(profile) and (profile.vendor or "").strip():
                notes.append(f"{name}: vendor {profile.vendor} is ignored: auto is routed (set model to pin a vendor)")
    if not judging:
        lines.append("no kiro-cli judge profile")
    message = "; ".join([*lines, *notes])
    if warnings:
        message = "; ".join([*warnings, message])
        return CheckResult(
            "fail", message,
            f"remove options.agent and set min_version to {KIRO_JUDGE_MIN_VERSION} or newer on the profile",
        )  # fmt: skip
    return CheckResult("pass", message)


CFG_011 = register(Check("CFG-011", "kiro-cli judge profiles", "warn", _cfg_011, scopes=CONFIG_SCOPES))


CFG_012_FIX = "set ci.time_budget: auto (the job timeout), or a duration at least soft_deadline_margin plus 10m"


def _cfg_012(ctx: DoctorContext) -> CheckResult:
    ci = ctx.cfg.ci
    error = too_short(ctx.cfg)
    warning = shortens_job(ctx.cfg, job_timeout(ctx.env, read_workflow(ctx.repo)))
    if error and warning:
        return CheckResult("fail", f"{error}; {warning}", CFG_012_FIX)
    if error:
        return CheckResult("fail", error, CFG_012_FIX)
    if warning:
        return CheckResult("fail", warning, CFG_012_FIX, severity="warn")
    if ci.time_budget == "auto":
        return CheckResult("pass", "ci.time_budget is auto: the job's timeout is the budget")
    left = (duration_seconds(ci.time_budget) - duration_seconds(ci.soft_deadline_margin)) // 60
    return CheckResult(
        "pass",
        f"ci.time_budget {ci.time_budget} leaves {left} min after soft_deadline_margin {ci.soft_deadline_margin}",
    )


CFG_012 = register(
    Check("CFG-012", "The soft deadline leaves room for a step", "error", _cfg_012, scopes=CONFIG_SCOPES)
)
