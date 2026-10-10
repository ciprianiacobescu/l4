"""`l4 eval --compare` (L4-EVAL-021 to 025): the deltas between two scorecards and the regression gate.

Only the cells present and rated in both scorecards enter a rate (matched by `cell_key`), so a profile that lost cells
to a rate limit is not compared on the others. A profile that is mostly `invalid` (more than half) in either scorecard
is `unrated`: printed, never failed. The gate is a threshold on a rate over a handful of cells: with 4 units and k = 1
one lost cell is 0.25 and fails the default `--max-drop 0.20`; a 5 point drift is invisible (docs/eval.md).
"""

import json
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from l4.eval.scorecard import SCHEMA_ID
from l4.exitcodes import ExitCode, L4Exit

RATED = ("pass", "fail")


NOTHING_COMPARED = (
    "nothing was compared: no profile has a cell rated in both scorecards (every row is new, gone or unrated), so the "
    "gate cannot pass; rerun the invalid cells (`--resume`) or compare scorecards of the same profiles"
)


class IncompleteScorecard(L4Exit):
    """A scorecard of a run that stopped early (`complete: false`): its missing cells would read as not measured."""

    def __init__(self, side: str) -> None:
        super().__init__(
            ExitCode.USAGE_ERROR,
            f"the {side} scorecard is incomplete (complete: false): finish its run with `--resume` before comparing",
        )


class SeedSetChanged(L4Exit):
    """The two scorecards measured different things; comparing their rates would be meaningless (exit 2)."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            ExitCode.USAGE_ERROR,
            f"the scorecards measure different seed sets ({detail}); pass --allow-seed-change for the deltas only",
        )


@dataclass
class Comparison:
    rows: list[dict[str, Any]]
    max_drop: float
    missed_defects: list[tuple[str, str]] = field(default_factory=list)  # (profile, unit) newly missed
    env_diff: list[str] = field(default_factory=list)
    seed_changed: bool = False
    require_all: bool = False

    @property
    def regressed(self) -> bool:
        return any(r["status"] == "regressed" for r in self.rows)

    @property
    def gone(self) -> list[str]:
        return [r["profile"] for r in self.rows if r["status"] == "gone"]

    @property
    def compared(self) -> int:
        """The rows whose rates were compared (`ok`, `improved` or `regressed`): 0 means the gate saw no evidence."""
        return sum(r["status"] in ("ok", "improved", "regressed") for r in self.rows)

    @property
    def failed(self) -> bool:
        """The gate: a regressed profile, a newly missed defect (a `regressed` row), or with `--require-all` a profile
        of the old scorecard that the new run did not evaluate."""
        return self.regressed or (self.require_all and bool(self.gone))

    def as_dict(self, exit_code: int) -> dict[str, Any]:
        return {
            "regressed": self.failed, "exit_code": exit_code, "max_drop": self.max_drop, "rows": self.rows,
            "env_diff": self.env_diff, "missed_defects": [list(m) for m in self.missed_defects],
            "seed_changed": self.seed_changed, "gone": self.gone, "require_all": self.require_all,
        }  # fmt: skip


def _by_profile(card: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    out: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for cell in card["cells"]:
        out.setdefault((cell["role"], cell["profile"]), {})[cell["cell_key"]] = cell
    return out


def _invalid_share(cells: Mapping[str, Mapping[str, Any]]) -> Fraction:
    return Fraction(sum(c["status"] == "invalid" for c in cells.values()), len(cells)) if cells else Fraction(0)


def _rate(cells: Sequence[Mapping[str, Any]], key: str = "status", good: Any = "pass") -> Fraction:
    return Fraction(sum(c[key] == good for c in cells), len(cells))


def _mean_attempts(cells: Sequence[Mapping[str, Any]]) -> dict[str, Fraction] | None:
    if not cells or any(not c.get("attempts") for c in cells):
        return None
    return {ph: Fraction(sum(c["attempts"][ph] for c in cells), len(cells)) for ph in ("red", "green")}


def _r(value: Fraction | float | None, places: int = 4) -> float | None:
    return None if value is None else round(float(value), places)


def _row(role: str, profile: str, old: Mapping[str, Any] | None, new: Mapping[str, Any] | None, drop: Fraction) -> dict:
    row: dict[str, Any] = {
        "role": role, "profile": profile, "status": "ok", "old_rate": None, "new_rate": None, "delta": None,
        "agreement_delta": None, "attempts_delta": None, "wall_delta_pct": None, "cost_delta": None,
        "matched_cells": 0, "missed_defects": [],
    }  # fmt: skip
    if old is None:
        return {**row, "status": "new"}
    if new is None:
        return {**row, "status": "gone"}
    matched = [k for k in old if k in new and old[k]["status"] in RATED and new[k]["status"] in RATED]
    row["matched_cells"] = len(matched)
    # a held-back defect that now passes is a regression at any threshold, unless the baseline missed it too: the
    # rule needs no rate, so it holds for a cell the baseline has no rated result for and for an unrated profile
    newly = [
        cell["unit"] for key, cell in sorted(new.items())
        if role == "judge" and cell["status"] in RATED and cell.get("missed_defect")
        and not (old.get(key) or {}).get("missed_defect")
    ]  # fmt: skip
    row["missed_defects"] = newly
    if not matched or _invalid_share(old) > Fraction(1, 2) or _invalid_share(new) > Fraction(1, 2):
        return {**row, "status": "regressed" if newly else "unrated"}
    o, n = [old[k] for k in matched], [new[k] for k in matched]
    old_rate, new_rate = _rate(o), _rate(n)
    row.update(old_rate=_r(old_rate), new_rate=_r(new_rate), delta=_r(new_rate - old_rate))
    status = "ok"
    if old_rate - new_rate > drop:
        status = "regressed"
    elif new_rate - old_rate > drop:
        status = "improved"
    if role == "judge":
        old_agree, new_agree = _rate(o, "agreement", True), _rate(n, "agreement", True)
        row["agreement_delta"] = _r(new_agree - old_agree)
        if old_agree - new_agree > drop:
            status = "regressed"
        if newly:
            status = "regressed"
    else:
        a_old, a_new = _mean_attempts(o), _mean_attempts(n)
        if a_old and a_new:
            row["attempts_delta"] = {ph: _r(a_new[ph] - a_old[ph]) for ph in ("red", "green")}
    walls_o, walls_n = statistics.median(c["wall_s"] for c in o), statistics.median(c["wall_s"] for c in n)
    row["wall_delta_pct"] = round((walls_n - walls_o) / walls_o * 100, 1) if walls_o else None
    if all(c.get("cost_usd") is not None for c in o + n):
        row["cost_delta"] = round(sum(c["cost_usd"] for c in n) - sum(c["cost_usd"] for c in o), 6)
    row["status"] = status
    return row


def find_baseline(
    directory: Path, seed_sha: str, *, exclude: Path | None = None, before: str | None = None
) -> Path | None:
    """The newest complete `scorecard.json` under `directory` that measured the seed set `seed_sha` (newest by the
    time its run started) and started before `before`, the new run's `started_at`; None when there is none. The new
    scorecard itself (`exclude`, when `--out` is under the baseline directory) and a copy of it (same start) are never
    its own baseline: the gate would compare a run with itself and pass. A file that is not a readable scorecard, or an
    incomplete one, is skipped."""
    skip = exclude.resolve() if exclude is not None else None
    found: list[tuple[str, str, Path]] = []
    for path in sorted(directory.glob("**/scorecard.json")) if directory.is_dir() else []:
        try:
            if skip is not None and path.resolve() == skip:
                continue
            doc = json.loads(path.read_text(encoding="utf-8"))
            started = str(doc["env"].get("started_at") or "")
            if before and started >= before:
                continue
            if doc.get("schema") == SCHEMA_ID and doc["seeds"]["sha256"] == seed_sha and doc.get("complete") is True:
                found.append((started, str(path), path))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return max(found)[2] if found else None


def _short(commit: object) -> str:
    return str(commit or "unknown")[:12]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _cli(record: Mapping[str, Any] | None) -> str:
    return "absent" if record is None else f"{record['adapter']} {record['version'] or '?'}"


def env_diff(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    """What differs in the environment of the two runs, one line each; empty when nothing does."""
    a, b = old.get("env") or {}, new.get("env") or {}
    lines: list[str] = []
    ha, hb = a.get("harness") or {}, b.get("harness") or {}
    if ha.get("commit") != hb.get("commit"):
        lines.append(f"harness commit: {_short(ha.get('commit'))} -> {_short(hb.get('commit'))}")
    if ha.get("dirty") != hb.get("dirty"):
        lines.append(f"harness dirty: {ha.get('dirty')} -> {hb.get('dirty')}")
    ta, tb = a.get("templates") or {}, b.get("templates") or {}
    for name in sorted(set(ta) | set(tb)):
        if name not in ta or name not in tb:
            lines.append(f"template {name}: {'added' if name not in ta else 'removed'}")
        elif ta[name]["version"] != tb[name]["version"]:
            lines.append(f"template {name}: v{ta[name]['version']} -> v{tb[name]['version']}")
        elif ta[name]["sha256"] != tb[name]["sha256"]:
            lines.append(f"template {name}: v{ta[name]['version']} body changed")
    ca, cb = a.get("cli_versions") or {}, b.get("cli_versions") or {}
    for name in sorted(set(ca) | set(cb)):
        ra, rb = ca.get(name), cb.get(name)
        if (ra and ra["version"]) != (rb and rb["version"]) or (ra or {}).get("adapter") != (rb or {}).get("adapter"):
            lines.append(f"cli {name}: {_cli(ra)} -> {_cli(rb)}")
    pa, pb = a.get("profiles") or {}, b.get("profiles") or {}
    for name in sorted(set(pa) | set(pb)):
        if name not in pa or name not in pb:
            lines.append(f"profile {name}: {'added' if name not in pa else 'removed'}")
            continue
        for key in ("adapter", "model", "vendor", "auth"):
            if pa[name].get(key) != pb[name].get(key):
                lines.append(f"profile {name} {key}: {pa[name].get(key)} -> {pb[name].get(key)}")
        if pa[name].get("options") != pb[name].get("options"):
            lines.append(
                f"profile {name} options: {_json(pa[name].get('options'))} -> {_json(pb[name].get('options'))}"
            )
    ma, mb = a.get("machine") or {}, b.get("machine") or {}
    for key in ("platform", "cpus", "runner"):
        if ma.get(key) != mb.get(key):
            lines.append(f"machine {key}: {ma.get(key)} -> {mb.get(key)}")
    for key in ("k", "cell_timeout_s", "python"):
        if a.get(key) != b.get(key):
            lines.append(f"{key}: {a.get(key)} -> {b.get(key)}")
    return lines


def compare(
    old: Mapping[str, Any], new: Mapping[str, Any], max_drop: float, *, allow_seed_change: bool = False,
    require_all: bool = False,
) -> Comparison:  # fmt: skip
    for side, card in (("old", old), ("new", new)):
        if card.get("complete") is not True:
            raise IncompleteScorecard(side)
    seed_changed = (old.get("seeds") or {}).get("sha256") != (new.get("seeds") or {}).get("sha256")
    schema_changed = old.get("schema") != new.get("schema") or new.get("schema") != SCHEMA_ID
    if (seed_changed or schema_changed) and not allow_seed_change:
        raise SeedSetChanged("the seed set or the scorecard schema differs")
    drop = Fraction(str(max_drop))
    old_p, new_p = _by_profile(old), _by_profile(new)
    rows = [_row(role, profile, old_p.get((role, profile)), new_p.get((role, profile)), drop)
            for role, profile in sorted(set(old_p) | set(new_p))]  # fmt: skip
    changed = seed_changed or schema_changed
    if changed:  # only deltas: the rates are of different things
        for r in rows:
            if r["status"] in ("ok", "improved", "regressed"):
                r["status"] = "delta"
            r["missed_defects"] = []
    missed = [(r["profile"], unit) for r in rows for unit in r["missed_defects"]]
    return Comparison(rows, max_drop, missed, env_diff(old, new), changed, require_all)
