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
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from l4.config.schema import L4Config
from l4.implementer.discrimination import _drop_bytecode
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


NO_SUPPORT = SupportPlan()  # the plan of a unit that changed no support file: runs are as before


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


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class _Original:
    path: Path
    kind: str  # file | link | absent
    data: bytes = b""
    mode: int = 0
    link: str = ""


def _base_entry(git: Git, base_sha: str, path: str) -> tuple[int, bytes] | None:
    """(mode, content) of `path` at the base, None when the base has no such file."""
    listed = git.run("ls-tree", "-z", base_sha, "--", f":(literal){path}", check=False).stdout
    if not listed:
        return None
    mode = int(listed.split(" ", 1)[0], 8)
    if mode == _LINK or listed.split("\t", 1)[0].split(" ")[1] != "blob":
        return mode, b""
    return mode, git.run_bytes("show", f"{base_sha}:{path}")


@contextmanager
def support_at_base(wb: Workbench, base_sha: str, plan: SupportPlan) -> Iterator[list[str]]:
    """Put the plan's files at their base versions for the block (an added one is set aside) and yield the paths that
    were reverted. A path that is a symbolic link at the base, or whose parent resolves outside the worktree, is left
    as it is and not yielded. On exit every original comes back (content, mode, link target), what the block wrote for
    an absent or deleted path is removed with the directories it made, and each regular file's sha256 is checked."""
    root = wb.worktree.resolve()
    originals: list[_Original] = []
    made: list[Path] = []
    reverted: list[str] = []
    try:
        for relative, status in plan.changes:
            target = wb.worktree / relative
            try:
                inside = (target.parent.resolve() / target.name).is_relative_to(root)
            except OSError:
                inside = False
            if not inside or target.is_dir() and not target.is_symlink():
                continue
            entry = _base_entry(wb.git, base_sha, relative) if status != "A" else None
            if status != "A" and (entry is None or entry[0] == _LINK):
                continue
            if target.is_symlink():
                originals.append(_Original(target, "link", link=os.readlink(target)))
            elif target.is_file():
                originals.append(_Original(target, "file", target.read_bytes(), target.stat().st_mode & 0o7777))
            else:
                originals.append(_Original(target, "absent"))
            if target.is_symlink() or target.is_file():
                target.unlink()
            if entry is not None:
                missing = [
                    p
                    for p in reversed(target.parents)
                    if p.is_relative_to(wb.worktree) and p != wb.worktree and not p.exists()
                ]
                target.parent.mkdir(parents=True, exist_ok=True)
                made += missing
                target.write_bytes(entry[1])
                target.chmod(0o755 if entry[0] == _EXECUTABLE else 0o644)
            _drop_bytecode(target)
            reverted.append(relative)
        yield reverted
    finally:
        broken = []
        for original in reversed(originals):
            target = original.path
            if target.is_symlink() or target.is_file():
                target.unlink()
            if original.kind == "file":
                target.write_bytes(original.data)
                target.chmod(original.mode)
            elif original.kind == "link":
                target.symlink_to(original.link)
            _drop_bytecode(target)
            if original.kind == "file" and hashlib.sha256(original.data).hexdigest() != _sha(target):
                broken.append(target.name)
        for directory in reversed(made):
            with contextlib.suppress(OSError):
                directory.rmdir()
        if broken:
            raise RuntimeError(
                f"could not restore {', '.join(broken)} after the run with the support files at the base"
            )
