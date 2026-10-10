"""The base merge of step 0 (SPEC 10.2 L4-VER-002 step 0 "branch contains base head (else merge first)", L4-VER-011,
12.3 L4-WTR-001; state-vcs-locks 1.27, verifier 1.6).

`bring_in_base` is the first call of `verify_hook`, before the verdict answers are read and the reuse of a previous
round is decided, because the merge commit changes the subject of the round (`evidence.subject_sha`). The base is the
ref `ensure` fetched when the worktree was made (`refs/remotes/origin/<forge.base_branch>`): step 0 does not fetch
again, a base that moves during the run is merged by the next run.

- The branch already contains the base head: nothing is merged, committed, pushed or recorded (a `base.conflict` that
  an earlier run left is cleared from the merge request's sticky note).
- Otherwise `merge_base_into` makes `chore(<unit>): merge <base>@<sha10> into the unit branch [skip ci]` with the bot
  identity and `L4-Phase: verifying` (no `L4-Task`, `L4-TDD` or `L4-Step`: reconcile and integrity key on those), the
  commit is pushed at once (a crash after it never merges twice) and `base.merged` is recorded. `questions.md` and
  `tasks.md` conflicts are settled by the harness (`l4.specs.harness_merge`).
- Any other conflict is the M1 form of verifier 1.6: the merge is aborted, nothing is pushed, `base.conflict` and
  `verify.step{step: "0", status: "error", reason: "base-merge-conflict"}` are recorded, and `BaseMergeConflict`
  ends the unit with exit 1 and no verdict (`Orchestrator._verify` returns it as the unit's code, so the other units
  of the run still run). The conflict task (state-vcs-locks 4.8, 4.9, verifier 5.12) is M2.
"""

from dataclasses import dataclass
from pathlib import Path

from l4.config.defaults import cache_root
from l4.exitcodes import ExitCode, L4Exit
from l4.implementer.workbench import HARNESS_EXCLUDES, clip_subject
from l4.services import HookContext
from l4.specs.harness_merge import harness_resolvers
from l4.state.fold import fold
from l4.state.ledger import ledger_path, read_ledger
from l4.vcs.merge import BaseMergeConflict, merge_base_into
from l4.vcs.trailers import CommitTrailers

SKIP_CI = "[skip ci]"


@dataclass(frozen=True)
class BaseMerge:
    kind: str  # "noop" | "merged"
    base: str
    base_sha: str
    merge_sha: str | None = None
    behind: int = 0
    resolved: tuple[str, ...] = ()
    frozen_touched: tuple[str, ...] = ()

    @property
    def note(self) -> str:
        """The step-0 note of verification.md."""
        short = self.base_sha[:10]
        if self.kind == "noop":
            return f"base {self.base}@{short} contained"
        text = f"base merged: {self.base}@{short} as {(self.merge_sha or '')[:10]} ({commits(self.behind)}"
        text += f"; resolved {', '.join(self.resolved)})" if self.resolved else ")"
        if self.frozen_touched:
            text += f"; frozen test files changed by the base: {', '.join(self.frozen_touched)}"
        return text


def commits(n: int) -> str:
    return f"{n} commit{'' if n == 1 else 's'}"


def _excludes(ctx: HookContext) -> Path:
    """The harness's ignore file of this unit (`Workbench.excludes`): the dirty check must not see `.venv/`."""
    s = ctx.services
    path = cache_root(s.app.environ, repo=s.app.repo) / "units" / s.ref.framework.value / s.ref.name / "excludes"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(HARNESS_EXCLUDES) + "\n", encoding="utf-8")
    return path


def bring_in_base(ctx: HookContext) -> BaseMerge:
    cfg, s = ctx.cfg, ctx.services
    base = cfg.forge.base_branch
    ref = f"refs/remotes/origin/{base}"
    base_sha = s.git.rev_parse(ref)
    if base_sha is None:
        raise L4Exit(ExitCode.INTERNAL_ERROR, f"the base branch {ref} is not in the checkout: fetch it first")
    events = read_ledger(s.ref.path).events
    state = fold(events, s.ref.id)
    last = next((e.type for e in reversed(sorted(events, key=lambda e: (e.ts, e.run_id, e.seq)))
                 if e.type.startswith("base.")), None)  # fmt: skip
    root = s.worktree.resolve()
    unit_rel = s.ref.path.resolve().relative_to(root).as_posix()
    ledger_rel = ledger_path(s.ref.path, s.app.run_id).resolve().relative_to(root).as_posix()
    short = base_sha[:10]
    subject = clip_subject(f"chore({s.ref.name}): merge {base}@{short} into the unit branch {SKIP_CI}")
    trailers = CommitTrailers(unit=s.ref.id, run_id=s.app.run_id, iteration=max(state.iteration, 1), phase="verifying")
    result = merge_base_into(
        s.git, base_sha, message=subject, trailers=trailers,
        resolvers=harness_resolvers(unit_rel, s.ref.framework), keep_dirty=(ledger_rel,),
        config=(("core.excludesFile", str(_excludes(ctx))),),
    )  # fmt: skip
    if result.kind == "conflict":
        round_no = (state.last_verdict.round if state.last_verdict else 0) + 1
        s.ledger.append(
            "base.conflict", base=base, base_sha=base_sha, files=list(result.files), resolved=list(result.resolved)
        )
        s.ledger.append("verify.step", round=round_no, step="0", status="error", reason="base-merge-conflict")
        raise BaseMergeConflict(base, base_sha, result.files)
    if last == "base.conflict":  # the conflict is resolved (merged now, or by a human): drop the sticky note's section
        ctx.shared["notes"] = ()
    if result.kind == "noop":
        return BaseMerge("noop", base, base_sha)
    frozen = {str(f) for e in events if e.type == "task.red_ok" for f in e.data.get("frozen") or []}
    touched = tuple(sorted(frozen & set(result.changed)))
    ctx.push()
    s.ledger.append(
        "base.merged", base=base, base_sha=base_sha, merge_sha=result.sha, behind=result.behind,
        resolved=list(result.resolved), frozen_touched=list(touched),
    )  # fmt: skip
    return BaseMerge("merged", base, base_sha, result.sha, result.behind, result.resolved, touched)
