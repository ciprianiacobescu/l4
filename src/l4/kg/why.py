"""`l4 kg why ID`: the recorded history of one record (L4-KG-010, design D9, SCN-KG-20, SCN-KG-21).

`explain(nodes, edges, target)` reads the index records and returns text. It reads no file, no git and no network.
An id the index does not hold exits 2 with the forms it accepts (`L4Exit(USAGE_ERROR)`, as `promote` refuses).

**A unit id** gets a timeline, oldest first. Each attempt is a block: the kept attempts in the order of their number,
then the current branch. A block lists its runs (start, end, exit code, failed task attempts), its rounds (verdict,
the findings by blame, the gates that failed), and the stops (code, phase, detail), questions (kind, who answered),
retries and restarts that its runs recorded. Every line ends with `[src <sha10>:<path>#<seq or /pointer>]`, so that
`git show <sha10>:<path>` shows the record. A kept attempt whose ref is not local has no records in the index; the
block says so.

The last line holds the facts, as facts and not as a command: the stop codes with their counts across all attempts,
whether the unit folder changed after the last stop (the caller compares the commits with git) or a retry with the
reason `spec edited` came after it, and the attempt number. The attempt number
is the number a person counts: the current branch is one more than the highest kept attempt (graph attempt `@0` is the
current branch, design D4). The line before it names `l4 status --unit ID`, which stays the place for the next command
(its `Next:` line).

**A finding, a lesson, a run or a question** gets the 1-hop neighbourhood: every edge that leaves or reaches the node,
with its attributes and its `src`. A view with more than `MAX_EDGES` edges shows the first ones and counts the rest.

Text passes `redact_text` and `scrub_for_commit` once more at the end (L4-KG-011).
"""

from collections import Counter
from collections.abc import Iterable
from typing import Any

from l4.exitcodes import ExitCode, L4Exit
from l4.kg.model import Edge, Node, canonical_json
from l4.kg.view import View, clean_text, count_lines, n_of, short
from l4.redact import Redactor

ACCEPTED_FORMS = (
    "a unit (openspec:<name> or kiro:<name>), a finding (F-<8 hex>), a lesson (L-<8 hex>), "
    "a run (r-<run id>), or a question (<unit>#Q-<n>)"
)
MAX_EDGES = 200
NEIGHBOUR_TYPES = frozenset({"finding", "lesson", "run", "question"})
SPEC_EDIT_REASON = "spec edited"
SPEC_EDIT_SIGNAL = "spec_edit:"
TIMES = "×"
_NO_TS = "~"  # sorts after every time stamp


def last_stop_src(nodes: Iterable[Node], edges: Iterable[Edge], unit: str) -> str | None:
    """The `src` (`<sha10>:<path>#<seq>`) of the latest stop of `unit`, for the caller that compares the unit folder
    since that stop with git (design D9); None when the unit has no stop."""
    v = View(nodes, edges)
    stops = [e for e in v.of_type("STOPPED") if v.unit_of_run(e.from_id) == unit]
    return max(stops, key=lambda e: (e.ts, e.src)).src if stops else None


def explain(
    nodes: Iterable[Node],
    edges: Iterable[Edge],
    target: str,
    *,
    redactor: Redactor | None = None,
    spec_edited: bool = False,
) -> str:
    """`spec_edited`: the caller found a change in the unit folder since the last stop (git, which this module does
    not read); it adds to the `unit.retried{spec edited}` records."""
    v = View(nodes, edges)
    node = v.nodes.get(target)
    if node is None or (node.type != "unit" and node.type not in NEIGHBOUR_TYPES):
        message = f"{target!r} is not in the index. The ids that kg why accepts: {ACCEPTED_FORMS}."
        raise L4Exit(ExitCode.USAGE_ERROR, message)
    text = _timeline(v, node, spec_edited) if node.type == "unit" else _neighbourhood(v, node)
    return clean_text(text, redactor)


# --- the 1-hop view -----------------------------------------------------------------------------------------


def _show(value: Any) -> str:
    if isinstance(value, list):
        return f"[{len(value)} items]" if len(value) > 3 else canonical_json(value)
    return value if isinstance(value, str) else canonical_json(value)


def _attrs(attrs: Any) -> str:
    shown = [f"{k}={short(_show(val), 60)}" for k, val in sorted(attrs.items()) if val not in (None, "", [], False)]
    return " {" + ", ".join(shown) + "}" if shown else ""


def _type_of(v: View, node_id: str) -> str:
    node = v.nodes.get(node_id)
    return node.type if node is not None else "?"


def _neighbourhood(v: View, node: Node) -> str:
    touching = [e for e in v.edges if node.id in (e.from_id, e.to_id)]
    touching.sort(key=lambda e: (e.type, e.from_id, e.to_id, e.src))
    lines = [f"{node.type} {node.id}{_attrs(node.attrs)}", f"Edges: {n_of(len(touching), 'edge')}."]
    for edge in touching[:MAX_EDGES]:
        lines.append(
            f"- {edge.type}: {edge.from_id} ({_type_of(v, edge.from_id)}) -> {edge.to_id} ({_type_of(v, edge.to_id)})"
            f"{_attrs(edge.attrs)} [src {edge.src}]"
        )
    if len(touching) > MAX_EDGES:
        lines.append(f"... {n_of(len(touching) - MAX_EDGES, 'more edge', 'more edges')} are not shown.")
    return "\n".join(lines) + "\n"


# --- the timeline of a unit ---------------------------------------------------------------------------------


def _number(attempt_id: str) -> int:
    tail = attempt_id.rsplit("@", 1)[-1]
    return int(tail) if tail.isdigit() else 0


class _Line:
    def __init__(self, ts: str, rank: int, text: str, src: str) -> None:
        self.ts, self.rank, self.text, self.src = ts, rank, text, src

    def key(self) -> tuple[str, int, str]:
        return (self.ts or _NO_TS, self.rank, self.text)

    def render(self) -> str:
        stamp = self.ts or "-"
        return f"  {stamp}  {self.text}  [src {self.src or 'none'}]"


def _round_label(v: View, round_id: str) -> str:
    number, folder = v.attr(round_id, "round"), v.attr(round_id, "folder")
    unit_name = round_id.split("#", 1)[0].rsplit("@", 1)[0].split(":", 1)[-1]
    if isinstance(folder, str) and folder and folder != unit_name:
        return f"fix folder {folder}, round {number}"
    return f"round {number}"


def _round_line(v: View, edge: Edge) -> _Line:
    blame: Counter[str] = Counter()
    for raised in v.out(edge.to_id, "RAISED"):
        for value in v.blame_of(raised.to_id, of="finding", src=raised.src) or ["unknown"]:
            blame[value] += 1
    findings = f"findings by blame {count_lines(blame)}" if blame else "no findings (n = 0)"
    gates = sorted({g.to_id.removeprefix("gate:") for g in v.out(edge.to_id, "GATE_FAILED")})
    failed = f"failed gates: {', '.join(gates)}" if gates else "no failed gate (n = 0)"
    text = f"{_round_label(v, edge.to_id)}: {edge.attrs.get('verdict') or '?'}; {findings}; {failed}"
    return _Line(edge.ts, 2, text, edge.src)


def _run_lines(v: View, attempt_id: str) -> list[_Line]:
    lines = []
    for has_run in v.out(attempt_id, "HAS_RUN"):
        run = has_run.to_id
        attrs = v.nodes[run].attrs if run in v.nodes else {}
        failures = len(v.out(run, "ATTEMPT_FAILED"))
        text = f"run {run}: started {attrs.get('start', '?')}, finished {attrs.get('end', 'not recorded')}"
        if "exit_code" in attrs:
            text += f", exit {attrs['exit_code']}"
        text += f"; {n_of(failures, 'failed task attempt')}"
        lines.append(_Line(str(attrs.get("start") or has_run.ts), 1, text, has_run.src))
        for stop in v.out(run, "STOPPED"):
            detail = f": {stop.attrs['detail']}" if stop.attrs.get("detail") else ""
            code = stop.to_id.removeprefix("stop:")
            lines.append(_Line(stop.ts, 3, f"stop {code} ({stop.attrs.get('phase') or '?'}){detail}", stop.src))
        for ask in v.out(run, "ASKED"):
            qid = ask.to_id.rsplit("#", 1)[-1]
            by = ask.attrs.get("answered_by") or "not answered"
            lines.append(_Line(ask.ts, 3, f"question {qid}: {ask.attrs.get('kind') or '?'}, answered by {by}", ask.src))
        for retry in v.out(run, "RETRIED"):
            extra = f" (by {retry.attrs['by']})" if retry.attrs.get("by") else ""
            lines.append(_Line(retry.ts, 3, f"retried: {retry.attrs.get('reason') or '?'}{extra}", retry.src))
        for restart in v.out(run, "RESTARTED"):
            text = (
                f"restarted: {restart.attrs.get('reason') or '?'}; the attempt kept is {restart.attrs.get('attempt')}"
            )
            lines.append(_Line(restart.ts, 3, text, restart.src))
    return lines


def _spec_edit(edge: Edge) -> bool:
    return edge.attrs.get("reason") == SPEC_EDIT_REASON or str(edge.attrs.get("signal") or "").startswith(
        SPEC_EDIT_SIGNAL
    )


def _facts(v: View, unit: str, highest_kept: int, spec_edited: bool = False) -> str:
    stops = [e for e in v.of_type("STOPPED") if v.unit_of_run(e.from_id) == unit]
    codes = Counter(e.to_id.removeprefix("stop:") for e in stops)
    if codes:
        ordered = sorted(codes.items(), key=lambda item: (-item[1], item[0]))
        shown = ", ".join(f"{code} {TIMES}{n}" for code, n in ordered)
        last = max(e.ts for e in stops)
        edited = spec_edited or any(
            _spec_edit(e) and e.ts > last for e in v.of_type("RETRIED") if v.unit_of_attempt(e.to_id) == unit
        )
        edit = "yes" if edited else "no"
    else:
        shown, edit = "none (n = 0)", "no stop"
    return f"stops: {shown}; spec edited since the last stop: {edit}; attempt {highest_kept + 1}"


def _timeline(v: View, unit: Node, spec_edited: bool = False) -> str:
    ids = {e.to_id for e in v.out(unit.id, "HAS_ATTEMPT")}
    ids |= {e.to_id for e in v.of_type("RESTARTED") if v.unit_of_attempt(e.to_id) == unit.id}
    attempts = sorted(ids, key=lambda a: (_number(a) == 0, _number(a)))
    highest = max((_number(a) for a in attempts), default=0)
    out = [f"Unit {unit.id} ({unit.attrs.get('framework', '?')}); {n_of(len(attempts), 'attempt')} in the index."]
    for attempt in attempts:
        number = _number(attempt)
        has = next((e for e in v.out(unit.id, "HAS_ATTEMPT") if e.to_id == attempt), None)
        human = number if number else highest + 1
        if has is None:
            out.append(f"Attempt {human}: no records in the index (the ref is not local) [src none]")
            continue
        ref = f"refs/l4/attempts/{unit.attrs.get('framework')}/{unit.attrs.get('name')}/{number}"
        where = "current branch" if number == 0 else f"kept as {ref}"
        read = ", ".join(has.attrs.get("places") or ()) or "none"
        out.append(f"Attempt {human} ({where}; read from {read}) [src {has.src}]")
        lines = _run_lines(v, attempt) + [_round_line(v, e) for e in v.out(attempt, "HAS_ROUND")]
        out += [line.render() for line in sorted(lines, key=_Line.key)]
    out.append(f"The command to run is the job of `l4 status --unit {unit.id}` (its Next: line).")
    out.append(_facts(v, unit.id, highest, spec_edited))
    return "\n".join(out) + "\n"
