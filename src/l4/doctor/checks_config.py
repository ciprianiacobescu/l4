"""CFG-006 and CFG-007 (adoption-kit L4-ACT-004): the pin of an action-form workflow, and the local `l4`.

CFG-004: `gates.test.command` is set. The run rejects every unit without it (no test oracle), so nothing else in
the configuration matters until it is.

CFG-005 (M1.8, A6): an explicitly set list that drops defaults.

CFG-002 (reduced): role chains reference defined profiles, the roles M0 runs (implementer, judges) are not empty,
and no profile has both adapter and backend. Registered at import. A typo or an empty chain would otherwise surface only
when the first agent is selected (`Factory.for_role` exits 12)."""

import re

from l4.ci.github import ACTION_PATH, WORKFLOW_RELPATH
from l4.config import defaults as d
from l4.config.schema import effective_delivery
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
