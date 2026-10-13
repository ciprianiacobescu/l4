"""`l4 retry --unit ID --reason TEXT [--rounds N] [--no-run]` (L4-OPS-001, L4-OPS-002, L4-OPS-003, SCN-OPS-01..07):
the unit continues from where it stopped, by its recorded phase (design D2).

| phase | what a retry does |
|---|---|
| `halted` | back to `previous_phase`, new task attempts |
| `escalated` | back to `verifying`; at the fix-round limit `budget.extended{fix_rounds}` first, at the feedback limit |
| | `budget.extended{feedback_rounds}` (N is `--rounds`, default 1); `same_failure` is the first case when its rounds |
| | are used up, a plain retry when they are not |
| `halted`, `escalated` after a person changed the unit folder | `implementing` (`spec_edit_since_stop`, L4-OPS-003) |
| `waiting_capacity` | `capacity_restored` now, to `previous_phase`; `retry_after` is ignored |
| `in_review` | `verifying` (`retry_requested`) |
| `merged` | the archive or the done-gate again: `l4 archive --unit ID --retry` |
| every other phase, unstarted | refused (exit 2) with what moves the unit |

A retry runs no agent, gate or sandbox. It records `unit.retried{reason, by, signal}` (it folds like `unit.resumed`),
commits `chore(<name>): retry [skip ci]` and pushes: the machinery of `l4 resume` (`Orchestrator.resume`), asked for a
different event, subject and edge. `retry_unit` starts no run: the command (`run_retry`) does, after the push, with
`start_run_line` (L4-OPS-002); the sweep, which is already in a run, does not.
"""

import logging

import click

from l4.config.redaction import load_app_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import ForgeUnavailable, fetch_auth_config, forge_platform, make_forge, parse_remote_url
from l4.forge.urls import origin_url
from l4.orchestrator import UnitOutcome, UnitRunResult, run_unit_in_worktree
from l4.outcome import CommandResult
from l4.progress import project_web_url
from l4.specs.base import SpecProvider, UnitRef
from l4.specs.providers import providers_for
from l4.state.budget import feedback_rounds_exhausted, fix_rounds_exhausted
from l4.state.fold import UnitState
from l4.state.lifecycle import Phase, Trigger
from l4.state.status import load_snapshot, refresh_refs, select_runnable, snapshots
from l4.vcs.git import Git
from l4.vcs.names import unit_branch
from l4.vcs.refresh import unit_refspecs

log = logging.getLogger("l4.retry")

_CONTINUES = frozenset(
    {Phase.INTAKE, Phase.READY, Phase.CLARIFYING, Phase.IMPLEMENTING, Phase.IMPLEMENTED, Phase.VERIFYING,
     Phase.FIXING, Phase.VERIFIED}
)  # fmt: skip
_EDGE_OF = {Phase.WAITING_CAPACITY: Trigger.CAPACITY_RESTORED, Phase.IN_REVIEW: Trigger.RETRY_REQUESTED}


def refuse(ref: UnitRef, state: UnitState, cfg: L4Config, relative: str) -> L4Exit | None:
    """The refusal of a phase that a retry cannot move, with what moves the unit instead (D2); None when it can."""
    phase = state.phase
    head = f"retry: {ref.id} is {phase or 'not started'}"
    branch = unit_branch(ref.id, cfg.forge.branch_prefix)
    if phase is None:
        text = f"{head}: the next run starts it"
    elif phase == Phase.AWAITING_HUMAN.value:
        asked = ", ".join(state.questions.open) or "the open questions"
        text = f"{head}: answer {asked} in {relative}/questions.md on {branch}, then push"
    elif phase == Phase.ABANDONED.value:
        text = f"{head}: use l4 restart --unit {ref.id} --reason TEXT"
    elif phase in {p.value for p in _CONTINUES}:
        text = f"{head}: the harness continues it at the next run"
    elif phase == Phase.REJECTED.value:
        text = f"{head}: correct the spec on {branch}, then the next run reads it again"
    elif phase in (Phase.ARCHIVED.value,):
        text = f"{head}: nothing is left to retry"
    elif phase not in (p.value for p in (Phase.HALTED, Phase.ESCALATED, Phase.WAITING_CAPACITY, Phase.IN_REVIEW,
                                          Phase.MERGED)):  # fmt: skip
        text = f"{head}: a retry cannot move it"  # `corrupt` and any phase this harness does not know
    else:
        return None
    return L4Exit(ExitCode.USAGE_ERROR, text)


def retry_unit(
    app: AppContext,
    cfg: L4Config,
    git: Git,
    provider: SpecProvider,
    ref: UnitRef,
    *,
    reason: str,
    signal: str | None = None,
    by: str | None = None,
    rounds: int | None = None,
) -> UnitRunResult:
    """The retry of one unit (design D2), for `l4 retry` and the sweep's `l4:retry` label. It starts no run: the caller
    decides. A phase that a retry cannot move is `L4Exit(USAGE_ERROR)` that says what moves it, before the lease, the
    worktree and the ledger, so nothing is recorded. `rounds`: how many fix (or feedback) rounds an escalated unit at
    its limit gets (default 1); a unit in another phase has no rounds to add."""
    if rounds is not None and rounds < 1:
        raise L4Exit(ExitCode.USAGE_ERROR, "retry: --rounds must be at least 1")
    state = load_snapshot(provider, git, ref, branch_prefix=cfg.forge.branch_prefix).state
    relative = provider.unit_dir(ref).resolve().relative_to(app.repo.resolve()).as_posix()
    if (refusal := refuse(ref, state, cfg, relative)) is not None:
        raise refusal
    phase = Phase(state.phase)
    if phase is Phase.MERGED:
        return _retry_archive(app, cfg, git, ref)
    if rounds is not None and phase is not Phase.ESCALATED:
        raise L4Exit(ExitCode.USAGE_ERROR, f"retry: {ref.id} is {phase}, not escalated: it has no rounds to add")
    if phase is not Phase.IN_REVIEW and state.previous_phase not in {p.value for p in Phase}:
        raise L4Exit(ExitCode.USAGE_ERROR, f"retry: {ref.id} is {phase} with no recorded phase to go back to")
    fix = feedback = None
    if phase is Phase.ESCALATED:
        if feedback_rounds_exhausted(state):
            feedback = rounds or 1
        elif fix_rounds_exhausted(cfg, state):
            fix = rounds or 1  # the fix-round limit, `same_failure` at the limit included
    return run_unit_in_worktree(
        app, cfg, git, provider, ref, resume_reason=reason, resume_signal=signal, resume_by=by,
        resume_extend_fix_rounds=fix, resume_extend_feedback_rounds=feedback,
        resume_event="unit.retried", resume_trigger=_EDGE_OF.get(phase, Trigger.RESUMED), resume_what="retry",
        resume_spec_edit_check=phase in (Phase.HALTED, Phase.ESCALATED),
    )  # fmt: skip


def _retry_archive(app: AppContext, cfg: L4Config, git: Git, ref: UnitRef) -> UnitRunResult:
    """A merged unit: the archive or the done-gate runs again, as `l4 archive --unit ID --retry` does (D2)."""
    from l4.ci.sweeper import sweep  # here: the sweep imports this module for its label duty

    rows = snapshots(app, cfg, (ref.id,))
    actions = sweep(app, cfg, git, rows, retry=True)
    if not actions:
        raise L4Exit(ExitCode.USAGE_ERROR, f"retry: {ref.id} is merged: no archive or done-gate failure is recorded")
    stuck = any(a.what == "archive_failed" or (a.what == "skipped" and "archive.failed" in a.detail) for a in actions)
    said = "; ".join(f"{a.what} {a.detail}".strip() for a in actions)
    outcome = UnitOutcome(unit=ref.id, phase_before="merged", phase_after="merged", exit_reason=said[:300])
    return UnitRunResult(outcome, ExitCode.HALTED if stuck else ExitCode.OK)


# --- the command, and the start of a run (L4-OPS-002) ----------------------------------------------------------------


def fetch_unit_refs(app: AppContext, cfg: L4Config, git: Git) -> None:
    """The base branch and the unit refs, as the worktree manager reads them: an operator's laptop does not fetch on
    its own (`refresh_refs` does only in CI), and a branch a person pushed since is what a retry must see."""
    if git.run("remote", "get-url", "origin", check=False).returncode != 0:
        return
    base = f"+refs/heads/{cfg.forge.base_branch}:refs/remotes/origin/{cfg.forge.base_branch}"
    git.fetch(
        "origin", refspecs=(base, *unit_refspecs(cfg.forge.branch_prefix)), prune=True,
        config=fetch_auth_config(cfg, app.environ, origin_url(app.repo, app.environ)),
    )  # fmt: skip


def how_to_start(app: AppContext, cfg: L4Config, base: str) -> str:
    """The exact command or page that starts the harness's CI on `base` by hand (GitHub: `gh workflow run`, GitLab: the
    new-pipeline page of the project)."""
    origin = origin_url(app.repo, app.environ)
    platform = forge_platform(cfg, app.environ, origin)
    if platform == "github":
        return f"gh workflow run l4.yml --ref {base}"
    if platform == "gitlab":
        remote = parse_remote_url(origin or "")
        web = project_web_url(app.environ, cfg.forge.gitlab.api_url, cfg.forge.gitlab.project)
        if web is None and remote is not None:
            web = f"https://{remote.host}/{remote.path}"
        if web is not None:
            return f"{web}/-/pipelines/new?ref={base}"
    return f"start the harness's CI on {base}"


def start_run_line(app: AppContext, cfg: L4Config) -> str:
    """After the push: ask the forge to start the harness's CI on the base branch and say what happened in one line
    (L4-OPS-002). A start the forge refuses or cannot do, and a missing token, are not errors: the line names the way to
    start a run by hand and the command exits 0."""
    base = cfg.forge.base_branch
    by_hand = f"start a run with: {how_to_start(app, cfg, base)}"
    try:
        answer = make_forge(cfg, app.environ, repo=app.repo).start_run(base)
    except ForgeUnavailable:
        return by_hand
    if answer == "started":
        return f"run started on {base}"
    if answer == "already_queued":
        return f"a run is already queued on {base}"
    return by_hand  # refused or unsupported


def run_retry(
    app: AppContext, *, unit: str, reason: str, rounds: int | None = None, no_run: bool = False
) -> CommandResult:
    if not reason.strip():
        raise L4Exit(ExitCode.USAGE_ERROR, "retry: --reason must say why")
    app, cfg = load_app_config(app)
    git = Git(app.repo, environ=app.environ)
    fetch_unit_refs(app, cfg, git)
    refresh_refs(app, cfg, git)
    provider, ref = select_runnable(cfg, git, list(providers_for(cfg, app.repo, app.environ)), unit)
    result = retry_unit(app, cfg, git, provider, ref, reason=reason, rounds=rounds)
    log.info("%s retried: now %s", unit, result.outcome.phase_after)
    if not no_run and result.exit_code == ExitCode.OK:
        click.echo(app.redactor.redact_text(start_run_line(app, cfg)))
    return CommandResult(result.exit_code, [result.outcome])
