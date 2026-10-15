"""After a human merges a unit's merge request (L4-ARC-003, L4-ARC-007, forge-and-ci 1.32 to 1.35).

`MergeDetector` says from the tree at the merge commit whether the merged result still holds the unit's change folder.
`PostMergeArchiver` then builds the archive merge request: a branch cut from the latest base, the pending ledger folded
into the unit's own ledger folder, `openspec archive`, one commit, one push, one ready MR. A second archive MR is never
opened while one is open, so each is built on the base the previous one merged into.

A merged unit's fix units (`<unit>-fix-<n>`, M1.3) are archived in the same commit, after the unit, in the order they
were spawned.

A Kiro unit has no change folder to archive (`kiro.archive_dir` is not honoured yet): `MergeDetector` asks for its spec
folder instead, and `PostMergeArchiver.check_done` runs the provider's done-gate on the base branch's head. A pass is
`ArchiveResult("done")` (the sweeper records `archive.done`), a refusal is `failed`; no branch and no MR are made.
M1: forge-and-ci 2.55 (`auto_merge_archive_pr`, the numbered rebuild of an unmergeable archive MR, `archive.done`).
"""

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from l4.config.defaults import cache_root
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.forge.base import Forge, PullRequest
from l4.forge.gitlab import push_auth_config
from l4.forge.pushfail import explain_push_failure
from l4.fsutil import UnsafeFile, atomic_write_bytes, reject_symlinks
from l4.specs.base import ArchiveFailed, ArchiveRefused, Framework, UnitRef
from l4.specs.kiro import KiroProvider
from l4.specs.openspec import OpenSpecProvider
from l4.state.ledger import LedgerCorrupt, ledger_dir, parse_ledger_files, read_ledger_files
from l4.state.pending import merge_ledgers, read_pending_files
from l4.vcs.errors import GitError
from l4.vcs.git import BOT_IDENTITY, Git
from l4.vcs.names import UnitNames
from l4.vcs.repokey import repository_key
from l4.vcs.trailers import CommitTrailers
from l4.vcs.worktree import WorktreeManager
from l4.verifier.fixloop import fix_units_of

if TYPE_CHECKING:
    from l4.yolo.model import MergeOutcome

log = logging.getLogger("l4.postmerge")


class MergeVerdict(StrEnum):
    NEEDS_ARCHIVE = "needs_archive"  # the change folder is still under `changes/` in the merged tree
    ARCHIVED = "archived"  # the folder is gone: the merge carried the archive, or there is nothing to archive
    UNKNOWN = "unknown"  # the merge commit is not in this clone: decide on a later run


class MergeDetector:
    """Whether a merged unit is archived is read from the tree at `merge_commit_sha`, never from a commit message or
    from the presence of an archive commit in history (L4-ARC-003): a history can hold an archive commit that a revert
    undid, or a message that lies. A merge method that makes no merge commit (fast-forward) leaves no sha: the
    question is then asked of the head of the base branch, which holds the merged result too."""

    def __init__(
        self,
        git: Git,
        *,
        base_branch: str,
        changes_dir: str = "openspec/changes",
        kiro_root: str = ".kiro/specs",
        remote: str = "origin",
        fetch_config: Sequence[tuple[str, str]] = (),
    ) -> None:
        self._git = git
        self._base = base_branch
        self._changes = changes_dir
        self._kiro = kiro_root
        self._remote = remote
        self._fetch_config = fetch_config

    def classify(self, pr: PullRequest, name: str, framework: str = "openspec") -> MergeVerdict:
        """`NEEDS_ARCHIVE` is "the unit's folder is still in the merged tree": under `changes/` for OpenSpec (an archive
        MR is due), under the Kiro root for Kiro (the done-gate is due: Kiro has no archive folder)."""
        if pr.state != "merged":
            raise ValueError(f"MR !{pr.number} is {pr.state}, not merged")
        commit = pr.merge_commit_sha or f"refs/remotes/{self._remote}/{self._base}"
        if self._git.rev_parse(commit) is None and pr.merge_commit_sha:
            self._fetch_base()  # the merge commit is on the base branch, which this clone may not have caught up with
        if self._git.rev_parse(commit) is None:
            log.warning("MR !%s: the merge commit %s is not in this clone", pr.number, commit[:12])
            return MergeVerdict.UNKNOWN
        folder = f"{self._kiro}/{name}" if framework == Framework.KIRO.value else f"{self._changes}/{name}"
        listing = self._git.run("ls-tree", "--name-only", commit, "--", folder, check=False)
        if listing.returncode != 0:
            return MergeVerdict.UNKNOWN
        return MergeVerdict.NEEDS_ARCHIVE if listing.stdout.strip() else MergeVerdict.ARCHIVED

    def _fetch_base(self) -> None:
        spec = f"+refs/heads/{self._base}:refs/remotes/{self._remote}/{self._base}"
        try:
            self._git.fetch(self._remote, refspecs=(spec,), config=self._fetch_config)
        except GitError as exc:
            log.warning("fetching %s/%s failed: %s", self._remote, self._base, str(exc).splitlines()[0][:200])


ARCHIVE_TITLE = "[l4] archive {name}"
ARCHIVE_BODY = """\
Archive of the merged unit `{unit}`, built by the L4 harness: the change folder moves to
`{changes}/archive/` under a dated name (its ledger, with the events after the hand-off, included) and the
capability specs are updated.

- Nothing else changes in this merge request.
- Merge it with the merge-commit method. The harness never merges it.
- It is built on the base branch as it was when the previous archive merge request merged: archive merge requests are
  opened one at a time.
"""
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class ArchiveResult:
    status: Literal["opened", "existing", "pending", "archived", "failed", "skipped", "done"]
    pr: PullRequest | None = None
    detail: str = ""
    archived_as: str | None = None
    base: str | None = None  # `done`: the base head whose tree the done-gate passed on


class ArchiveBlocked(Exception):
    """The archive of a unit cannot be built as it should: nothing is pushed and no merge request is opened."""


def outside_archive_paths(changed: Sequence[str], directories: Sequence[str], files: Sequence[str]) -> list[str]:
    """The changed paths that are neither under one of the directories nor exactly one of the files."""
    prefixes = tuple(d.rstrip("/") + "/" for d in directories)
    return [path for path in changed if not path.startswith(prefixes) and path not in files]


class PostMergeArchiver:
    """Opens the archive MR of one merged unit (forge-and-ci 1.33 to 1.35). The pending ledger of the unit's lock ref
    is folded into the archived `.l4/ledger/` before the folder moves (state-vcs-locks 5.6, reduced): it is never
    dropped, and the lock ref stays."""

    def __init__(
        self,
        cfg: L4Config,
        app: AppContext,
        git: Git,
        forge: Forge,
        *,
        provider_for: Callable[[Path], OpenSpecProvider] | None = None,
        kiro_provider_for: Callable[[Path], KiroProvider] | None = None,
        fetch_config: Sequence[tuple[str, str]] = (),
    ) -> None:
        self._cfg, self._app, self._git, self._forge = cfg, app, git, forge
        self._key: str | None = None
        self._other_base_said: set[int] = set()  # archive MRs to another base, said once per sweep (L4-YOLO-009)
        root = cfg.spec.openspec.root
        self._provider_for = provider_for or (lambda path: OpenSpecProvider(path, app.environ, root=root))
        kiro = cfg.spec.kiro
        self._kiro_provider_for = kiro_provider_for or (
            lambda path: KiroProvider(
                path, root=kiro.root, enforce=cfg.sdd.enforce, exempt_kinds=cfg.tdd.exempt_task_kinds
            )
        )
        self._kiro_root = kiro.root
        self._changes = f"{root}/changes"
        self._specs = f"{root}/specs"
        self._push_config = push_auth_config(cfg, app.environ)
        self._worktrees = WorktreeManager(
            git,
            base_branch=cfg.forge.base_branch,
            branch_prefix=cfg.forge.branch_prefix,
            fetch_config=fetch_config,
            cache=cache_root(app.environ, repo=app.repo),
        )

    def names(self, ref: UnitRef) -> UnitNames:
        cache = cache_root(self._app.environ, repo=self._app.repo)
        if self._key is None:
            self._key = repository_key(self._app.repo, self._app.environ)  # once per command
        return UnitNames.for_unit(ref.id, branch_prefix=self._cfg.forge.branch_prefix, cache=cache, repo_key=self._key)

    def open_archive_pr(self, ref: UnitRef, *, iteration: int = 1) -> ArchiveResult:
        names = self.names(ref)
        opened = self._forge.list_prs(f"{self._cfg.forge.branch_prefix}archive/", "open")  # L4-ARC-007: one at a time
        ours = next((pr for pr in opened if pr.head_branch == names.archive_branch), None)
        if ours is not None:
            return ArchiveResult("existing", ours)
        base = self._cfg.forge.base_branch
        waiting = [pr for pr in opened if pr.base_branch == base]  # only an archive MR to the base blocks (L4-YOLO-009)
        for other in opened:
            if other.base_branch != base and other.number not in self._other_base_said:
                self._other_base_said.add(other.number)
                log.warning(
                    "archive MR !%s (%s) is aimed at %s, not the base %s: it does not block other archives",
                    other.number, other.head_branch, other.base_branch, base,
                )  # fmt: skip
        if waiting:
            first = waiting[0]
            return ArchiveResult("pending", first, f"archive MR !{first.number} ({first.head_branch}) is open")
        if self._remote_has(names.archive_branch):
            return self._resume(names)
        try:
            return self._build(ref, names, iteration)
        except (ArchiveRefused, ArchiveFailed, ArchiveBlocked, LedgerCorrupt) as exc:
            log.error("archive of %s failed: %s", ref.id, exc)
            return ArchiveResult("failed", detail=str(exc))
        finally:
            self._worktrees.remove(names.archive_worktree)

    def check_done(self, ref: UnitRef) -> ArchiveResult:
        """The Kiro equivalent of the archive (L4-KSP-004): Kiro has no archive command and the folder stays where it
        is, so the merged tree is checked with the done-gate and nothing is pushed. `done`: every required leaf is
        `[x]` on the base branch's head. `failed`: the gate refused (the open leaves are named). `archived`: the spec
        folder is gone from the base (a person moved it)."""
        names = self.names(ref)
        tree = self._worktrees.ensure_from_base(names.archive_branch, names.archive_worktree)
        try:
            provider = self._kiro_provider_for(tree.path)
            unit = next((r for r in provider.list_units() if r.id == ref.id), None)
            if unit is None:
                gone = f"{ref.id} is no longer under {self._kiro_root} on the base branch"
                return ArchiveResult("archived", detail=gone)
            try:
                provider.archive(unit)
            except (ArchiveRefused, ArchiveFailed) as exc:
                log.error("done-gate of %s failed: %s", ref.id, exc)
                return ArchiveResult("failed", detail=str(exc))
            return ArchiveResult("done", detail=f"the done-gate passed on {tree.head[:10]}", base=tree.head)
        finally:
            self._worktrees.remove(names.archive_worktree)

    # --- internals --------------------------------------------------------------------------------------------

    def _remote_has(self, branch: str) -> bool:
        out = self._git.run("ls-remote", "origin", f"refs/heads/{branch}", config=self._push_config).stdout
        return bool(out.strip())

    def _resume(self, names: UnitNames) -> ArchiveResult:
        """The branch was pushed but the MR was not opened (a crash or a network error between the two): open it. A
        branch that has had an MR which a human closed is left alone."""
        branch = names.archive_branch
        history = [pr for pr in self._forge.list_prs(branch, "all") if pr.head_branch == branch]
        if history:
            return ArchiveResult("skipped", history[0], f"{branch} had MR !{history[0].number} ({history[0].state})")
        return ArchiveResult("opened", self._open_mr(names))

    def _open_mr(self, names: UnitNames) -> PullRequest:
        name = names.unit_id.split(":", 1)[1]
        body = ARCHIVE_BODY.format(unit=names.unit_id, changes=self._changes)
        return self._forge.create_pr(
            names.archive_branch, self._cfg.forge.base_branch, ARCHIVE_TITLE.format(name=name), body, draft=False
        )

    def _build(self, ref: UnitRef, names: UnitNames, iteration: int) -> ArchiveResult:
        tree = self._worktrees.ensure_from_base(names.archive_branch, names.archive_worktree)
        git = self._git.at(tree.path)
        provider = self._provider_for(tree.path)
        unit = next((r for r in provider.list_units() if r.id == ref.id), None)
        if unit is None:
            return ArchiveResult("archived", detail=f"{ref.id} is no longer under {self._changes} on the base branch")
        fixes = fix_units_of(provider, unit)  # the parent's fix units, in the order they were spawned (M1.3)
        capabilities = sorted({c for member in (unit, *fixes) for c in self._capabilities(member.path)})
        self._fold_pending(git, names, unit.path)
        report = provider.archive(unit)
        fix_reports = [(fix, provider.archive(fix)) for fix in fixes]  # after the parent: their requirements add to its
        git.run("add", "-A")
        listing = git.run_bytes("diff", "--cached", "--name-only", "--no-renames", "-z")
        changed = listing.decode("utf-8", "surrogateescape")
        paths = [p for p in changed.split("\0") if p]
        stray = outside_archive_paths(
            paths,
            [f"{self._changes}/{member.name}" for member in (unit, *fixes)]
            + [f"{self._changes}/archive/{done.archived_as}" for done in (report, *(r for _, r in fix_reports))],
            [f"{self._specs}/{cap}/spec.md" for cap in capabilities],
        )
        if stray:
            more = f" (+{len(stray) - 3} more)" if len(stray) > 3 else ""
            named = ", ".join(stray[:3])
            raise ArchiveBlocked(f"the archive changed paths outside the unit's archive paths: {named}{more}")
        if not paths:
            raise ArchiveBlocked("the archive changed nothing")
        trailers = CommitTrailers(unit=ref.id, run_id=self._app.run_id, iteration=max(iteration, 1), phase="archived")
        git.commit(f"chore({ref.name}): archive", trailers, BOT_IDENTITY)  # no `[skip ci]`: the repo's own CI runs
        try:
            git.push("origin", [f"HEAD:refs/heads/{names.archive_branch}"], config=self._push_config)
        except GitError as exc:
            raise explain_push_failure(
                exc, branch=names.archive_branch, token_env=self._cfg.forge.token_env, environ=self._app.environ,
                redact=self._app.redactor.redact_text,
            ) from None  # fmt: skip
        return ArchiveResult("opened", self._open_mr(names), archived_as=report.archived_as)

    @staticmethod
    def _capabilities(unit_dir: Path) -> list[str]:
        specs = unit_dir / "specs"
        if not specs.is_dir() or specs.is_symlink():
            return []
        return sorted(
            p.name for p in specs.iterdir() if p.is_dir() and not p.is_symlink() and _SAFE_SEGMENT.match(p.name)
        )

    def _fold_pending(self, git: Git, names: UnitNames, unit_dir: Path) -> None:
        """Each pending file replaces the unit branch's copy of the same run (the whole run file extends it); a copy
        that is not a prefix of the pending one was edited by someone, and the archive stops."""
        pending = read_pending_files(git, names.lock_ref)
        if not pending:
            return
        try:
            reject_symlinks(unit_dir, ".l4", "ledger")  # merged repo content: a link must not redirect the writes
        except UnsafeFile as exc:
            raise ArchiveBlocked(f"{exc}: the pending ledger cannot be folded") from None
        on_branch = read_ledger_files(unit_dir)
        merge_ledgers(parse_ledger_files(on_branch), parse_ledger_files(pending))  # LedgerCorrupt on a contradiction
        target = ledger_dir(unit_dir)
        target.mkdir(parents=True, exist_ok=True)
        if not target.resolve().is_relative_to(unit_dir.resolve()):
            raise ArchiveBlocked(f"{target} leaves the unit folder: the pending ledger cannot be folded")
        for name, data in pending.items():
            if (target / name).is_symlink():
                raise ArchiveBlocked(f"{target / name} is a symlink: the pending ledger cannot be folded")
            if name in on_branch and not data.startswith(on_branch[name]):
                raise ArchiveBlocked(f"the ledger {name} of the base branch is not a prefix of the pending ledger")
            atomic_write_bytes(target / name, data)


def merge_archive_guarded(
    app: AppContext, cfg: L4Config, git: Git, head: str, target: str, *, pr: PullRequest
) -> "MergeOutcome":
    """Fast-forward `target` to the archive branch `head` under the guard of a unit merge plus the archive's own
    (design D9, R6, L4-YOLO-009): `target` is `forge.base_branch`; `pr`, the archive pull request, is open and aimed
    at `target`; every commit after the target tip is a strict harness commit (author and committer the bot, an
    `L4-Run` trailer: the review re-entry rule), so a person's edit on the archive branch is never merged unattended;
    the target tip is an ancestor of `head`; the push is never forced. Anything that fails a check is `not_ready` and
    pushes nothing; a refusal of the push is `stale` (the target moved) or `refused` (the forge's redacted message).
    Only the checks and the push: the caller decides when to call it and records `archive.failed`."""
    from l4.yolo.merge import foreign_commits, guarded_push, remote_tip  # yolo builds on this module: imported late
    from l4.yolo.model import MergeOutcome

    def not_ready(detail: str) -> "MergeOutcome":
        return MergeOutcome("not_ready", head, None, pr.number, detail)

    if target != cfg.forge.base_branch:
        return not_ready(f"the target {target} is not the base branch {cfg.forge.base_branch}")
    if pr.state != "open":
        return not_ready(f"the archive pull request !{pr.number} is {pr.state}, not open")
    if pr.base_branch != target:
        return not_ready(f"the archive pull request !{pr.number} is aimed at {pr.base_branch}, not the target {target}")
    tip = remote_tip(git, cfg, app.environ, target)
    if tip is None:
        return not_ready(f"the target branch {target} does not exist on origin")
    foreign = foreign_commits(git, cfg, app.environ, tip, head)
    if foreign:
        return not_ready("the archive branch holds commits that are not a harness commit: " + ", ".join(foreign))
    return guarded_push(app, cfg, git, head, target, pr=pr.number)
