"""`l4 resume --unit ID --reason TEXT [--extend-fix-rounds N] [--extend-feedback-rounds N]` (SPEC L4-IMP-013,
SCN-RES-01..03), for a unit in `halted` or `escalated`.

The unit goes back to the phase it was halted from (`verifying` for an escalated one), `unit.resumed{reason}` is
recorded (the fold resets the breaker counters), and the ledger is committed as `chore(<unit>): resume [skip ci]` and
pushed. The next `l4 run` continues it. An escalated unit whose fix rounds are used up needs an extension:
`budget.extended{fix_rounds}` is recorded before `unit.resumed`, and the fold adds it to `verifier.max_fix_rounds`. The
local user is trusted, so there is no member check here. The label `l4:resume` is read by the sweep (`l4.ci.sweeper`,
which checks the member who set it; on an escalated unit it grants `LABEL_FIX_ROUNDS` more fix round, or
`LABEL_FEEDBACK_ROUNDS` more feedback round when the unit was escalated at the feedback limit) and ends in `resume_unit`
too.
A unit escalated at the feedback limit (`feedback_rounds_exhausted`, L4-FBK-006) needs `--extend-feedback-rounds N`
(`budget.extended{feedback_rounds}`, recorded before `unit.resumed`, added to `feedback.max_rounds`); fix rounds do not
help it.
M1: `--extend-iterations` and `--extend-cost` (the limits that read them are not built).
`l4 retry` (`l4.state.retry`, L4-OPS-001) is the same step for more phases: both end in `run_unit_in_worktree` and
`Orchestrator.resume`. `l4 resume` is `retry` restricted to `halted` and `escalated`, with its flags and refusals
unchanged; it keeps recording `unit.resumed` (compatibility), takes the `resumed` edge, and starts no run.
"""

import logging

from l4.config.redaction import load_app_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.orchestrator import UnitRunResult, run_unit_in_worktree
from l4.outcome import CommandResult
from l4.specs.base import SpecProvider, UnitRef
from l4.specs.providers import providers_for
from l4.state.budget import (
    feedback_round_limit,
    feedback_rounds_exhausted,
    fix_round_limit,
    fix_rounds_exhausted,
)
from l4.state.lifecycle import Phase
from l4.state.status import load_snapshot, refresh_refs, select_runnable
from l4.vcs.git import Git

log = logging.getLogger("l4.resume")


def resume_unit(
    app: AppContext,
    cfg: L4Config,
    git: Git,
    provider: SpecProvider,
    ref: UnitRef,
    *,
    reason: str,
    signal: str | None = None,
    by: str | None = None,
    extend_fix_rounds: int | None = None,
    extend_feedback_rounds: int | None = None,
) -> UnitRunResult:
    """The resume itself, for `l4 resume` and for the sweep's `l4:resume` label (SPEC L4-CI-004): the unit's lease and
    worktree, `budget.extended` when a fix-round extension is given, `unit.resumed{reason, by, signal}`, the lifecycle
    edge and the commit `chore(<unit>): resume [skip ci]` with its push. It runs no agent and no gate, so it needs no
    sandbox. A unit that is neither `halted` nor `escalated` is a usage error; an escalated unit with all its fix rounds
    used and no extension is refused, naming the budget (SCN-RES-02); an escalated unit at the feedback limit needs
    `extend_feedback_rounds` (L4-FBK-006); an extension of a halted unit is refused."""
    state = load_snapshot(provider, git, ref, branch_prefix=cfg.forge.branch_prefix).state
    phase = state.phase
    extra = extend_fix_rounds or 0
    if extend_fix_rounds is not None and extend_fix_rounds < 1:
        raise L4Exit(ExitCode.USAGE_ERROR, "resume: --extend-fix-rounds must be at least 1")
    more_feedback = extend_feedback_rounds or 0
    if extend_feedback_rounds is not None and extend_feedback_rounds < 1:
        raise L4Exit(ExitCode.USAGE_ERROR, "resume: --extend-feedback-rounds must be at least 1")
    if phase == Phase.ESCALATED:
        if feedback_rounds_exhausted(state):
            if not more_feedback:
                limit = feedback_round_limit(cfg, state)
                raise L4Exit(
                    ExitCode.USAGE_ERROR,
                    f"resume: {ref.id} is escalated with all its feedback rounds used ({state.feedback_rounds_used}/"
                    f"{limit}, feedback.max_rounds); add --extend-feedback-rounds N to allow N more",
                )
        elif not extra and fix_rounds_exhausted(cfg, state):
            limit = fix_round_limit(cfg, state)
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                f"resume: {ref.id} is escalated with all its fix rounds used ({state.fix_rounds_counted}/{limit}, "
                "verifier.max_fix_rounds); add --extend-fix-rounds N to allow N more",
            )
    elif phase != Phase.HALTED:
        raise L4Exit(ExitCode.USAGE_ERROR, f"resume: {ref.id} is {phase or 'unstarted'}, not halted or escalated")
    elif extra or more_feedback:
        what = "fix rounds" if extra else "feedback rounds"
        raise L4Exit(ExitCode.USAGE_ERROR, f"resume: {ref.id} is halted, not escalated: it has no {what} to extend")
    return run_unit_in_worktree(
        app, cfg, git, provider, ref, resume_reason=reason, resume_signal=signal, resume_by=by,
        resume_extend_fix_rounds=extra or None, resume_extend_feedback_rounds=more_feedback or None,
    )  # fmt: skip


def run_resume(
    app: AppContext,
    *,
    unit: str,
    reason: str,
    extend_iterations: int | None = None,
    extend_cost: float | None = None,
    extend_fix_rounds: int | None = None,
    extend_feedback_rounds: int | None = None,
) -> CommandResult:
    if any(value is not None for value in (extend_iterations, extend_cost)):
        raise L4Exit(ExitCode.USAGE_ERROR, "resume: --extend-iterations and --extend-cost not yet implemented")
    if not reason.strip():
        raise L4Exit(ExitCode.USAGE_ERROR, "resume: --reason must say why")
    app, cfg = load_app_config(app)
    git = Git(app.repo, environ=app.environ)
    refresh_refs(app, cfg, git)
    provider, ref = select_runnable(cfg, git, list(providers_for(cfg, app.repo, app.environ)), unit)
    result = resume_unit(
        app,
        cfg,
        git,
        provider,
        ref,
        reason=reason,
        extend_fix_rounds=extend_fix_rounds,
        extend_feedback_rounds=extend_feedback_rounds,
    )
    log.info("%s resumed: back in %s", unit, result.outcome.phase_after)
    return CommandResult(result.exit_code, [result.outcome])
