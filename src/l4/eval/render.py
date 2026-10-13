"""The markdown form of a scorecard (L4-EVAL-013). Pure: a mapping in, text out; nothing is read or written."""

from collections.abc import Mapping, Sequence
from typing import Any


def _esc(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _num(value: float | None, fmt: str = "{:g}") -> str:
    return "n/a" if value is None else fmt.format(value)


def _attempts(mean: Mapping[str, float] | None) -> str:
    return "n/a" if not mean else f"red {mean['red']:.2f} / green {mean['green']:.2f}"


def _errors(errors: Mapping[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in errors.items()) or "-"


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(_esc(c) for c in row) + " |" for row in rows]
    return lines


def _cell_line(cell: Mapping[str, Any]) -> str:
    parts = [f"`{_esc(cell['profile'])}` {cell['role']} {cell['unit']} k{cell['k']}: **{cell['status']}**"]
    if cell["role"] == "judge":
        if cell.get("verdict"):
            parts.append(
                f"verdict {cell['verdict']} (expected {cell.get('expected_verdict')}), "
                f"{cell.get('findings', 0)} finding(s)"
            )
        if cell.get("worst_severity"):
            parts.append(f"worst {cell['worst_severity']}")
        if cell.get("missed_defect"):
            parts.append("MISSED the designed defect")
    else:
        if cell.get("attempts"):
            parts.append(f"red {cell['attempts']['red']} / green {cell['attempts']['green']} attempt(s)")
        if cell.get("halted_at"):
            parts.append(f"halted at {cell['halted_at']}")
        if cell.get("verdict"):
            parts.append(f"verdict {cell['verdict']}")
    kinds = sorted({e["kind"] for e in cell.get("errors", [])})
    if kinds:
        parts.append("errors: " + ", ".join(kinds))
    parts.append(f"{cell['wall_s']:g} s")
    return "- " + "; ".join(parts)


def render_markdown(card: Mapping[str, Any]) -> str:
    env, seeds = card["env"], card["seeds"]
    harness = env.get("harness") or {}
    commit = (harness.get("commit") or "unknown")[:12]
    machine = env.get("machine") or {}
    title = "# l4 eval scorecard" + ("" if card.get("complete") else " (PARTIAL: the run did not finish)")
    lines = [
        title, "",
        "## Environment", "",
        f"- harness: `{commit}`{' (dirty)' if harness.get('dirty') else ''} [{harness.get('source', 'unknown')}]",
        f"- started: {env.get('started_at')}",
        f"- seed set: `{str(seeds['sha256'])[:12]}`, units {', '.join(seeds['units'])}; k = {env.get('k')}, "
        f"cell timeout {_num(env.get('cell_timeout_s'))} s",
        f"- templates lock: `{str(env.get('templates_lock_sha256', ''))[:12]}`; "
        + ", ".join(f"{name} v{t['version']}" for name, t in sorted((env.get("templates") or {}).items())),
        "- CLIs: " + (", ".join(
            f"{name} = {c['adapter']} {c['version'] or '?'}" + (" (unrecorded)" if c.get("unrecorded") else "")
            for name, c in sorted((env.get("cli_versions") or {}).items())) or "none"),
        f"- machine: {machine.get('platform')}, {machine.get('cpus')} cpu(s), runner {machine.get('runner')}",
        f"- scorecard sha256: `{str(card.get('scorecard_sha256', ''))[:12]}`",
        "", "## Profiles", "",
    ]  # fmt: skip
    rows = [
        (
            p["role"], p["profile"], _pct(p["pass_rate"]),
            _pct(p.get("agreement_rate")) if p["role"] == "judge" else "-",
            _attempts(p.get("attempts_mean")), _num(p.get("median_wall_s"), "{:g} s"),
            _num(p.get("cost_usd"), "${:.4f}"), p["invalid"], _errors(p["errors"]),
        )
        for p in card["profiles"]
    ]  # fmt: skip
    lines += _table(
        ("role", "profile", "pass rate", "agreement", "attempts (mean)", "median wall", "cost", "invalid", "errors"),
        rows,
    )
    lines += ["", "## Cells", ""]
    rated = [c for c in card["cells"] if c["status"] != "invalid"]
    lines += [_cell_line(c) for c in rated] or ["None."]
    invalid = [c for c in card["cells"] if c["status"] == "invalid"]
    if invalid:
        lines += ["", "## Invalid cells (not in any rate)", ""]
        for c in invalid:
            lines.append(f"- `{_esc(c['profile'])}` {c['role']} {c['unit']} k{c['k']}: {c.get('invalid_reason')}")
    return "\n".join(lines) + "\n"


def _delta(value: float | None, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:+g}{suffix}"


def render_comparison(comparison: Any) -> str:
    """The markdown of a `Comparison`: the environment changes first, then one row per profile."""
    lines = ["# l4 eval comparison", "", "## Environment changes", ""]
    lines += [f"- {line}" for line in comparison.env_diff] or ["No environment change."]
    if comparison.seed_changed:
        lines += ["", "The seed sets differ: only deltas are reported, no profile is marked regressed."]
    lines += ["", "## Profiles", ""]
    rows = []
    for r in comparison.rows:
        attempts = r["attempts_delta"]
        rows.append((
            r["role"], r["profile"], r["status"], _pct(r["old_rate"]), _pct(r["new_rate"]), _delta(r["delta"]),
            _delta(r["agreement_delta"]),
            "n/a" if not attempts else f"red {attempts['red']:+g} / green {attempts['green']:+g}",
            _delta(r["wall_delta_pct"], "%"), _delta(r["cost_delta"]), r["matched_cells"],
        ))  # fmt: skip
    lines += _table(
        (
            "role",
            "profile",
            "status",
            "old rate",
            "new rate",
            "delta",
            "agreement",
            "attempts",
            "wall",
            "cost",
            "cells",
        ),
        rows,
    )
    notes = [f"- `{_esc(r['profile'])}` is unrated: too few valid cells to compare" for r in comparison.rows
             if r["status"] == "unrated"]  # fmt: skip
    notes += [
        f"- `{_esc(p)}` missed the designed defect of {u}, which the baseline did not miss"
        for p, u in comparison.missed_defects
    ]
    notes += [f"- `{_esc(p)}` is gone: the new run did not evaluate it" for p in comparison.gone]
    if comparison.require_all and comparison.gone:
        notes.append("- --require-all: a missing profile fails the gate")
    if notes:
        lines += ["", "## Notes", "", *notes]
    vacuous = not comparison.failed and not comparison.seed_changed and comparison.compared == 0
    verdict = "FAILED" if comparison.failed else "nothing compared (not passed)" if vacuous else "passed"
    lines += ["", f"Gate (--max-drop {comparison.max_drop:g}): {verdict}"]
    return "\n".join(lines) + "\n"
