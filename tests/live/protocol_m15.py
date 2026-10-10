"""Pure rules of the M1.5 acceptance protocol: how the `.l4-out/s1/<run>.jsonl` artefact is read (unit tested).

With M1.6's shadow on (`verifier.s1.shadow`), the same file holds two shapes: step 8's v1 calibration rows (M1.5,
`record_calibration`: one per judged criterion, no `kind`) and the l4/s1-calibration@2 `item` and `answer` records of
the shadow half (`kind`, no `criterion`). The M1.5 checks are about the first shape only.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass
class S1Lines:
    criteria: list[dict[str, Any]] = field(default_factory=list)  # v1 rows: one per criterion that got a `p`
    items: list[dict[str, Any]] = field(default_factory=list)  # shadow `item` records
    answers: list[dict[str, Any]] = field(default_factory=list)  # shadow `answer` records, one per item and engine

    def by_engine(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for answer in self.answers:
            grouped.setdefault(answer.get("engine") or answer.get("profile") or "?", []).append(answer)
        return grouped


def s1_lines(files: Mapping[str, str]) -> S1Lines:
    """Every non-blank line of the given files (path → text), split by shape."""
    found = S1Lines()
    for text in files.values():
        for line in text.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            kind = row.get("kind")
            if kind is None:
                found.criteria.append(row)
            elif kind == "item":
                found.items.append(row)
            elif kind == "answer":
                found.answers.append(row)
    return found


def commits_above(branch_log: Sequence[dict[str, Any]], seed_id: str) -> list[dict[str, Any]]:
    """The commits of a unit branch above its seed commit, oldest first. `branch_log` is GitLab's list (newest first).
    Unlike "the branch commits not on main", this is the same set before and after the human merge (step 3), when every
    one of them is on `main` too. A log that never reaches the seed gives nothing."""
    above: list[dict[str, Any]] = []
    for commit in branch_log:
        if commit["id"] == seed_id:
            return list(reversed(above))
        above.append(commit)
    return []
