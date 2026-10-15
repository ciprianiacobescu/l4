"""`l4 kg propose`: drafts of lessons for a person, in the inbox (L4-KG-012, design D10, SCN-KG-22, SCN-KG-24 to 26).

`propose(nodes, edges, *, repo, git, ...)` finds the patterns that recur in at least `min_units` units and writes, for
each one that no lesson covers, a draft and an evidence file under `.serena/memories/inbox/kg-<date>/`. It never
writes a lesson: it does not touch `lessons.md`, does not stage and does not commit. A person writes the advice, then
runs `l4 lessons promote <L-id>` (`memory/promote.py`, which this module does not import, L4-KG-001).

The three patterns of design D10, each counted in distinct units:

- (a) an attempt failure class (`ATTEMPT_FAILED`): the dedupe key is `kg-a-<slug>` of the class;
- (b) the recurrence key of a deterministic finding (`RAISED` with `source: deterministic`): `kg-b-<slug>` of the key;
- (c) a guard rule (`CLASSIFIED` with a `rule`, which `extract` takes from a guard event): `kg-c-<slug>` of the rule.

`slug` is the one of `extract`, so that `extract` links the lesson back to the pattern by the dedupe key (L4-KG-005).
The lesson id is `lesson_id(dedupe key)`, which `promote` checks.

A pattern is covered, and gets no draft, when a lesson node has its dedupe key (`lessons.md` and `_archive/` are both
in the index), when a `LESSON_RULES` rule has the finding's title (b), or when curation's own lesson for the guard rule
exists (`guard-violation-<slug>`, c). The result says `covered by <L-id>`.

**Only harness-owned strings reach a draft:** a failure class (the harness's reason template after `norm`), the title
of a deterministic finding, a guard rule name, a unit id, a run id and a `src` pointer. A judge finding, a question,
an answer, a path an agent wrote and an agent's output are never quoted: pattern (b) counts only `source:
deterministic`, and (c) quotes the rule, not the path. Every label passes `redact_text` and `scrub_for_commit` first
(L4-KG-011), so the dedupe key and the id are made from clean text.

A draft is `render_lessons` of one section, so `parse_proposal` reads it back. Its scope is `feedback_scope` of the
changed files of the rounds that raised the finding (b), where both shas were local when the index was built; (a) and
(c) have no scope. Its body is one template sentence and the `TODO(person):` line, which `promote` refuses until the
person replaces it. The evidence file lists units, runs, rounds and `src` pointers, and `promote` never reads it.

Files are written only under the inbox, with no symlink on the path (a symlinked inbox exits 2). A second run on the
same day with the same index writes the same bytes. A draft that differs from what this run would write was edited by
the person, and it is kept. A draft with the same id in another day's folder is not made twice (`promote` would refuse
two). With `dry_run`, the texts are returned and nothing is written. When `git check-ignore` says the draft path is
not ignored, the result carries the warning of D10.
"""

import os
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath

from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import atomic_write_bytes, reject_symlinks
from l4.kg.extract import slug
from l4.kg.model import Edge, Node
from l4.kg.normalise import KEY_SEPARATOR, norm
from l4.kg.report import DEFAULT_MIN_UNITS, by_key, failure_rows, raised_findings
from l4.kg.view import View, clean_text, display_key, n_of
from l4.memory.curate import LESSON_RULES, feedback_scope
from l4.memory.lessons import Lesson, LessonsFile, lesson_id, render_lessons
from l4.redact import Redactor
from l4.vcs.git import Git

INBOX = ".serena/memories/inbox"
TODO_LINE = "TODO(person): write what the implementer should do instead, then run l4 lessons promote {lid}"
IGNORE_WARNING = (
    "do not commit .serena/memories/inbox/kg-*: "
    "a committed inbox file is readable and writable by agents through Serena"
)
GUARD_PREFIX = "guard-violation-"  # the dedupe key of curation's own lesson for a guard rule
MAX_EVIDENCE_LINES = 200


@dataclass
class Proposal:
    kind: str  # "a", "b" or "c"
    dedupe_key: str
    lesson_id: str
    title: str
    label: str  # the pattern in words: `failure class …`, `finding …`, `guard rule …`
    covered_by: str | None
    path: str = ""
    evidence_path: str = ""
    text: str = ""
    evidence: str = ""
    units: int = 0
    status: str = ""  # "", "written", "would write", "unchanged", "kept, the person edited it", "already drafted in …"


@dataclass
class ProposeResult:
    proposals: list[Proposal] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False
    min_units: int = DEFAULT_MIN_UNITS

    def render(self) -> str:
        lines: list[str] = []
        for p in self.proposals:
            if p.covered_by is not None:
                lines.append(f"{p.label}: covered by {p.covered_by}, no draft.")
                continue
            if p.status.startswith("already drafted"):
                lines.append(f"{p.label}: {p.status}.")
                continue
            verb = "wrote" if p.status == "written" else p.status
            lines.append(f"{verb} {p.path} ({p.label}, {n_of(p.units, 'unit')})")
            lines.append(f"    evidence: {p.evidence_path}")
            if self.dry_run:
                lines += ["", f"--- {p.path}", p.text.rstrip("\n"), "", f"--- {p.evidence_path}"]
                lines += [p.evidence.rstrip("\n"), ""]
            elif p.status == "written":
                lines.append(f"    next: replace the TODO(person) line, then run l4 lessons promote {p.lesson_id}")
        if not self.proposals:
            lines.append(f"no pattern recurs in at least {n_of(self.min_units, 'unit')} ({n_of(0, 'draft')}).")
        lines += [f"warning: {w}" for w in self.warnings]
        return "\n".join(lines) + "\n"


# --- the patterns -------------------------------------------------------------------------------------------


@dataclass
class _Pattern:
    kind: str
    label_text: str  # the failure class, the finding title or the rule
    key_text: str  # what the slug is made from
    title: str
    units: set[str]
    count: int
    count_word: str
    phases: set[str]
    scope: tuple[str, ...]
    sentence: str
    evidence: list[str]
    covering: tuple[str, ...] = ()  # dedupe keys of lessons that cover it, besides its own


def _evidence_lines(rows: Iterable[str]) -> list[str]:
    ordered = sorted(set(rows))
    shown = [f"- {row}" for row in ordered[:MAX_EVIDENCE_LINES]]
    if len(ordered) > MAX_EVIDENCE_LINES:
        shown.append(f"- {n_of(len(ordered) - MAX_EVIDENCE_LINES, 'more source')} are not listed.")
    return shown


def _failure_patterns(v: View, floor: int, clean) -> list[_Pattern]:
    patterns = []
    for cls, units, found in failure_rows(v, floor):
        text = clean(cls)
        phases = {str(e.attrs.get("phase") or "?") for e in found}
        phase = next(iter(phases)) if len(phases) == 1 else "attempt"
        rows = [
            f"{v.unit_of_run(e.from_id)} {e.from_id} task {e.attrs.get('task')} {e.attrs.get('phase')} attempt "
            f"{e.attrs.get('attempt')} src {e.src}"
            for e in found
        ]
        sentence = (
            f'The task attempt failure "{text}" was recorded in {len(units)} separate units, {len(found)} times in all.'
        )
        patterns.append(
            _Pattern(
                "a",
                text,
                text,
                f"Recurring {phase} failure: {text}",
                units,
                len(found),
                "attempt",
                phases,
                (),
                sentence,
                _evidence_lines(rows),
            )  # fmt: skip
        )
    return patterns


def _finding_patterns(v: View, floor: int, clean) -> list[_Pattern]:
    deterministic = (r for r in raised_findings(v) if r.edge.attrs.get("source") == "deterministic")
    patterns = []
    for key, found in by_key(deterministic).items():
        units = {r.unit for r in found}
        if len(units) < floor:
            continue
        rule_keys = tuple(
            k for k, rule in LESSON_RULES.items() if norm(rule.finding_title) == key.split(KEY_SEPARATOR)[0]
        )
        # never a title the agent could shape (a finding title can quote a path the agent chose): the harness's own
        # rule title, else the normalised recurrence key (review #5)
        title = clean(LESSON_RULES[rule_keys[0]].finding_title if rule_keys else display_key(key))
        rounds = {r.edge.from_id for r in found}
        files: set[str] = set()
        for round_id in rounds:
            for has in v.into(round_id, "HAS_ROUND"):
                files.update(f for f in has.attrs.get("files") or () if isinstance(f, str))
        rows = [
            f"{r.unit} {r.edge.from_id} {r.edge.to_id} {r.edge.attrs.get('severity')} src {r.edge.src}" for r in found
        ]
        sentence = (
            f'The deterministic finding "{title}" was raised in {len(units)} separate units, in {len(rounds)} rounds.'
        )
        patterns.append(
            _Pattern(
                "b",
                title,
                clean(key),
                f"Recurring finding: {title}",
                units,
                len(rounds),
                "round",
                set(),
                feedback_scope(sorted(files)) if files else (),
                sentence,
                _evidence_lines(rows),
                rule_keys,
            )  # fmt: skip
        )
    return patterns


def _guard_patterns(v: View, floor: int, clean) -> list[_Pattern]:
    rules: dict[str, list[Edge]] = defaultdict(list)
    for edge in v.of_type("CLASSIFIED"):
        if isinstance(edge.attrs.get("rule"), str) and edge.attrs["rule"]:
            rules[edge.attrs["rule"]].append(edge)
    patterns = []
    for rule, found in rules.items():
        units = {v.unit_of_run(e.from_id) for e in found}
        if len(units) < floor:
            continue
        text = clean(rule)
        rows = [f"{v.unit_of_run(e.from_id)} {e.from_id} {e.attrs.get('of')} src {e.src}" for e in found]
        sentence = (
            f"The guard rule `{text}` was triggered in {len(units)} separate units. "
            "Do not touch the files it protects; the harness reverts the change and the run loses time."
        )
        covering = (GUARD_PREFIX + (slug(text) or "unnamed"),)
        patterns.append(
            _Pattern(
                "c",
                text,
                text,
                f"Recurring guard rule: {text}",
                units,
                len(found),
                "event",
                set(),
                (),
                sentence,
                _evidence_lines(rows),
                covering,
            )  # fmt: skip
        )
    return patterns


# --- files --------------------------------------------------------------------------------------------------


def _draft_text(p: Proposal, pattern: _Pattern, today: date) -> str:
    source = f"l4 kg propose {today.isoformat()}: {n_of(len(pattern.units), 'unit')}, "
    source += n_of(pattern.count, pattern.count_word)
    body = pattern.sentence + "\n\n" + TODO_LINE.format(lid=p.lesson_id)
    lesson = Lesson(p.lesson_id, p.title, p.dedupe_key, body, pattern.scope, (), source)
    return render_lessons(LessonsFile([lesson]))


def _evidence_text(p: Proposal, pattern: _Pattern) -> str:
    scope = ", ".join(f"`{g}`" for g in pattern.scope) or "none"
    head = [
        f"# Evidence for {p.lesson_id}",
        "",
        f"Pattern: {p.label}. Dedupe key: {p.dedupe_key}.",
        f"Seen in {n_of(len(pattern.units), 'unit')}: {', '.join(sorted(pattern.units))}.",
        f"Scope proposed: {scope}.",
        "This file is for the person who writes the advice. promote never reads this file.",
        "",
        "## Sources",
        "",
    ]
    return "\n".join([*head, *pattern.evidence]) + "\n"


def _elsewhere(repo: Path, folder: str, lid: str) -> str | None:
    root = repo / INBOX
    try:
        with os.scandir(root) as it:
            names = sorted(e.name for e in it if e.is_dir(follow_symlinks=False) and e.name != folder)
    except OSError:
        return None
    for name in names:
        if (root / name / f"{lid}.md").is_file():
            return f"{INBOX}/{name}/{lid}.md"
    return None


def _write(repo: Path, p: Proposal, folder: str, dry_run: bool) -> None:
    other = _elsewhere(repo, folder, p.lesson_id)
    if other is not None:
        p.status = f"already drafted in {other}"
        return
    target = repo / p.path
    existing = target.read_bytes() if target.is_file() and not target.is_symlink() else None
    data = p.text.encode("utf-8")
    if existing == data:
        p.status = "unchanged"
    elif existing is not None:
        p.status = "kept, the person edited it"
    else:
        p.status = "would write" if dry_run else "written"
    if dry_run or p.status == "kept, the person edited it":
        return
    for relative, content in ((p.path, p.text), (p.evidence_path, p.evidence)):
        try:
            reject_symlinks(repo, *PurePosixPath(relative).parts)
            (repo / relative).parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(repo / relative, content.encode("utf-8"))
        except OSError as exc:  # UnsafeFile is one
            raise L4Exit(ExitCode.USAGE_ERROR, f"{relative} is not written: {exc}") from None


def _ignored(git: Git, relative: str) -> bool | None:
    done = git.run("check-ignore", "-q", "--", relative, check=False)
    if done.returncode == 0:
        return True
    return False if done.returncode == 1 else None


# --- the command --------------------------------------------------------------------------------------------


def propose(
    nodes: Iterable[Node],
    edges: Iterable[Edge],
    *,
    repo: Path,
    git: Git,
    min_units: int = DEFAULT_MIN_UNITS,
    dry_run: bool = False,
    today: date | None = None,
    redactor: Redactor | None = None,
) -> ProposeResult:
    day = today or date.today()
    folder = f"kg-{day.isoformat()}"
    floor = max(min_units, 1)
    v = View(nodes, edges)

    def clean(text: str) -> str:
        return clean_text(text, redactor)

    have = {
        str(n.attrs["dedupe_key"]): n.id for n in v.nodes_of("lesson") if isinstance(n.attrs.get("dedupe_key"), str)
    }
    patterns = [
        *_failure_patterns(v, floor, clean),
        *_finding_patterns(v, floor, clean),
        *_guard_patterns(v, floor, clean),
    ]
    result = ProposeResult(dry_run=dry_run, min_units=floor)
    labels = {"a": "failure class", "b": "finding", "c": "guard rule"}
    for pattern in sorted(patterns, key=lambda p: (p.kind, p.key_text)):
        key = f"kg-{pattern.kind}-{slug(pattern.key_text) or 'unnamed'}"
        lid = lesson_id(key)
        covered = have.get(key)
        for candidate in pattern.covering:
            if covered is None:
                covered = lesson_id(candidate) if candidate in LESSON_RULES else have.get(candidate)
        p = Proposal(
            pattern.kind, key, lid, pattern.title, f"{labels[pattern.kind]} {pattern.label_text}", covered,
            units=len(pattern.units),
        )  # fmt: skip
        if covered is None:
            p.path = f"{INBOX}/{folder}/{lid}.md"
            p.evidence_path = f"{INBOX}/{folder}/{lid}.evidence.md"
            p.text = clean(_draft_text(p, pattern, day))
            p.evidence = clean(_evidence_text(p, pattern))
            _write(repo, p, folder, dry_run)
        result.proposals.append(p)
    first = next((p for p in result.proposals if p.covered_by is None), None)
    if first is not None and _ignored(git, first.path) is False:
        result.warnings.append(IGNORE_WARNING)
    return result


__all__ = ["IGNORE_WARNING", "INBOX", "TODO_LINE", "Proposal", "ProposeResult", "propose"]
