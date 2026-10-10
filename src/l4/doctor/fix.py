"""`l4 doctor --fix` (SPEC L4-DOC-001 e): run the fixes that failing checks registered, re-run those checks, and make
sure nothing tracked in git changed (SCN-DOC-03). With `--ci` only provisioning fixes run (L4-DOC-002)."""

import hashlib
import logging
from collections.abc import Collection
from dataclasses import dataclass

from l4.doctor.context import DoctorContext
from l4.doctor.registry import (
    DEFAULT_SCOPES,
    SAFE_FIX_KINDS,
    CheckOutcome,
    Fix,
    Registry,
    Scope,
    run_checks,
)
from l4.exitcodes import ExitCode, L4Exit
from l4.provision.runner import FixAction

log = logging.getLogger("l4.doctor")


class TrackedFilesChanged(L4Exit):
    def __init__(self, files: list[str]) -> None:
        super().__init__(ExitCode.INTERNAL_ERROR, f"a fix modified tracked files: {', '.join(files)}")


@dataclass(frozen=True)
class FixRun:
    outcomes: list[CheckOutcome]  # after fixing: what the exit code is computed from
    actions: list[FixAction]


def _git(ctx: DoctorContext, *args: str) -> tuple[int, str]:
    git = ctx.which("git")
    if git is None:
        return 127, ""
    done = ctx.run([git, "-C", str(ctx.repo), *args], timeout=60.0)
    return done.returncode, done.stdout


def _tracked_state(ctx: DoctorContext) -> tuple[str, list[str]] | None:
    """(digest of every tracked change against HEAD, the names), or None outside a repository or before a first
    commit, where there is nothing to guard."""
    code, body = _git(ctx, "diff", "HEAD", "--binary", "--no-color")
    if code != 0:
        return None
    _, names = _git(ctx, "diff", "HEAD", "--name-only")
    return hashlib.sha256(body.encode("utf-8", "replace")).hexdigest(), names.splitlines()


def _selected(outcomes: list[CheckOutcome], registry: Registry, *, ci: bool) -> list[tuple[str, Fix]]:
    """The fix of every failing check, once per distinct `apply` (one provisioning fix hangs on several checks)."""
    chosen: list[tuple[str, Fix]] = []
    for outcome in outcomes:
        if outcome.status != "fail":
            continue
        check = next(c for c in registry.checks() if c.id == outcome.id)
        fix = check.fix
        if fix is None or fix.kind not in SAFE_FIX_KINDS or (ci and fix.scope != "provision"):
            continue
        if all(fix.apply is not other.apply for _, other in chosen):
            chosen.append((outcome.id, fix))
    return chosen


def _surveyed(
    outcomes: list[CheckOutcome], registry: Registry, chosen: list[tuple[str, Fix]], *, ci: bool
) -> list[Fix]:
    """Fixes of passing checks that can report what is in place, once each and never next to the same fix applying."""
    found: list[Fix] = []
    for outcome in outcomes:
        if outcome.status != "pass":
            continue
        fix = next(c for c in registry.checks() if c.id == outcome.id).fix
        if fix is None or fix.survey is None or fix.kind not in SAFE_FIX_KINDS or (ci and fix.scope != "provision"):
            continue
        if all(fix.apply is not other.apply for other in [*(f for _, f in chosen), *found]):
            found.append(fix)
    return found


def apply_fixes(
    ctx: DoctorContext,
    outcomes: list[CheckOutcome],
    registry: Registry,
    *,
    ci: bool,
    live: bool = False,
    scopes: Collection[Scope] = DEFAULT_SCOPES,
    unit: str | None = None,
) -> FixRun:
    chosen = _selected(outcomes, registry, ci=ci)
    surveyed = _surveyed(outcomes, registry, chosen, ci=ci)
    if not chosen and not surveyed:
        return FixRun(outcomes, [])
    before = _tracked_state(ctx)
    actions: list[FixAction] = []
    for fix in surveyed:
        assert fix.survey is not None
        actions.extend(fix.survey(ctx))
    for check_id, fix in chosen:
        try:
            actions.extend(fix.apply(ctx))
        except Exception as exc:  # one broken fix must not hide the others or the report
            log.warning("fix for %s crashed: %s", check_id, type(exc).__name__)
            actions.append(FixAction(check_id, "fix crashed", "", (), False, "failed", type(exc).__name__))
    after = _tracked_state(ctx)
    if before is not None and after is not None and before[0] != after[0]:
        changed = [n for n in after[1] if n not in before[1]] or after[1]
        raise TrackedFilesChanged(changed)
    rerun = {o.id for o in outcomes if o.status == "fail"}
    fresh = {o.id: o for o in run_checks(ctx, live=live, registry=registry, scopes=scopes, unit=unit, only=rerun)}
    return FixRun([fresh.get(o.id, o) for o in outcomes], actions)
