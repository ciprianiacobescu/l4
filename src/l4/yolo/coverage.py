"""The checks across all plan files that `scripts/validate_plan.py` ran alone until `l4 yolo check --worktree`
(L4-YOLO-034): `uncovered` and `covered_twice`. The rules are the script's, and a parity test holds them to it:

- a plan file lists a unit when a batch names it (planned) or its `exclude` does (excluded), whatever else is wrong with
  the file; a file that is not a JSON object lists nothing;
- a unit no file lists is `uncovered`, unless a unit it is derived from (a `<parent>-fix-<n>` or `<parent>-followup-<n>`
  name, at any depth) is listed, or a `yolo.hold` entry (a unit id or an fnmatch pattern) matches it;
- a unit that two files plan (not merely exclude) is `covered_twice` (plan ids: the file stems, in path order)."""

import fnmatch
from collections.abc import Iterable, Sequence

from l4.yolo.draft import derived_parents
from l4.yolo.plans import PlanFile, _raw_ids, listed_ids

UNCOVERED_HINT = "add it to a plan or to a plan's exclude with a reason"


def coverage_findings(files: Sequence[PlanFile], known: Iterable[str], hold: Sequence[str] = ()) -> list[str]:
    """`uncovered: <unit> (...)` lines in unit order, then `covered_twice: <unit> (...)` lines; empty when every unit
    is covered once. `known` is every unit the providers find in the tree being checked."""
    listed: set[str] = set()
    planned_in: dict[str, list[str]] = {}
    for file in files:
        listed |= listed_ids(file)
        raw = _raw_ids(file.text)
        if raw is None:
            continue
        ids, excluded = raw
        for unit in ids:
            if unit not in excluded:
                planned_in.setdefault(unit, []).append(file.plan_id)
    out: list[str] = []
    for unit in sorted(set(known)):
        if unit in listed or any(parent in listed for parent in derived_parents(unit)):
            continue
        if not any(fnmatch.fnmatchcase(unit, pattern) for pattern in hold):
            out.append(f"uncovered: {unit} ({UNCOVERED_HINT})")
    for unit, plans in sorted(planned_in.items()):
        if len(plans) > 1:
            out.append(f"covered_twice: {unit} (listed in plans {', '.join(plans)})")
    return out
