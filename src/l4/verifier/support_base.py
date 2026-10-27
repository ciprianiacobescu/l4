"""The unit's test-support files at their base versions, for the length of a run (L4-VER-033).

An audit test (and a generated UI test's head run) must not be judged with a `conftest.py`, a fixture file or a helper
the unit itself wrote: an autouse fixture there can make the code under test look right (the verifier-6 review finding,
SPEC 10.2 step 4a). `support_at_base` puts every test-support file the unit added, changed or deleted at its base
version for the block and restores it byte for byte after, also after an error (the pattern of
`discrimination.red_code_in_place`). Runner configuration (`tdd.runner_config_files`: `pytest.ini`, `tox.ini`,
`pyproject.toml`, ...) is never reverted: those files carry dependencies and build settings the run needs, and their
runner sections are held by the red-to-green freeze and the step-1 `addopts` scan; another change guards runner
configuration in red and green."""

import contextlib
import hashlib
import os
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from l4.config.schema import L4Config
from l4.evidence.diffcov import CODE_SUFFIXES
from l4.fsutil import LinkedPath, UnsafeFile, read_inside, unlink_inside, write_inside
from l4.implementer import confined
from l4.implementer.discrimination import _drop_bytecode
from l4.implementer.tamper import facts_of
from l4.implementer.workbench import Workbench
from l4.security.protected import glob_match
from l4.vcs.git import Git
from l4.verifier.types import IntegrityReport

_EXECUTABLE = 0o100755
_LINK = 0o120000


@dataclass(frozen=True)
class SupportPlan:
    """`changes`: (path, status) with status A (the unit added it), M (changed) or D (deleted), for the test-support
    paths the unit touched. `fallback`: step 1's content scan read them and found nothing, so a test that does not run
    without them may run with them in place (L4-VER-034). `why_not`: why not, when it is false."""

    changes: tuple[tuple[str, str], ...] = ()
    fallback: bool = False
    why_not: str = ""
    base_sha: str = ""
    head_sha: str = ""


NO_SUPPORT = SupportPlan()  # the plan of a unit that changed no support file: runs are as before

# Data directories (design D13 step 3): a file ADDED under one that is not source code stays in place in every run. New
# data cannot change what a base test checks, and setting it aside breaks an honest app (review M6).
DATA_GLOBS = ("**/fixtures/**", "**/mocks/**", "**/__mocks__/**", "**/testdata/**")
_TESTISH = re.compile(r"(^test_|_test\.|\.test\.|\.spec\.)")


def collect_only_env(paths: Sequence[str]) -> dict[str, str]:
    """The environment that makes the harness's pytest plugin collect only these Python files (`L4_COLLECT_ONLY`)."""
    return {"L4_COLLECT_ONLY": os.pathsep.join(paths)}


def _readable(integrity: IntegrityReport | None) -> tuple[bool, str]:
    check = next((c for c in integrity.checks if c.name == "content scan"), None) if integrity is not None else None
    if check is not None and check.status == "ok":
        return True, ""
    if integrity is None:
        return False, "step 1 did not run"
    if check is None:
        return False, "step 1 has no content scan"
    return False, f"step 1's content scan did not read them: {check.note}"


def unit_test_plan(git: Git, cfg: L4Config, base_sha: str, head: str, integrity: IntegrityReport | None) -> SupportPlan:
    """Every test and support file the unit added, changed or deleted (design D13 step 3): the paths of
    `tdd.test_globs` and `tdd.test_support_globs`, less `.l4/` directories, runner configuration and added data files
    under `DATA_GLOBS` that are not source code. `fallback` and `why_not` are `support_plan`'s (step 5 uses them)."""
    tdd = cfg.tdd
    fields = [f for f in git.run_bytes("diff", "--name-status", "-z", "--no-renames", base_sha, head).split(b"\0") if f]
    changes = []
    for status, raw in zip(fields[0::2], fields[1::2], strict=True):
        path, letter = raw.decode("utf-8", "replace"), status.decode()[:1]
        letter = "M" if letter == "T" else letter
        if (
            not any(glob_match(g, path) for g in (*tdd.test_globs, *tdd.test_support_globs))
            or any(glob_match(g, path) for g in tdd.runner_config_files)
            or "/.l4/" in f"/{path}"
        ):
            continue
        data = any(glob_match(g, path) for g in DATA_GLOBS) and PurePosixPath(path).suffix.lower() not in CODE_SUFFIXES
        if letter == "A" and data:
            continue
        changes.append((path, letter))
    fallback, why = _readable(integrity)
    return SupportPlan(tuple(sorted(changes)), fallback, why, base_sha, head)


def runner_support(plan: SupportPlan, cfg: L4Config, git: Git) -> SupportPlan:
    """The part of a plan that step 5's head run reverts (design D16): the e2e runner's own support files. A test-glob
    `.py` file counts as support when it defines no test (`tamper.facts_of`, as `integrity._is_support` does: a helper
    named `test_utils.py` is one); the unit's real test files stay but are not collected. Another language's test-glob
    file is support when its name does not look like a test module."""
    keep = [
        (path, status)
        for path, status in plan.changes
        if is_support_file(git, cfg, path, plan.base_sha if status == "D" else plan.head_sha)
    ]
    return SupportPlan(tuple(keep), plan.fallback, plan.why_not, plan.base_sha, plan.head_sha)


def is_support_file(git: Git, cfg: L4Config, path: str, rev: str) -> bool:
    """A test or support path of the unit is support, not a test module (`runner_support`'s rule): one of
    `tdd.test_support_globs`, a `.py` file that defines no test at `rev` (or does not parse), or another language's file
    whose name does not look like a test module."""
    if any(glob_match(g, path) for g in cfg.tdd.test_support_globs):
        return True
    if path.endswith(".py"):
        shown = git.run("show", f"{rev}:{path}", check=False) if rev else None
        found = facts_of(shown.stdout) if shown is not None and shown.returncode == 0 else None
        return not found or not any(f.test for f in found.values())
    return not _TESTISH.search(PurePosixPath(path).name)


def support_plan(git: Git, cfg: L4Config, base_sha: str, head: str, integrity: IntegrityReport | None) -> SupportPlan:
    tdd = cfg.tdd
    fields = [f for f in git.run_bytes("diff", "--name-status", "-z", "--no-renames", base_sha, head).split(b"\0") if f]
    changes = []
    for status, raw in zip(fields[0::2], fields[1::2], strict=True):
        path = raw.decode("utf-8", "replace")
        if (
            any(glob_match(g, path) for g in tdd.test_support_globs)
            and not any(glob_match(g, path) for g in tdd.runner_config_files)
            and "/.l4/" not in f"/{path}"
        ):
            changes.append((path, "M" if status.decode()[:1] == "T" else status.decode()[:1]))
    check = next((c for c in integrity.checks if c.name == "content scan"), None) if integrity is not None else None
    if check is not None and check.status == "ok":
        return SupportPlan(tuple(sorted(changes)), True, "", base_sha)
    if integrity is None:
        why = "step 1 did not run"
    elif check is None:
        why = "step 1 has no content scan"
    else:
        why = f"step 1's content scan did not read them: {check.note}"
    return SupportPlan(tuple(sorted(changes)), False, why, base_sha)


def _sha(root: Path, rel: str) -> str:
    """The sha256 of a file read without following a link (L4-SEC-020); '' when it cannot be read that way."""
    try:
        read = read_inside(root, rel, limit=1 << 30)
    except UnsafeFile:
        return ""
    return hashlib.sha256(read[0]).hexdigest() if read is not None else ""


def _link_of(root: Path, rel: str) -> str | None:
    """The target of the link at `rel`, read without following anything; None when it is not a link there."""
    try:
        found = confined.read_entry(root, rel)
    except confined.LinkedParent:
        return None
    return found[1] if found is not None and found[0] == "link" else None


@dataclass
class _Original:
    path: Path
    kind: str  # file | link | absent
    data: bytes = b""
    mode: int = 0
    link: str = ""
    rel: str = ""  # the real path below the resolved worktree root: every write goes through it (L4-SEC-020)


def _base_entry(git: Git, base_sha: str, path: str) -> tuple[int, bytes] | None:
    """(mode, content) of `path` at the base, None when the base has no such file."""
    listed = git.run("ls-tree", "-z", base_sha, "--", f":(literal){path}", check=False).stdout
    if not listed:
        return None
    mode = int(listed.split(" ", 1)[0], 8)
    if mode == _LINK or listed.split("\t", 1)[0].split(" ")[1] != "blob":
        return mode, b""
    return mode, git.run_bytes("show", f"{base_sha}:{path}")


def _is_link_or_file(root: Path, rel: str) -> bool:
    return (root / rel).is_symlink() or (root / rel).is_file()


@contextmanager
def support_at_base(wb: Workbench, base_sha: str, plan: SupportPlan) -> Iterator[list[str]]:
    """Put the plan's files at their base versions for the block (an added one is set aside) and yield the paths that
    were reverted. A path that is a symbolic link at the base, or whose parent resolves outside the worktree, is left
    as it is and not yielded. Two plan paths that resolve to one real file count once. On exit every original comes
    back (content, mode, link target; a link through `l4.implementer.confined` by its real path), what the block wrote
    for an absent or deleted path is removed with the directories it made, and each file's sha256 and each link's
    target is checked. Every write, removal and read after agent code ran goes through `l4.fsutil` or `confined`, which
    never follow a link: one planted in a parent directory is removed and recorded (`Workbench.refused_write`,
    L4-SEC-021)"""
    root = wb.worktree.resolve()
    originals: list[_Original] = []
    made: list[Path] = []
    reverted: list[str] = []
    seen: set[str] = set()  # canonical paths already taken: two plan paths that resolve to one file count once
    try:
        for relative, status in plan.changes:
            target = wb.worktree / relative
            try:
                real = target.parent.resolve() / target.name
                inside = real.is_relative_to(root)
            except OSError:
                inside = False
            if not inside or target.is_dir() and not target.is_symlink():
                continue
            rel = real.relative_to(root).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            entry = _base_entry(wb.git, base_sha, relative) if status != "A" else None
            if status != "A" and (entry is None or entry[0] == _LINK):
                continue
            try:
                if target.is_symlink():
                    originals.append(_Original(target, "link", link=os.readlink(target), rel=rel))
                elif target.is_file():
                    read = read_inside(root, rel, limit=1 << 30)
                    if read is None:
                        continue
                    originals.append(_Original(target, "file", read[0], read[1] & 0o7777, rel=rel))
                else:
                    originals.append(_Original(target, "absent", rel=rel))
                if _is_link_or_file(root, rel):
                    unlink_inside(root, rel)
                if entry is not None:
                    missing = [
                        p
                        for p in reversed((root / rel).parents)
                        if p.is_relative_to(root) and p != root and not p.exists()
                    ]
                    write_inside(root, rel, entry[1], mode=0o755 if entry[0] == _EXECUTABLE else 0o644)
                    made += missing
            except UnsafeFile as exc:
                wb.refused_write(exc, path=relative, where="support-at-base")
                continue  # an original already taken is put back by the `finally` below
            _drop_bytecode(root, rel)
            reverted.append(relative)
        yield reverted
    finally:
        broken = []
        for original in reversed(originals):
            target = original.path
            try:
                if _is_link_or_file(root, original.rel):
                    unlink_inside(root, original.rel)
                if original.kind == "file":
                    write_inside(root, original.rel, original.data, mode=original.mode)
                elif original.kind == "link":
                    try:
                        confined.put_entry(root, original.rel, ("link", original.link))
                    except confined.LinkedParent as exc:
                        raise LinkedPath(exc.rel) from exc
                _drop_bytecode(root, original.rel)
                if original.kind == "file" and hashlib.sha256(original.data).hexdigest() != _sha(root, original.rel):
                    broken.append(target.name)
                if original.kind == "link" and _link_of(root, original.rel) != original.link:
                    broken.append(target.name)
            except UnsafeFile as exc:
                wb.refused_write(exc, path=original.rel, where="support-at-base")
                broken.append(target.name)
        for directory in reversed(made):
            with contextlib.suppress(OSError):
                directory.rmdir()
        if broken:
            raise RuntimeError(
                f"could not restore {', '.join(broken)} after the run with the support files at the base"
            )
