"""Findings of a readiness review: identifiers, history, resolution lines and rendering (review-resolution design
D1, section 8). Pure functions over ledger events; no git, no network.

A subject is named `<unit id>` or `batch:<batch id>` everywhere. A history entry is the recorded entry of
`plan.reviewed` (`verdict`, `digest`, `findings`, `material`, ...) plus the event's `at` and `source`, and a `material`
key that older entries get from the unit digest (a unit) or the event time (a batch).
"""

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from l4.yolo.model import PlanEvent

# A finding of these criteria is the harness saying that no review happened for the item (never reused, never a round).
HARNESS_CRITERIA = frozenset({"schema", "unit_missing", "completeness"})
BATCH_PREFIX = "batch:"

Entry = dict[str, Any]


def finding_id(subject: str, finding: Mapping[str, str]) -> str:
    """`F-` and the first six hex digits of sha256 of `subject NUL criterion NUL severity NUL text`."""
    raw = "\0".join((subject, finding.get("criterion", ""), finding.get("severity", ""), finding.get("text", "")))
    return "F-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:6]


def findings_sha(findings: Sequence[Mapping[str, Any]]) -> str:
    """The first 16 hex digits of sha256 of the findings as canonical JSON."""
    raw = json.dumps([dict(f) for f in findings], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# --- reading the ledger -----------------------------------------------------------------------------------------------


def _version(event: PlanEvent) -> int:
    version = event.data.get("prompt_version")
    return version if isinstance(version, int) and not isinstance(version, bool) else 1  # as the fold reads it


def _entries(event: PlanEvent) -> Iterable[tuple[str, Entry]]:
    """Every (subject, entry) of a `plan.reviewed` event: units first, then batches as `batch:<id>`."""
    for prefix, group in (("", event.data.get("units")), (BATCH_PREFIX, event.data.get("batches"))):
        for ident, entry in (group or {}).items():
            if isinstance(entry, dict) and entry.get("verdict") is not None:
                yield f"{prefix}{ident}", entry


def _harness(entry: Mapping[str, Any]) -> bool:
    return any(isinstance(f, dict) and f.get("criterion") in HARNESS_CRITERIA for f in entry.get("findings") or ())


def _key(subject: str, entry: Mapping[str, Any], event: PlanEvent) -> str:
    material = entry.get("material")
    if material:
        return str(material)
    if subject.startswith(BATCH_PREFIX):
        return event.at
    return str(entry.get("digest") or event.at)


def prior_entries(events: Sequence[PlanEvent], prompt_version: int) -> dict[str, Entry]:
    """Material key -> the newest recorded entry with it (current prompt version only), never one with a harness
    `schema`, `unit_missing` or `completeness` finding. The returned entry is a copy of the recorded one plus `at`: the
    time of the judgement itself (of the original when the recorded entry was already a reuse)."""
    found: dict[str, Entry] = {}
    for event in events:
        if event.type != "plan.reviewed" or _version(event) != prompt_version:
            continue
        for _, entry in _entries(event):
            material = entry.get("material")
            if not material or _harness(entry):
                continue
            found[str(material)] = {**entry, "at": str(entry.get("reused_from") or event.at)}
    return found


def history(events: Sequence[PlanEvent], subject: str, prompt_version: int) -> list[Entry]:
    """The subject's entries of the given prompt version, oldest first, each a copy with `at`, `source`, `material`."""
    out: list[Entry] = []
    for event in events:
        if event.type != "plan.reviewed" or _version(event) != prompt_version:
            continue
        for name, entry in _entries(event):
            if name == subject:
                out.append(
                    {
                        **entry,
                        "at": event.at,
                        "source": str(event.data.get("source") or "ci"),
                        "material": _key(subject, entry, event),
                    }
                )
    return out


def judged(hist: Sequence[Mapping[str, Any]]) -> list[Entry]:
    """One entry per distinct material key: the reuses dropped; a key judged again keeps its latest judgement, placed
    where that judgement was made."""
    seen: dict[str, Entry] = {}
    for entry in hist:
        if entry.get("reused_from"):
            continue
        key = str(entry["material"])
        seen.pop(key, None)
        seen[key] = dict(entry)
    return list(seen.values())


# --- the change between two judgements --------------------------------------------------------------------------------


def _ident(f: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(f.get("criterion")), str(f.get("severity")), str(f.get("text")))


@dataclass(frozen=True)
class RoundDiff:
    new: tuple[dict[str, Any], ...]
    repeated: tuple[dict[str, Any], ...]  # same criterion, severity and text
    gone: tuple[dict[str, Any], ...]
    # (criterion, severity) -> (findings before, findings now): rewording shows as a concern that stays
    by_criterion: dict[tuple[str, str], tuple[int, int]]


def diff(prev: Sequence[Mapping[str, Any]], cur: Sequence[Mapping[str, Any]]) -> RoundDiff:
    remaining = [dict(f) for f in prev]
    new: list[dict[str, Any]] = []
    repeated: list[dict[str, Any]] = []
    for f in cur:
        match = next((i for i, p in enumerate(remaining) if _ident(p) == _ident(f)), None)
        if match is None:
            new.append(dict(f))
        else:
            repeated.append(dict(f))
            del remaining[match]
    before = Counter(_ident(f)[:2] for f in prev)
    now = Counter(_ident(f)[:2] for f in cur)
    by_criterion = {k: (before[k], now[k]) for k in sorted(set(before) | set(now))}
    return RoundDiff(tuple(new), tuple(repeated), tuple(remaining), by_criterion)


def persistent(judged_entries: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Criterion -> the number of judgements, for each criterion raised at major or above in every judgement that was
    not READY, when there are at least two of them."""
    against = [e for e in judged_entries if e.get("verdict") != "READY"]
    if len(against) < 2:
        return {}
    counts: Counter[str] = Counter()
    for entry in against:
        counts.update(
            {str(f.get("criterion")) for f in entry.get("findings") or () if f.get("severity") in ("blocking", "major")}
        )
    every = {c: n for c, n in counts.items() if n == len(against)}
    return dict(sorted(every.items(), key=lambda kv: (-kv[1], kv[0])))


def rounds_not_ready(events: Sequence[PlanEvent], subject: str) -> int:
    """Distinct versions of the subject's own text judged not READY, over every prompt version. A unit's version is its
    entry's `digest`; a batch's is its entry's `digests` or, for an old entry, the unit digests of the event. A reuse,
    a prerequisite-only change and a review that did not happen (harness finding) add nothing."""
    versions: set[Any] = set()
    for event in events:
        if event.type != "plan.reviewed":
            continue
        for name, entry in _entries(event):
            if name != subject or entry.get("verdict") == "READY" or _harness(entry):
                continue
            if subject.startswith(BATCH_PREFIX):
                digests = entry.get("digests")
                if not isinstance(digests, dict):
                    digests = {
                        unit: e.get("digest")
                        for unit, e in (event.data.get("units") or {}).items()
                        if isinstance(e, dict)
                    }
                versions.add(tuple(sorted((str(u), str(d)) for u, d in digests.items())))
            elif entry.get("digest") is not None:
                versions.add(str(entry["digest"]))
    return len(versions)
