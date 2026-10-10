import json

from l4.doctor.registry import CheckOutcome
from l4.exitcodes import ExitCode
from l4.provision.runner import FixAction

SCHEMA_ID = "l4/doctor@1"
COLUMNS = ("id", "severity", "status", "message", "fix")


def _rows(outcomes: list[CheckOutcome]) -> list[tuple[str, ...]]:
    return [(o.id, o.severity, o.status, o.message, o.fix_hint or "-") for o in outcomes]


def render_table(outcomes: list[CheckOutcome]) -> str:
    rows = _rows(outcomes)
    widths = [max(len(COLUMNS[i]), *(len(r[i]) for r in rows)) for i in range(4)]
    lines = []
    for row in (COLUMNS, *rows):
        cells = [row[i].ljust(widths[i]) for i in range(4)] + [row[4]]
        lines.append("  ".join(cells).rstrip())
        if row is COLUMNS:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def render_fixes(actions: list[FixAction]) -> str:
    """One line per fix action: `fix  <tool>  <status>  <message>`, then the commands a human would run."""
    lines = []
    for action in actions:
        lines.append(f"fix  {action.tool}  {action.status}  {action.message or action.reason}".rstrip())
        lines.extend(f"       {command}" for command in action.commands if action.status in ("manual", "failed"))
    return "\n".join(lines)


def render_json(outcomes: list[CheckOutcome], code: ExitCode, fixes: list[FixAction] | None = None) -> str:
    document = {
        "schema": SCHEMA_ID,
        "ok": not any(o.severity == "error" and o.status == "fail" for o in outcomes),
        "exit_code": int(code),
        "checks": [
            {"id": o.id, "severity": o.severity, "status": o.status, "message": o.message, "fix": o.fix_hint}
            for o in outcomes
        ],
        "probe_cost_usd": round(sum(o.cost_usd for o in outcomes), 6),
    }
    if fixes is not None:
        document["fixes"] = [
            {"tool": a.tool, "status": a.status, "message": a.message or a.reason, "commands": list(a.commands)}
            for a in fixes
        ]
    return json.dumps(document, indent=2)
