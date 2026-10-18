"""Reading a pytest traceback or log for the harness (SPEC L4-IMP-060, L4-IMP-064, L4-VER-009): the `E` lines of a
collection error, the deepest repository location, the names a traceback's code lines call, and the bounded text the
committed ledger keeps. Pure text work shared by the implementer and the verifier; no redaction here (the callers
redact what they emit)."""

import re
from collections.abc import Collection, Sequence
from pathlib import Path

COLLECTION_LINE = re.compile(r"^(E\s+.+|\w*(?:Error|Exception)\b.*)$")
_COLLECTING = re.compile(r"^_{3,} ERROR collecting (\S+) _{3,}$")
_SECTION_END = re.compile(r"^(?:_{3,}|={3,})")
MAX_COLLECTION_ERROR_CHARS = 600
LOCATION = re.compile(r"^(?P<path>[^\s:][^:\s]*):(?P<line>\d+): ?(?P<what>.*)$")
_NOT_REPO = ("site-packages/", "/lib/python", "<frozen", ".venv/", "<tmp>")
_MARKERS_ONLY = re.compile(r"^[\s^~]*$")
_CALLED = re.compile(r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\(")
_DECORATOR = re.compile(r"@\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)")


def in_repository(path: str) -> bool:
    return not path.startswith("/") and not any(mark in path for mark in _NOT_REPO)


def own_section(lines: Sequence[str], stem: str) -> Sequence[str] | None:
    """The lines pytest printed under `ERROR collecting <the file of stem>`; None when it printed no such section."""
    for i, line in enumerate(lines):
        if (m := _COLLECTING.match(line.strip())) and stem in m.group(1):
            end = next((j for j in range(i + 1, len(lines)) if _SECTION_END.match(lines[j].strip())), len(lines))
            return lines[i + 1 : end]
    return None


def collection_error(log_path: Path, stem: str) -> str:
    """What the test run printed for the audit file that could not be imported: its `E ` lines (a pytest collection
    error) from its own `ERROR collecting` section when there is one (two broken files must not see each other's
    error), else from the whole log, bounded. Empty log or unreadable: the plain fact."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")[-40_000:]
    except OSError:
        text = ""
    every = text.splitlines()
    own = own_section(every, stem)
    picked = every if own is None else own
    lines = [m.group(1).strip() for line in picked if (m := COLLECTION_LINE.match(line.strip()))]
    shown = "\n".join(dict.fromkeys(lines))[:MAX_COLLECTION_ERROR_CHARS]
    return shown or "the file could not be imported when the tests were collected"


def error_lines(text: str, limit: int = MAX_COLLECTION_ERROR_CHARS) -> str:
    """The `E` lines of a traceback (stripped, each once, in order), cut at `limit`."""
    lines = [m.group(1).strip() for line in text.splitlines() if (m := COLLECTION_LINE.match(line.strip()))]
    return "\n".join(dict.fromkeys(lines))[:limit]


def first_error_line(text: str, limit: int = 300) -> str:
    return error_lines(text).split("\n", 1)[0][:limit]


def deepest_location(text: str) -> tuple[str, int] | None:
    """The last `path:line:` frame of a traceback that is a repository file (not site-packages, the stdlib or a
    virtual environment)."""
    found: tuple[str, int] | None = None
    for line in text.splitlines():
        m = LOCATION.match(line.strip())
        if m is not None and in_repository(m.group("path")):
            found = (m.group("path"), int(m.group("line")))
    return found


def own_statement(text: str, own_files: Collection[str]) -> str | None:
    """The source line a traceback shows under its first frame in one of `own_files` (the outermost frame the unit's own
    test module has), stripped of the `>` marker; None when the traceback has no such frame or shows no line."""
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        found = LOCATION.match(raw.strip())
        if found is None or found.group("path") not in own_files:
            continue
        for follow in lines[i + 1 :]:
            code = follow.strip().removeprefix(">").strip()
            if not code or _MARKERS_ONLY.match(code):
                continue
            return None if LOCATION.match(follow.strip()) or COLLECTION_LINE.match(code) else code
        return None
    return None


def called_names(text: str) -> frozenset[str]:
    """The names a traceback's code lines call or decorate with (`a.b.c(` gives `c`, `@a.b` gives `b`)."""
    names: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or _MARKERS_ONLY.match(line) or LOCATION.match(line) or COLLECTION_LINE.match(line):
            continue
        line = line.removeprefix(">").strip()
        names.update(dotted.rsplit(".", 1)[-1] for dotted in _CALLED.findall(line))
        names.update(dotted.rsplit(".", 1)[-1] for dotted in _DECORATOR.findall(line))
    return frozenset(names)


def ledger_excerpt(text: str, limit: int = MAX_COLLECTION_ERROR_CHARS) -> str:
    """What the committed ledger keeps of a failed run: the `E` lines and the deepest repository location, at most
    `limit` characters. The callers redact it."""
    where = deepest_location(text)
    tail = f"{where[0]}:{where[1]}" if where else ""
    head = error_lines(text, limit - len(tail) - 1 if tail else limit)
    return f"{head}\n{tail}" if head and tail else head or tail
