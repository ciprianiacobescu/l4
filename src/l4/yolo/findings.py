"""Findings of a readiness review: identifiers, history, resolution lines and rendering (review-resolution design
D1, section 8). Pure functions over ledger events; no git, no network.

A subject is named `<unit id>` or `batch:<batch id>` everywhere. A history entry is the recorded entry of
`plan.reviewed` (`verdict`, `digest`, `findings`, `material`, ...) plus the event's `at` and `source`, and a `material`
key that older entries get from the unit digest (a unit) or the event time (a batch).
"""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
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


# --- how to resolve a finding (design D1) -------------------------------------------------------------------------


def _id_pattern(unit_id: str) -> re.Pattern[str]:
    """The id as a whole token: not part of a longer id (`openspec:ab`), a trailing full stop is not part of it."""
    return re.compile(rf"(?<![\w:.\-]){re.escape(unit_id)}(?![\w:\-])(?!\.\w)")


def _named_units(text: str, subject: str, depends_on: Collection[str], known_units: Collection[str]) -> list[str]:
    return [
        unit
        for unit in sorted(known_units)
        if unit != subject and unit not in depends_on and _id_pattern(unit).search(text)
    ]


def resolve(
    plan_id: str,
    base: str,
    subject: str,
    finding: Mapping[str, str],
    *,
    folder: str | None,
    batch: str | None,
    depends_on: Collection[str] = (),
    known_units: Collection[str] = (),
) -> str:
    """The `Resolve:` text of a finding (without the label): harness text per criterion with the subject's folder, the
    plan file and the batch filled in. Nothing is parsed from the finding but the ids of the plan's own units."""
    criterion = finding.get("criterion", "")
    where = folder if folder else "the unit's folder"
    kiro = subject.startswith("kiro:")
    plan_file = f".l4/plans/{plan_id}.json"
    if criterion == "outcome":
        target = f"{where}/requirements.md" if kiro else f"{where}/proposal.md or the spec"
        return f"State the observable result in {target}, not only the work."
    if criterion == "testability":
        target = f"{where}/requirements.md" if kiro else f"{where}/specs/*/spec.md"
        return (
            f"Give the scenario concrete inputs and outputs in {target}; "
            "a time bound needs a tolerance or an injected clock."
        )
    if criterion == "interfaces":
        return (
            "Fix names, signatures, data shapes and error values in the spec "
            "(the implementer and the dependent units read the spec, not only tasks.md)."
        )
    if criterion == "failure_cases":
        return "State what happens on bad input, absence, concurrency and a failing dependency."
    if criterion == "feasibility":
        return (
            "Split the unit (a new change folder and a plan entry) "
            "or remove the part that needs a person, a secret or a service."
        )
    if criterion == "duplicate_scope":
        return "Remove the overlap from one of the units the finding names."
    if criterion == "contradiction":
        return "Make the two statements agree, in this folder or in a prerequisite's."
    if criterion == "missing_dependency":
        batch_note = f" (batch {batch})" if batch else ""
        named = _named_units(finding.get("text", ""), subject, depends_on, known_units)
        if named:
            ids = ", ".join(f'"{unit}"' for unit in named)
            return f"add {ids} to depends_on of {subject} in {plan_file}{batch_note}"
        batch_code = f" (batch `{batch}`)" if batch else ""
        return f"Add the unit it needs to `depends_on` of `{subject}` in `{plan_file}`{batch_code}."
    if criterion == "batch_acceptance":
        name = batch or (subject[len(BATCH_PREFIX) :] if subject.startswith(BATCH_PREFIX) else "the batch")
        return (
            f"State the batch outcome in a unit's proposal, or give batch {name} "
            "an acceptance profile that can show it."
        )
    if criterion == "material":
        return finding.get("text", "")
    if criterion == "schema":
        return f"No review happened for this item: run the review again (l4 yolo review {plan_id})."
    if criterion in ("unit_missing", "completeness"):
        return (
            "No review happened for this item: push the folder to "
            f"{base} or remove the unit from {plan_file}, then run the review again (l4 yolo review {plan_id})."
        )
    if criterion == "verdict":
        return (
            "The judge said NEEDS_REVISION and named no finding: read the missing list, "
            f"or ask again with l4 yolo review {plan_id} --worktree --fresh {subject}."
        )
    return "Read the finding and change the specification it points to, then run the review again."
