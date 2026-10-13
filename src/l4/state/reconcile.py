"""Reconciling a step that a killed run left half done (SPEC L4-STA-003, state-vcs-locks D1 and 1.23, local form).

While an agent runs, `Workbench.wip_snapshots` keeps a snapshot of the worktree under `refs/l4/wip/<fw>/<name>`; its
message names the step (`L4-Step: <task>/<phase>/<attempt>`), and the run's ledger file travels in it. A worktree is
rebuilt from the remote branch on every run, so the next run decides from git alone, in the SPEC's order:
- a commit of this unit carries that `L4-Step`: the step finished, and the snapshot is stale (`MarkFinished`);
- else the snapshot sits right on this worktree's head: it is put back and the step runs again on it (`RestoreWip`);
- else the work belonged to a head that is gone (`Rerun`): the snapshot is dropped and the step starts over.
A run that died before its first snapshot left nothing to find: the step starts over as it always did.
M1: the `step_key` of `l4.state.idempotency` as the trailer (state-vcs-locks 1.22 wiring), the pushed `l4-wip/` branch.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from l4.specs.base import UnitRef
from l4.state.ledger import LedgerWriter, ledger_dir
from l4.vcs.git import Git
from l4.vcs.wip import STEP_TRAILER, WipMismatch, restore_wip, wip_ref

log = logging.getLogger("l4.reconcile")
LOOKBACK_COMMITS = 100


@dataclass(frozen=True)
class MarkFinished:
    step: str | None
    commit: str


@dataclass(frozen=True)
class RestoreWip:
    step: str | None
    sha: str


@dataclass(frozen=True)
class Rerun:
    step: str | None


Action = MarkFinished | RestoreWip | Rerun


def _step_of(git: Git, sha: str) -> str | None:
    out = git.run("log", "-1", f"--format=%(trailers:key={STEP_TRAILER},valueonly)", sha).stdout.strip()
    return out or None


def _commit_of_step(git: Git, unit_id: str, step: str) -> str | None:
    fmt = "%H%x01" + "%x01".join(f"%(trailers:key=L4-{k},valueonly,separator=%x2c)" for k in ("Unit", "Step"))
    log_text = git.run("log", f"--max-count={LOOKBACK_COMMITS}", f"--format={fmt}%x02").stdout
    for record in filter(None, (r.strip("\n") for r in log_text.split("\x02"))):
        sha, unit, found = (part.strip() for part in record.split("\x01"))
        if unit == unit_id and found == step:
            return sha
    return None


def plan_reconcile(git: Git, unit_id: str) -> Action | None:
    """What the snapshot left by an earlier run means for this worktree. Reads only."""
    ref = wip_ref(unit_id)
    sha = git.rev_parse(ref)
    if sha is None:
        return None
    step = _step_of(git, sha)
    if step is not None and (commit := _commit_of_step(git, unit_id, step)) is not None:
        return MarkFinished(step, commit)
    if git.rev_parse(f"{sha}^") == git.rev_parse("HEAD"):
        return RestoreWip(step, sha)
    return Rerun(step)


def _drop_foreign_ledgers(git: Git, ref: UnitRef, own: Path | None) -> None:
    """A restored snapshot also brings back the killed run's ledger file, as the agent left it at the end of its step.
    That file is not trusted (the agent could have written to it before the harness restored it), and the next
    protected-path revert would remove it and record a `guard.violation`. What the run committed stays; its
    uncommitted tail is dropped, because every event the next run needs is inside a commit already."""
    directory = ledger_dir(ref.path).resolve().relative_to(git.repo.resolve())
    raw = git.run_bytes("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", directory.as_posix())
    for rec in filter(None, raw.split(b"\0")):
        path = git.repo / os.fsdecode(rec[3:])
        if own is not None and path.resolve() == own.resolve():
            continue
        if rec[:2] == b"??":
            path.unlink(missing_ok=True)
        else:
            git.run("checkout", "HEAD", "--", os.fsdecode(rec[3:]))


def reconcile(git: Git, ref: UnitRef, ledger: LedgerWriter) -> Action | None:
    """Plan, apply (restore the snapshot, or drop a stale one), and record `step.reconciled{action, ...}`."""
    action = plan_reconcile(git, ref.id)
    if action is None:
        return None
    if isinstance(action, RestoreWip):
        try:
            restore_wip(git, action.sha)
        except WipMismatch:  # the snapshot is not for this head after all: start the step over
            action = Rerun(action.step)
        else:
            _drop_foreign_ledgers(git, ref, ledger.path)
    if isinstance(action, MarkFinished | Rerun):
        git.run("update-ref", "-d", wip_ref(ref.id))
    data: dict[str, object] = {"step": action.step}
    if isinstance(action, RestoreWip):
        ledger.append("step.reconciled", action="restore_wip", sha=action.sha, **data)
    elif isinstance(action, MarkFinished):
        ledger.append("step.reconciled", action="mark_finished", commit=action.commit, **data)
    else:
        ledger.append("step.reconciled", action="rerun", **data)
    log.info("%s: reconciled an interrupted step: %s", ref.id, type(action).__name__)
    return action
