"""`lessons.md` (SPEC L4-MEM-001): the data model, a tolerant parser, the canonical writer and the lint.

The parser never raises on content: a malformed section is skipped and reported, and a file whose header is not
`v1` yields no lessons at all, because an unknown format must never reach a prompt (fail safe). The writer emits
lessons in id order with LF endings, so two branches that create different lessons merge cleanly (L4-MEM-002a).
"""

import hashlib
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath

from l4.fsutil import atomic_write_bytes
from l4.security.protected import glob_match

HEADER_LINE = "<!-- l4:lessons v1 — harness-owned; propose changes via .serena/memories/inbox/ -->"
EMPTY_TEMPLATE = HEADER_LINE + "\n"

_HEADER = re.compile(r"^<!--\s*l4:lessons\s+(\S+)")
_SECTION = re.compile(r"^## (L-[0-9a-f]{8}) · (.+?)\s*$")
_BULLET = re.compile(r"^- \*\*([^*:]+):\*\*[ \t]*(.*?)\s*$")
_GLOB = re.compile(r"`([^`]+)`")
_REINFORCED = re.compile(r"^(\d+)(?:\s*[,·]\s*(\d{4}-\d{2}-\d{2}))?$")
# design.md writes ' · '; the ',' form an earlier build wrote is still read
_KINDS_MARK = "task kinds:"
_BULLET_ORDER = ("Scope", "Source", "Dedupe key", "Supersedes", "Reinforced")


def lesson_id(dedupe_key: str) -> str:
    """`L-` + the first 8 hex digits of sha256 of the key as UTF-8, stripped of surrounding whitespace (L4-MEM-002a)."""
    return "L-" + hashlib.sha256(dedupe_key.strip().encode("utf-8")).hexdigest()[:8]


@dataclass(frozen=True)
class Lesson:
    id: str
    title: str
    dedupe_key: str
    body: str = ""
    scope_globs: tuple[str, ...] = ()
    scope_kinds: tuple[str, ...] = ()
    source: str = ""
    supersedes: str | None = None
    reinforced_count: int = 1
    last_reinforced: date | None = None
    extra_bullets: tuple[tuple[str, str], ...] = ()  # bullets this version does not know are kept on a round trip


@dataclass(frozen=True)
class Problem:
    line: int  # 1-based line of the section heading (or of the header); 0: the file as a whole
    message: str
    lesson_id: str | None = None


@dataclass
class LessonsFile:
    lessons: list[Lesson] = field(default_factory=list)
    header: str = HEADER_LINE


@dataclass(frozen=True)
class ParseResult:
    file: LessonsFile
    problems: list[Problem]


def _scope(value: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    head, _, kinds = value.partition(_KINDS_MARK)
    globs = tuple(_GLOB.findall(head))
    return globs, tuple(k for k in (part.strip() for part in kinds.split(",")) if k)


def _render_scope(globs: Sequence[str], kinds: Sequence[str]) -> str:
    parts = [", ".join(f"`{g}`" for g in globs)] if globs else []
    if kinds:
        parts.append(f"{_KINDS_MARK} {', '.join(kinds)}")
    return ", ".join(parts)


def _parse_section(number: int, lid: str, title: str, lines: list[str]) -> tuple[Lesson | None, Problem | None]:
    bullets: dict[str, str] = {}
    extras: list[tuple[str, str]] = []
    index = 0
    while index < len(lines) and (match := _BULLET.match(lines[index])):
        name, value = match.group(1).strip(), match.group(2)
        if name in _BULLET_ORDER:
            bullets.setdefault(name, value)
        else:
            extras.append((name, value))
        index += 1
    body = "\n".join(lines[index:]).strip("\n")
    key = bullets.get("Dedupe key", "").strip()
    if not key:
        return None, Problem(number, "section has no Dedupe key bullet", lid)
    count, last = 1, None
    if "Reinforced" in bullets:
        match = _REINFORCED.match(bullets["Reinforced"].strip())
        if match is None:
            return None, Problem(number, "Reinforced bullet is not '<count>[ · <YYYY-MM-DD>]'", lid)
        count = max(int(match.group(1)), 1)
        try:
            last = date.fromisoformat(match.group(2)) if match.group(2) else None
        except ValueError:
            return None, Problem(number, "Reinforced bullet has an impossible date", lid)
    globs, kinds = _scope(bullets.get("Scope", ""))
    supersedes = bullets.get("Supersedes", "").strip() or None
    lesson = Lesson(
        lid, title, key, body, globs, kinds, bullets.get("Source", "").strip(), supersedes, count, last, tuple(extras)
    )  # fmt: skip
    return lesson, None


def parse_lessons(text: str) -> ParseResult:
    """LF or CRLF. An empty or header-only file is zero lessons; a header that is absent or not v1 is a problem and
    zero lessons."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not text.strip():
        return ParseResult(LessonsFile(), [])
    first = next((i for i, line in enumerate(lines) if line.strip()), 0)
    head = _HEADER.match(lines[first].strip())
    if head is None or head.group(1) != "v1":
        found = "no lessons header" if head is None else f"unsupported lessons format {head.group(1)}"
        return ParseResult(LessonsFile(), [Problem(first + 1, f"{found}: no lesson is used")])
    file, problems = LessonsFile(header=lines[first].strip()), []
    sections: list[tuple[int, str, list[str]]] = []  # (heading line number, heading, lines below it)
    for number, line in enumerate(lines[first + 1 :], first + 2):
        if line.startswith("## "):
            sections.append((number, line, []))
        elif sections:
            sections[-1][2].append(line)
    for number, heading, body_lines in sections:
        match = _SECTION.match(heading)
        if match is None:
            problems.append(Problem(number, "heading is not '## L-<8 hex> · <title>'"))
            continue
        lesson, problem = _parse_section(number, match.group(1), match.group(2), body_lines)
        if problem is not None:
            problems.append(problem)
        elif lesson is not None:
            file.lessons.append(lesson)
    return ParseResult(file, problems)


def _render_one(lesson: Lesson) -> str:
    values = {
        "Scope": _render_scope(lesson.scope_globs, lesson.scope_kinds),
        "Source": lesson.source,
        "Dedupe key": lesson.dedupe_key,
        "Supersedes": lesson.supersedes or "",
        "Reinforced": "",
    }
    if lesson.reinforced_count != 1 or lesson.last_reinforced is not None:
        values["Reinforced"] = str(lesson.reinforced_count) + (
            f" · {lesson.last_reinforced.isoformat()}" if lesson.last_reinforced else ""
        )
    out = [f"## {lesson.id} · {lesson.title}"]
    out += [f"- **{name}:** {values[name]}" for name in _BULLET_ORDER if values[name]]
    out += [f"- **{name}:** {value}" for name, value in lesson.extra_bullets]
    body = lesson.body.strip("\n")
    if body:
        if _BULLET.match(body.split("\n", 1)[0]):
            out.append("")  # a body that starts like a bullet would be read back as one
        out.append(body)
    return "\n".join(out)


def render_lessons(file: LessonsFile) -> str:
    """Canonical: header, then the lessons in id order (a stable sort keeps duplicates in their input order), one
    blank line between sections, LF, one final newline."""
    sections = [_render_one(lesson) for lesson in sorted(file.lessons, key=lambda lesson: lesson.id)]
    return "\n\n".join([file.header, *sections]) + "\n"


def write_lessons(path: Path, file: LessonsFile) -> bool:
    """Atomic (temp file and rename: Serena 1.7.0 writes non-atomically). False when the bytes are unchanged."""
    data = render_lessons(file).encode("utf-8")
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, data)
    return True


def valid_glob(pattern: str) -> bool:
    pure = PurePosixPath(pattern)
    return bool(pattern.strip()) and not pure.is_absolute() and ".." not in pure.parts and "\\" not in pattern


def lint(file: LessonsFile, *, max_lessons: int, max_bytes: int, archived_ids: Collection[str] = ()) -> list[Problem]:
    """What `l4 lessons lint` and doctor MEM-001 report: unique ids, `id == lesson_id(dedupe key)`, scopes, caps and
    a `Supersedes` that points somewhere."""
    problems: list[Problem] = []
    seen: set[str] = set()
    known = {lesson.id for lesson in file.lessons} | set(archived_ids)
    for lesson in file.lessons:
        if lesson.id in seen:
            problems.append(Problem(0, "duplicate lesson id", lesson.id))
        seen.add(lesson.id)
        if lesson.id != lesson_id(lesson.dedupe_key):
            expected = lesson_id(lesson.dedupe_key)
            problems.append(Problem(0, f"id does not match the dedupe key (expected {expected})", lesson.id))
        bad = [g for g in lesson.scope_globs if not valid_glob(g)]
        problems += [Problem(0, f"invalid scope glob {g!r}", lesson.id) for g in bad]
        if lesson.supersedes and lesson.supersedes not in known:
            problems.append(Problem(0, f"supersedes unknown lesson {lesson.supersedes}", lesson.id))
    if len(file.lessons) > max_lessons:
        problems.append(Problem(0, f"{len(file.lessons)} lessons exceed memory.max_lessons ({max_lessons})"))
    size = len(render_lessons(file).encode("utf-8"))
    if size > max_bytes:
        problems.append(Problem(0, f"{size} bytes exceed memory.max_bytes ({max_bytes})"))
    return problems


def select_lessons(file: LessonsFile, task_paths: Sequence[str], task_kinds: Sequence[str] = ()) -> list[Lesson]:
    """A lesson applies when (it has no globs or a task path matches one) and (it has no kinds or one is the task's).
    Id order. # M1: memory-lessons 2.1 gives tasks kinds; 2.2 drops a superseded lesson."""
    chosen = []
    for lesson in sorted(file.lessons, key=lambda lesson: lesson.id):
        paths_ok = not lesson.scope_globs or any(glob_match(g, p) for g in lesson.scope_globs for p in task_paths)
        kinds_ok = not lesson.scope_kinds or bool(set(lesson.scope_kinds) & set(task_kinds))
        if paths_ok and kinds_ok:
            chosen.append(lesson)
    return chosen
