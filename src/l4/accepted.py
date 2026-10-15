"""The review findings a person accepted, as they travel with a unit (L4-YOLO-028, review-resolution design D8).

The run writes `<unit folder>/.l4/review-accepted.json` (`{"schema": "l4/review-accepted@1", "plan", "items":
[{"subject", "reason", "by", "actor", "findings": [{"id", "criterion", "severity", "text"}]}]}`); the implementer's
prompt and the verifier's judge read it here. A file that cannot be read or does not have this shape is a warning
and no items: an accepted finding never stops a run.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from l4.fsutil import UnsafeFile, read_regular_file

log = logging.getLogger("l4.accepted")

ACCEPTED_FILE = ".l4/review-accepted.json"  # relative to the unit folder
ACCEPTED_SCHEMA = "l4/review-accepted@1"
MAX_ACCEPTED_BYTES = 256 * 1024


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _item(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("findings"), list):
        return None
    findings = []
    for f in raw["findings"]:
        if not isinstance(f, dict) or _text(f.get("id")) is None or _text(f.get("text")) is None:
            return None
        findings.append({k: _text(f.get(k)) or "" for k in ("id", "criterion", "severity", "text")})
    if _text(raw.get("reason")) is None:
        return None
    return {
        "subject": _text(raw.get("subject")) or "",
        "reason": raw["reason"],
        "by": _text(raw.get("by")) or "",
        "actor": _text(raw.get("actor")) or "",
        "findings": findings,
    }


def read_accepted(unit_dir: Path) -> tuple[dict[str, Any], ...]:
    """The items of the unit's carrier file. No file, an unreadable or invalid one: no items (the last two with a
    warning)."""
    path = unit_dir / ACCEPTED_FILE
    try:
        data = json.loads(read_regular_file(path, limit=MAX_ACCEPTED_BYTES))
    except FileNotFoundError:
        return ()
    except (OSError, UnsafeFile, ValueError) as exc:
        log.warning("%s: not read (%s)", path, exc)
        return ()
    items = data.get("items") if isinstance(data, dict) and data.get("schema") == ACCEPTED_SCHEMA else None
    parsed = [_item(i) for i in items] if isinstance(items, list) else None
    if parsed is None or any(i is None for i in parsed):
        log.warning("%s: not in the shape of %s; ignored", path, ACCEPTED_SCHEMA)
        return ()
    return tuple(i for i in parsed if i is not None)
