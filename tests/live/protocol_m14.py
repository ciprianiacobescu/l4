"""Pure rules of the M1.4 acceptance protocol: how a GitLab job log and the merge request list are read (unit
tested over lines GitLab and the harness produce)."""

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

# GitLab 17 job logs start every line with an RFC 3339 timestamp and a stream marker: `00O`, `01E`, `00O+`.
_DECORATION = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z \d\d[OE]\+? ?")
_UNIT_ROW = re.compile(r"^((?:kiro|openspec):\S+)\s")


def log_text(line: str) -> str:
    """One job-log line without GitLab's timestamp and stream marker (an undecorated line is returned as it is)."""
    return _DECORATION.sub("", line, count=1)


def command_output(trace: str, command: str) -> list[str]:
    """The lines a script line printed: after its `$ <command>` echo, up to the next `$ ` echo."""
    lines = [log_text(raw).rstrip() for raw in trace.splitlines()]
    start = next((i for i, line in enumerate(lines) if line.startswith(f"$ {command}")), None)
    if start is None:
        return []
    found = []
    for line in lines[start + 1 :]:
        if line.startswith("$ "):
            break
        found.append(line)
    return found


def plan_rows(lines: Iterable[str]) -> dict[str, str]:
    """The rows of an `l4 plan` table by unit id (the first column); progress (`[l4] …`) lines are not rows."""
    rows: dict[str, str] = {}
    for line in lines:
        text = line.strip()
        if found := _UNIT_ROW.match(text):
            rows.setdefault(found.group(1), text)
    return rows


def created_before(mrs: Iterable[dict[str, Any]], anchor: str | None) -> list[dict[str, Any]]:
    """The merge requests created before `anchor` (every one when there is no anchor); instants, not strings."""
    if anchor is None:
        return list(mrs)
    limit = datetime.fromisoformat(anchor)
    return [m for m in mrs if datetime.fromisoformat(m["created_at"]) < limit]
