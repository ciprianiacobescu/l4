"""What the judge reads of a unit's diff (L4-VER-040 to L4-VER-043): the harness's bookkeeping, named once, and the
diff in parts."""

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from l4.state.review import UNIT_CHANNELS
from l4.vcs.git import Git

BOOKKEEPING_GLOBS = ("**/.l4/**", ".serena/memories/harness/**")


def bookkeeping_pathspecs(unit_dirs: Sequence[str]) -> list[str]:
    """`:(glob,exclude)` for each glob, then `:(literal,exclude)<d>/<name>` for each unit folder `d` of the family and
    each file name of `l4.state.review.UNIT_CHANNELS` (every name but `.l4`, which the first glob covers)."""
    names = [n for n in UNIT_CHANNELS if n != ".l4"]
    return [f":(glob,exclude){g}" for g in BOOKKEEPING_GLOBS] + [
        f":(literal,exclude){d}/{n}" for d in unit_dirs for n in names
    ]


MAX_PART_CHARS = 120_000  # read at call time, so a test can lower it
MAX_JUDGE_PARTS = 8
RETAIN_PARTS = (
    64  # the text of about this many parts is kept while listing; the rest is fetched again if a part shows it
)
LISTING_MAX_LINES = 200  # the file list of a part prompt
LISTING_PATH_CHARS = 200
LISTING_SHARE = 4  # the file list of a part prompt takes at most 1/LISTING_SHARE of the part's characters
MAX_LOCK_HOSTS = 10
# lock files are shown to the judge as one line each and never diffed: nobody reviews them line by line, and a
# large one must not make a hold on the judge's view (L4-VER-045)
LOCK_FILES = (
    "uv.lock", "poetry.lock", "Pipfile.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "go.sum",
    "Cargo.lock", "composer.lock", "Gemfile.lock",
)  # fmt: skip
_DIFF = ("diff", "--no-color", "--no-ext-diff", "--no-textconv", "-M")
_SOURCE_FIELDS = (
    "resolved",
    "registry",
    "source",
    "url",
    "integrity",
    "hash",
    "checksum",
    "remote",
    "tarball",
    "resolution",
)
_HOST = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://(?:[^/@\s\"']*@)?([^\s/?#:\"'<>{}(),\\]+)")  # any host characters
_PY_IMPORT = re.compile(r"^\+\s*(?:from\s+([\w.]+)\s+import\s+([\w., ]+)|import\s+([\w., ]+))", re.M)
_JS_IMPORT = re.compile(r"""(?:from|require\(|import)\s*\(?\s*['"]([^'"]+)['"]""")
_TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec", "specs"})


@dataclass(frozen=True)
class DiffEntry:
    paths: tuple[str, ...]  # one path, or (old, new) for a rename or a copy
    text: str  # the entry's own `git diff` (cut to one part and one character), or the one line of a lock file
    lock: bool = False  # a lock file: `text` is its summary line
    chars: int | None = None  # the length of the whole diff when `text` holds less of it

    @property
    def length(self) -> int:
        return len(self.text) if self.chars is None else self.chars


@dataclass(frozen=True)
class DiffPart:
    index: int  # 1-based
    entries: tuple[DiffEntry, ...]
    cut: bool  # the part is one entry longer than its limit, cut to it
    limit: int = 0  # the characters a part holds; 0: MAX_PART_CHARS

    @property
    def text(self) -> str:
        joined = "".join(e.text for e in self.entries)
        return joined[: self.limit or MAX_PART_CHARS] if self.cut else joined


@dataclass(frozen=True)
class DiffParts:
    parts: tuple[DiffPart, ...]  # at most MAX_JUDGE_PARTS
    unseen: tuple[str, ...]  # the paths of the entries packed after the last part judged
    total_chars: int
    unseen_chars: tuple[int, ...] = ()  # the length of each unseen entry's text
    reserve: int = 0  # the characters of each part kept for the file list of its prompt


def group_key(path: str) -> str:
    """The base name, lower case, cut at its first `.`, without a leading `test_` and without a trailing `_test`,
    `_tests` or `_spec`: a test sits next to the code it is named after."""
    key = PurePosixPath(path).name.lower().split(".", 1)[0]
    key = key.removeprefix("test_")
    for suffix in ("_tests", "_test", "_spec"):
        if key.endswith(suffix) and len(key) > len(suffix):
            return key[: -len(suffix)]
    return key


def _is_test(path: str) -> bool:
    pure = PurePosixPath(path)
    name = pure.name.lower()
    stem = name.split(".", 1)[0]
    named = (
        stem.startswith("test_") or stem.endswith(("_test", "_tests", "_spec")) or ".test." in name or ".spec." in name
    )
    return named or any(part in _TEST_DIRS for part in pure.parts[:-1])


def _imported(text: str) -> list[str]:
    """The module names a test imports (from its added lines), as lower-case last segments, in order of appearance."""
    found: list[str] = []
    for m in _PY_IMPORT.finditer(text):
        modules = [m.group(1)] if m.group(1) else []
        modules += [n.strip() for n in (m.group(2) or m.group(3) or "").split(",")]
        found += modules
    found += _JS_IMPORT.findall(text)
    tails = (re.split(r"[./\\]", name.split(" as ")[0].strip())[-1].lower() for name in found)
    return [t for t in tails if t]


def _keys(entries: Sequence[DiffEntry]) -> dict[tuple[str, ...], str]:
    """The key an entry sorts by: the name key, and for a test with no code of its name in the diff the key of the first
    module it imports that is in the diff, so that a test lands with the code it exercises (review M2)."""
    names = {e.paths: group_key(e.paths[-1]) for e in entries}
    code = {names[e.paths] for e in entries if not _is_test(e.paths[-1])}
    keys = dict(names)
    for e in entries:
        if _is_test(e.paths[-1]) and names[e.paths] not in code:
            pick = next((t for t in _imported(e.text) if t in code), None)
            if pick is not None:
                keys[e.paths] = pick
    return keys


def pack(entries: Sequence[DiffEntry], reserve: int = 0) -> DiffParts:
    """Whole entries in `(key, path)` order, a part taking the next while it stays within MAX_PART_CHARS less `reserve`
    (the file list its prompt carries); an entry over it is a part of its own, cut. After MAX_JUDGE_PARTS parts the rest
    is `unseen`."""
    cap = MAX_PART_CHARS - reserve
    keys = _keys(entries)
    ordered = sorted(entries, key=lambda e: (keys[e.paths], e.paths[-1]))
    groups: list[list[DiffEntry]] = []
    size = 0
    for item in ordered:
        n = item.length
        if not groups or size + n > cap or size > cap:  # `size > cap`: the part is one cut entry
            groups.append([])
            size = 0
        groups[-1].append(item)
        size += n
    shown, rest = groups[:MAX_JUDGE_PARTS], groups[MAX_JUDGE_PARTS:]
    parts = tuple(
        DiffPart(i, tuple(g), cut=len(g) == 1 and g[0].length > cap, limit=cap) for i, g in enumerate(shown, start=1)
    )
    unseen = tuple(e.paths[-1] for g in rest for e in g)
    unseen_chars = tuple(e.length for g in rest for e in g)
    return DiffParts(parts, unseen, sum(e.length for e in ordered), unseen_chars, reserve)


def file_rows(parts: DiffParts) -> list[tuple[int, str, int]]:
    """Every file of the diff as `(part number, path, characters)`: part order, then the unseen files with number 0."""
    rows = [(p.index, path, e.length) for p in parts.parts for e in p.entries for path in e.paths[-1:]]
    return rows + [(0, path, chars) for path, chars in zip(parts.unseen, parts.unseen_chars, strict=True)]


def part_listing(parts: DiffParts) -> tuple[tuple[tuple[int, str, int], ...], int]:
    """The rows a part prompt lists and the number of files left out: at most LISTING_MAX_LINES, paths cut, and no more
    characters than 1/LISTING_SHARE of a part (the room `judge_parts` keeps free)."""
    rows = file_rows(parts)
    budget = MAX_PART_CHARS // LISTING_SHARE
    shown: list[tuple[int, str, int]] = []
    for n, path, chars in rows[:LISTING_MAX_LINES]:
        row = (n, path[:LISTING_PATH_CHARS], chars)
        budget -= len(f"part {n}: {row[1]} ({chars} characters)") + 1
        if budget < 0:
            break
        shown.append(row)
    return tuple(shown), len(rows) - len(shown)


def listing_chars(parts: DiffParts) -> int:
    """The characters of the file list of a part prompt (what `pack` keeps free in every part)."""
    rows, more = part_listing(parts)
    lines = sum(len(f"part {n}: {path} ({chars} characters)") + 1 for n, path, chars in rows)
    return lines + (len(f"+{more} more files: see verification.md") + 1 if more else 0)


def _lock_line(git: Git, base: str, head: str, paths: tuple[str, ...], block: str) -> str:
    """The one line of a lock file: sizes, lines changed, how many changed lines touch a source field and the hosts
    they name (a swapped package source is visible, review N3). `block` is the file's own diff: read, never shown."""
    old, new = paths[0], paths[-1]
    merge_base = git.run("merge-base", base, head, check=False).stdout.strip() or base

    def size(rev: str, path: str) -> int:
        out = git.run("cat-file", "-s", f"{rev}:{path}", check=False).stdout.strip()
        return int(out) if out.isdigit() else 0

    changed = [ln for ln in block.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    added = sum(ln.startswith("+") for ln in changed)
    lines = "binary" if "Binary files" in block and not changed else f"+{added} -{len(changed) - added} lines"
    touching = [ln for ln in changed if any(f in ln.lower() for f in _SOURCE_FIELDS)]
    hosts = sorted({h for ln in changed for h in _HOST.findall(ln)})  # as written, from every changed line
    shown = ", ".join(hosts[:MAX_LOCK_HOSTS]) + (
        f", +{len(hosts) - MAX_LOCK_HOSTS} more" if len(hosts) > MAX_LOCK_HOSTS else ""
    )
    name = new if old == new else f"{new} (renamed from {old})"
    return (
        f"lock file {name}: {size(merge_base, old)} -> {size(head, new)} bytes, {lines}, {len(touching)} touch a "
        f"source field, hosts: {shown or 'none'} (not diffed)\n"
    )


def _blocks(raw: bytes) -> list[bytes]:
    starts = [m.start() for m in re.finditer(rb"(?m)^diff --git ", raw)]
    return [raw[a:b] for a, b in zip(starts, [*starts[1:], len(raw)], strict=True)]


def _records(raw: bytes) -> list[tuple[str, ...]]:
    fields = os.fsdecode(raw).split("\0")
    found: list[tuple[str, ...]] = []
    i = 0
    while i < len(fields) and fields[i]:
        width = 2 if fields[i][0] in "RC" else 1
        found.append(tuple(fields[i + 1 : i + 1 + width]))
        i += 1 + width
    return found


def _is_lock(paths: tuple[str, ...]) -> bool:
    """Both the old and the new name are lock files: a source file renamed to `go.sum` is code, and is diffed."""
    return all(PurePosixPath(p).name in LOCK_FILES for p in paths)


def list_entries(git: Git, base: str, head: str, pathspecs: Sequence[str]) -> list[DiffEntry]:
    """One entry per changed file (a rename or a copy: one entry with both paths): the paths from one
    `git diff --name-status -z`, the content from one `git diff` split at its `diff --git` lines (the same count, else
    one diff per file). The text of the entries past about RETAIN_PARTS parts is not kept, only its length: the few that
    land in a part are fetched again (`judge_parts`). A lock file's text is its one summary line."""
    spec = ("--", ".", *pathspecs)
    records = _records(git.run_bytes("diff", "--name-status", "-z", "-M", "--no-color", f"{base}...{head}", *spec))
    blocks = _blocks(git.run_bytes(*_DIFF, f"{base}...{head}", *spec)) if records else []
    if len(blocks) != len(records):  # a header the split cannot count: ask for each file's own diff
        blocks = [git.run_bytes(*_DIFF, f"{base}...{head}", "--", *(f":(literal){p}" for p in r)) for r in records]
    budget = RETAIN_PARTS * MAX_PART_CHARS
    keep = MAX_PART_CHARS + 1
    found: list[DiffEntry] = []
    for paths, block in zip(records, blocks, strict=True):
        text = block.decode("utf-8", errors="replace")
        if _is_lock(paths):
            line = _lock_line(git, base, head, paths, text)
            found.append(DiffEntry(paths, line, lock=True, chars=len(line)))
            continue
        kept = text[:keep] if budget > 0 else ""
        budget -= len(kept)
        found.append(DiffEntry(paths, kept, chars=len(text)))
    return found


def _refill(git: Git, base: str, head: str, parts: DiffParts) -> DiffParts:
    """Fetch again the text of the entries a part shows whose text was dropped while listing."""
    keep = MAX_PART_CHARS + 1
    out: list[DiffPart] = []
    for part in parts.parts:
        entries = []
        for e in part.entries:
            if e.chars is not None and len(e.text) < min(e.chars, keep):
                full = git.run_bytes(*_DIFF, f"{base}...{head}", "--", *(f":(literal){p}" for p in e.paths))
                e = replace(e, text=full.decode("utf-8", errors="replace")[:keep])
            entries.append(e)
        out.append(replace(part, entries=tuple(entries)))
    return replace(parts, parts=tuple(out))


def judge_parts(git: Git, base: str, head: str, unit_dirs: Sequence[str]) -> DiffParts:
    """The parts the judge reads: the bookkeeping left out (L4-VER-040), whole files packed in order, each part leaving
    room for the file list of its prompt (review M3)."""
    entries = list_entries(git, base, head, bookkeeping_pathspecs(unit_dirs))
    packed = pack(entries)
    if len(packed.parts) > 1 and (reserve := listing_chars(packed)):
        packed = pack(entries, reserve=reserve)
    return _refill(git, base, head, packed)


def blob_ids(git: Git, head: str, paths: Sequence[str]) -> dict[str, str]:
    """The blob id of each of `paths` at `head` (a path not in the tree is left out), a few `git ls-tree` calls."""
    found: dict[str, str] = {}
    for i in range(0, len(paths), 200):
        out = git.run_bytes("ls-tree", "-z", head, "--", *paths[i : i + 200], check=False)
        for record in os.fsdecode(out).split("\0"):
            meta, _, path = record.partition("\t")
            if path and len(meta.split()) == 3:
                found[path] = f"{meta.split()[0]} {meta.split()[2]}"  # the mode is part of what an accept covers
    return found
