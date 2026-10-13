"""The scenario-conflict lint of intake (SPEC L4-ODD-004): two scenarios with the same GIVEN and WHEN and a different
THEN.

Deterministic and free: it runs before any agent or probe, and each new pair becomes one `ambiguous` question that
blocks the pending tasks. Only equal GIVEN and WHEN with different THEN is seen; a conflict between requirement
prose and a scenario is not (the spec says so). OpenSpec does not link tasks to scenarios (L4-OSP-008 is not built),
so every pending task is blocked. M1: implementer-tdd-loop 1.6 (the rest of intake).
"""

import hashlib
import re
import unicodedata
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from l4.redact import Redactor
from l4.specs.base import Criterion, Task
from l4.specs.criteria import normalise
from l4.specs.questions import QUESTIONS_FILENAME, NewQuestion, QuestionKind, QuestionsFile, raise_questions

ASKED_BY = "intake lint (L4-ODD-004)"
_CODE_SPAN = re.compile(r"(`[^`\n]*`)")
_KEYWORD = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*)?(GIVEN|WHEN|THEN|AND)(?:\*\*)?:?(?:\s+|$)(.*)$", re.IGNORECASE)
_THEN_INLINE = re.compile(r"\s+THEN\s+", re.IGNORECASE)
_CRITERION_ID = re.compile(r"C-[0-9a-f]{8}")


@dataclass(frozen=True)
class ScenarioConflict:
    first: Criterion  # document order: the change's scenarios, then the base specs
    second: Criterion
    given: str
    when: str
    first_then: str
    second_then: str


def _normal(text: str) -> str:
    """NFC and whitespace runs collapsed to one space, case kept (the rule of `l4.specs.criteria.normalise`), except
    that the inside of a code span is compared verbatim: `f("a  b")` and `f("a b")` are different WHENs."""
    parts = _CODE_SPAN.split(unicodedata.normalize("NFC", text.replace("**", "")))
    return "".join(p if i % 2 else re.sub(r"\s+", " ", p) for i, p in enumerate(parts)).strip()


def _clauses(body: str) -> tuple[str, str, str] | None:
    """(GIVEN, WHEN, THEN) of a scenario body; GIVEN is empty when there is none. An AND line belongs to the clause
    above it. None when the body has no WHEN or no THEN."""
    clauses: dict[str, list[str]] = {"given": [], "when": [], "then": []}
    current: str | None = None
    for line in body.splitlines():
        match = _KEYWORD.match(line)
        if match is None:
            continue
        word, rest = match.group(1).lower(), match.group(2)
        if word == "and":
            if current is not None:
                clauses[current].append(rest)
        else:
            current = word
            if word == "when" and (split := _THEN_INLINE.split(rest, maxsplit=1)) and len(split) == 2:
                clauses["when"].append(split[0])
                current, rest = "then", split[1]
            clauses[current].append(rest)
    given, when, then = (_normal(" ".join(clauses[key])) for key in ("given", "when", "then"))
    return (given, when, then) if when and then else None


def scenario_conflicts(
    unit: Iterable[Criterion], base_specs: Iterable[Criterion], removed: Collection[tuple[str, str]] = ()
) -> list[ScenarioConflict]:
    """Pairs with an equal GIVEN and WHEN and a different THEN, within the change and between the change and the
    archived specs. A base scenario under a requirement that the change adds, modifies, removes or renames away
    (`removed`, see `l4.specs.criteria.replaced_requirements`) is left out: the change replaces it. Two base
    scenarios that disagree are not this unit's doing."""
    own = list(unit)
    replaced = {(c.capability, normalise(c.requirement)) for c in own} | set(removed)
    pool = own + [c for c in base_specs if (c.capability, normalise(c.requirement)) not in replaced]
    parsed = [(c, _clauses(c.text)) for c in pool]
    found = []
    for (a, ca), (b, cb) in combinations(parsed, 2):
        if ca is None or cb is None or (a not in own and b not in own):
            continue
        if ca[:2] == cb[:2] and ca[2] != cb[2]:
            found.append(ScenarioConflict(a, b, ca[0], ca[1], ca[2], cb[2]))
    return found


def _already_asked(file: QuestionsFile | None, conflict: ScenarioConflict) -> bool:
    """Any question, in any Status, that names both criteria."""
    if file is None:
        return False
    wanted = {conflict.first.id, conflict.second.id}
    return any(
        wanted <= set(_CRITERION_ID.findall(file.data[q.section.start : q.section.end].decode("utf-8", "replace")))
        for q in file.questions
    )


def _question(conflict: ScenarioConflict, blocking: tuple[str, ...]) -> NewQuestion:
    def describe(c: Criterion, then: str) -> str:
        given = f"\n  GIVEN {conflict.given}" if conflict.given else ""
        return f"- {c.alias} ({c.source_path}:{c.source_line}){given}\n  WHEN {conflict.when}\n  THEN {then}"

    context = (
        "These two scenarios have the same GIVEN and WHEN and different THEN, so the implementer cannot satisfy both.\n"
        f"{describe(conflict.first, conflict.first_then)}\n{describe(conflict.second, conflict.second_then)}\n"
        "Which behaviour is wanted? Answer below and set Status to answered. If one scenario is wrong, delete it from "
        "the spec on this unit branch in the same commit; a change on the base branch does not reach this unit."
    )
    title = f'Scenarios "{conflict.first.scenario}" and "{conflict.second.scenario}" conflict'
    return NewQuestion(
        title=title, kind=QuestionKind.AMBIGUOUS, blocking_tasks=blocking, context=context, asked=ASKED_BY,
        criteria=(conflict.first, conflict.second),
    )  # fmt: skip


def raise_scenario_questions(
    unit_dir: Path, unit_name: str, conflicts: Sequence[ScenarioConflict], tasks: Sequence[Task], *, redactor: Redactor
) -> list[str]:
    """One `ambiguous` question for every conflict that has none yet; returns the new ids. A unit with no pending
    task has nothing to block, so nothing is raised."""
    blocking = tuple(t.key for t in tasks if not t.done)
    file = QuestionsFile.load(unit_dir / QUESTIONS_FILENAME)
    fresh = [c for c in conflicts if not _already_asked(file, c)]
    if not fresh or not blocking:
        return []
    return raise_questions(unit_dir, unit_name, [_question(c, blocking) for c in fresh], redactor=redactor)


# --- open questions listed in design.md / proposal.md (L4-ODD-004, intake) ---------------------------------------

OPEN_QUESTIONS_ASKED_BY = "intake (open questions in design.md)"
_OPEN_HEADING = re.compile(r"^##\s+open questions\s*$", re.IGNORECASE)
_HEADING = re.compile(r"^#{1,2}\s")
_BULLET = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.*)$")
_LABEL = re.compile(r"^\((technical|product|ambiguous)\)\s*", re.IGNORECASE)
_ITEM_HASH = re.compile(r"Open-question-hash: ([0-9a-f]{16})")
_TITLE_CHARS = 100


@dataclass(frozen=True)
class OpenQuestionItem:
    source: str  # file name inside the unit directory
    text: str  # the item as written: continuation lines joined with newlines, labels kept
    kind: QuestionKind

    @property
    def digest(self) -> str:
        return _item_digest(self.text)


def _item_digest(text: str) -> str:
    return hashlib.sha256(_normal(text).casefold().encode()).hexdigest()[:16]


def _section_items(source: str, text: str) -> list[OpenQuestionItem]:
    items: list[list[str]] = []
    inside = False
    for line in text.replace("\r\n", "\n").splitlines():
        if _OPEN_HEADING.match(line):
            inside = True
        elif inside and _HEADING.match(line):
            inside = False
        elif inside:
            bullet = _BULLET.match(line)
            if bullet:
                items.append([bullet.group(1).strip()])
            elif items and line.strip():
                items[-1].append(line.strip())  # indented continuation (or a nested bullet) of the item above
    found = []
    for lines in items:
        body = "\n".join(lines)
        label = _LABEL.match(body)
        kind = QuestionKind(label.group(1).lower()) if label else QuestionKind.AMBIGUOUS
        found.append(OpenQuestionItem(source, body, kind))
    return found


def open_question_items(unit_dir: Path) -> list[OpenQuestionItem]:
    """Every list item under `## Open questions` in design.md, then proposal.md. Missing file or section: nothing."""
    found: list[OpenQuestionItem] = []
    for name in ("design.md", "proposal.md"):
        try:
            text = (unit_dir / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found += _section_items(name, text)
    return found


def _item_question(item: OpenQuestionItem, blocking: tuple[str, ...]) -> NewQuestion:
    shown = _LABEL.sub("", " ".join(item.text.split()))
    title = shown if len(shown) <= _TITLE_CHARS else shown[: _TITLE_CHARS - 1] + "\u2026"
    context = f'{item.text}\n\nListed under "Open questions" in {item.source}.\nOpen-question-hash: {item.digest}'
    return NewQuestion(
        title=title, kind=item.kind, blocking_tasks=blocking, context=context, asked=OPEN_QUESTIONS_ASKED_BY
    )


def raise_open_questions(unit_dir: Path, unit_name: str, tasks: Sequence[Task], *, redactor: Redactor) -> list[str]:
    """One question per open-question item that has none yet (a question in any Status carrying the item's hash);
    returns the new ids. Blocks every pending task; a unit with none has nothing to block, so nothing is raised."""
    blocking = tuple(t.key for t in tasks if not t.done)
    items = open_question_items(unit_dir)
    if not items or not blocking:
        return []
    file = QuestionsFile.load(unit_dir / QUESTIONS_FILENAME)
    known = (
        {
            h
            for q in file.questions
            for h in _ITEM_HASH.findall(file.data[q.section.start : q.section.end].decode("utf-8", "replace"))
        }
        if file
        else set()
    )
    batch, seen = [], set(known)
    for item in items:
        if item.digest not in seen:
            seen.add(item.digest)
            batch.append(_item_question(item, blocking))
    return raise_questions(unit_dir, unit_name, batch, redactor=redactor)
