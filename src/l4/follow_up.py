"""Follow-up units: feedback on a merged unit becomes a unit of its own (L4-FBK-010; design D11).

`make_follow_up` is the step a base-branch run takes for one `merged` unit whose `feedback.md` on the base has takeable
items and no open follow-up (the planner's `follow_up`). It cuts the unit branch `<prefix><fw>/<parent>-followup-<n>`
from the base head in a worktree of its own, writes the follow-up the way a fix unit is written (one task per item by
kind: the same `plan_fix_unit`), adds `.l4/followup.json`, sets the items' Status `taken` (Outcome
`Taken into <follow-up>`) in the branch's copy of the parent's file, writes `feedback.taken` for each item to the
follow-up's own ledger, commits, and pushes that branch. The base branch is never pushed to, and nothing is opened
on the forge: the follow-up is an ordinary unit from here on, and its first run pushes it again and opens its draft pull
request.

`perform_follow_ups` does it for every such unit of a run (`l4 run`, `l4 plan --sweep`), one at a time, each under the
parent's lease; a failure of one never stops the others and is raised after the last.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from l4.config.defaults import cache_root
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.forge.base import fetch_auth_config
from l4.forge.gitlab import push_auth_config
from l4.forge.pushfail import explain_push_failure
from l4.outcome import new_run_id
from l4.specs.base import Criterion, Framework, SpecProvider, UnitRef
from l4.specs.criteria import openspec_criteria
from l4.specs.feedback import FeedbackFile, FeedbackItem, FeedbackStatus
from l4.specs.followup import follow_up_name, parent_folder, read_follow_up_marker
from l4.specs.kiro import KiroProvider
from l4.specs.openspec import OpenSpecProvider
from l4.state.ledger import LedgerWriter
from l4.state.lifecycle import Phase
from l4.state.status import UnitSnapshot
from l4.vcs.errors import GitError
from l4.vcs.git import BOT_IDENTITY, Git
from l4.vcs.locks import Busy, LocalFileLease
from l4.vcs.names import UnitNames
from l4.vcs.trailers import CommitTrailers
from l4.vcs.worktree import WorktreeManager
from l4.verifier.fixunit import plan_follow_up, redact_plan
from l4.verifier.types import FeedbackRef

log = logging.getLogger("l4.follow_up")


@dataclass(frozen=True)
class FollowUpMade:
    parent: str  # the parent's unit id
    follow_up: str  # the follow-up's unit id
    branch: str
    items: tuple[str, ...]  # the item ids it took
    waiting: tuple[str, ...] = ()  # the ids past the task cap, left for the next follow-up


def _family(provider: SpecProvider, parent: UnitRef) -> list[Criterion]:
    return provider.criteria(parent) if isinstance(provider, KiroProvider) else openspec_criteria(parent.path)


def _parent_in(tree: Path, cfg: L4Config, snapshot: UnitSnapshot) -> UnitRef | None:
    """The parent's folder in the follow-up's worktree: the Kiro spec, the change, or its newest archive folder."""
    ref = snapshot.ref
    if ref.framework is Framework.KIRO:
        folder = tree.joinpath(*Path(cfg.spec.kiro.root).parts, ref.name)
    else:
        changes = tree.joinpath(*Path(cfg.spec.openspec.root).parts, "changes")
        folder = changes / ref.name
        if not folder.is_dir():
            archive = sorted(d for d in (changes / "archive").glob(f"*-{ref.name}") if d.is_dir())
            folder = archive[-1] if archive else folder
    return UnitRef(ref.framework, ref.name, folder) if folder.is_dir() and not folder.is_symlink() else None


def _provider_in(tree: Path, cfg: L4Config, app: AppContext, framework: Framework) -> SpecProvider:
    if framework is Framework.KIRO:
        kiro = cfg.spec.kiro
        return KiroProvider(tree, root=kiro.root, enforce=cfg.sdd.enforce, exempt_kinds=cfg.tdd.exempt_task_kinds)
    return OpenSpecProvider(tree, app.environ, root=cfg.spec.openspec.root)


def make_follow_up(
    app: AppContext, cfg: L4Config, git: Git, snapshot: UnitSnapshot, items: tuple[FeedbackItem, ...], n: int
) -> FollowUpMade | None:
    """Create and push follow-up `n` of the merged unit for `items`. None when the branch is already on `origin` (an
    earlier run made it, or a concurrent one is), and nothing was written."""
    parent = snapshot.ref
    name = follow_up_name(parent.name, n)
    follow_id = f"{parent.framework.value}:{name}"
    cache = cache_root(app.environ, repo=app.repo)
    names = UnitNames.for_unit(follow_id, branch_prefix=cfg.forge.branch_prefix, cache=cache)
    push_config = push_auth_config(cfg, app.environ)
    exists = git.run("ls-remote", "origin", f"refs/heads/{names.branch}", config=fetch_auth_config(cfg, app.environ))
    if exists.stdout.strip():
        log.info("%s: %s is on origin already", parent.id, names.branch)
        return None
    manager = WorktreeManager(
        git, base_branch=cfg.forge.base_branch, branch_prefix=cfg.forge.branch_prefix,
        fetch_config=fetch_auth_config(cfg, app.environ),
    )  # fmt: skip
    tree = manager.ensure_from_base(names.branch, names.worktree)
    try:
        provider = _provider_in(tree.path, cfg, app, parent.framework)
        parent_in_tree = _parent_in(tree.path, cfg, snapshot)
        if parent_in_tree is None:
            log.warning("%s: its folder is not on %s any more; no follow-up", parent.id, cfg.forge.base_branch)
            return None
        plan = redact_plan(
            plan_follow_up(_family(provider, parent_in_tree), items, ordinal=n), app.redactor.redact_text
        )
        if not plan.taken:
            return None
        taken = [(ref.id, ref.sha256) for ref in plan.taken]
        assert isinstance(provider, KiroProvider | OpenSpecProvider)
        created = provider.create_follow_up(parent_in_tree, n, plan.groups, plan.delta, taken)
        _mark_taken(app, created, [i for i, _ in taken], name)
        run_id = _write_ledger(app, created, follow_id, names, tree.head, plan.taken)
        _commit_and_push(app, cfg, git.at(tree.path), names, parent.id, follow_id, name, n, push_config, run_id)
        log.info("%s: follow-up %s created on %s for %s", parent.id, name, names.branch, ", ".join(i for i, _ in taken))
        return FollowUpMade(parent.id, follow_id, names.branch, tuple(i for i, _ in taken), tuple(plan.waiting))
    finally:
        manager.remove(names.worktree)


def _mark_taken(app: AppContext, created: UnitRef, ids: list[str], name: str) -> None:
    """Status `taken` and the Outcome line in the follow-up branch's copy of the parent's `feedback.md`."""
    marker = read_follow_up_marker(created.path)
    assert marker is not None
    folder = parent_folder(created.path, marker)
    file = FeedbackFile.load(folder) if folder is not None else None
    if file is None:
        return
    for fid in ids:
        if file.get(fid) is not None:
            file = file.set_status(fid, FeedbackStatus.TAKEN).set_outcome(
                fid, f"Taken into {name}", redactor=app.redactor
            )
    file.save()


def _write_ledger(
    app: AppContext, created: UnitRef, follow_id: str, names: UnitNames, head: str, refs: Sequence[FeedbackRef]
) -> str:
    run_id = new_run_id()
    while run_id == app.run_id:
        run_id = new_run_id()
    writer = LedgerWriter.open(
        created.path, follow_id, run_id, redactor=app.redactor, command="follow-up", branch=names.branch, base=head,
        source="base",
    )  # fmt: skip
    for ref in refs:
        writer.append("feedback.taken", id=ref.id, kind=ref.kind, sha256=ref.sha256, round=0, fix_unit=created.name)
    writer.finish(0)
    return run_id


def _commit_and_push(
    app: AppContext, cfg: L4Config, git: Git, names: UnitNames, parent_id: str, follow_id: str, name: str, n: int,
    push_config: tuple[tuple[str, str], ...], run_id: str,
) -> None:  # fmt: skip
    git.run("add", "-A")
    trailers = CommitTrailers(unit=follow_id, run_id=run_id, iteration=1, phase="intake")  # the ledger's run
    git.commit(f"docs({name}): follow-up {n} of {parent_id.partition(':')[2]} [skip ci]", trailers, BOT_IDENTITY)
    try:
        git.push("origin", [f"HEAD:refs/heads/{names.branch}"], config=push_config)
    except GitError as exc:
        raise explain_push_failure(
            exc, branch=names.branch, token_env=cfg.forge.token_env, environ=app.environ,
            redact=app.redactor.redact_text,
        ) from None  # fmt: skip
    remote_ref = f"refs/remotes/origin/{names.branch}"
    if git.rev_parse(remote_ref) is None:  # a clone with a narrower fetch refspec: the next listing needs the ref
        git.run("update-ref", remote_ref, "HEAD")


def perform_follow_ups(
    app: AppContext, cfg: L4Config, git: Git, snapshots: Sequence[UnitSnapshot]
) -> list[FollowUpMade]:
    """A follow-up for every merged unit the planner says `follow_up` for (takeable items, none open)."""
    made: list[FollowUpMade] = []
    errors: list[Exception] = []
    for snapshot in snapshots:
        offer = snapshot.follow_up
        if snapshot.state.phase != Phase.MERGED.value or offer is None or not offer.items or offer.open:
            continue
        names = UnitNames.for_unit(
            snapshot.ref.id, branch_prefix=cfg.forge.branch_prefix, cache=cache_root(app.environ, repo=app.repo)
        )
        lease = LocalFileLease(names.flock_path, unit=snapshot.ref.id, run_id=app.run_id)
        try:
            lease.acquire()
        except Busy:
            log.info("%s: locked by another run, no follow-up this time", snapshot.ref.id)
            continue
        try:
            if (one := make_follow_up(app, cfg, git, snapshot, offer.items, offer.n)) is not None:
                made.append(one)
        except Exception as exc:  # noqa: BLE001 - one unit's failure never stops the others
            first = (str(exc).splitlines() or [type(exc).__name__])[0]
            log.error("%s: no follow-up: %s", snapshot.ref.id, app.redactor.redact_text(first))
            errors.append(exc)
        finally:
            lease.release()
    if errors:
        raise errors[0]
    return made
