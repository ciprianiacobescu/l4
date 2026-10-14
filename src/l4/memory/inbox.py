"""Finding and checking one inbox proposal for `l4 lessons promote` (L4-KG-013, design D11 steps 1 and 2).

The inbox is `.serena/memories/inbox/<folder>/<L-id>.md`, the one place agents may write (L4-MEM-004), so every byte
here is untrusted: the id must have the form `L-<8 hex>` before it reaches a path, no component may be a symlink, the
file is read as a regular file of at most 256 KiB, and the text must be exactly one valid v1 lesson section whose id is
`lesson_id(dedupe key)`. A draft that still has its `TODO(person):` line, or has no body, is refused: a person must
write the advice. Every refusal is exit 2 (L4-KG-002) and writes nothing; this module writes nothing at all.
Imported only by `l4.memory.cli` and `l4.memory.promote` (L4-KG-001).
"""

import re
from pathlib import Path, PurePosixPath

from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import UnsafeFile, read_regular_file, reject_symlinks
from l4.memory.inject import MAX_LESSONS_FILE_BYTES
from l4.memory.lessons import Lesson, lesson_id, parse_lessons, valid_glob

INBOX = PurePosixPath(".serena/memories/inbox")
MAX_PROPOSAL_BYTES = MAX_LESSONS_FILE_BYTES  # 256 KiB
TODO_MARK = "TODO(person)"
_LID = re.compile(r"^L-[0-9a-f]{8}$")


def _refuse(message: str) -> L4Exit:
    return L4Exit(ExitCode.USAGE_ERROR, message)


def _folder_from(repo: Path, from_dir: str | Path) -> str:
    """`--from` names a folder of the inbox: its name, or its path from the repository (or absolute)."""
    root = (repo / INBOX).resolve()
    raw = Path(from_dir)
    candidates = [raw] if raw.is_absolute() else [repo / raw, root / raw]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.parent == root and resolved.is_dir() and ".." not in raw.parts:
            return resolved.name
    raise _refuse(f"--from {from_dir} is not a folder of {INBOX}/")


def find_proposal(repo: Path, lid: str, from_dir: str | Path | None) -> Path:
    """`.serena/memories/inbox/*/<lid>.md`. None: exit 2. More than one: exit 2 listing them, unless `from_dir` names
    the folder. A symlink anywhere on the path, a file that is not regular, or one over 256 KiB: exit 2."""
    if not _LID.match(lid):
        raise _refuse(f"{lid!r} is not a lesson id; the form is L-<8 hex>")
    root = repo / INBOX
    try:
        reject_symlinks(repo, *INBOX.parts)
        if from_dir is not None:
            folders = [_folder_from(repo, from_dir)]
        else:
            folders = sorted(p.name for p in root.iterdir() if p.is_dir() or p.is_symlink()) if root.is_dir() else []
        found = []
        for folder in folders:
            reject_symlinks(root, folder)
            path = root / folder / f"{lid}.md"
            if path.is_symlink() or path.exists():
                reject_symlinks(root, folder, path.name)
                found.append(path)
    except UnsafeFile as exc:
        raise _refuse(f"the proposal is not used: {exc}") from None
    if not found:
        where = f"in {INBOX}/{folders[0]}/" if from_dir is not None and folders else f"under {INBOX}/"
        raise _refuse(f"no proposal {lid}.md {where}")
    if len(found) > 1:
        listing = "\n".join(f"  {path.relative_to(repo).as_posix()}" for path in found)
        raise _refuse(f"{lid} is in more than one inbox folder; name one with --from:\n{listing}")
    return found[0]


def parse_proposal(path: Path, lid: str) -> Lesson:
    """The one lesson of a proposal file, or exit 2 with the reason."""
    try:
        text = read_regular_file(path, limit=MAX_PROPOSAL_BYTES).decode("utf-8")
    except (UnsafeFile, OSError) as exc:
        raise _refuse(f"the proposal is not used: {exc}") from None
    except UnicodeDecodeError:
        raise _refuse("the proposal is not used: it is not UTF-8") from None
    parsed = parse_lessons(text)
    if parsed.problems:
        first = parsed.problems[0]
        where = f"line {first.line}: " if first.line else ""
        raise _refuse(f"the proposal has a problem ({where}{first.message}); it must be one valid v1 lesson section")
    if len(parsed.file.lessons) != 1:
        raise _refuse(f"the proposal must have exactly one lesson section, it has {len(parsed.file.lessons)}")
    lesson = parsed.file.lessons[0]
    expected = lesson_id(lesson.dedupe_key)
    if lesson.id != expected:
        raise _refuse(f"the proposal id {lesson.id} does not match its dedupe key (expected {expected})")
    if lesson.id != lid:
        raise _refuse(f"the file holds {lesson.id}, not {lid}")
    for glob in lesson.scope_globs:
        if not valid_glob(glob):
            raise _refuse(f"the proposal has an invalid scope glob {glob!r}")
    if any(TODO_MARK in line for line in text.splitlines()):
        raise _refuse("the proposal still has its TODO(person) line")
    if not lesson.body.strip():
        raise _refuse("the proposal body is empty")
    return lesson
