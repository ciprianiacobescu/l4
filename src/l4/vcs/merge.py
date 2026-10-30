"""The base branch merged into a unit branch (state-vcs-locks 1.27, 1.28; SPEC 12.3 L4-WTR-001).

`merge_base_into` runs `git merge --no-ff --no-commit <base sha>` in the unit worktree and commits the result with
the bot identity: a commit with two parents, the unit's old head first. It never fast-forwards, rebases, amends or
forces anything, so every commit the remote already has stays an ancestor of the new head and the push that follows
is a plain fast-forward (1.28). A branch that already contains the base head is left alone (no `merge` is run).

Conflicts are classified from the index (`ls-files -u`, `show :N:path`), because the runner's git (2.34) has no
`merge-tree --write-tree`. A file a resolver of the table can settle (`questions.md`, `tasks.md`, see
`l4.verifier.basemerge`) is written and staged; any other conflicting file is a source conflict: the merge is aborted
(`merge --abort`, which keeps unstaged changes such as the run's open ledger), nothing is committed, and the result
names the files. A conflict in a run ledger, or a branch that holds an `L4-Phase: archived` commit, is refused.
"""

import logging
import os
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import atomic_write_bytes
from l4.vcs.git import BOT_IDENTITY, Git, Identity
from l4.vcs.trailers import CommitTrailers

log = logging.getLogger("l4.vcs")

LEDGER_MARK = "/.l4/ledger/"
MERGE_CONFIG = (("rerere.enabled", "false"), ("merge.autoStash", "false"))  # the runner user's ~/.gitconfig is not ours
MAX_SHOWN = 5


class Escalate(Exception):
    """A resolver cannot settle the file: it stays a conflict."""


class MergeRefused(L4Exit):
    """A merge the harness will not make (dirty worktree, a run ledger in conflict, an archived branch): exit 1."""

    def __init__(self, message: str) -> None:
        super().__init__(ExitCode.INTERNAL_ERROR, message)


class BaseMergeConflict(L4Exit):
    """Step 0 found a source conflict with the base (the M1 form of verifier 1.6): exit 1, no verdict."""

    def __init__(self, base: str, base_sha: str, files: Sequence[str]) -> None:
        self.base, self.base_sha, self.files = base, base_sha, tuple(files)
        shown = ", ".join(self.files[:MAX_SHOWN]) + (
            f" (+{len(self.files) - MAX_SHOWN} more)" if len(self.files) > MAX_SHOWN else ""
        )
        super().__init__(
            ExitCode.INTERNAL_ERROR,
            f"base merge conflict with {base}@{base_sha[:10]}: {shown}; merge it by hand and push (exit 1)",
        )


@dataclass(frozen=True)
class Sides:
    """The three versions of a conflicting file; `base` is None when the file is new on both sides (add/add)."""

    path: str
    base: bytes | None
    ours: bytes
    theirs: bytes
    ours_time: int  # commit time of the last commit that touched the file on each side
    theirs_time: int
    ours_lines: tuple[int, ...] = ()  # commit time that last touched each line, per side (empty when unknown)
    theirs_lines: tuple[int, ...] = ()

    @property
    def ours_newer(self) -> bool:
        return self.ours_time >= self.theirs_time  # a tie goes to the unit branch


Resolver = Callable[[Sides], bytes]
Resolvers = Sequence[tuple[Callable[[str], bool], Resolver]]


@dataclass(frozen=True)
class MergeResult:
    kind: Literal["merged", "noop", "conflict"]
    base_sha: str
    sha: str | None = None  # the merge commit
    behind: int = 0  # commits of the base that the branch lacked
    files: tuple[str, ...] = ()  # conflicting files no resolver settled
    resolved: tuple[str, ...] = ()  # files a resolver settled
    changed: tuple[str, ...] = ()  # files the merge commit changes against the old head


def _status_paths(git: Git, config: Sequence[tuple[str, str]]) -> list[str]:
    raw = (
        git.run_bytes("status", "--porcelain=v1", "-z", "--untracked-files=all")
        if not config
        else git.run_bytes(
            *(arg for key, value in config for arg in ("-c", f"{key}={value}")),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        )
    )
    return [os.fsdecode(rec[3:]) for rec in raw.split(b"\0") if len(rec) > 3]


def _unmerged(git: Git) -> dict[str, set[int]]:
    """path -> the index stages present (1 base, 2 ours, 3 theirs)."""
    found: dict[str, set[int]] = {}
    for rec in git.run_bytes("ls-files", "-u", "-z").split(b"\0"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        found.setdefault(os.fsdecode(path), set()).add(int(meta.split()[2]))
    return found


def _commit_time(git: Git, rev: str, path: str) -> int:
    out = git.run("log", "-1", "--format=%ct", rev, "--", path, check=False).stdout.strip()
    return int(out) if out.isdigit() else 0


def _line_times(git: Git, since: str | None, rev: str, path: str) -> tuple[int, ...]:
    """Per line of `path` at `rev`: the committer time of the commit that last touched it, or 0 for a line that
    `since` (the merge base) already had. Empty when blame fails."""
    out = git.run("blame", "--line-porcelain", f"{since}..{rev}" if since else rev, "--", path, check=False)
    if out.returncode != 0:
        return ()
    times: list[int] = []
    stamp, boundary = 0, False
    for line in out.stdout.splitlines():
        if line.startswith("\t"):  # the content line closes the block of one line
            times.append(0 if boundary else stamp)
            stamp, boundary = 0, False
        elif line.startswith("committer-time "):
            stamp = int(line.split()[1])
        elif line == "boundary":
            boundary = True
    return tuple(times)


def _archived(git: Git, base_sha: str) -> bool:
    out = git.run("log", "--format=%(trailers:key=L4-Phase,valueonly,separator=%x2c)%x02", f"{base_sha}..HEAD").stdout
    return any(phase.strip() == "archived" for rec in out.split("\x02") for phase in rec.split(","))


def _abort(git: Git) -> None:
    git.run("merge", "--abort", check=False)


def merge_base_into(
    git: Git,
    base_sha: str,
    *,
    message: str,
    trailers: CommitTrailers,
    resolvers: Resolvers = (),
    keep_dirty: Collection[str] = (),
    config: Sequence[tuple[str, str]] = (),
    identity: Identity = BOT_IDENTITY,
) -> MergeResult:
    """See the module docstring. `keep_dirty`: paths that may differ from HEAD (the run's open ledger); `config`: `-c`
    pairs for the dirty check (the harness's ignore file). The worktree is `git.repo`."""
    return merge_commit_into(
        git, base_sha, message=message, trailers=trailers, resolvers=resolvers, keep_dirty=keep_dirty, config=config,
        identity=identity, label="base", refuse_archived=True,
    )  # fmt: skip


def merge_commit_into(
    git: Git,
    other_sha: str,
    *,
    message: str,
    trailers: CommitTrailers,
    resolvers: Resolvers = (),
    keep_dirty: Collection[str] = (),
    config: Sequence[tuple[str, str]] = (),
    identity: Identity = BOT_IDENTITY,
    label: str = "base",
    refuse_archived: bool = False,
) -> MergeResult:
    """The merge of `merge_base_into` for any commit: HEAD first, `other_sha` second, resolvers per conflicting path,
    an abort that names the files the table cannot settle. `label` is what the refusals call `other_sha` (the base, the
    answer commits of a person's push, L4-RACE-001); `refuse_archived` is the base merge's guard. In the result
    `base_sha` is `other_sha` and `behind` the commits of it that HEAD lacked."""
    base_sha = other_sha
    head = git.rev_parse("HEAD")
    if head is None:
        raise MergeRefused("the unit worktree has no HEAD")
    if git.run("merge-base", "--is-ancestor", base_sha, head, check=False).returncode == 0:
        return MergeResult("noop", base_sha)
    dirty = [p for p in _status_paths(git, config) if p not in set(keep_dirty)]
    if dirty:
        raise MergeRefused(
            f"the unit worktree has uncommitted changes: refusing to merge the {label} ({', '.join(dirty[:MAX_SHOWN])})"
        )
    if refuse_archived and _archived(git, base_sha):
        raise MergeRefused(
            "archive revert before a base merge (L4-ARC-006, state-vcs-locks 4.7) is not built: "
            "the branch holds an `L4-Phase: archived` commit"
        )
    behind = int(git.run("rev-list", "--count", f"{head}..{base_sha}").stdout.strip() or 0)
    # git wants a committer identity even for `--no-commit`; the runner user has none and git may not guess one
    who = (("user.name", identity.name), ("user.email", identity.email))
    done = git.run("merge", "--no-ff", "--no-commit", "--no-edit", base_sha, check=False, config=MERGE_CONFIG + who)
    conflicts = _unmerged(git) if done.returncode != 0 else {}
    if done.returncode != 0 and not conflicts:  # e.g. an untracked file would be overwritten
        _abort(git)
        first = (done.stderr.strip().splitlines() or ["git merge failed"])[0]
        raise MergeRefused(f"git merge of the {label} failed without a conflict: {first}")
    for path in conflicts:
        if LEDGER_MARK in f"/{path}":
            _abort(git)
            raise MergeRefused(f"the {label} merge conflicts in a run ledger ({path}): a harness bug, refusing")
    fork = git.run("merge-base", head, base_sha, check=False).stdout.strip() or None
    plan: dict[str, bytes] = {}
    unresolved: list[str] = []
    for path, stages in conflicts.items():
        rule = next((resolver for matches, resolver in resolvers if matches(path)), None)
        if rule is None or not {2, 3} <= stages:
            unresolved.append(path)
            continue
        sides = Sides(
            path, git.run_bytes("show", f":1:{path}") if 1 in stages else None,
            git.run_bytes("show", f":2:{path}"), git.run_bytes("show", f":3:{path}"),
            _commit_time(git, "HEAD", path), _commit_time(git, base_sha, path),
            _line_times(git, fork, "HEAD", path), _line_times(git, fork, base_sha, path),
        )  # fmt: skip
        try:
            plan[path] = rule(sides)
        except Escalate as exc:
            log.warning("%s merge: %s needs a human: %s", label, path, exc)
            unresolved.append(path)
        except Exception as exc:  # noqa: BLE001 - a rule that fails did not resolve: the abort below is clean
            log.warning(
                "%s merge: the resolver of %s failed (%s: %s): a conflict", label, path, type(exc).__name__, exc
            )
            unresolved.append(path)
    resolved = tuple(sorted(plan))
    if unresolved:
        _abort(git)
        return MergeResult("conflict", base_sha, behind=behind, files=tuple(sorted(unresolved)), resolved=resolved)
    for path, data in plan.items():
        atomic_write_bytes(Path(git.repo) / path, data)
        git.run("add", "--", path)
    sha = git.commit(message, trailers, identity, allow_empty=True)
    raw = git.run_bytes("diff", "--name-only", "-z", "--no-renames", head, sha)
    changed = tuple(sorted(os.fsdecode(p) for p in raw.split(b"\0") if p))
    return MergeResult("merged", base_sha, sha=sha, behind=behind, resolved=resolved, changed=changed)


@dataclass(frozen=True)
class BaseMoved:
    base_sha: str
    behind: int  # commits of the base that the branch lacks
    both: tuple[str, ...]  # files changed on both sides since the merge base (sorted): where a conflict can arise


def _changed(git: Git, start: str, end: str) -> set[str]:
    raw = git.run_bytes("diff", "--name-only", "-z", "--no-renames", start, end)
    return {os.fsdecode(p) for p in raw.split(b"\0") if p and LEDGER_MARK not in f"/{os.fsdecode(p)}"}


def base_moved(git: Git, base_ref: str, branch_ref: str) -> BaseMoved | None:
    """Read-only (valid on git 2.34): what step 0 would merge into `branch_ref`, or None when the branch contains the
    base head, either ref is missing, or the two share no history."""
    base, branch = git.rev_parse(base_ref), git.rev_parse(branch_ref)
    if (
        base is None
        or branch is None
        or git.run("merge-base", "--is-ancestor", base, branch, check=False).returncode == 0
    ):
        return None
    fork = git.run("merge-base", base, branch, check=False).stdout.strip()
    if not fork:
        return None
    behind = int(git.run("rev-list", "--count", f"{branch}..{base}").stdout.strip() or 0)
    return BaseMoved(base, behind, tuple(sorted(_changed(git, fork, base) & _changed(git, fork, branch))))
