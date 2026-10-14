"""`l4 kg report`: the index as markdown, with n on every number (L4-KG-006, L4-KG-008, L4-KG-009, design D5, D7, D8).

`render(nodes, edges, *, ...)` reads the nodes and edges that `store.read_index` or `extract` gave, and nothing else:
no git, no file, no network. It returns one markdown text. The caller (`kg/cli.py`) supplies what the index does not
hold: the base ref, its commit and its commit date (the manifest has no time, L4-KG-003, so the caller reads the date
with `git log -1 --format=%cI`), the skips of the manifest, and the warnings of the build.

The sections come in the order of design D8, and each has a heading with no digit: coverage, lessons, recurring
attempt failures, recurring findings, gate candidates, spec-gap hotspots, profiles by role, and stops. Rules that hold
for all of them:

- A line that carries a number names its n (`n = 2 units`). A section with no line says `none (n = 0)`.
- Lines are sorted by count (largest first), then by key, so equal inputs give equal text. `View` sorts the records
  first, so the order of the index does not matter.
- A count is of distinct units, never of finding ids (L4-KG-006). A key section says `approximate` in its heading:
  two different mistakes can share a key, and one reworded mistake can get two.
- `min_units` (default 2) is the recurrence floor. Gate candidates use `max(min_units, 3)`. Spec-gap hotspots have
  no floor: one spec gap is a line (SCN-KG-14).

What the lessons section counts (D7, L4-KG-008): the `INJECTED` edges are the prompts; units are the units of the runs
that were injected; tasks are distinct `(unit, task)`. A failure follows an injection when it is an `ATTEMPT_FAILED` of
the same run and task with a higher `seq`. A finding follows it when its recurrence key is a key the lesson is linked to
(by dedupe key only, L4-KG-005), it is raised in the same attempt, and its round has a time later than the injection.
A round with no time is never counted: nothing is guessed. The section says that it shows what followed a lesson, not
what the lesson caused. A failure class is cut at 80 characters (L4-KG-006), so a long reason loses its last letters
(the class of the `NotImplementedError` reason ends `notimplementederro`).

The index holds three gaps, and the report says so where they matter. It has no record of a task that passed at its
first attempt (a task is visible only through an injected prompt or a failed attempt), so the profiles section counts
failures and does not give a first-attempt share. It has no `merged` event; a stop whose unit sits in an archive folder,
with no later retry or restart, is counted as merged. It has no capability on a question or a NEEDS_HUMAN round; they
count for each capability of their unit's criteria (a Kiro capability is the unit).
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence

from l4.kg.model import Edge, Node
from l4.kg.sources import FETCH_ATTEMPTS, PLACES
from l4.kg.view import (
    UNKNOWN_UNIT,
    View,
    clean_text,
    count_lines,
    display_key,
    event_seq,
    joined,
    n_of,
    plural,
    short,
)
from l4.redact import Redactor

DEFAULT_MIN_UNITS = 2
GATE_FLOOR = 3
SECTIONS = (
    "Coverage",
    "Lessons",
    "Recurring attempt failures",
    "Recurring findings",
    "Gate candidates",
    "Spec-gap hotspots",
    "Profiles by role",
    "Stops",
)
APPROXIMATE = " (approximate)"
NONE = "none (n = 0)"
NO_CAPABILITY = "(no capability recorded)"
QUESTION_KINDS = frozenset({"product", "ambiguous"})
SPEC_EDIT_REASON = "spec edited"


def _bullets(lines: Sequence[str]) -> list[str]:
    return [f"- {line}" for line in lines] if lines else [NONE]


def _count_key(row: tuple[str, int]) -> tuple[int, str]:
    return (-row[1], row[0])


# --- 1. coverage --------------------------------------------------------------------------------------------


def _coverage(
    v: View,
    *,
    base_ref: str,
    base_sha: str | None,
    base_date: str | None,
    skipped: Mapping[str, int],
    warnings: Sequence[str],
    min_units: int,
) -> list[str]:
    commit = base_sha[:10] if base_sha else "none"
    lines = [
        f"Base ref: {base_ref}, commit {commit}, committed {base_date or 'unknown'}. "
        "History newer than this commit is not read: run `git fetch` first."
    ]
    lines.append(
        f"Floor: a key needs at least {n_of(min_units, 'unit')}; "
        f"a gate candidate needs at least {n_of(max(min_units, GATE_FLOOR), 'unit')}."
    )
    units = v.nodes_of("unit")
    places: dict[str, set[str]] = {place: set() for place in PLACES}
    for edge in v.of_type("HAS_ATTEMPT"):
        for place in edge.attrs.get("places") or ():
            places.setdefault(place, set()).add(edge.from_id)
    by_place = ", ".join(f"{place} n = {len(ids)}" for place, ids in places.items())
    lines.append(f"Units: {n_of(len(units), 'unit')} ({by_place}).")
    lines.append(f"Attempts: {n_of(len(v.nodes_of('attempt')), 'attempt')}.")
    lines.append(f"Runs: {n_of(len(v.nodes_of('run')), 'run')}.")
    lines.append(f"Rounds: {n_of(len(v.nodes_of('round')), 'round')}.")
    shown = sorted((reason, n) for reason, n in skipped.items() if n)
    if shown:
        lines.append("Skipped inputs: " + "; ".join(f"{reason}: n = {n}" for reason, n in shown) + ".")
    else:
        lines.append(f"Skipped inputs: {NONE}.")
    if skipped.get("attempt_not_local"):
        lines.append(f"To read the attempts that are not local, run `{FETCH_ATTEMPTS}`. This command never fetches.")
    lines += [f"Warning: {short(w, 200)}" for w in sorted(set(warnings))]
    return _bullets(lines)


# --- 2. lessons ---------------------------------------------------------------------------------------------


def _followed_failures(v: View, injections: Sequence[Edge]) -> set[Edge]:
    by_run: dict[str, list[Edge]] = defaultdict(list)
    for edge in v.of_type("ATTEMPT_FAILED"):
        by_run[edge.from_id].append(edge)
    followed: set[Edge] = set()
    for inj in injections:
        seq = inj.attrs.get("seq")
        for fail in by_run.get(inj.from_id, ()):
            later = isinstance(seq, int) and isinstance(fail.attrs.get("seq"), int) and fail.attrs["seq"] > seq
            if later and fail.attrs.get("task") == inj.attrs.get("task"):
                followed.add(fail)
    return followed


def _followed_findings(v: View, lesson_id: str, injections: Sequence[Edge]) -> set[tuple[str, str, str]]:
    """`(round, finding, key)` of the findings in later rounds of an injected attempt, with the lesson's linked key."""
    first_ts: dict[str, str] = {}  # attempt -> the earliest injection time
    for inj in injections:
        attempt = v.attempt_of_run(inj.from_id)
        if attempt is not None and inj.ts:
            first_ts[attempt] = min(inj.ts, first_ts.get(attempt, inj.ts))
    found: set[tuple[str, str, str]] = set()
    for link in v.out(lesson_id, "KEYED"):
        if not link.to_id.startswith("recurrence:"):
            continue
        for keyed in v.into(link.to_id, "KEYED"):
            if keyed.from_id not in v.nodes or v.nodes[keyed.from_id].type != "finding":
                continue
            for raised in v.into(keyed.from_id, "RAISED"):
                since = first_ts.get(v.attempt_of_round(raised.from_id))
                if since is not None and raised.ts and raised.ts > since:
                    found.add((raised.from_id, keyed.from_id, link.to_id.removeprefix("recurrence:")))
    return found


def _lesson_line(v: View, lesson: Node) -> tuple[int, str, str]:
    injections = v.into(lesson.id, "INJECTED")
    prompts = len(injections)
    units = {v.unit_of_run(e.from_id) for e in injections}
    tasks = {(v.unit_of_run(e.from_id), e.attrs.get("task")) for e in injections}
    title = lesson.attrs.get("title")
    name = f'{lesson.id} "{title}"' if title else f"{lesson.id} (seen only in events)"
    if lesson.attrs.get("archived"):
        name += " [archived]"
    head = f"{name} ({n_of(prompts, 'prompt')}): "
    if not injections:
        return prompts, lesson.id, head + "never injected"
    counts = f"{len(units)} {plural(len(units), 'unit')} / {len(tasks)} {plural(len(tasks), 'task')} / {prompts} "
    counts += plural(prompts, "prompt")
    failures = _followed_failures(v, injections)
    findings = _followed_findings(v, lesson.id, injections)
    total = len(failures) + len({(r, f) for r, f, _ in findings})
    if total == 0:
        return prompts, lesson.id, head + f"injected, nothing followed ({counts})"
    parts: list[str] = []
    classes = Counter((str(e.attrs.get("phase") or "?"), e.to_id.removeprefix("failure:")) for e in failures)
    for (phase, cls), n in sorted(classes.items(), key=lambda item: (-item[1], item[0])):
        parts.append(f"{phase}: {cls}" + (f" ×{n}" if n > 1 else ""))
    parts += [f"finding: {display_key(key)}" for key in sorted({key for _, _, key in findings})]
    status = f"followed by {total} {plural(total, 'failure')} ({'; '.join(parts)})"
    return prompts, lesson.id, head + f"injected {counts}, {status}"


def _lessons(v: View) -> list[str]:
    rows = sorted((_lesson_line(v, lesson) for lesson in v.nodes_of("lesson")), key=lambda r: (-r[0], r[1]))
    return _bullets([row[2] for row in rows])


# --- 3. recurring attempt failures --------------------------------------------------------------------------


def _by_failure_class(v: View) -> dict[str, list[Edge]]:
    classes: dict[str, list[Edge]] = defaultdict(list)
    for edge in v.of_type("ATTEMPT_FAILED"):
        classes[edge.to_id.removeprefix("failure:")].append(edge)
    return classes


def _failure_rows(v: View, floor: int) -> list[tuple[str, set[str], list[Edge]]]:
    rows = []
    for cls, found in _by_failure_class(v).items():
        units = {v.unit_of_run(e.from_id) for e in found}
        if len(units) >= floor:
            rows.append((cls, units, found))
    return sorted(rows, key=lambda r: (-len(r[1]), -len(r[2]), r[0]))


def _recurring_failures(v: View, floor: int) -> list[str]:
    lines = []
    for cls, units, found in _failure_rows(v, floor):
        phases = Counter(str(e.attrs.get("phase") or "?") for e in found)
        blame: Counter[str] = Counter()
        for e in found:
            for value in v.blame_of(e.from_id, of="task.attempt_failed", src=e.src) or ["unknown"]:
                blame[value] += 1
        lines.append(
            f"{cls}: {n_of(len(units), 'unit')}, {n_of(len(found), 'attempt')}; "
            f"phase {count_lines(phases)}; blame {count_lines(blame)}"
        )
    return _bullets(lines)


# --- 4. recurring findings ----------------------------------------------------------------------------------


class _Raised:
    """One RAISED edge with the unit, the key and the blame of its finding."""

    def __init__(self, edge: Edge, unit: str, key: str, blame: Sequence[str]) -> None:
        self.edge, self.unit, self.key, self.blame = edge, unit, key, blame


def _raised(v: View) -> list[_Raised]:
    out = []
    for edge in v.of_type("RAISED"):
        keys = [k.to_id.removeprefix("recurrence:") for k in v.out(edge.to_id, "KEYED")]
        blame = v.blame_of(edge.to_id, of="finding") or ["unknown"]
        for key in keys:
            out.append(_Raised(edge, v.unit_of_round(edge.from_id), key, blame))
    return out


def _by_key(raised: Iterable[_Raised]) -> dict[str, list[_Raised]]:
    keys: dict[str, list[_Raised]] = defaultdict(list)
    for row in raised:
        keys[row.key].append(row)
    return keys


def _per_unit(rows: Sequence[_Raised], value) -> dict[str, int]:
    """For each value, the number of distinct units that have it."""
    seen: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        for item in value(row):
            seen[item].add(row.unit)
    return {item: len(units) for item, units in seen.items()}


def _recurring_findings(v: View, floor: int) -> list[str]:
    rows = []
    for key, found in _by_key(_raised(v)).items():
        units = sorted({r.unit for r in found})
        if len(units) >= floor:
            rows.append((key, units, found))
    lines = []
    for key, units, found in sorted(rows, key=lambda r: (-len(r[1]), r[0])):
        rounds = {r.edge.from_id for r in found}
        severity = _per_unit(found, lambda r: [str(r.edge.attrs.get("severity") or "?")])
        source = _per_unit(found, lambda r: [str(r.edge.attrs.get("source") or "?")])
        blame = _per_unit(found, lambda r: r.blame)
        lines.append(
            f"{display_key(key)}: {n_of(len(units), 'unit')} ({joined(units)}), {n_of(len(rounds), 'round')}; "
            f"severity {count_lines(severity)}; source {count_lines(source)}; blame {count_lines(blame)}"
        )
    return _bullets(lines)


# --- 5. gate candidates -------------------------------------------------------------------------------------


def _gate_candidates(v: View, floor: int) -> list[str]:
    rows: list[tuple[int, str, str]] = []
    for key, found in _by_key(r for r in _raised(v) if r.edge.attrs.get("source") == "deterministic").items():
        units = {r.unit for r in found}
        if len(units) >= floor:
            rounds = len({r.edge.from_id for r in found})
            text = f"finding {display_key(key)}: {n_of(len(units), 'unit')}, {n_of(rounds, 'round')}"
            rows.append((len(units), f"1 {key}", text))
    for cls, units, found in _failure_rows(v, floor):
        rows.append(
            (len(units), f"0 {cls}", f"failure class {cls}: {n_of(len(units), 'unit')}, {n_of(len(found), 'attempt')}")
        )
    return _bullets([text for _, _, text in sorted(rows, key=lambda r: (-r[0], r[1]))])


# --- 6. spec-gap hotspots -----------------------------------------------------------------------------------


def _unit_capabilities(v: View) -> dict[str, set[str]]:
    caps: dict[str, set[str]] = defaultdict(set)
    for edge in v.of_type("IN_CAPABILITY"):
        caps[str(v.attr(edge.from_id, "unit") or edge.from_id.split("#", 1)[0])].add(edge.to_id.removeprefix("cap:"))
    for unit in v.nodes_of("unit"):
        if unit.attrs.get("framework") == "kiro":
            caps[unit.id].add(str(unit.attrs.get("name") or unit.id.split(":", 1)[-1]))
    return caps


def _hotspots(v: View) -> list[str]:
    caps_of = _unit_capabilities(v)

    def capabilities(unit: str) -> set[str]:
        return caps_of.get(unit) or {NO_CAPABILITY}

    findings: dict[str, set[str]] = defaultdict(set)
    questions: dict[str, set[str]] = defaultdict(set)
    rounds: dict[str, set[str]] = defaultdict(set)
    units: dict[str, set[str]] = defaultdict(set)
    for edge in v.of_type("CLASSIFIED"):
        if edge.attrs.get("of") != "finding" or edge.to_id != "blame:spec":
            continue
        for about in v.out(edge.from_id, "ABOUT"):
            for cap in v.out(about.to_id, "IN_CAPABILITY"):
                name = cap.to_id.removeprefix("cap:")
                findings[name].add(edge.from_id)
                units[name].update(v.unit_of_round(r.from_id) for r in v.into(edge.from_id, "RAISED"))
    for edge in v.of_type("ASKED"):
        if edge.attrs.get("kind") in QUESTION_KINDS:
            unit = edge.to_id.split("#", 1)[0]
            for name in capabilities(unit):
                questions[name].add(edge.to_id)
                units[name].add(unit)
    for edge in v.of_type("HAS_ROUND"):
        if edge.attrs.get("verdict") == "NEEDS_HUMAN":
            unit = v.unit_of_attempt(edge.from_id)
            for name in capabilities(unit):
                rounds[name].add(edge.to_id)
                units[name].add(unit)
    rows = []
    for name in set(findings) | set(questions) | set(rounds):
        total = len(findings[name]) + len(questions[name]) + len(rounds[name])
        rows.append((len(units[name]), total, name))
    lines = []
    for n_units, _, name in sorted(rows, key=lambda r: (-r[0], -r[1], r[2])):
        lines.append(
            f"{name}: {n_of(n_units, 'unit')}; spec-blame findings n = {len(findings[name])}; "
            f"product or ambiguous questions n = {len(questions[name])}; NEEDS_HUMAN rounds n = {len(rounds[name])}"
        )
    return _bullets(lines)


# --- 7. profiles by role ------------------------------------------------------------------------------------

IMPLEMENTER = "implementer"


def _selections(v: View) -> dict[str, list[tuple[int, str, str]]]:
    """For each run, its profile choices `(seq, role, profile)` in order."""
    chosen: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for edge in v.of_type("USED_PROFILE"):
        seq = event_seq(edge.src)
        chosen[edge.from_id].append(
            (seq if seq is not None else -1, str(edge.attrs.get("role") or "?"), edge.to_id.removeprefix("profile:"))
        )
    return {run: sorted(rows) for run, rows in chosen.items()}


def _profiles(v: View) -> list[str]:
    chosen = _selections(v)
    runs: dict[tuple[str, str], set[str]] = defaultdict(set)
    for run, rows in chosen.items():
        for _, role, profile in rows:
            runs[(role, profile)].add(run)
    failed: dict[tuple[str, str], list[Edge]] = defaultdict(list)
    for edge in v.of_type("ATTEMPT_FAILED"):
        seq = edge.attrs.get("seq")
        picks = [
            p
            for s, role, p in chosen.get(edge.from_id, ())
            if role == IMPLEMENTER and isinstance(seq, int) and s <= seq
        ]
        if picks:
            failed[(IMPLEMENTER, picks[-1])].append(edge)
    first: dict[str, list[str]] = defaultdict(list)  # implementer profile -> verdicts of its first rounds
    for edge in v.of_type("HAS_ROUND"):
        if edge.to_id.endswith("#round-1"):
            for profile in edge.attrs.get("implementer") or ():
                first[profile].append(str(edge.attrs.get("verdict") or ""))
    keys = set(runs) | set(failed) | {(IMPLEMENTER, p) for p in first}
    lines = []
    for role, profile in sorted(keys, key=lambda k: (-len(runs.get(k, ())), k)):
        parts = [n_of(len(runs.get((role, profile), ())), "run")]
        if role == IMPLEMENTER:
            fails = failed.get((role, profile), [])
            tasks = {(e.from_id, e.attrs.get("task")) for e in fails}
            parts.append(f"{n_of(len(tasks), 'task')} with a failed attempt")
            parts.append(n_of(len(fails), "failed attempt"))
            if tasks:
                parts.append(f"mean {len(fails) / len(tasks):.1f} failed attempts per such task")
            rounds = first.get(profile, [])
            passed = sum(1 for verdict in rounds if verdict == "PASS")
            share = f" ({round(100 * passed / len(rounds))}%)" if rounds else ""
            parts.append(f"first-round PASS n = {passed} of n = {len(rounds)}{share}")
        lines.append(f"{role} / {profile}: " + "; ".join(parts))
    return _bullets(lines)


PROFILES_NOTE = (
    "The index has no record of a task that passed at its first attempt: a task is visible only through an injected "
    "prompt or a failed attempt. So this section counts failed attempts, and gives no first attempt share. "
    "The eval scorecards stay the authority for comparing models."
)


# --- 8. stops -----------------------------------------------------------------------------------------------


def _stops(v: View) -> list[str]:
    retried: dict[str, list[str]] = defaultdict(list)
    restarted: dict[str, list[str]] = defaultdict(list)
    for edge in v.of_type("RETRIED"):
        retried[v.unit_of_attempt(edge.to_id)].append(edge.ts)
    for edge in v.of_type("RESTARTED"):
        restarted[v.unit_of_attempt(edge.to_id)].append(edge.ts)
    merged = {e.from_id for e in v.of_type("HAS_ATTEMPT") if "archive" in (e.attrs.get("places") or ())}
    by_code: dict[str, list[tuple[str, str]]] = defaultdict(list)  # code -> [(unit, how it ended)]
    for edge in v.of_type("STOPPED"):
        unit = v.unit_of_run(edge.from_id)
        later = [("retried", t) for t in retried.get(unit, ()) if t > edge.ts]
        later += [("restarted", t) for t in restarted.get(unit, ()) if t > edge.ts]
        ended = "merged" if unit in merged else "still stopped"
        how = min(later, key=lambda item: item[1])[0] if later else ended
        by_code[edge.to_id.removeprefix("stop:")].append((unit, how))
    lines = []
    for code, rows in sorted(by_code.items(), key=lambda item: (-len({u for u, _ in item[1]}), item[0])):
        ends = Counter(how for _, how in rows)
        lines.append(
            f"{code}: {n_of(len({u for u, _ in rows}), 'unit')}, {n_of(len(rows), 'stop')}; "
            + ", ".join(f"{how} n = {ends.get(how, 0)}" for how in ("retried", "restarted", "merged", "still stopped"))
        )
    return _bullets(lines)


# --- the report ---------------------------------------------------------------------------------------------

PREFACES = {
    "Coverage": "",
    "Lessons": (
        "This shows what followed each lesson, not what the lesson caused. A lesson is linked to a finding key only "
        "by its dedupe key."
    ),
    "Recurring attempt failures": (
        "A failure class is the first part of the reason of a failed task attempt, normalised."
    ),
    "Recurring findings": (
        "A key is the normalised title and the normalised requirement and scenario of the criterion."
    ),
    "Gate candidates": (
        "Deterministic findings and failure classes that recur in many units. A person may write a deterministic "
        "gate or a lint rule; this report writes nothing."
    ),
    "Spec-gap hotspots": (
        "Kiro capabilities are units. A question or a NEEDS_HUMAN round counts for each capability of its unit's "
        "criteria."
    ),
    "Profiles by role": PROFILES_NOTE,
    "Stops": (
        "How a stop ended: a later retry or restart of the unit, else merged when the unit is in an archive folder, "
        "else still stopped."
    ),
}


def render(
    nodes: Iterable[Node],
    edges: Iterable[Edge],
    *,
    base_ref: str = "HEAD",
    base_sha: str | None = None,
    base_date: str | None = None,
    skipped: Mapping[str, int] | None = None,
    warnings: Sequence[str] = (),
    min_units: int = DEFAULT_MIN_UNITS,
    redactor: Redactor | None = None,
) -> str:
    """The report. `base_date` is not in the index (L4-KG-003): the caller reads it with `git log -1 --format=%cI`."""
    v = View(nodes, edges)
    floor = max(min_units, 1)
    gate_floor = max(min_units, GATE_FLOOR)
    bodies = {
        "Coverage": _coverage(
            v,
            base_ref=base_ref,
            base_sha=base_sha,
            base_date=base_date,
            skipped=skipped or {},
            warnings=warnings,
            min_units=floor,
        ),  # fmt: skip
        "Lessons": _lessons(v),
        "Recurring attempt failures": _recurring_failures(v, floor),
        "Recurring findings": _recurring_findings(v, floor),
        "Gate candidates": _gate_candidates(v, gate_floor),
        "Spec-gap hotspots": _hotspots(v),
        "Profiles by role": _profiles(v),
        "Stops": _stops(v),
    }
    out = ["# Experience report", ""]
    for title in SECTIONS:
        heading = title + (APPROXIMATE if title in KEY_SECTIONS else "")
        out += [f"## {heading}", ""]
        if PREFACES[title]:
            out += [PREFACES[title], ""]
        out += [*bodies[title], ""]
    return clean_text("\n".join(out), redactor)


KEY_SECTIONS = frozenset({"Lessons", "Recurring attempt failures", "Recurring findings", "Gate candidates"})
__all__ = ["DEFAULT_MIN_UNITS", "SECTIONS", "UNKNOWN_UNIT", "render"]
