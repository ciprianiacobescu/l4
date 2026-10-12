"""Curation at the end of a verification round (plan line 36, L4-MEM-002, C18): after the evidence commit and
`after_verdict`, and only on the final PASS (a PASS that spawned a fix unit would curate nothing the next PASS could
not, and a lesson about a gap must come from the round in which the gap was closed). The lesson text is the harness's
own template; the change is its own `chore(memory)` commit (`L4-Phase: lessons`, which `subject_sha` ignores) and
reaches the branch before the hand-off."""

import logging
from pathlib import PurePosixPath

from l4.fsutil import read_regular_file, reject_symlinks
from l4.implementer.workbench import Workbench
from l4.memory.commit import commit_memory_change
from l4.memory.curate import apply_candidates, candidates_from_round, feedback_candidates, guard_violation_candidates
from l4.services import HookContext
from l4.state.fold import fold
from l4.state.ledger import read_ledger
from l4.state.lifecycle import Trigger
from l4.verifier.playwright import unit_changed_files
from l4.verifier.types import VerifyResult

log = logging.getLogger("l4.memory")
_LIMIT = 4 * 1024 * 1024  # more than any lessons file the curation would accept


def _worktree_differs_from_head(wb: Workbench, relative: str) -> bool:
    """Lessons come from what is committed: a copy in the work tree that is not at HEAD was not written by a
    `chore(memory)` commit, so it is not ours (an agent's gate or step could have planted it)."""
    pure = PurePosixPath(relative)
    if not relative or pure.is_absolute() or ".." in pure.parts:
        return False  # `apply_candidates` refuses an unusable path on its own
    try:
        reject_symlinks(wb.worktree, *pure.parts)
        current: bytes | None = read_regular_file(wb.worktree / pure, limit=_LIMIT)
    except FileNotFoundError:
        current = None
    except OSError:  # UnsafeFile is one
        return True
    committed = None
    if wb.git.run("cat-file", "-e", f"HEAD:{relative}", check=False).returncode == 0:
        committed = wb.git.run_bytes("show", f"HEAD:{relative}")
    return current != committed


def _restore_to_head(wb: Workbench, relative: str) -> None:
    """Put one path back to HEAD (or remove it when HEAD has none) and out of the index."""
    wb.git.run("reset", "--quiet", "--", f":(literal){relative}", check=False)
    if wb.git.run("cat-file", "-e", f"HEAD:{relative}", check=False).returncode == 0:
        wb.git.run("checkout", "HEAD", "--", f":(literal){relative}")
        return
    target = wb.worktree / relative
    if target.is_symlink() or target.is_file():
        target.unlink()


def curate_round(ctx: HookContext, wb: Workbench, result: VerifyResult, trigger: Trigger) -> str | None:
    """The sha of the `chore(memory)` commit, or None when nothing was curated. The caller's push comes after it.
    Lessons are advisory: a failure here is recorded as `lessons.curated{action: refused}` and never fails the PASS
    that is already pushed."""
    try:
        sha = _curate(ctx, wb, result, trigger)
    except Exception as exc:  # noqa: BLE001 - git, the file system and the curation itself all end up here
        log.warning("lesson curation failed: %s", exc)
        ctx.services.ledger.append("lessons.curated", action="refused", id="", reason=f"{type(exc).__name__}: {exc}")
        _restore_quietly(wb, ctx.cfg.memory.lessons_file)
        return None
    if sha is not None:
        ctx.push()
    return sha


def _restore_quietly(wb: Workbench, relative: str) -> None:
    """Leave no half-written lessons file for the next commit to sweep up."""
    try:
        _restore_to_head(wb, relative)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not restore %s: %s", relative, exc)


def _curate(ctx: HookContext, wb: Workbench, result: VerifyResult, trigger: Trigger) -> str | None:
    cfg = ctx.cfg
    spawned = result.fix is not None and result.fix.action == "spawn"
    if trigger is not Trigger.VERIFY_PASS or not cfg.memory.enabled:
        return None
    if _worktree_differs_from_head(wb, cfg.memory.lessons_file):
        ctx.services.ledger.append(
            "lessons.curated", action="refused", id="",
            reason="the lessons file in the work tree is not the committed one",
        )
        _restore_to_head(wb, cfg.memory.lessons_file)
        return None
    events = read_ledger(wb.ref.path).events
    # a PASS that spawned a fix unit leaves the verifier's lessons to the final PASS; feedback is judged in the round
    # that confirms it, and that round's items are not seen again in a later one
    candidates = [] if spawned else candidates_from_round(
        result, cfg, changed_files=unit_changed_files(wb.git, result.base_sha, result.head_sha),
        generated_criteria=[o.criterion for o in result.generated if o.accepted],
    )  # fmt: skip
    if not spawned:
        candidates += guard_violation_candidates(events)
    candidates += feedback_candidates(wb.ref.path, wb.ref.id, fold(events, wb.ref.id).feedback, result.round)
    if not candidates:
        return None
    applied = apply_candidates(wb.worktree, cfg.memory, candidates, writer=ctx.services.ledger)
    detail = ", ".join(f"lesson {o.lesson_id} {o.action}" for o in applied.outcomes)
    return commit_memory_change(
        wb.git, applied.paths, unit=wb.ref.id, run_id=wb.run_id, iteration=max(wb.iteration, 1), detail=detail
    )  # fmt: skip
