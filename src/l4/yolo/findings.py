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
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
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


def prior_entries(
    events: Sequence[PlanEvent], prompt_version: int, accepted: Mapping[str, Mapping[str, Any]] | None = None
) -> dict[str, Entry]:
    """Material key -> the newest recorded entry with it (current prompt version only), never one with a harness
    `schema`, `unit_missing` or `completeness` finding. The returned entry is a copy of the recorded one plus `at`: the
    time of the judgement itself (of the original when the recorded entry was already a reuse). For a material key that
    an acceptance in `accepted` (subject -> the `plan.accepted` data) is bound to, the entry is the newest one with
    that key whose `findings_sha` equals the acceptance's, when the ledger holds one (L4-YOLO-065, design D9.1)."""
    found: dict[str, Entry] = {}
    bound: dict[str, Entry] = {}
    wanted: dict[str, set[str]] = {}
    for item in (accepted or {}).values():
        if item.get("material") and item.get("findings_sha"):
            wanted.setdefault(str(item["material"]), set()).add(str(item["findings_sha"]))
    for event in events:
        if event.type != "plan.reviewed" or _version(event) != prompt_version:
            continue
        for _, entry in _entries(event):
            material = entry.get("material")
            if not material or _harness(entry):
                continue
            row = {**entry, "at": str(entry.get("reused_from") or event.at)}
            found[str(material)] = row
            if str(material) in wanted and findings_sha(entry.get("findings") or []) in wanted[str(material)]:
                bound[str(material)] = row
    return {**found, **bound}


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
                if digests:  # no digest at all: the version of the text cannot be told, so it is no round
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


_TIME_WORDS = re.compile(r"\b(time|timeout|time-out|duration|clock|seconds?|milliseconds?|deadline|wall-clock)\b", re.I)


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
        line = f"Give the scenario concrete inputs and outputs in {target}, including the failure and the empty case."
        if _TIME_WORDS.search(finding.get("text", "")):
            line += " A time bound needs a tolerance or an injected clock."
        return line
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
        return (
            "Edit one of the two statements so both say the same; if they live in two units, "
            "fix the one that is wrong and say which in the proposal."
        )
    if criterion == "missing_dependency":
        batch_note = f" (batch {batch})" if batch else ""
        named = _named_units(finding.get("text", ""), subject, depends_on, known_units)
        if named:
            ids = ", ".join(f'"{unit}"' for unit in named)
            return f"add {ids} to depends_on of {subject} in {plan_file}{batch_note}"
        batch_code = f" (batch `{batch}`)" if batch else ""
        return (
            f"Add a `depends_on` to `{subject}` in `{plan_file}`{batch_code} only on a unit of the plan that "
            "introduces it; if the code already exists on the base branch, say so in the spec instead."
        )
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


# --- showing the findings ---------------------------------------------------------------------------------------------

SCHEMA = "l4/yolo-findings@1"
_RANK = {"blocking": 0, "major": 1, "minor": 2}


def _by_severity(items: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Blocking, major, minor; the judge's order within a severity. An unknown severity comes last."""
    return sorted(items, key=lambda f: _RANK.get(str(f.get("severity")), len(_RANK)))


def most_severe(findings: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The finding the one-line views show: the first blocking, else the first major, else the first minor."""
    ordered = _by_severity(findings)
    return ordered[0] if ordered else None


@dataclass(frozen=True)
class UnitInfo:
    """What the plan says about a subject, for its `Resolve:` lines: a batch is given as `batch:<id>` with no folder."""

    folder: str | None = None
    batch: str | None = None
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Facts:
    subject: str
    verdict: str
    material: str | None
    findings: list[dict[str, Any]]
    assumptions: list[str]
    missing: list[str]
    since: RoundDiff | None
    persistent: dict[str, int]
    accepted: Mapping[str, Any] | None
    holds: bool
    accept_available: bool
    accept_refusal: Any = None  # the `accept.Refusal` (message, fix) of a not-READY subject that cannot be accepted
    why: str | None = None  # `accept.why_not_holds` of an acceptance that no longer holds


def _subjects(review: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    for prefix, group in (("", review.get("units")), (BATCH_PREFIX, review.get("batches"))):
        for ident, entry in (group or {}).items():
            if isinstance(entry, dict) and entry.get("verdict") is not None:
                yield f"{prefix}{ident}", entry


def _facts(
    review: Mapping[str, Any],
    history_of: Callable[[str], Sequence[Mapping[str, Any]]],
    *,
    show_all: bool,
    only: str | None,
    accepted: Mapping[str, Mapping[str, Any]] | None,
    holds: Mapping[str, bool] | None,
    can_accept: Callable[[str], Any] | None,
    why: Mapping[str, str] | None = None,
) -> list[_Facts]:
    out: list[_Facts] = []
    for subject, entry in _subjects(review):
        verdict = str(entry["verdict"])
        if only is not None:
            if subject != only:
                continue
        elif verdict == "READY" and not show_all:
            continue
        hist = list(history_of(subject))
        material = entry.get("material") or (hist[-1]["material"] if hist else None)
        judgements = judged(hist)
        earlier = [j for j in judgements if j["material"] != material]
        findings = [dict(f) for f in entry.get("findings") or ()]
        since = diff(earlier[-1].get("findings") or (), findings) if earlier else None
        accept = (accepted or {}).get(subject)
        accept_holds = bool((holds or {}).get(subject, False)) if accept else False
        refusal = None
        available = False
        if verdict != "READY" and not (accept and accept_holds) and can_accept is not None:
            refusal = can_accept(subject)
            available = refusal is None
        out.append(
            _Facts(
                subject=subject,
                verdict=verdict,
                material=str(material) if material else None,
                findings=findings,
                assumptions=[str(a) for a in entry.get("assumptions") or ()],
                missing=[str(m) for m in entry.get("missing") or ()],
                since=since,
                persistent=persistent(judgements),
                accepted=accept,
                holds=accept_holds,
                accept_available=available,
                accept_refusal=refusal,
                why=(why or {}).get(subject) if accept and not accept_holds else None,
            )
        )
    return out


def _resolver(plan_id: str, base: str, units: Mapping[str, UnitInfo] | None):
    known = [u for u in (units or {}) if not u.startswith(BATCH_PREFIX)]

    def line(subject: str, finding: Mapping[str, Any]) -> str:
        info = (units or {}).get(subject)
        if info is None and subject.startswith(BATCH_PREFIX):
            info = UnitInfo(batch=subject[len(BATCH_PREFIX) :])
        info = info or UnitInfo()
        return resolve(
            plan_id,
            base,
            subject,
            finding,
            folder=info.folder,
            batch=info.batch,
            depends_on=info.depends_on,
            known_units=known,
        )

    return line


def render(
    plan_id: str,
    base: str,
    review: Mapping[str, Any],
    history_of: Callable[[str], Sequence[Mapping[str, Any]]],
    *,
    show_all: bool = False,
    units: Mapping[str, UnitInfo] | None = None,
    accepted: Mapping[str, Mapping[str, Any]] | None = None,
    holds: Mapping[str, bool] | None = None,
    can_accept: Callable[[str], Any] | None = None,
    only: str | None = None,
    why: Mapping[str, str] | None = None,
) -> list[str]:
    """The text of `l4 yolo findings` for the latest review (`review` is the data of its `plan.reviewed` event;
    `history_of(subject)` is `history(...)` of the ledger). `can_accept(subject)` is the caller's `accept.check`:
    None when the subject may be accepted, else its `Refusal`. `only` names one subject, shown whatever its verdict."""
    resolver = _resolver(plan_id, base, units)
    lines: list[str] = []
    for fact in _facts(
        review, history_of, show_all=show_all, only=only, accepted=accepted, holds=holds, can_accept=can_accept, why=why
    ):
        lines.append(f"{fact.subject}: {fact.verdict}")
        shown = _by_severity(fact.findings)
        minors = [f for f in shown if f.get("severity") == "minor"]
        for f in shown if show_all else [f for f in shown if f.get("severity") != "minor"]:
            lines.append(f"  {finding_id(fact.subject, f)} [{f.get('severity')}/{f.get('criterion')}] {f.get('text')}")
            lines.append(f"    Resolve: {resolver(fact.subject, f)}")
        if minors and not show_all:
            n = len(minors)
            lines.append(f"  {n} minor finding{'s' if n != 1 else ''} (--all shows {'them' if n != 1 else 'it'})")
        if show_all:
            lines.extend(f"  assumption: {a}" for a in fact.assumptions)
            lines.extend(f"  missing: {m}" for m in fact.missing)
        if fact.since is not None:
            s = fact.since
            lines.append(
                f"  since the previous judgement: {len(s.new)} new, {len(s.repeated)} repeated, {len(s.gone)} gone"
            )
        if fact.persistent:
            lines.append("  persistent: " + ", ".join(f"{c} ×{n}" for c, n in fact.persistent.items()))
        if fact.accepted is not None:
            state = "holds" if fact.holds else f"no longer holds: it was for {fact.why or 'other material'}"
            lines.append(
                f"  accepted by {fact.accepted.get('by')} ({fact.accepted.get('actor')}): "
                f"{fact.accepted.get('reason')} ({state})"
            )
        if fact.accept_available:
            lines.append(f"  accept: l4 yolo accept {plan_id} {fact.subject} --reason TEXT")
        elif fact.accept_refusal is not None:
            lines.append(f"  accept: not available: {fact.accept_refusal.message} ({fact.accept_refusal.fix})")
    return lines


def render_json(
    plan_id: str,
    base: str,
    review: Mapping[str, Any],
    history_of: Callable[[str], Sequence[Mapping[str, Any]]],
    *,
    show_all: bool = False,
    units: Mapping[str, UnitInfo] | None = None,
    accepted: Mapping[str, Mapping[str, Any]] | None = None,
    holds: Mapping[str, bool] | None = None,
    can_accept: Callable[[str], Any] | None = None,
    only: str | None = None,
    why: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The same facts as `render`, as a JSON-serialisable document (`schema: l4/yolo-findings@1`). Every finding of a
    shown subject is listed, minor ones too, in the order of `render`."""
    resolver = _resolver(plan_id, base, units)
    subjects: list[dict[str, Any]] = []
    for fact in _facts(
        review, history_of, show_all=show_all, only=only, accepted=accepted, holds=holds, can_accept=can_accept, why=why
    ):
        since = None
        if fact.since is not None:
            since = {
                "new": len(fact.since.new),
                "repeated": len(fact.since.repeated),
                "gone": len(fact.since.gone),
                "by_criterion": [
                    {"criterion": c, "severity": s, "before": before, "now": now}
                    for (c, s), (before, now) in fact.since.by_criterion.items()
                ],
            }
        subjects.append(
            {
                "subject": fact.subject,
                "verdict": fact.verdict,
                "material": fact.material,
                "findings": [
                    {
                        "id": finding_id(fact.subject, f),
                        "criterion": f.get("criterion"),
                        "severity": f.get("severity"),
                        "text": f.get("text"),
                        "resolve": resolver(fact.subject, f),
                    }
                    for f in _by_severity(fact.findings)
                ],
                "minor": sum(1 for f in fact.findings if f.get("severity") == "minor"),
                "assumptions": fact.assumptions,
                "missing": fact.missing,
                "since": since,
                "persistent": fact.persistent,
                "accepted": (
                    {
                        "by": fact.accepted.get("by"),
                        "actor": fact.accepted.get("actor"),
                        "reason": fact.accepted.get("reason"),
                        "holds": fact.holds,
                        "why": fact.why,
                    }
                    if fact.accepted is not None
                    else None
                ),
                "accept_available": fact.accept_available,
                "accept_refusal": (
                    {"why": fact.accept_refusal.message, "fix": fact.accept_refusal.fix}
                    if fact.accept_refusal is not None
                    else None
                ),
            }
        )
    return {
        "schema": SCHEMA,
        "plan": plan_id,
        "base": base,
        "plan_digest": review.get("plan_digest"),
        "subjects": subjects,
    }
