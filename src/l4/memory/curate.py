"""Curation (SPEC L4-MEM-002): a lesson is created or reinforced only from evidence the harness itself holds, never
from an agent's claim, and the lesson text is a harness template, never model text.

Origins built here: (a) a deterministic verifier finding of a known rule, closed in the same PASS round by an accepted
generated test (the reduced reading of "whose fix later passed": no fix units exist yet, plan D5); (b) a guard
violation kind repeated in at least two distinct runs; (c) a human-edited lesson, which `curate` accepts from any
caller that names that origin. Agent `lesson_proposals` are not an origin: M1 ignores them.
M1: memory-lessons 3.6/3.7 (inbox and quarantine), 3.9 (union-merge repair); the fix-unit reading of (a) after M1.3.
"""

import hashlib
import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Literal

from l4.config.schema import L4Config, MemoryCfg
from l4.fsutil import atomic_write_bytes, reject_symlinks
from l4.memory.inject import EventWriter, read_lessons_file
from l4.memory.lessons import Lesson, LessonsFile, lesson_id, parse_lessons, render_lessons, write_lessons
from l4.security.protected import glob_match
from l4.specs.feedback import FeedbackFile
from l4.specs.followup import feedback_home
from l4.state.fold import FeedbackState
from l4.state.ledger import LedgerEvent
from l4.verifier.types import Verdict, VerifyResult

Origin = Literal["verifier_finding_fixed", "guard_violation_repeated", "human_edit", "feedback"]
ARCHIVE_DIR = "_archive"
GUARD_EVENTS = ("guard.violation", "guard.test_tamper")
# the guards of the green phase report only `path, phase`; the key then comes from the event, never from the path
DERIVED_RULES = {"guard.test_tamper": "frozen test"}
GREEN_VIOLATION_RULE = "frozen support file"
MIN_GUARD_RUNS = 2  # [I] the SPEC gives no threshold (design D "Open points")
MAX_RULE_CHARS = 80

UI_GAP_KEY = "ui-criterion-without-e2e-test"
# The title of the deterministic finding that step 5 raises for a UI criterion with no e2e test (verifier/generate.py
# imports it, so the finding and the rule agree on one string).
UI_GAP_TITLE = "UI criterion without an end-to-end test"


@dataclass(frozen=True)
class LessonCandidate:
    dedupe_key: str
    title: str
    scope_globs: tuple[str, ...]
    scope_kinds: tuple[str, ...]
    source: str
    body: str
    origin: Origin


@dataclass(frozen=True)
class LessonRule:
    """What a known finding becomes. `finding_title` picks the finding; the lesson text is `title` and `body`."""

    finding_title: str
    title: str
    body: str


LESSON_RULES: dict[str, LessonRule] = {
    UI_GAP_KEY: LessonRule(
        UI_GAP_TITLE,
        "UI criteria need an end-to-end test",
        "A criterion about what a user sees or does needs a browser test that traces it by id (`C-<hex>` in the test "
        "name). A unit test does not cover it. Put the browser test in the end-to-end directory (`e2e/`, not under "
        "`tests/`, whose gate has no server) and write it with the change, not after the verifier asks.",
    )
}


@dataclass(frozen=True)
class CurationResult:
    file: LessonsFile
    action: Literal["created", "reinforced"]
    lesson_id: str
    archived: tuple[Lesson, ...] = ()


def ui_scope(changed_files: Iterable[str], ui_paths: Sequence[str]) -> tuple[str, ...]:
    """The `ui_paths` patterns that some file the unit changed matches; all of them when none does."""
    changed = list(changed_files)
    matched = tuple(p for p in ui_paths if any(glob_match(p, f) for f in changed))
    return matched or tuple(ui_paths)


def candidates_from_round(
    result: VerifyResult,
    cfg: L4Config,
    *,
    changed_files: Sequence[str] = (),
    generated_criteria: Collection[str] = (),
) -> list[LessonCandidate]:
    """Only deterministic findings of a known rule count, and only in a PASS round. `generated_criteria` are the
    criteria that an accepted generated test now covers: a finding about one of them is "closed". (The result gets
    its own field for them in M1.5 Stage C; until then the caller passes them.)"""
    if result.verdict is not Verdict.PASS:
        return []
    out: dict[str, LessonCandidate] = {}
    for finding in result.findings:
        if finding.source != "deterministic" or finding.criterion not in generated_criteria:
            continue
        for key, rule in LESSON_RULES.items():
            if finding.title == rule.finding_title and key not in out:
                scope = ui_scope(changed_files, cfg.verifier.playwright.ui_paths)
                out[key] = LessonCandidate(
                    key, rule.title, scope, (), f"verifier round {result.round}", rule.body, "verifier_finding_fixed"
                )  # fmt: skip
    return list(out.values())


def _guard_rule(event: LedgerEvent) -> str:
    if event.type not in GUARD_EVENTS:
        return ""
    rule = event.data.get("rule")
    if isinstance(rule, str) and rule.strip():
        return rule.strip()
    if event.type in DERIVED_RULES:
        return DERIVED_RULES[event.type]
    return GREEN_VIOLATION_RULE if event.data.get("phase") == "green" else ""


def guard_violation_candidates(
    events: Iterable[LedgerEvent], *, min_runs: int = MIN_GUARD_RUNS
) -> list[LessonCandidate]:
    """One candidate per guard `rule` that appears in at least `min_runs` distinct runs of the unit's ledger. Only
    the rule (a string of the harness's own) is used: the violating path comes from the agent and is not quoted."""
    runs: dict[str, set[str]] = {}
    for event in events:
        rule = _guard_rule(event)
        if rule:
            runs.setdefault(rule[:MAX_RULE_CHARS], set()).add(event.run_id)
    out = []
    for rule, seen in sorted(runs.items()):
        if len(seen) < min_runs:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", rule.lower()).strip("-") or "unnamed"
        body = (
            f"The guard rule `{rule}` was triggered in {len(seen)} separate runs. Do not touch the files it protects; "
            "the harness reverts the change and the run loses time."
        )
        out.append(LessonCandidate(
            f"guard-violation-{slug}", f"Guard rule repeated: {rule}", (), (), f"{len(seen)} runs", body,
            "guard_violation_repeated",
        ))  # fmt: skip
    return out


FEEDBACK_BODY_CHARS = 600
FEEDBACK_TITLE_CHARS = 60


def _cut(text: str, limit: int) -> str:
    """At most `limit` characters, cut on a word boundary with an ellipsis."""
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    if not text[limit - 1].isspace() and " " in head:
        head = head.rsplit(" ", 1)[0]
    return head.rstrip() + "\u2026"


def feedback_scope(places: Iterable[str]) -> tuple[str, ...]:
    """The directories of the places as `<dir>/**`; unscoped when a place sits at the repository root (or none
    has a usable path)."""
    dirs: set[str] = set()
    for path in places:
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or "\\" in path:
            continue
        parent = pure.parent.as_posix()
        if parent == ".":
            return ()
        dirs.add(parent)
    return tuple(f"{d}/**" for d in sorted(dirs))


def feedback_candidates(
    unit_dir: Path, unit: str, feedback: Mapping[str, FeedbackState], round_: int
) -> list[LessonCandidate]:
    """L4-FBK-009 (design D10): one candidate per item of `feedback.md` with `Lesson: yes` that the ledger records as
    addressed in `round_`. The text is a person's, collapsed to one line (a line that began `## ` would break the
    lessons file); a leading `#` is dropped for the same reason."""
    file = FeedbackFile.load(feedback_home(unit_dir))  # a follow-up's items are its parent's (L4-FBK-010)
    if file is None:
        return []
    out: dict[str, LessonCandidate] = {}
    for item in file.items:
        state = feedback.get(item.id)
        if not item.lesson or state is None or state.status != "addressed" or state.round != round_:
            continue
        text = " ".join(item.text.split())
        digest = hashlib.sha256(text.lower().encode("utf-8")).hexdigest()[:12]
        body = _cut(re.sub(r"^#+\s*", "", text), FEEDBACK_BODY_CHARS)
        if not body:
            continue
        key = f"feedback-{digest}"
        out.setdefault(key, LessonCandidate(
            key, "Human feedback: " + _cut(body, FEEDBACK_TITLE_CHARS), feedback_scope(p.path for p in item.places), (),
            f"human feedback {item.id} ({unit} round {round_})", body, "feedback",
        ))  # fmt: skip
    return list(out.values())


def _recency(lesson: Lesson) -> tuple[date, int, str]:
    return (lesson.last_reinforced or date.min, lesson.reinforced_count, lesson.id)


def _over(file: LessonsFile, cfg: MemoryCfg) -> bool:
    return len(file.lessons) > cfg.max_lessons or len(render_lessons(file).encode("utf-8")) > cfg.max_bytes


def curate(file: LessonsFile, candidate: LessonCandidate, cfg: MemoryCfg, today: date) -> CurationResult:
    """An existing dedupe key reinforces (count + 1, date today; nothing else changes), a new one is added with
    count 1. Over the caps, the least recently reinforced other lessons are archived until both hold or only the
    touched lesson is left."""
    lid = lesson_id(candidate.dedupe_key)
    lessons = list(file.lessons)
    index = next((i for i, existing in enumerate(lessons) if existing.id == lid), None)
    if index is not None:
        lessons[index] = replace(lessons[index], reinforced_count=lessons[index].reinforced_count + 1,
                                 last_reinforced=today)  # fmt: skip
        action: Literal["created", "reinforced"] = "reinforced"
    else:
        lessons.append(Lesson(
            lid, candidate.title, candidate.dedupe_key.strip(), candidate.body, candidate.scope_globs,
            candidate.scope_kinds, candidate.source, None, 1, today,
        ))  # fmt: skip
        action = "created"
    updated = LessonsFile(lessons, file.header)
    archived: list[Lesson] = []
    while _over(updated, cfg):
        others = [x for x in updated.lessons if x.id != lid]
        if not others:
            break
        oldest = min(others, key=_recency)
        archived.append(oldest)
        updated = LessonsFile([x for x in updated.lessons if x is not oldest], file.header)
    return CurationResult(updated, action, lid, tuple(archived))


@dataclass(frozen=True)
class Applied:
    """`paths` are what `commit_memory_change` stages; `outcomes` (action and lesson id, in order) are its detail."""

    paths: list[str] = field(default_factory=list)
    outcomes: list[CurationResult] = field(default_factory=list)


def archive_path(lessons_file: str, lid: str) -> str:
    return str(PurePosixPath(lessons_file).parent / ARCHIVE_DIR / f"{lid}.md")


def apply_candidates(
    worktree: Path,
    cfg: MemoryCfg,
    candidates: Sequence[LessonCandidate],
    writer: EventWriter | None = None,
    *,
    today: date | None = None,
) -> Applied:
    """Curate in order, write the lessons file and the archive files, and emit one `lessons.curated{action, id}` event
    per outcome. The result names the repository-relative paths that changed and the outcomes; an unusable lessons
    path or file, or one with parts that could not be read, changes nothing (`refused`)."""
    if not cfg.enabled or not candidates:
        return Applied()
    text, problem = read_lessons_file(worktree, cfg.lessons_file)
    parsed = parse_lessons(text)
    refusal = problem or (parsed.problems[0] if parsed.problems else None)
    if refusal is not None:  # rewriting would drop what could not be read, and a human's edit is not ours to lose
        if writer is not None:
            writer.append("lessons.curated", action="refused", id="", reason=refusal.message)
        return Applied()
    file = parsed.file
    day = today or date.today()
    archived: list[Lesson] = []
    outcomes: list[CurationResult] = []
    events: list[dict[str, str]] = []
    for candidate in candidates:
        done = curate(file, candidate, cfg, day)
        outcomes.append(done)
        file = done.file
        archived += done.archived
        events.append({"action": done.action, "id": done.lesson_id, "origin": candidate.origin})
        events += [{"action": "archived", "id": lesson.id, "origin": candidate.origin} for lesson in done.archived]
    changed: list[str] = []
    try:  # the ledger must not claim a lesson that never landed: events follow the writes
        for relative in (cfg.lessons_file, *(archive_path(cfg.lessons_file, x.id) for x in archived)):
            reject_symlinks(worktree, *PurePosixPath(relative).parts)
        for lesson in archived:
            relative = archive_path(cfg.lessons_file, lesson.id)
            target = worktree / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(target, render_lessons(LessonsFile([lesson], file.header)).encode("utf-8"))
            changed.append(relative)
        if write_lessons(worktree / cfg.lessons_file, file):
            changed.append(cfg.lessons_file)
    except OSError as exc:  # UnsafeFile is one
        if writer is not None:
            writer.append("lessons.curated", action="refused", id="", reason=str(exc))
        return Applied()
    if writer is not None:
        for event in events:
            writer.append("lessons.curated", **event)
    return Applied(changed, outcomes)
