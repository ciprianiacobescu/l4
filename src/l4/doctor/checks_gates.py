"""GATE-001 (M1.8 A3, L4-GAT-001): the gates pass at HEAD. Scope `adoption`: `l4 doctor --adoption`, and the first
pipeline `l4 setup gitlab` triggers (`L4_ADOPTION_CHECK`), where it runs on the runner and its platform (a laptop
cannot see a failure that is Linux-only). Registered at import."""

from l4.ci.detect import ci_like
from l4.doctor.context import DoctorContext
from l4.doctor.registry import Check, CheckResult, register
from l4.gates.dryrun import MAX_FAILING, GateDryRun, GateRun, dry_run_gates
from l4.gates.pyproject import read_pyproject
from l4.gates.suggest import suggestions

NOTE = "uncommitted changes are not included"


def _failing(run: GateRun) -> str:
    if not run.failing_tests:
        return ""
    shown = ", ".join(run.failing_tests[:MAX_FAILING])
    more = len(run.failing_tests) - MAX_FAILING
    return f"{len(run.failing_tests)} failing: {shown}" + (f" (+{more} more)" if more > 0 else "")


def _line(run: GateRun) -> str:
    if run.status == "pass":
        counts = f" ({run.tests_passed}/{run.tests_total} passed)" if run.gate == "test" and run.tests_total else ""
        return f"{run.gate}: pass{counts}"
    if run.status == "skipped":
        return f"{run.gate}: skipped ({run.reason})"
    detail = [run.reason]
    if run.gate == "test" and run.tests_total:
        detail[0] = f"{run.tests_passed}/{run.tests_total} passed, {run.reason}"
    if failing := _failing(run):
        detail.append(failing)
    if run.excerpt:
        detail.append(run.excerpt.replace("\n", " | "))
    return f"{run.gate}: fail ({'; '.join(d for d in detail if d)})"


def render(result: GateDryRun) -> str:
    head = f"HEAD {result.sha[:10]}; {NOTE}; gates ran {result.sandbox or 'nowhere'}"
    return head + ": " + "; ".join(_line(r) for r in result.runs)


def _gate_001(ctx: DoctorContext) -> CheckResult:
    result = dry_run_gates(ctx.cfg, ctx.repo, ctx.env, in_ci=ci_like(ctx.env))
    if result.error:
        return CheckResult("fail", result.error, "commit, then run `l4 doctor --adoption` again")
    if not result.runs:
        return CheckResult("skip", f"no gate is configured (HEAD {result.sha[:10]})")
    if result.ok:
        return CheckResult("pass", render(result))
    return CheckResult("fail", render(result), fix_hint(ctx, result))


def fix_hint(ctx: DoctorContext, result: GateDryRun) -> str:
    found = suggestions(ctx.cfg, read_pyproject(ctx.repo), result)
    return "; ".join(found) or "every verification FAILs while the base is red: fix the failures above"


GATE_001 = register(Check("GATE-001", "The gates pass at HEAD", "error", _gate_001, frozenset({"adoption"})))
