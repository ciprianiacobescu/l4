"""Protected paths (SPEC L4-SEC-004, L4-IMP-006 step 1): what an agent step may not change is put back.

The M0 set is the design's contract list (with every `.l4/` directory at any depth and, since HB-3, the whole spec root:
`openspec/**` and `.kiro/specs/**`), `odd.forbidden_paths`, and the
unit's own spec directory, except the current run's ledger file (the ledger is appended to during the step). Every
other file under the unit directory, including a ledger file of another run, is restored or removed: a planted ledger
would otherwise fold into the unit's state.
This replaces the byte-region tasks guard (spec-providers 1.12), which is deferred.
Per-commit attribution (sandbox-security 2.10, L4-SEC-004, M1.9): `protected_changes_by_human` names the protected paths
that only people's commits changed on the unit branch (not the harness's: bot author with an `L4-Run` trailer). They
are allowed and listed; a path any harness commit also touched stays a violation.
"""

import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from l4.agents.base import EventSink
from l4.vcs.authorship import AUTHOR, SHA, commit_records, is_harness
from l4.vcs.git import Git

SPEC_ROOT_GLOBS = ("openspec/**", ".kiro/specs/**")  # reported last: a unit or family rule names a hit first
CONTRACT_PROTECTED_GLOBS = (
    ".github/workflows/**", ".gitlab-ci.yml", ".gitlab/**", ".l4/**", ".claude/**", ".mcp.json", ".codex/**",
    "opencode.json", ".kiro/agents/**", ".kiro/settings/**", ".serena/project.yml", ".serena/memories/harness/**",
    # repo guidance files the CLIs load as instructions (docs/research/07 A1): human-owned, like the specs
    "**/AGENTS.md", "**/CLAUDE.md", "**/CLAUDE.local.md", ".agents/**", ".kiro/steering/**", ".opencode/**",
    "opencode.jsonc",
    # the result alias of a prompt-contract agent step (`implementer/resultalias.py`): the harness makes and removes it
    ".l4-result/**",
    # every unit's ledger and evidence: another unit's ledger folds into that unit's state once this branch is merged
    "**/.l4/**",
    # the spec root (HB-3): the archived specs are the verifier's pass-to-pass baseline, and a sibling or archived
    # change is another unit's contract; the current unit's own directory and its run-ledger exception: `unit_dir`
    *SPEC_ROOT_GLOBS,
)  # fmt: skip
# `**/` globs match at any depth and cannot be a `git ls-files` pathspec; these root files are also listed literally,
# so an edited `.gitignore` cannot hide a root-level one. Nested ones are found under the ignore rules of the base.
ANCHORED_GUIDANCE_FILES = ("AGENTS.md", "CLAUDE.md", "CLAUDE.local.md")


@lru_cache(maxsize=256)
def _compile(pattern: str, fold_case: bool = False) -> re.Pattern[str]:
    """`**/` spans directories (also none), `**` anything, `*` and `?` stay within a segment; `dir/**` also matches
    `dir` itself, so a protected directory replaced by a file is caught. `fold_case`: any case matches."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == len(pattern):
            out.append("(?:/.*)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z", re.DOTALL | (re.IGNORECASE if fold_case else 0))


def glob_match(pattern: str, path: str, *, fold_case: bool = False) -> bool:
    return _compile(pattern, fold_case).match(path) is not None


@dataclass(frozen=True)
class ProtectedSet:
    """`unit_dir` and `run_ledger` are repository-relative POSIX paths."""

    odd_forbidden: tuple[str, ...] = ()
    unit_dir: str | None = None
    run_ledger: str | None = None
    extra_dirs: tuple[str, ...] = ()  # more unit directories: a fix unit's step may not edit its parent's
    family_globs: tuple[str, ...] = ()  # directory globs (`<changes>/<parent>-fix-*`): fix units no step may create

    def anchored_roots(self) -> list[str]:
        """Repository-relative paths that every rule not starting with `**` protects: the anchored contract list
        and the unit directory. A file hidden there stays a violation even if the ignore rules of the
        step base cover it; `odd_forbidden` is not included (`**/migrations/**` also matches installed packages)."""
        roots = [glob.removesuffix("/**") for glob in CONTRACT_PROTECTED_GLOBS if not glob.startswith("**")]
        return [*roots, *ANCHORED_GUIDANCE_FILES, *([self.unit_dir] if self.unit_dir else []), *self.extra_dirs]

    def match(self, path: str) -> str | None:
        """The rule that protects `path` (or one of its parent directories), else None."""
        if path == self.run_ledger:
            return None
        parts = path.split("/")
        for end in range(1, len(parts) + 1):
            candidate = "/".join(parts[:end])
            if candidate == self.run_ledger:
                continue
            # the contract list in any case: on a case-insensitive file system (the macOS default) a CLI that opens
            # `AGENTS.md` or `.claude/settings.json` reads `Agents.md` or `.Claude/settings.json`; a user's
            # `odd.forbidden_paths` and the unit names keep their case
            for glob in CONTRACT_PROTECTED_GLOBS:
                if glob not in SPEC_ROOT_GLOBS and glob_match(glob, candidate, fold_case=True):
                    return glob
            for glob in (*self.odd_forbidden, *self.family_globs):
                if glob_match(glob, candidate):
                    return glob
            for protected in ((self.unit_dir,) if self.unit_dir else ()) + self.extra_dirs:
                if candidate == protected or candidate.startswith(protected + "/"):
                    return f"{protected}/**"
        # the spec root (HB-3): what no unit, family or forbidden-path rule names, e.g. the archived specs
        return next((glob for glob in SPEC_ROOT_GLOBS if glob_match(glob, path, fold_case=True)), None)


def is_protected(path: str, odd_forbidden: Iterable[str] = ()) -> str | None:
    return ProtectedSet(tuple(odd_forbidden)).match(path)


@dataclass(frozen=True)
class Violation:
    path: str
    rule: str
    action: str  # "restored" (back to the step base) or "removed" (did not exist at the step base)


def _split(raw: bytes) -> list[str]:
    return [os.fsdecode(part) for part in raw.split(b"\0") if part]


def _name_status(raw: bytes) -> dict[str, bool]:
    """path -> existed at the base, from `diff --name-status -z --no-renames`."""
    fields = _split(raw)
    return {path: status != "A" for status, path in zip(fields[0::2], fields[1::2], strict=True)}


def _escape(segment: str) -> str:
    return re.sub(r"([*?\[\\])", r"\\\1", segment)


def _anchored(prefix: str, line: str) -> str:
    """A pattern of `<prefix>/.gitignore` as a pattern of the root ignore file with the same meaning."""
    body = line[1:] if line.startswith("!") else line
    bang = line[: len(line) - len(body)]
    if "/" in body.rstrip("/"):
        return f"{bang}/{prefix}/{body.lstrip('/')}"
    return f"{bang}/{prefix}/**/{body}"


def base_ignore_rules(git: Git, base: str) -> bytes:
    """The `.gitignore` files as committed at `base`, merged into one root-level exclude list (outer files first, so
    the deepest wins). The agent can edit the work tree's ignore files but not `base`, so it cannot hide a file."""
    entries = [rec for rec in git.run_bytes("ls-tree", "-r", "-z", base).split(b"\0") if rec]
    paths = []
    for rec in entries:
        meta, _, name = rec.partition(b"\t")
        path = os.fsdecode(name)
        if meta.startswith((b"100644", b"100755")) and path.rsplit("/", 1)[-1] == ".gitignore":
            paths.append(path)
    lines: list[bytes] = []
    for path in sorted(paths, key=lambda p: (p.count("/"), p)):
        prefix = "/".join(_escape(part) for part in path.split("/")[:-1])
        text = git.run_bytes("show", f"{base}:{path}").decode("utf-8", "surrogateescape")
        for line in text.splitlines():
            if not line.strip() or (line.startswith("#") and not line.startswith("\\#")):
                continue
            lines.append(os.fsencode(_anchored(prefix, line) if prefix else line))
    return b"\n".join(lines) + b"\n"


def untracked_files(git: Git, base: str, *, excludes: Path | None = None, paths: Sequence[str] = ()) -> list[str]:
    """Untracked files that the ignore rules of `base` (and the harness's `excludes` file) do not hide. Installed
    dependencies (`.venv/`, `node_modules/`) are ignored at `base` and therefore never look like a planted file."""
    with tempfile.TemporaryDirectory(prefix="l4-ignore-") as tmp:
        rules = Path(tmp) / "base-ignore"
        rules.write_bytes(base_ignore_rules(git, base))
        extra = ["--exclude-from", str(rules), *(["--exclude-from", str(excludes)] if excludes else [])]
        tail = ["--", *_literal(paths)] if paths else []
        return _split(git.run_bytes("ls-files", "--others", "-z", *extra, *tail))


def changed_paths(
    git: Git, base: str, *, excludes: Path | None = None, anchored: Sequence[str] = ()
) -> dict[str, bool]:
    """Every path whose content, index entry or existence differs from `base`, mapped to "it existed at `base`".
    The caller has already moved HEAD back to `base`. Untracked files are listed with the ignore rules of `base`,
    never those of the work tree, so an agent cannot hide a planted file behind an edited `.gitignore`; files
    under the `anchored` paths are listed without any ignore rule."""
    changed: dict[str, bool] = {}
    for extra in ((), ("--cached",)):
        raw = git.run_bytes("diff", "--name-status", "-z", "--no-renames", *extra, base, "--")
        for path, existed in _name_status(raw).items():
            changed[path] = changed.get(path, True) and existed
    for path in untracked_files(git, base, excludes=excludes):
        changed.setdefault(path, False)
    if anchored:
        for path in _split(git.run_bytes("ls-files", "--others", "-z", "--", *_literal(anchored))):
            changed.setdefault(path, False)
    return changed


def _literal(paths: Sequence[str]) -> list[str]:
    return [f":(literal){path}" for path in paths]


def _prune_empty_parents(root: Path, path: Path) -> None:
    parent = path.parent
    while parent != root and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def revert_protected(
    git: Git, protected: ProtectedSet, base: str, *, events: EventSink | None = None, excludes: Path | None = None
) -> list[Violation]:
    """Put every protected path back to its state at `base` (a commit id). `git` runs in the unit worktree.
    An agent commit (the sandbox makes `.git` read-only, so this is defence in depth) is dropped: HEAD returns to
    `base` with the work tree kept, so protected content never stays in the branch history."""
    git.run("reset", "--quiet", "--mixed", base)
    changed = changed_paths(git, base, excludes=excludes, anchored=protected.anchored_roots())
    hits = [(path, existed, rule) for path, existed in sorted(changed.items())
            if (rule := protected.match(path))]  # fmt: skip
    violations = _put_back(git, base, hits)
    if events is not None:
        for violation in violations:
            events.append("guard.violation", path=violation.path, rule=violation.rule, action=violation.action)
    return violations


def _put_back(git: Git, base: str, hits: Sequence[tuple[str, bool, str]]) -> list[Violation]:
    """(path, existed at `base`, rule): a path that did not exist is removed, one that did is checked out."""
    root = git.repo
    gone = [path for path, existed, _ in hits if not existed]
    for path in gone:
        target = root / path
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        _prune_empty_parents(root, target)
    if gone:
        git.run("rm", "--quiet", "--cached", "--ignore-unmatch", "-r", "--", *_literal(gone))
    back = [path for path, existed, _ in hits if existed]
    if back:
        git.run("checkout", base, "--", *_literal(back))
    return [Violation(path, rule, "restored" if existed else "removed") for path, existed, rule in hits]


# --- around a gate run ------------------------------------------------------------------------------------------
# Gates run agent-written test code with the worktree writable. `revert_protected` compares with a commit, which would
# undo the harness's own earlier writes (a marker, `questions.md`) that are not committed yet: the protected set is
# snapshotted before the gate and put back after it instead.

Entry = bytes | str | None  # file content, a symlink's target (as `str`), or None for a directory


def _linked_ancestor(root: Path, rel: str) -> Path | None:
    """The first parent directory of `rel` that is a symlink: nothing beneath it is ours to read or write."""
    current = root
    for part in rel.split("/")[:-1]:
        current = current / part
        if current.is_symlink():
            return current
    return None


def _entries(root: Path, rel: str, skip: str | None) -> dict[str, Entry]:
    found: dict[str, Entry] = {}
    if _linked_ancestor(root, rel) is not None:
        return found
    start = root / rel
    stack = [(start, rel)]
    while stack:
        path, name = stack.pop()
        if name == skip:
            continue
        try:
            if path.is_symlink():
                found[name] = os.readlink(path)
            elif path.is_dir():
                found[name] = None
                stack += [(child, f"{name}/{child.name}") for child in path.iterdir()]
            elif path.is_file():
                found[name] = path.read_bytes()
        except OSError:
            continue  # unreadable: the file is not the agent's to have made readable, and there is nothing to restore
    return found


def _family_roots(root: Path, protected: ProtectedSet) -> list[str]:
    """The existing directories that a family glob names (`dir/<parent>-fix-*`)."""
    found: list[str] = []
    for glob in protected.family_globs:
        parent = glob.rpartition("/")[0]
        if not parent or _linked_ancestor(root, parent + "/x") is not None:
            continue
        try:
            names = sorted(entry.name for entry in os.scandir(root / parent))
        except OSError:
            continue
        found += [f"{parent}/{name}" for name in names if glob_match(glob, f"{parent}/{name}")]
    return found


def snapshot_protected(root: Path, protected: ProtectedSet) -> dict[str, Entry]:
    """Every file under the contract paths, the unit directory and the extra unit directories, except the run's ledger
    (an open file descriptor appends to it; `Workbench.restore_ledger` owns it). A directory is an entry of its own,
    so that an emptied one is put back."""
    snapshot: dict[str, Entry] = {}
    for rel in (*protected.anchored_roots(), *_family_roots(root, protected)):
        snapshot |= _entries(root, rel, protected.run_ledger)
    return snapshot


def revert_unsnapshotted(git: Git, protected: ProtectedSet, *, excludes: Path | None = None) -> list[Violation]:
    """After a gate, the protected paths that `snapshot_protected` does not cover and that differ from HEAD are put back
    to HEAD: a rule at any depth (`**/AGENTS.md`, `**/CLAUDE.md`, `**/migrations/**`) or an `odd.forbidden_paths`
    entry. The snapshot holds only the anchored roots, since walking the whole worktree for `**` rules would read every
    installed dependency. The agent step before the gate was reverted against its base, and between two commits the
    harness writes only below the snapshot's roots (the unit directories, the run's ledger), so any other protected
    difference from HEAD is the gate's own. Untracked files are listed under the ignore rules of HEAD and the
    harness's excludes, as for the agent step."""
    head = git.rev_parse("HEAD")
    if head is None:
        return []
    covered = [*protected.anchored_roots(), *_family_roots(git.repo, protected)]
    hits = [
        (path, existed, rule)
        for path, existed in sorted(changed_paths(git, head, excludes=excludes).items())
        if not any(path == r or path.startswith(r + "/") for r in covered) and (rule := protected.match(path))
    ]
    return _put_back(git, head, hits)


def restore_protected(root: Path, protected: ProtectedSet, before: dict[str, Entry]) -> list[Violation]:
    """Put the snapshot back: changed and deleted entries are rewritten, new ones removed."""
    after = snapshot_protected(root, protected)
    violations: list[Violation] = []
    for path in sorted(after.keys() - before.keys(), key=len, reverse=True):  # children before their directory
        _remove(root / path)
        violations.append(Violation(path, protected.match(path) or "protected path", "removed"))
    for path in sorted(before.keys() - after.keys() | {p for p in before if p in after and before[p] != after[p]}):
        if (planted := _linked_ancestor(root, path)) is not None:
            planted.unlink()  # a symlink the gate put in place of a directory: never write through it
        _write(root / path, before[path])
        violations.append(Violation(path, protected.match(path) or "protected path", "restored"))
    return violations


def _remove(target: Path) -> None:
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)


def _write(target: Path, entry: Entry) -> None:
    if entry is None:
        if target.is_symlink() or target.is_file():
            target.unlink()
        target.mkdir(parents=True, exist_ok=True)
        return
    if target.is_symlink() or target.is_file() or target.is_dir():
        _remove(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(entry, str):
        os.symlink(entry, target)
    else:
        target.write_bytes(entry)


# --- per-commit attribution (L4-SEC-004) ------------------------------------------------------------------------


@dataclass(frozen=True)
class HumanCommit:
    sha: str
    author: str


@dataclass(frozen=True)
class HumanChange:
    """A protected path that only people's commits changed on the unit branch."""

    path: str
    commits: tuple[HumanCommit, ...]


def protected_changes_by_human(git: Git, base: str, head: str, paths: Sequence[str]) -> list[HumanChange]:
    """Of `paths` (protected paths that differ between `base` and `head`), the ones whose every touching commit in
    `base..head` is a person's (`git log`, default history simplification). A path a harness commit also touched, or
    that no commit in the range names, is not listed: the caller keeps it a blocker."""
    found: list[HumanChange] = []
    for path in paths:
        records = commit_records(git, f"{base}..{head}", "--", f":(literal){path}")
        if records and not any(is_harness(r) for r in records):
            found.append(HumanChange(path, tuple(HumanCommit(r[SHA], r[AUTHOR]) for r in reversed(records))))
    return found
