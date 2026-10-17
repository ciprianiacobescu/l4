"""What the judge reads of a unit's diff (L4-VER-040 to L4-VER-043): the harness's bookkeeping, named once, and the
diff in parts."""

import os
from collections.abc import Sequence
from dataclasses import dataclass
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
# lock files are shown to the judge as one line each and never diffed: nobody reviews them line by line, and a
# large one must not make a hold on the judge's view (L4-VER-041)
LOCK_FILES = (
    "uv.lock", "poetry.lock", "Pipfile.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "go.sum",
    "Cargo.lock", "composer.lock", "Gemfile.lock",
)  # fmt: skip
_DIFF = ("diff", "--no-color", "--no-ext-diff", "--no-textconv", "-M")


@dataclass(frozen=True)
class DiffEntry:
    paths: tuple[str, ...]  # one path, or (old, new) for a rename or a copy
    text: str  # the entry's own `git diff`, or the one line of a lock file
    lock: bool = False  # a lock file: `text` is its summary line


@dataclass(frozen=True)
class DiffPart:
    index: int  # 1-based
    entries: tuple[DiffEntry, ...]
    cut: bool  # the part is one entry longer than MAX_PART_CHARS, cut to it

    @property
    def text(self) -> str:
        joined = "".join(e.text for e in self.entries)
        return joined[:MAX_PART_CHARS] if self.cut else joined


@dataclass(frozen=True)
class DiffParts:
    parts: tuple[DiffPart, ...]  # at most MAX_JUDGE_PARTS
    unseen: tuple[str, ...]  # the paths of the entries packed after the last part judged
    total_chars: int
    unseen_chars: tuple[int, ...] = ()  # the length of each unseen entry's text


def group_key(path: str) -> str:
    """The base name, lower case, cut at its first `.`, without a leading `test_` and without a trailing `_test`,
    `_tests` or `_spec`: a test sits next to the code it is named after."""
    key = PurePosixPath(path).name.lower().split(".", 1)[0]
    key = key.removeprefix("test_")
    for suffix in ("_tests", "_test", "_spec"):
        if key.endswith(suffix) and len(key) > len(suffix):
            return key[: -len(suffix)]
    return key


def pack(entries: Sequence[DiffEntry]) -> DiffParts:
    """Whole entries in `(group_key, path)` order, a part taking the next while it stays within MAX_PART_CHARS; an
    entry over it is a part of its own, cut. After MAX_JUDGE_PARTS parts the rest is `unseen`."""
    cap = MAX_PART_CHARS
    ordered = sorted(entries, key=lambda e: (group_key(e.paths[-1]), e.paths[-1]))
    groups: list[list[DiffEntry]] = []
    size = 0
    for item in ordered:
        n = len(item.text)
        if not groups or size + n > cap or size > cap:  # `size > cap`: the part is one cut entry
            groups.append([])
            size = 0
        groups[-1].append(item)
        size += n
    shown, rest = groups[:MAX_JUDGE_PARTS], groups[MAX_JUDGE_PARTS:]
    parts = tuple(DiffPart(i, tuple(g), cut=len(g) == 1 and len(g[0].text) > cap) for i, g in enumerate(shown, start=1))
    unseen = tuple(e.paths[-1] for g in rest for e in g)
    unseen_chars = tuple(len(e.text) for g in rest for e in g)
    return DiffParts(parts, unseen, sum(len(e.text) for e in ordered), unseen_chars)


def _lock_line(git: Git, base: str, head: str, paths: tuple[str, ...]) -> str:
    old, new = paths[0], paths[-1]
    merge_base = git.run("merge-base", base, head, check=False).stdout.strip() or base

    def size(rev: str, path: str) -> int:
        out = git.run("cat-file", "-s", f"{rev}:{path}", check=False).stdout.strip()
        return int(out) if out.isdigit() else 0

    counts = git.run("diff", "--numstat", "-M", f"{base}...{head}", "--", *(f":(literal){p}" for p in paths))
    first = (counts.stdout.splitlines() or ["0\t0"])[0].split("\t")
    lines = f"+{first[0]} -{first[1]} lines" if first[0].isdigit() else "binary"
    return f"lock file {new}: {size(merge_base, old)} -> {size(head, new)} bytes, {lines} (not diffed)\n"


def list_entries(git: Git, base: str, head: str, pathspecs: Sequence[str]) -> list[DiffEntry]:
    """One entry per changed file (a rename or a copy: one entry with both paths), from `git diff --name-status -z`;
    no parsing of unified diff output. A lock file's text is its one summary line."""
    raw = git.run_bytes("diff", "--name-status", "-z", "-M", "--no-color", f"{base}...{head}", "--", ".", *pathspecs)
    fields = os.fsdecode(raw).split("\0")
    found: list[DiffEntry] = []
    i = 0
    while i < len(fields) and fields[i]:
        width = 2 if fields[i][0] in "RC" else 1
        paths = tuple(fields[i + 1 : i + 1 + width])
        i += 1 + width
        if PurePosixPath(paths[-1]).name in LOCK_FILES:
            found.append(DiffEntry(paths, _lock_line(git, base, head, paths), lock=True))
            continue
        diff = git.run_bytes(*_DIFF, f"{base}...{head}", "--", *(f":(literal){p}" for p in paths))
        found.append(DiffEntry(paths, diff.decode("utf-8", errors="replace")))
    return found


def judge_parts(git: Git, base: str, head: str, unit_dirs: Sequence[str]) -> DiffParts:
    """The parts the judge reads: the bookkeeping left out (L4-VER-040), whole files packed in order."""
    return pack(list_entries(git, base, head, bookkeeping_pathspecs(unit_dirs)))
