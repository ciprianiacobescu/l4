"""The records `sources.collect` returned, as nodes and edges (L4-KG-005, L4-KG-011, design D4, D6, D12).

`extract(collected, redactor, git=None)` is pure over its input: it calls no model, no forge and no network, and its
only git calls are `cat-file -e` and `diff --name-only`, which it makes for the changed files of a round (see below).
It reads nothing from the work tree. The same `Collected` gives the same nodes and edges, in any order, because the
writer (`model.jsonl_bytes`) sorts.

Every edge carries `src`: `<sha10>:<path>#<seq>` for a ledger event (`SourcedEvent.src`) and `<sha10>:<path>#/<json
pointer>` for a `verdict.json` field (`VerdictFile.src`), so that a line of a report can be checked with `git show`
(SCN-KG-10). An edge made from an event keeps the event's `ts`; one made from `verdict.json` takes the `ts` of the
round's `verify.verdict` event, else the empty string. No `ts` is a build time (L4-KG-003).

What each record becomes:

- A unit is the node `openspec:<name>` or `kiro:<name>`. Each attempt is `<unit>@<n>` (0: the current branch and the
  base folders), joined by `HAS_ATTEMPT` (its attrs name the places and folders read). A run is `HAS_RUN` of its
  attempt.
- A ledger event gives: `USED_PROFILE{role}` (`availability.selected`), `INJECTED{task, role, seq}` (one per lesson id
  of `prompt.rendered`), `ATTEMPT_FAILED{task, phase, attempt, seq}` to the failure class (`normalise.failure_class`),
  `ASKED{kind, source, answered_by}` (`question.raised`, joined to its `question.answered` by id), `STOPPED{phase,
  detail}` (a `phase.changed` into `halted` or `escalated`; the code is its `reason`), `RETRIED{reason}`,
  `RESTARTED{attempt, reason}` (to the attempt the restart kept) and `VERDICT{verdict}` (`verify.verdict`, to the
  round).
- A round of `verdict.json` is `<unit>@<n>#round-<k>` (a fix-unit folder `<unit>@<n>#<folder>/round-<k>`), joined by
  `HAS_ROUND{verdict, base_sha, head_sha, judge, implementer, files | files_unknown}`. A finding is `RAISED{severity,
  source, spec_gap}` by the round, `ABOUT` its criterion `<unit>#<C-id>`, and `KEYED` to `recurrence:<key>`
  (`normalise.recurrence_key`, which drops the capability part, so two units meet). A criterion is `IN_CAPABILITY` of
  `cap:<first part of its alias>` (OpenSpec) or `cap:<unit name>` (Kiro). A failed gate is `GATE_FAILED`.
- The changed files of a round come from `git diff --name-only base_sha head_sha`, only when both commits are local.
  After a squash merge they often are not: the round then has `files_unknown: true`, nothing is guessed, and
  `Extracted.skipped["files_unknown"]` counts them.
- Blame (design D6, `blame.classify`): `CLASSIFIED{of}` to `blame:<value>`, for each finding (from the finding),
  question (from the question), NEEDS_HUMAN round (from the round), and, from the run, for each stop and attempt
  failure, and for each event the table names (`guard.*`, `verify.error`, ...). A `CLASSIFIED` made from an event has
  the `src` of the edge it classifies (`STOPPED`, `ATTEMPT_FAILED`) so that a reader joins them on `src`. A guard
  event also carries its `rule` (the harness's own rule name, as `memory.curate` derives it), which `propose` pattern
  (c) counts.
- A lesson is `L-<id>` with its title, dedupe key, scope, and whether it is archived. It is linked by its dedupe key
  only (L4-KG-005, SCN-KG-11): a `LESSON_RULES` key gives `KEYED` from the lesson to every recurrence key seen whose
  title part is that rule's `finding_title` (the criterion part differs from unit to unit; with none seen, to the bare
  key); a `kg-a-<slug>` key to the failure class, and a `kg-b-<slug>` key to the recurrence key, that `slug()` of
  makes `<slug>`. A `kg-c-` key (a guard rule) has no node to link to. The `Source` line is never read.

Every string that enters a node or an edge, ids and `src` included, passes `redact_text` and then `scrub_for_commit`
(L4-KG-011, SCN-KG-22). A reason is redacted before its class is made. No question text, answer text, judge detail or
agent output is stored: a finding node holds only its title, and a failure only its class.

A node id that two records make is one node. Its attrs are the same by construction; if they ever differ, the keys are
merged and a conflicting value keeps the greater canonical text, so the result does not depend on the order. An
exception while reading one unit skips that unit (`skipped["error"]`), as in `sources` (L4-KG-002).

"""

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from l4.kg import blame
from l4.kg.model import Edge, Node, canonical_json
from l4.kg.normalise import ALIAS_SEPARATOR, KEY_SEPARATOR, failure_class, norm, recurrence_key
from l4.kg.sources import Collected, LessonRecord, UnitRecord, VerdictFile
from l4.memory.curate import LESSON_RULES, _guard_rule
from l4.redact import Redactor
from l4.state.ledger import TS_FORMAT
from l4.vcs.git import Git

log = logging.getLogger("l4.kg")

MAX_FILES = 1000  # changed files kept on one round
MAX_TEXT = 300
STOP_PHASES = ("halted", "escalated")
GUARD_EVENTS = frozenset({"guard.violation", "guard.test_tamper"})
CLASSIFIED_EVENTS = frozenset(
    {
        "guard.secret", "guard.violation", "guard.test_tamper", "verify.error", "gate.hung", "ci.preexisting",
        "availability.limit", "judge.reply_repaired", "feedback.not_addressed",
    }
)  # fmt: skip

_SHA = re.compile(r"^[0-9a-f]{7,64}$")
_KG_KEY = re.compile(r"^kg-(?P<kind>[abc])-(?P<slug>.+)$")
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    """The slug of a recurrence key or a failure class in a `kg-<a|b|c>-<slug>` dedupe key (design D10)."""
    return _NON_SLUG.sub("-", text.casefold()).strip("-")


@dataclass
class Extracted:
    nodes: list[Node]
    edges: list[Edge]
    skipped: dict[str, int]  # `Collected.skipped`, plus `error` for a unit that failed here and `files_unknown`
    warnings: list[str] = field(default_factory=list)


def _merge_attrs(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(old)
    for key, value in new.items():
        if key not in merged or canonical_json(value) > canonical_json(merged[key]):
            merged[key] = value
    return merged


class _Graph:
    """The nodes (one per id) and the edges (a set) of some records, with every string cleaned on the way in."""

    def __init__(self, redactor: Redactor) -> None:
        self.redactor = redactor
        self.nodes: dict[str, Node] = {}
        self.edges: set[Edge] = set()

    def clean(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redactor.scrub_for_commit(self.redactor.redact_text(value))
        if isinstance(value, Mapping):
            return {k: self.clean(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self.clean(v) for v in value]
        return value

    def node(self, id: str, type: str, /, **attrs: Any) -> str:
        node = Node(self.clean(id), type, self.clean(attrs))
        old = self.nodes.get(node.id)
        if old is not None and old != node:
            node = Node(node.id, type, _merge_attrs(old.attrs, node.attrs))
        self.nodes[node.id] = node
        return node.id

    def edge(self, type: str, from_id: str, to_id: str, src: str, ts: str, /, **attrs: Any) -> None:
        self.edges.add(Edge(type, self.clean(from_id), self.clean(to_id), self.clean(src), ts, self.clean(attrs)))

    def absorb(self, other: "_Graph") -> None:
        for node in other.nodes.values():
            self.node(node.id, node.type, **node.attrs)
        self.edges |= other.edges


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _name(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) and value else None


def _round_id(rec: UnitRecord, folder: str, number: int) -> str:
    attempt = f"{rec.unit_id}@{rec.attempt}"
    return f"{attempt}#round-{number}" if folder == rec.name else f"{attempt}#{folder}/round-{number}"


class _Extractor:
    def __init__(self, redactor: Redactor, git: Git | None, base_sha: str | None, refs: Mapping[str, str]) -> None:
        self.redactor, self.git = redactor, git
        self.base_sha = base_sha
        self.read_tips = sorted(set(refs.values()))  # the commits of the refs the manifest records
        self._reachable: dict[str, bool] = {}
        self.files_unknown = 0
        self._diffs: dict[tuple[str, str], list[str] | None] = {}

    # --- the changed files of a round -----------------------------------------------------------------------------

    def changed_files(self, base: Any, head: Any) -> list[str] | None:
        if self.git is None or not isinstance(base, str) or not isinstance(head, str):
            return None
        if not (_SHA.match(base) and _SHA.match(head)):
            return None
        key = (base, head)
        if key not in self._diffs:
            self._diffs[key] = self._diff(base, head)
        return self._diffs[key]

    def reachable(self, sha: str) -> bool:
        """Whether `sha` is a commit that the read refs reach. A commit that is local but only because something else
        fetched it is not: the same refs must give the same bytes (review #7), and the manifest records the refs."""
        if sha not in self._reachable:
            assert self.git is not None
            lines = [sha, *(f"^{tip}" for tip in self.read_tips)]
            done = self.git.run("log", "--format=%H", "-1", "--stdin", input="\n".join(lines) + "\n", check=False)
            self._reachable[sha] = done.returncode == 0 and not done.stdout.strip()
        return self._reachable[sha]

    def _diff(self, base: str, head: str) -> list[str] | None:
        assert self.git is not None
        if not (self.reachable(base) and self.reachable(head)):
            return None
        done = self.git.run_bytes("diff", "--name-only", "--no-renames", "-z", base, head, check=False)
        names = [n.decode("utf-8", "surrogateescape") for n in done.split(b"\0") if n]
        return sorted(names)[:MAX_FILES]

    # --- one unit record -------------------------------------------------------------------------------------------

    def record(self, g: _Graph, rec: UnitRecord) -> None:
        unit, attempt = rec.unit_id, f"{rec.unit_id}@{rec.attempt}"
        g.node(unit, "unit", framework=rec.framework, name=rec.name)
        g.node(attempt, "attempt", attempt=rec.attempt, unit=unit)
        first = rec.events[0] if rec.events else None
        if first is not None:
            src, ts = first.src, first.event.ts.strftime(TS_FORMAT)
        elif rec.verdicts:
            src, ts = rec.verdicts[0].src(), ""
        else:
            src, ts = f"{(self.base_sha or '')[:10]}:", ""
        g.edge("HAS_ATTEMPT", unit, attempt, src, ts, places=list(rec.places), folders=list(rec.folders))
        verdict_ts = self.events(g, rec, attempt)
        for verdict in rec.verdicts:
            self.verdict(g, rec, attempt, verdict, verdict_ts.get((verdict.folder, verdict.round), ""))

    def events(self, g: _Graph, rec: UnitRecord, attempt: str) -> dict[tuple[str, int], str]:
        unit = rec.unit_id
        answered = {
            se.event.data["id"]: se.event.data.get("by")
            for se in rec.events
            if se.event.type == "question.answered" and isinstance(se.event.data.get("id"), str)
        }
        runs: dict[str, dict[str, Any]] = {}
        verdict_ts: dict[tuple[str, int], str] = {}
        for se in rec.events:
            ev, src, ts = se.event, se.src, se.event.ts.strftime(TS_FORMAT)
            data = ev.data
            info = runs.setdefault(ev.run_id, {"first": (src, ts)})
            if ev.type == "run.started":
                info["start"] = ts
            elif ev.type == "run.finished":
                info["end"] = ts
                if isinstance(data.get("exit_code"), int):
                    info["exit_code"] = data["exit_code"]
            run = ev.run_id
            if ev.type == "availability.selected":
                if (role := _name(data, "role")) and (selected := _name(data, "selected")):
                    g.node(f"profile:{selected}", "profile")
                    g.edge("USED_PROFILE", run, f"profile:{selected}", src, ts, role=role)
            elif ev.type == "prompt.rendered":
                lessons = data.get("lessons")
                for lid in lessons if isinstance(lessons, list) else ():
                    if isinstance(lid, str) and lid:
                        g.edge(
                            "INJECTED", run, lid, src, ts,
                            task=_text(data.get("task"), 40), role=_text(data.get("role"), 40), seq=ev.seq,
                        )  # fmt: skip
            elif ev.type == "task.attempt_failed":
                reason = g.clean(data.get("reason") if isinstance(data.get("reason"), str) else "")
                cls = failure_class(reason) or "unspecified"
                g.node(f"failure:{cls}", "failure_class")
                g.edge(
                    "ATTEMPT_FAILED", run, f"failure:{cls}", src, ts,
                    task=_text(data.get("task"), 40), phase=_text(data.get("phase"), 40),
                    attempt=data.get("attempt") if isinstance(data.get("attempt"), int) else None, seq=ev.seq,
                )  # fmt: skip
                self.classified(g, run, blame.classify("task.attempt_failed"), "task.attempt_failed", src, ts, ev.seq)
            elif ev.type == "question.raised":
                if qid := _name(data, "id"):
                    node = f"{unit}#{qid}"
                    g.node(node, "question", id=qid)
                    kind = _text(data.get("kind"), 40)
                    g.edge(
                        "ASKED", run, node, src, ts,
                        kind=kind,
                        source=_text(data.get("source"), 40),
                        answered_by=_text(answered.get(qid), 40) or None,
                    )  # fmt: skip
                    g.node("blame:" + blame.classify("question", {"kind": kind}), "blame")
                    g.edge(
                        "CLASSIFIED",
                        node,
                        "blame:" + blame.classify("question", {"kind": kind}),
                        src,
                        ts,
                        of="question",
                    )
            elif ev.type == "phase.changed" and data.get("to") in STOP_PHASES:
                code = _name(data, "reason") or _name(data, "trigger") or "unspecified"
                g.node(f"stop:{code}", "stop")
                g.edge("STOPPED", run, f"stop:{code}", src, ts, phase=data["to"], detail=_text(data.get("detail")))
                self.classified(g, run, blame.classify("stop", {"code": code}), "stop", src, ts, ev.seq)
            elif ev.type == "unit.retried":
                extra = {k: _text(data.get(k), 80) for k in ("by", "signal") if _text(data.get(k), 80)}
                g.edge("RETRIED", run, attempt, src, ts, reason=_text(data.get("reason"), 200), **extra)
            elif ev.type == "unit.restarted":
                number = data.get("attempt")
                if isinstance(number, int):
                    kept = f"{unit}@{number}"
                    g.node(kept, "attempt", attempt=number, unit=unit)
                    g.edge("RESTARTED", run, kept, src, ts, attempt=number, reason=_text(data.get("reason"), 200))
            elif ev.type == "verify.verdict":
                number, verdict = data.get("round"), _name(data, "verdict")
                if isinstance(number, int) and verdict:
                    node = g.node(_round_id(rec, rec.name, number), "round", folder=rec.name, round=number)
                    g.edge("VERDICT", run, node, src, ts, verdict=verdict)
                    verdict_ts.setdefault((rec.name, number), ts)
            elif ev.type in CLASSIFIED_EVENTS:
                rule = _guard_rule(ev) if ev.type in GUARD_EVENTS else ""
                self.classified(g, run, blame.classify(ev.type), ev.type, src, ts, ev.seq, rule=rule)
        for run_id, info in runs.items():
            attrs = {k: info[k] for k in ("start", "end", "exit_code") if k in info}
            g.node(run_id, "run", **attrs)
            run_src, run_ts = info["first"]
            g.edge("HAS_RUN", attempt, run_id, run_src, run_ts)
        return verdict_ts

    @staticmethod
    def classified(g: _Graph, run: str, value: str, of: str, src: str, ts: str, seq: int, rule: str = "") -> None:
        g.node(f"blame:{value}", "blame")
        extra = {"rule": rule} if rule else {}
        g.edge("CLASSIFIED", run, f"blame:{value}", src, ts, of=of, seq=seq, **extra)

    # --- one verdict.json ------------------------------------------------------------------------------------------

    def verdict(self, g: _Graph, rec: UnitRecord, attempt: str, vf: VerdictFile, ts: str) -> None:
        data = vf.data
        round_node = g.node(_round_id(rec, vf.folder, vf.round), "round", folder=vf.folder, round=vf.round)
        verdict = _name(data, "verdict") or ""
        files = self.changed_files(data.get("base_sha"), data.get("head_sha"))
        attrs: dict[str, Any] = {
            "verdict": verdict,
            "base_sha": _text(data.get("base_sha"), 64),
            "head_sha": _text(data.get("head_sha"), 64),
        }  # fmt: skip
        if isinstance(profiles := data.get("profiles"), Mapping):
            attrs["judge"] = _text(profiles.get("judge"), 80)
            implementer = profiles.get("implementer")
            attrs["implementer"] = (
                [p for p in implementer if isinstance(p, str)] if isinstance(implementer, list) else []
            )
        if files is None:
            attrs["files_unknown"] = True
            self.files_unknown += 1
        else:
            attrs["files"] = files
        g.edge("HAS_ROUND", attempt, round_node, vf.src("/verdict"), ts, **attrs)

        aliases: dict[str, str] = {}
        criteria = data.get("criteria")
        for index, crit in enumerate(criteria if isinstance(criteria, list) else ()):
            if not isinstance(crit, Mapping) or not (cid := _name(crit, "id")):
                continue
            alias = crit.get("alias") if isinstance(crit.get("alias"), str) else ""
            aliases[cid] = alias
            capability = self.capability(rec, alias)
            node = g.node(f"{rec.unit_id}#{cid}", "criterion", alias=alias, unit=rec.unit_id, capability=capability)
            if capability:
                g.node(f"cap:{capability}", "capability")
                g.edge("IN_CAPABILITY", node, f"cap:{capability}", vf.src(f"/criteria/{index}/alias"), ts)

        findings = data.get("findings")
        for index, found in enumerate(findings if isinstance(findings, list) else ()):
            if (
                not isinstance(found, Mapping)
                or not (fid := _name(found, "id"))
                or not isinstance(found.get("title"), str)
            ):
                continue
            src = vf.src(f"/findings/{index}")
            title = g.clean(found["title"])
            source = _text(found.get("source"), 40)
            spec_gap = found.get("spec_gap") is True
            g.node(fid, "finding", title=title)
            g.edge(
                "RAISED", round_node, fid, src, ts,
                severity=_text(found.get("severity"), 40), source=source, spec_gap=spec_gap,
            )  # fmt: skip
            criterion = _name(found, "criterion")
            if criterion in aliases:
                g.edge("ABOUT", fid, f"{rec.unit_id}#{criterion}", vf.src(f"/findings/{index}/criterion"), ts)
            alias = g.clean(aliases[criterion]) if criterion in aliases else None
            key = recurrence_key(title, alias, rec.framework)
            g.node(f"recurrence:{key}", "recurrence_key")
            g.edge("KEYED", fid, f"recurrence:{key}", vf.src(f"/findings/{index}/title"), ts)
            value = blame.classify("finding", {"source": source, "spec_gap": spec_gap})
            g.node(f"blame:{value}", "blame")
            g.edge("CLASSIFIED", fid, f"blame:{value}", src, ts, of="finding")

        gates = data.get("gates")
        for index, gate in enumerate(gates if isinstance(gates, list) else ()):
            if isinstance(gate, Mapping) and gate.get("status") == "fail" and (name := _name(gate, "name")):
                g.node(f"gate:{name}", "gate")
                g.edge("GATE_FAILED", round_node, f"gate:{name}", vf.src(f"/gates/{index}"), ts)

        if verdict == "NEEDS_HUMAN":
            value = blame.classify("round", {"verdict": verdict, "findings": findings})
            g.node(f"blame:{value}", "blame")
            g.edge("CLASSIFIED", round_node, f"blame:{value}", vf.src("/verdict"), ts, of="round")

    @staticmethod
    def capability(rec: UnitRecord, alias: str) -> str:
        if rec.framework == "kiro":
            return rec.name
        return alias.split(ALIAS_SEPARATOR, 1)[0].strip()


def _lesson_nodes(g: _Graph, collected: Collected) -> dict[str, LessonRecord]:
    chosen: dict[str, LessonRecord] = {}
    for record in sorted(collected.lessons, key=lambda r: (r.archived, r.origin.pointer, r.lesson.id)):
        chosen.setdefault(record.lesson.id, record)
    for lid, record in chosen.items():
        lesson = record.lesson
        g.node(
            lid, "lesson", title=lesson.title, dedupe_key=lesson.dedupe_key, scope=list(lesson.scope_globs),
            archived=record.archived, reinforced=lesson.reinforced_count,
        )  # fmt: skip
    return chosen


def _link_lessons(g: _Graph, chosen: Mapping[str, LessonRecord], ts: str) -> None:
    """The lesson-to-pattern link, by dedupe key only (L4-KG-005). The `Source` line is never read (SCN-KG-11)."""
    keys = sorted(n[len("recurrence:") :] for n, node in g.nodes.items() if node.type == "recurrence_key")
    classes = sorted(n[len("failure:") :] for n, node in g.nodes.items() if node.type == "failure_class")
    for lid, record in chosen.items():
        dedupe, src = record.lesson.dedupe_key, f"{record.origin.pointer}#{lid}"
        targets: list[str] = []
        if (rule := LESSON_RULES.get(dedupe)) is not None:
            prefix = norm(rule.finding_title) + KEY_SEPARATOR
            matching = [k for k in keys if k.startswith(prefix)]
            targets = [f"recurrence:{k}" for k in matching] or [f"recurrence:{prefix}"]
            for target in targets:
                g.node(target, "recurrence_key")
        elif (match := _KG_KEY.match(dedupe)) is not None:
            if match["kind"] == "a":
                targets = [f"failure:{c}" for c in classes if slug(c) == match["slug"]]
            elif match["kind"] == "b":
                targets = [f"recurrence:{k}" for k in keys if slug(k) == match["slug"]]
        for target in targets:
            g.edge("KEYED", lid, target, src, ts)


def extract(collected: Collected, redactor: Redactor, *, git: Git | None = None) -> Extracted:
    """The graph of `collected`. `git` is read-only and optional: without it, no round has its changed files."""
    graph = _Graph(redactor)
    worker = _Extractor(redactor, git, collected.base_sha, collected.refs)
    skipped = dict(collected.skipped)
    warnings = list(collected.warnings)
    for rec in collected.units:
        part = _Graph(redactor)
        before = worker.files_unknown
        try:
            worker.record(part, rec)
        except Exception as exc:  # noqa: BLE001 - one unit never fails the build (L4-KG-002)
            worker.files_unknown = before
            skipped["error"] = skipped.get("error", 0) + 1
            warnings.append(f"{rec.unit_id}@{rec.attempt}: skipped: {type(exc).__name__}")
            log.warning("kg: %s@%s skipped: %s", rec.unit_id, rec.attempt, type(exc).__name__)
            continue
        graph.absorb(part)
    chosen = _lesson_nodes(graph, collected)
    for edge in [e for e in graph.edges if e.type == "INJECTED"]:  # a lesson seen only in events is still a node
        if edge.to_id not in graph.nodes:
            graph.node(edge.to_id, "lesson")
    _link_lessons(graph, chosen, collected.base_date or "")
    if worker.files_unknown:
        skipped["files_unknown"] = worker.files_unknown
    return Extracted(list(graph.nodes.values()), list(graph.edges), dict(sorted(skipped.items())), warnings)
