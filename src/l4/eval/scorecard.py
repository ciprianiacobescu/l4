"""The scorecard (L4-EVAL-011, plan E1): the cells of a run, their per-profile aggregates and the environment they
were measured in (handbook section 38), as canonical JSON.

Deterministic: the same cells in any order give the same bytes. The only wall-clock value in the body is
`env.started_at`, and `scorecard_sha256` leaves it out. `pass_rate = pass / (pass + fail)`: an `invalid` cell (plan D5)
is listed and counted but never rated.
"""

import copy
import hashlib
import json
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_ID = "l4/eval-scorecard@1"
_CELL_DEFAULTS: dict[str, Any] = {
    "invalid_reason": None, "wall_s": 0.0, "attempts": None, "halted_at": None, "breaker": None, "blocked": False,
    "verdict": None, "expected_verdict": None, "agreement": None, "findings": None, "worst_severity": None,
    "missed_defect": False, "cost_usd": None, "input_tokens": 0, "output_tokens": 0, "errors": [], "returncode": None,
}  # fmt: skip


def cell_result(fields: Mapping[str, Any]) -> dict[str, Any]:
    """A cell as the scorecard holds it: every field present, `cell_key` and a rounded wall time."""
    cell = {**copy.deepcopy(_CELL_DEFAULTS), **copy.deepcopy(dict(fields))}
    cell["wall_s"] = round(float(cell["wall_s"] or 0.0), 3)
    cell["cell_key"] = f"{cell['role']}|{cell['profile']}|{cell['unit']}|{cell['k']}"
    return cell


def canonical_json(doc: Mapping[str, Any]) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _aggregate(role: str, profile: str, cells: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rated = [c for c in cells if c["status"] in ("pass", "fail")]
    passed = sum(c["status"] == "pass" for c in rated)
    walls = [c["wall_s"] for c in rated]
    with_attempts = [c["attempts"] for c in rated if c.get("attempts")]
    costs = [c["cost_usd"] for c in cells if c.get("cost_usd") is not None]
    errors: Counter[str] = Counter(e["kind"] for c in cells for e in c.get("errors", []))
    agreeing = sum(bool(c.get("agreement")) for c in rated)
    return {
        "role": role, "profile": profile, "cells": len(cells), "pass": passed, "fail": len(rated) - passed,
        "invalid": len(cells) - len(rated), "pass_rate": _rate(passed, len(rated)),
        "median_wall_s": round(statistics.median(walls), 3) if walls else None,
        "attempts_mean": (
            {ph: round(sum(a.get(ph, 0) for a in with_attempts) / len(with_attempts), 4) for ph in ("red", "green")}
            if with_attempts else None
        ),
        "agreement_rate": _rate(agreeing, len(rated)) if role == "judge" else None,
        "cost_usd": round(sum(costs), 6) if costs else None,
        "errors": dict(sorted(errors.items())),
    }  # fmt: skip


def build_scorecard(
    cells: Sequence[Mapping[str, Any]], env: Mapping[str, Any], seeds: Mapping[str, Any], *, complete: bool = True
) -> dict[str, Any]:
    ordered = sorted((dict(c) for c in cells), key=lambda c: (c["role"], c["profile"], c["unit"], c["k"]))
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for cell in ordered:
        groups.setdefault((cell["role"], cell["profile"]), []).append(cell)
    doc: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "complete": complete,
        "env": copy.deepcopy(dict(env)),
        "seeds": copy.deepcopy(dict(seeds)),
        "cells": ordered,
        "profiles": [_aggregate(role, name, group) for (role, name), group in sorted(groups.items())],
    }
    body = copy.deepcopy(doc)
    body["env"].pop("started_at", None)
    doc["scorecard_sha256"] = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    return doc
