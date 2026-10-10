"""Lessons as prompt data (SPEC L4-MEM-003): select by the task's paths, wrap in `<l4:data kind="lessons">`, record
the ids in the ledger.

The file is read from the unit's worktree, so an agent sees the lessons of the base branch plus those of its own unit
branch and never those of another open unit (L4-MEM-002a). Lessons are information, not instructions: the text is
redacted and defused, so no lesson can close or open a data block.
M1: memory-lessons 2.3/2.4 add the Claude and Kiro channels (this channel is always `prompt_section`).
"""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from l4.config.schema import MemoryCfg
from l4.fsutil import UnsafeFile, read_regular_file, reject_symlinks
from l4.implementer.prompt import defuse
from l4.memory.lessons import Lesson, Problem, parse_lessons, select_lessons
from l4.vcs.git import Git

MAX_LESSONS_FILE_BYTES = 256 * 1024
CHANNEL = "prompt_section"
_BACKTICKED = re.compile(r"`([^`\s]+)`")


class EventWriter(Protocol):
    def append(self, event_type: str, /, **data: Any) -> Any: ...


@dataclass(frozen=True)
class Injection:
    block: str = ""
    ids: tuple[str, ...] = ()
    bytes: int = 0
    skipped: tuple[Problem, ...] = ()  # sections or files that were not used, for a warning


def build_lessons_block(lessons: Sequence[Lesson], redact: Callable[[str], str] = lambda text: text) -> str:
    """`<l4:data kind="lessons" ids="L-a,L-b">` with one `### <id> <title>` section per lesson. Empty for no lessons."""
    if not lessons:
        return ""
    ids = ",".join(lesson.id for lesson in lessons)
    text = "\n\n".join(f"### {lesson.id} {lesson.title}\n{lesson.body}".rstrip() for lesson in lessons)
    return f'<l4:data kind="lessons" ids="{ids}">\n{defuse(redact(text))}\n</l4:data>'


def task_paths(task_line: str, changed_files: Iterable[str] = ()) -> tuple[str, ...]:
    """The paths a task names (backticked tokens that look like a file path) plus the files the unit branch has
    already changed: what `select_lessons` matches the scopes against."""
    named = [t for t in _BACKTICKED.findall(task_line) if "/" in t or PurePosixPath(t).suffix]
    return tuple(dict.fromkeys([*named, *changed_files]))


def branch_changed_files(git: Git, base_ref: str, head: str = "HEAD") -> list[str]:
    """Paths `head` changed since its merge base with `base_ref`, committed ones: [] when either ref is missing. A
    later task of the unit is given the lessons scoped to the files an earlier task of the branch already changed."""
    base = git.rev_parse(base_ref)
    if base is None or git.rev_parse(head) is None:
        return []
    merged = git.run("merge-base", base, head, check=False)
    if merged.returncode != 0:
        return []
    raw = git.run_bytes("diff", "--name-only", "-z", "--no-renames", merged.stdout.strip(), head, check=False)
    return sorted({name.decode("utf-8", "surrogateescape") for name in raw.split(b"\0") if name})


def read_lessons_file(worktree: Path, relative: str) -> tuple[str, Problem | None]:
    """The file's text, or "" with a problem when the path is unusable (absent is not a problem)."""
    pure = PurePosixPath(relative)
    if not relative or pure.is_absolute() or ".." in pure.parts:
        return "", Problem(0, "memory.lessons_file must be a relative path inside the repository")
    try:
        reject_symlinks(worktree, *pure.parts)
        return read_regular_file(worktree / pure, limit=MAX_LESSONS_FILE_BYTES).decode("utf-8"), None
    except FileNotFoundError:
        return "", None
    except UnicodeDecodeError:  # decoding leniently would let curation rewrite a human's bytes as U+FFFD
        return "", Problem(0, "lessons file is not UTF-8")
    except (UnsafeFile, OSError) as exc:
        return "", Problem(0, f"lessons file not used: {exc}")


def inject_for_task(
    worktree: Path,
    cfg: MemoryCfg,
    task_paths: Sequence[str],
    task_kinds: Sequence[str] = (),
    writer: EventWriter | None = None,
    *,
    redact: Callable[[str], str] = lambda text: text,
) -> Injection:
    """Empty when memory is disabled, the file is absent or nothing matches. One `lessons.injected` event otherwise."""
    if not cfg.enabled:
        return Injection()
    text, problem = read_lessons_file(worktree, cfg.lessons_file)
    parsed = parse_lessons(text)
    skipped = tuple([*([problem] if problem else []), *parsed.problems])
    chosen = select_lessons(parsed.file, task_paths, task_kinds)
    block = build_lessons_block(chosen, redact)
    if not block:
        return Injection(skipped=skipped)
    result = Injection(block, tuple(lesson.id for lesson in chosen), len(block.encode("utf-8")), skipped)
    if writer is not None:
        writer.append("lessons.injected", ids=list(result.ids), channel=CHANNEL, bytes=result.bytes)
    return result
