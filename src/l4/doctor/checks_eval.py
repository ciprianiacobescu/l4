"""EVAL-001 (L4-EVAL-026, M1.14): a reminder, never a gate. When the repository holds eval baselines under
`docs/eval/` and a prompt template has changed since the newest one, `l4 doctor` warns that `l4 eval --compare`
has not been run against the change. A warning never makes doctor exit 3, so a template bump never turns it red."""

import json

from l4 import templatelock
from l4.doctor.context import DoctorContext
from l4.doctor.registry import Check, CheckResult, register

BASELINE_DIR = ("docs", "eval")


def _newest_baseline_templates(ctx: DoctorContext) -> dict | None:
    root = ctx.repo.joinpath(*BASELINE_DIR)
    found: list[tuple[str, str, dict]] = []
    for path in sorted(root.glob("**/scorecard.json")) if root.is_dir() else []:
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
            templates = card["env"]["templates"]
            found.append((str(card["env"].get("started_at") or ""), str(path), templates))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return max(found, key=lambda f: f[:2])[2] if found else None


def _eval_001(ctx: DoctorContext) -> CheckResult:
    recorded = _newest_baseline_templates(ctx)
    if recorded is None:
        return CheckResult("skip", "no eval baseline under docs/eval/")
    now = json.loads(json.dumps(templatelock.current()))
    changed = sorted(name for name in now if recorded.get(name) != now[name])
    if not changed:
        return CheckResult("pass", "the templates are as the newest eval baseline recorded them (baseline up to date)")
    listed = ", ".join(changed[:6]) + (f" (+{len(changed) - 6} more)" if len(changed) > 6 else "")
    return CheckResult(
        "fail", f"a template changed since the last eval baseline: run `l4 eval --compare` ({listed})",
        "l4 eval --compare",
    )  # fmt: skip


EVAL_001 = register(Check("EVAL-001", "Templates match the last eval baseline", "warn", _eval_001))
