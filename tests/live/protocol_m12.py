"""Pure rules of the M1.2 acceptance protocol: what the console lines and ledger events of a pipeline must say (unit
tested over lines the harness itself produces)."""

import re
from typing import Any


def console_lines(trace: str, role: str, profile: str) -> list[str]:
    """The `[l4] <role>: <profile> …` lines of a job log, one per selection decision, without log decoration."""
    prefix = f"[l4] {role}: {profile} "
    found = []
    for raw in trace.splitlines():
        line = raw.strip()
        if (at := line.find(prefix)) >= 0:
            found.append(line[at:])
    return found


def selected_line(trace: str, role: str, profile: str) -> str | None:
    return next((line for line in console_lines(trace, role, profile) if " → selected" in line), None)


def skipped_line(trace: str, role: str, profile: str) -> str | None:
    return next((line for line in console_lines(trace, role, profile) if f"{profile} skipped — " in line), None)


def fallback_number(line: str) -> int | None:
    match = re.search(r"→ selected, fallback #(\d+)$", line)
    return int(match.group(1)) if match else None


def selections(events: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    return [e for e in events if e["type"] == "availability.selected" and e.get("role") == role]


def trailer_values(message: str, key: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(rf"^{re.escape(key)}: (.*)$", message, re.MULTILINE)]


def independence_line(verification_md: str) -> str | None:
    match = re.search(r"^- (independence: .*)$", verification_md, re.MULTILINE)
    return match.group(1) if match else None


def unit_implementer_commits(commits: list[dict[str, Any]], unit_id: str) -> list[dict[str, Any]]:
    """The red and green commits of one unit (`L4-Task`, title `test(`/`feat(`, `L4-Unit: <unit_id>`). A unit branch
    also reaches main's history, which holds other units' merged commits."""
    return [
        c
        for c in commits
        if c["title"].startswith(("test(", "feat("))
        and "L4-Task: " in c["message"]
        and trailer_values(c["message"], "L4-Unit") == [unit_id]
    ]
