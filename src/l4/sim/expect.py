"""Judging a scenario run: `compare_expect` against what was observed, `format_mismatches` for a human, and
`normalize_events` so that two runs can be compared (SPEC L4-SIM-002, SCN-SIM-01, SCN-SIM-03).

Not in `runner.py`: `commands.HANDLERS["simulate"]` is `l4.sim.runner:run_simulate`, and the handler stays a "not yet
implemented" stub only while that module does not exist. M1.4 lines 33 and 34 (M14-G4, `run_simulate`) create it.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from l4.sim.scenarios import Expect

_SHA = re.compile(r"\b[0-9a-f]{40}\b")
_SHA256 = re.compile(r"\b[0-9a-f]{64}\b")
_RUN_ID = re.compile(r"\br-\d{8}T\d{4}Z-[0-9a-f]{4}\b")
_DROPPED_KEYS = frozenset({"ts", "run_id", "seq", "nonce", "holder", "repository_key"})
# holder is host:pid, nonce is random, the repository key of a repository with no origin hashes its temporary path
_DROPPED_TYPES = frozenset({"sandbox.disabled"})  # depends on whether bubblewrap exists on the machine


@dataclass(frozen=True)
class Observed:
    exit_code: int
    final_phase: str | None
    events: Sequence[Mapping[str, Any]]  # the unit's ledger events, in order
    trailers: Mapping[str, Sequence[str]]  # trailer key -> its values over the commits of the unit branch


@dataclass(frozen=True)
class Mismatch:
    field: str
    expected: Any
    actual: Any


def _matches(wanted: Mapping[str, Any], event: Mapping[str, Any]) -> bool:
    return all(key in event and event[key] == value for key, value in wanted.items())


def compare_expect(expect: Expect, observed: Observed) -> list[Mismatch]:
    found: list[Mismatch] = []
    if expect.exit_code is not None and expect.exit_code != observed.exit_code:
        found.append(Mismatch("exit_code", expect.exit_code, observed.exit_code))
    if expect.final_phase is not None and expect.final_phase != observed.final_phase:
        found.append(Mismatch("final_phase", expect.final_phase, observed.final_phase))
    cursor = 0  # events are expected in the order given, not necessarily next to each other
    for index, wanted in enumerate(expect.events_include):
        at = next((i for i in range(cursor, len(observed.events)) if _matches(wanted, observed.events[i])), None)
        if at is None:
            after = f"after event {cursor - 1}" if cursor else "anywhere"
            found.append(Mismatch(f"events_include[{index}]", wanted, f"no matching event {after}"))
            break  # the later ones depend on this one; the first divergence is the useful one
        cursor = at + 1
    for key, value in expect.trailers_include.items():
        values = list(observed.trailers.get(key, ()))
        if value not in values:
            found.append(Mismatch(f"trailers_include.{key}", value, values or "absent"))
    return found


def format_mismatches(mismatches: Sequence[Mismatch], events: Sequence[Mapping[str, Any]]) -> str:
    """One `expected`/`actual` pair per mismatch; for an event that never happened, the last event that did match
    its place (the nearest predecessor), so the reader sees where the run diverged."""
    lines = []
    for mismatch in mismatches:
        lines.append(f"{mismatch.field}: expected {mismatch.expected!r}, actual {mismatch.actual!r}")
        if mismatch.field.startswith("events_include["):
            wanted = mismatch.expected
            wanted_type = wanted.get("type")
            same_type = [e for e in events if e.get("type") == wanted_type]
            if same_type:
                lines.append(f"  closest event of that type: {dict(same_type[-1])!r}")
            elif events:
                lines.append(f"  no {wanted_type!r} event at all; the last event was {dict(events[-1])!r}")
            else:
                lines.append("  the run recorded no events")
    return "\n".join(lines)


def _scrub(value: Any, roots: Sequence[str]) -> Any:
    if isinstance(value, str):
        for root in roots:
            value = value.replace(root, "<tmp>")
        return _RUN_ID.sub("<run>", _SHA256.sub("<sha256>", _SHA.sub("<sha>", value)))
    if isinstance(value, Mapping):
        return {k: _scrub(v, roots) for k, v in value.items() if k not in _DROPPED_KEYS}
    if isinstance(value, list | tuple):
        return [_scrub(v, roots) for v in value]
    return value


def normalize_events(events: Sequence[Mapping[str, Any]], roots: Sequence[str] = ()) -> list[dict[str, Any]]:
    """Events as two runs of one scenario must agree on them: no timestamps, run ids, sequence numbers, lock holders,
    nonces or commit ids, the machine-dependent `sandbox.disabled` gone, and the temporary directories (`roots`)
    written as `<tmp>`."""
    ordered = sorted(roots, key=len, reverse=True)  # the longest prefix first
    return [_scrub(dict(e), ordered) for e in events if e.get("type") not in _DROPPED_TYPES]
