"""The orchestrator (SPEC 12.0) and `l4 run` (implementer-tdd-loop D8).

`Orchestrator.run_unit` is the only code that changes a unit's phase, always through `l4.state.lifecycle.transition`,
which does not update `UnitState`: the state is folded from the ledger again after every transition. A run that has
nothing more to do ends with the exit code of the edge it took, or with these decisions where the lifecycle table
has none:
- `implemented` and no `verify` hook: exit 0. SPEC 12.0 gives `implementing -> implemented` no exit code and 2.2
  calls exit 0 "done or nothing to do"; the unit waits for the verifier (M1: verifier 1.20) and `l4 plan` still
  reports `verify` for it.
- `verified` and no `handoff` hook, or a hook that returns False (no forge credential): exit 0, for the same reason.
- a unit that has no tasks, or a repository with no test gate: exit 14 (rejected), no phase change (M1:
  state-vcs-locks 1.20 adds the `intake -> rejected` edge, implementer-tdd-loop 1.6/1.7 the full intake).
- `halted` and `escalated` units: exit 13 with a message; a rerun cannot move them. A `halted` unit goes back with
  `l4 resume` (`l4.state.resume`); an `escalated` one the same way, with `--extend-fix-rounds N` when its fix rounds are
  used up (M1.13).
- `fixing` units run the open fix unit's tasks (`hooks.fix`) in the same run, then go back to `verifying`; a FAIL
  (`verifying -> fixing`) continues into the fix loop in the same run when the hook exists (D2), and a PASS with
  convertible minor findings does the same before the hand-off. `l4 verify` has no fix hook and stops with exit 10.
Questions: a task that reports blocked raises its questions, and the unit goes to `clarifying` when a clarify hook
exists (and `clarifier.enabled` is not false), else to `awaiting_human` (exit 11). While questions are open, the
other tasks still run; when none is eligible the unit waits for a human. A unit in `awaiting_human` re-enters
`implementing` only when the committed answers free at least one task (`Clarifier.reenter` runs at the start of
every run and records what is new); `--unit` does not force it.
A human edits the Status in a question's section, not in the index table: `Clarifier.reenter` rewrites the stale rows
and the run commits them (`docs(<unit>): questions index [skip ci]`), before verification only.
After the hand-off commit H the unit branch stays at H: the run's remaining lines (`pr.updated`, `in_review`,
`lock.released`, `run.finished`) and every later run's go to `ledger-pending/<run-id>.jsonl` in a commit of the unit's
lock ref (`l4.state.pending`), and every fold reads the branch plus those files (M1.1 lines 27-29).
Intake lint (L4-ODD-004): at the start of every run, before any agent or probe, scenarios with the same WHEN and a
different THEN become `ambiguous` questions that block the pending tasks (`l4.gates.odd`).
M1: implementer-tdd-loop 1.6 ODD intake (the rest of it), 1.22/1.23 step keys and reconcile, 1.24 budgets,
1.25 exemptions.
"""

import contextlib
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from l4 import cancel
from l4 import services as services_module
from l4.agents.base import AgentAdapter, LimitSignal, RunResult
from l4.agents.factory import RoleUnavailable, Selected
from l4.availability.cooldown import iso_utc
from l4.availability.errors import WaitingCapacity
from l4.availability.fallback import minute_stamp
from l4.ci.resume_label import halted_section
from l4.clarifier.clarifier import Clarifier, Reentry, awaiting_section, clarified_ids, commit_questions
from l4.config.defaults import cache_root
from l4.config.preflight import preflight_run_config
from l4.config.redaction import load_app_config
from l4.config.schema import L4Config, duration_seconds
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit, classify_exception, most_severe
from l4.follow_up import FollowUpMade, perform_follow_ups
from l4.forge.base import ForgeUnavailable, fetch_auth_config, make_forge
from l4.forge.pushfail import PushFailed, explain_push_failure
from l4.forge.urls import app_forge_urls, origin_url
from l4.gates.odd import raise_open_questions, raise_scenario_questions, scenario_conflicts
from l4.implementer.loop import run_task
from l4.implementer.tasks import (
    open_blocking_questions,
    questions_hold,
    required,
    select_next_step,
    tick_completed_parents,
    unselectable,
)
from l4.implementer.tdd import BaselineFailed, RoleLimit
from l4.implementer.workbench import PreviousAttempt, Workbench, make_workbench
from l4.outcome import CommandResult, TaskCounts, UnitOutcome
from l4.planner import facts_of, next_action
from l4.progress import ProgressTrace, log_artefacts, project_web_url
from l4.provision.readiness import platform_of, steps_for
from l4.services import H_PUSHED, ForgeHook, HookContext, Hooks, MirrorHook, Services, build_services
from l4.specs.base import Framework, SpecProvider, UnitRef, UnknownUnit
from l4.specs.criteria import base_criteria, replaced_requirements
from l4.specs.detect import require_framework
from l4.specs.providers import providers_for
from l4.specs.questions import QUESTIONS_FILENAME, QuestionsFile, blocked_tasks, question_titles
from l4.state.breaker import LIMIT as VERIFIER_ERROR_LIMIT
from l4.state.breaker import consecutive_verifier_errors
from l4.state.environment import run_environment
from l4.state.fold import UnitState, fold
from l4.state.ledger import LedgerClosed, LedgerEvent, LedgerRead, LedgerWriter, ledger_path, read_ledger
from l4.state.lifecycle import Edge, Phase, Trigger, transition
from l4.state.pending import PendingLedger, keep_unpublished, merge_ledgers, read_pending, unpublished_files
from l4.state.reconcile import reconcile
from l4.state.review import after_handoff, review_note, review_trigger
from l4.state.status import discover, load_snapshot, refresh_refs
from l4.vcs.git import Git, GitError
from l4.vcs.locks import LocalFileLease, acquire_for_run
from l4.vcs.merge import BaseMergeConflict
from l4.vcs.names import UnitNames
from l4.vcs.secretscan import SecretInPush, outgoing_secrets
from l4.vcs.trailers import CommitTrailers
from l4.vcs.worktree import WorktreeManager
from l4.verifier.fixloop import without_fix_units
from l4.verifier.notes import verdict_section
from l4.verifier.verdicts import legacy_round, verdict_status

MAX_CLARIFIER_ROUNDS_PER_TASK = 2  # a task that blocks again after this many auto-answers is a human's to unblock

log = logging.getLogger("l4.run")

ACTIONABLE = frozenset({"implement", "clarify", "verify", "hand_off"})
# the phases in which the intake lint (L4-ODD-004) still matters: from then on the verifier is the judge
_LINT_PHASES = frozenset({None, Phase.INTAKE, Phase.READY, Phase.IMPLEMENTING, Phase.AWAITING_HUMAN, Phase.CLARIFYING})
# the phases after the hand-off commit H: the unit branch stays at H, so what a run writes from here on goes to the
# pending ledger of the lock ref (L4-STA-004)
_AFTER_HAND_OFF = frozenset({Phase.IN_REVIEW, Phase.ARCHIVED, Phase.MERGED})
_NOTHING_TO_DO = frozenset({Phase.ARCHIVED, Phase.MERGED, Phase.ABANDONED})
_NEEDS_A_HUMAN = {
    Phase.HALTED: "halted: a human decides, then `l4 resume --unit ID --reason TEXT`",
    Phase.ESCALATED: "escalated: `l4 resume ... --extend-fix-rounds N` or a member's l4:resume label",
}


def _retry_after(exc: Exception) -> str | None:
    """When the capacity a parked unit waits for is expected back: the end of the earliest cool-down
    (`WaitingCapacity`), or the reset the agent itself reported."""
    moment = getattr(exc, "retry_after", None)
    if moment is None and isinstance(exc, RoleLimit) and exc.result.limit is not None:
        moment = exc.result.limit.resets_at
    return iso_utc(moment) if moment is not None else None


def base_conflict_section(exc: BaseMergeConflict, branch: str) -> str:
    """The sticky note of a unit whose base merge conflicts; `bring_in_base` clears it after the next success."""
    return (
        "### Base merge needed\n\n"
        f"Merging `{exc.base}`@`{exc.base_sha[:10]}` into `{branch}` conflicts in {', '.join(exc.files)}. "
        f"Merge `{exc.base}` into the branch by hand, resolve, push; the next run verifies again. "
        "Every run until then exits 1."
    )


def capacity_section(
    exc: Exception,
    *,
    base: str,
    now: datetime,
    retry_after: str | None,
    platform: str = "gitlab",
    environment: str | None = None,
) -> str:
    """The sticky note of a unit that parked for capacity (L4-ARC-002; live job 5561: the MR stayed silent): what
    is missing, the human steps for a login, and when the unit comes back. `bring_in_base`'s sibling: the next
    `CAPACITY_RESTORED` clears it, a re-park writes it again."""
    lines = ["### Waiting for capacity", ""]
    unready = exc.unready if isinstance(exc, WaitingCapacity) else ()
    due_now = retry_after is not None and datetime.fromisoformat(retry_after) <= now
    if unready:
        lines.append("No profile of the role could be used:")
        lines.append("")
        for u in unready:
            lines.append(f"- `{u.profile}` ({u.adapter or 'backend'}): {u.step}: {u.reason}")
            if u.step == "auth" and u.adapter:
                steps = steps_for(u.adapter, u.auth, platform=platform, environment=environment)
                lines += [f"  - {step}" for step in steps]
        lines.append("")
    else:
        lines += [f"{str(exc)[:300]}", ""]
    if retry_after is not None and not due_now:
        when = minute_stamp(datetime.fromisoformat(retry_after))
        lines.append(
            f"Capacity is expected back at {when}. The scheduled `l4 sweep` resumes the unit after that; without a "
            f"schedule, run a pipeline on `{base}` after {when}."
        )
    else:
        lines.append(
            f"Once that is fixed, run a pipeline on `{base}`, or wait for the scheduled `l4 sweep`: the unit "
            "is probed again on every run and resumes at once."
        )
    return "\n".join(lines)


def _sections(section: str | None) -> tuple[str, ...] | None:
    """The mirror's notes for a section; None (no section to show) leaves the sticky note as it is."""
    return (section,) if section else None


@dataclass(frozen=True)
class UnitRunResult:
    outcome: UnitOutcome
    exit_code: ExitCode


@dataclass
class RunWaits:
    """What one `l4 run` has waited in place for a cool-down (L4-AVL-011). `run_units` hands the same one to every
    unit, so `availability.wait_in_run_max_total` bounds the run, not each unit. `began`: the run's start on the
    factory's clock, set by its first unit (the job's start when `CI_JOB_STARTED_AT` is unknown)."""

    waited_s: int = 0
    began: datetime | None = None


class Orchestrator:
    def __init__(self, cfg: L4Config, services: Services, waits: RunWaits | None = None) -> None:
        self.cfg = cfg
        self.services = services
        self.state: UnitState = UnitState(unit=services.ref.id)
        self._selected: Selected | None = None
        ctx = HookContext(cfg, services, self.push)
        ctx.shared["implementer"] = self._select  # the current profile, also after a mid-run fallback (contract C21)
        self._forge: ForgeHook | None = services.hooks.forge(ctx) if services.hooks.forge else None
        self._mirror: MirrorHook | None = services.hooks.mirror(ctx) if services.hooks.mirror else None
        self._ctx = ctx
        ctx.shared["fall_back"] = self.switch_profile  # for hooks that see a limit themselves (the audit writer)
        ctx.shared["answers_recorded"] = self.answers_recorded  # the fix loop records a fix unit's answers itself
        self._push_failed = False
        self._commit_what = "ledger"  # the subject of the final ledger commit: `chore(<unit>): <what> [skip ci]`
        self._start = services.git.rev_parse("HEAD")
        self._clarifier = Clarifier(services.ref.path, services.ledger)
        self._reentry: Reentry | None = None
        self._notes: tuple[str, ...] | None = None  # the sticky note's sections for the mirror; None: leave it alone
        self._exit_reason: str | None = None  # one line for `ci map-exit` when the exit code alone says too little
        self._rounds: dict[str, int] = {}  # per task, the times it blocked and went to the clarifier in this run
        self._sent: set[str] = set()  # questions handed to the clarify hook in this run: never handed over twice
        self._waits = waits if waits is not None else RunWaits()  # `availability.wait_in_run_max_total`, run-wide
        if self._waits.began is None:
            self._waits.began = services.factory.now()
        self._previous_attempt: PreviousAttempt | None = None  # set when a limit moved the task to another profile
        self._publish_unpublished()
        # what earlier runs wrote after their hand-off commit lives only in the lock ref: without it a unit in
        # review would fold as `verified` and be handed off again
        self._pending = read_pending(services.git, services.names.lock_ref)
        self._refold()

    # --- state ------------------------------------------------------------------------------------------------

    def _ledger(self) -> LedgerRead:
        return merge_ledgers(read_ledger(self.services.ref.path), self._pending)

    def _refold(self) -> UnitState:
        self.state = fold(self._ledger().events, self.services.ref.id)
        return self.state

    def _go(self, trigger: Trigger, **context: object) -> Edge:
        """One `phase.changed`; the state is folded again because `transition()` only appends. An undeclared edge
        raises `IllegalTransition` and writes nothing."""
        edge = transition(self.services.ledger, self.state, trigger, **context)
        self._refold()
        self._sync_mirror()
        return edge

    def _sync_mirror(self) -> None:
        if self._mirror is not None and not cancel.is_cancelled():  # a cancelled run writes nothing to the forge
            self._mirror.sync(self.state.phase, notes=self._notes)

    def push(self) -> None:
        """Fast-forward push of the unit branch with the forge hook's credentials, then the hooks' follow-ups."""
        cancel.check()  # W-D2: a run that was cancelled never pushes, whoever asks
        config = self._forge.push_config if self._forge else ()
        s = self.services
        self._scan_outgoing()
        try:
            s.git.push_branch("origin", s.names.branch, config=config)
        except GitError as exc:  # one explained error (exit 3 for a credential problem), never a git traceback
            self._push_failed = True
            raise explain_push_failure(
                exc, branch=s.names.branch, token_env=self.cfg.forge.token_env, environ=s.app.environ,
                redact=s.app.redactor.redact_text,
            ) from None  # fmt: skip
        if self._forge is not None:
            try:
                self._forge.after_push(self.state.phase)
            except LedgerClosed:  # the first push of a run that halts happens in `close()`, after `ledger.finish`
                log.info("%s: the merge request is open; `pr.updated` is recorded by the next run", s.ref.id)
        self._sync_mirror()

    def _scan_outgoing(self) -> None:
        """HB-4 (L4-SEC-007): before every push, the commits the forge does not have yet are read for secrets with the
        redactor's values and token shapes. A hit is `guard.secret {path, kind}` (never the value) and no push; the
        run's final ledger push would carry the same commits, so it is switched off like after a refused push."""
        s = self.services
        base = f"refs/remotes/origin/{self.cfg.forge.base_branch}"
        hits = outgoing_secrets(s.git, s.app.redactor, exclude=(f"refs/remotes/origin/{s.names.branch}", base))
        if not hits:
            return
        self._push_failed = True
        for hit in hits:
            s.ledger.append("guard.secret", path=hit.path, kind=hit.kind)
        raise SecretInPush(hits)

    def _block_secret(self, exc: SecretInPush) -> ExitCode:
        """The unit halts (exit 13) with the reason in the outcome. `implementing` and `fixing` have the lifecycle's
        breaker edge; in any other phase (verifying, the hand-off) the phase stays, only the exit code says halted."""
        self.services.ledger.append("breaker.tripped", reason="secret_in_push", paths=[h.path for h in exc.hits][:20])
        self._exit_reason = exc.reason
        if self.state.phase in (Phase.IMPLEMENTING, Phase.FIXING):
            return self._halt(exc.reason)
        log.error("%s halted: %s", self.services.ref.id, exc.reason)
        return ExitCode.HALTED

    # --- one unit ---------------------------------------------------------------------------------------------

    def run_unit(self) -> UnitRunResult:
        before = self._refold().phase or "none"
        try:
            self._reconcile()
            if (rejected := self._lint_scenarios()) is not None:
                return UnitRunResult(self._outcome(before), rejected)
            self._reentry = self._clarifier.reenter(
                self.services.provider.tasks(self.services.ref), refresh_index=self._may_commit_questions()
            )
            for qid in self._reentry.drafts:
                log.warning("%s has an answer but its Status is still open: set it to `answered` to submit", qid)
            if self._reentry.index_refreshed:  # a human changed a Status in its section, not in the index table
                self._commit_questions("questions index")
            if self._reentry.answered:
                self.answers_recorded()
            code = self._drive()
        except (RoleUnavailable, RoleLimit) as exc:
            code = self._park(exc)
        except SecretInPush as exc:
            code = self._block_secret(exc)
        return UnitRunResult(self._outcome(before), code)

    def answers_recorded(self) -> None:
        """`question.answered` was just appended (for the unit or for its open fix unit): when that changed which
        questions are open, the mirror is synced once, before any agent step, so `l4:needs-answers` goes when the last
        answer is recorded and not at the next push (live MF-1: it stayed for ten minutes after the answer). Labels
        only: the sticky note is left as it is."""
        before = tuple(self.state.questions.open)
        if tuple(self._refold().questions.open) != before:
            self._sync_mirror()

    def resume(
        self,
        reason: str,
        *,
        signal: str | None = None,
        by: str | None = None,
        extend_fix_rounds: int | None = None,
        extend_feedback_rounds: int | None = None,
    ) -> UnitRunResult:
        """`l4 resume` (L4-IMP-013, SCN-RES-01, SCN-RES-03): `unit.resumed{reason}` and the halted or escalated unit
        goes back to the phase it was halted from (`verifying` for an escalated one). Nothing else runs; the next
        `l4 run` continues the unit. `signal` (`label:<event id>`) and `by` (`member`) say that a member's `l4:resume`
        label asked for it: one resume per signal. `extend_fix_rounds` records `budget.extended` first, so that the fold
        has the extra rounds when the verifier decides again; `extend_feedback_rounds` is the same for the feedback
        limit (`feedback_rounds` in the same event, L4-FBK-006)."""
        before = self._refold().phase or "none"
        self._commit_what = "resume"
        extra = {k: v for k, v in (("by", by), ("signal", signal)) if v}
        if extend_fix_rounds or extend_feedback_rounds:
            rounds = {
                k: v for k, v in (("fix_rounds", extend_fix_rounds), ("feedback_rounds", extend_feedback_rounds)) if v
            }
            self.services.ledger.append("budget.extended", **rounds, reason=reason[:300], **extra)
        self.services.ledger.append("unit.resumed", reason=reason[:300], **extra)
        self._notes = ()  # the halted section is out of date: the mirror says nothing is waiting
        self._go(Trigger.RESUMED)
        return UnitRunResult(self._outcome(before), ExitCode.OK)

    def _reconcile(self) -> None:
        """A step that a killed run left half done is reconciled before anything else (L4-STA-003). A restored
        snapshot's copy of the killed run's ledger is dropped (its committed part is the record), then the state is
        folded again."""
        if reconcile(self.services.git, self.services.ref, self.services.ledger) is not None:
            self._refold()

    def _may_commit_questions(self) -> bool:
        """Before verification only: a `[skip ci]` commit on the head of a unit in review hides its pipeline."""
        return (Phase(self.state.phase) if self.state.phase else None) in _LINT_PHASES

    def _validate_kiro(self) -> ExitCode | None:
        """L4-KSP-003, before any agent or probe: under `sdd.enforce` a Kiro leaf without `_Requirements:_` (unless it
        is TDD-exempt), a reference that no requirement has, a missing file, a task line outside Kiro's grammar and an
        invalid Task Dependency Graph are errors that reject the unit, exactly like `_discover`. The graph is an ERROR
        here, so the runtime fallback to document order (`read_waves` logs it) only serves doctor and the verifier."""
        s = self.services
        report = s.provider.validate(s.ref, strict=True)
        if report.valid:
            return None
        reasons = [
            f"{i.path}{f':{i.line}' if i.line else ''}: {i.message}" for i in report.issues if i.level == "ERROR"
        ]
        s.ledger.append("unit.rejected", reasons=reasons)
        log.error("%s rejected: %s", s.ref.id, "; ".join(reasons))
        return ExitCode.REJECTED

    def _lint_scenarios(self) -> ExitCode | None:
        """L4-ODD-004, before any agent or probe: a pair of scenarios with the same WHEN and a different THEN becomes
        a question that blocks the pending tasks. It is committed at once, but only reaches the remote when the run
        does more than park or reject the unit (`_worth_pushing`); otherwise the next run raises it again. A Kiro
        unit has no scenarios: it is validated instead (`_validate_kiro`), and the exit code is that rejection's."""
        s = self.services
        if not self._may_commit_questions():
            return None
        if s.ref.framework is not Framework.OPENSPEC:
            return self._validate_kiro()
        base = base_criteria(s.worktree / "openspec" / "specs") if s.ref.framework is Framework.OPENSPEC else []
        removed = replaced_requirements(s.ref.path) if s.ref.framework is Framework.OPENSPEC else frozenset()
        conflicts = scenario_conflicts(s.provider.criteria(s.ref), base, removed)
        tasks = s.provider.tasks(s.ref)
        ids = raise_scenario_questions(s.ref.path, s.ref.name, conflicts, tasks, redactor=s.app.redactor)
        titles = question_titles(s.ref.path) if ids else {}
        for qid in ids:
            s.ledger.append(
                "question.raised", id=qid, kind="ambiguous", source="intake_lint", title=titles.get(qid, "")
            )
        if ids:
            log.warning("%s: conflicting scenarios, questions raised: %s", s.ref.id, ", ".join(ids))
        opened = []
        if s.ref.framework is Framework.OPENSPEC:
            opened = raise_open_questions(s.ref.path, s.ref.name, tasks, redactor=s.app.redactor)
            file = QuestionsFile.load(s.ref.path / QUESTIONS_FILENAME)
            kinds = {q.id: q.kind.value for q in file.questions if q.kind} if file else {}
            titles = {q.id: q.title for q in file.questions} if file else {}
            for qid in opened:
                s.ledger.append(
                    "question.raised",
                    id=qid,
                    kind=kinds.get(qid, "ambiguous"),
                    source="intake_open_questions",
                    title=titles.get(qid, ""),
                )
            if opened:
                log.warning("%s: open questions in design.md, questions raised: %s", s.ref.id, ", ".join(opened))
        if ids or opened:
            self._commit_questions("questions")
            # this commit alone must not make the branch worth pushing (`_worth_pushing`): a run that then parks or
            # rejects the unit raises the same questions again next time instead of freezing today's spec copy
            self._start = s.git.rev_parse("HEAD")
        return None

    def _commit_questions(self, what: str) -> None:
        commit_questions(self.services, phase=self.state.phase, iteration=self.state.iteration, what=what)

    def _record_limit(self, exc: Exception) -> None:
        if isinstance(exc, RoleLimit) and exc.result.limit is not None:
            limit = exc.result.limit
            self.services.ledger.append(
                "availability.limit", tool=limit.tool, kind=limit.kind, source=limit.source, excerpt=limit.raw_excerpt
            )  # fmt: skip

    def _park(self, exc: Exception) -> ExitCode:
        self._record_limit(exc)
        context: dict[str, object] = {"reason": str(exc)[:200]}
        retry_after = _retry_after(exc)
        if retry_after is None and isinstance(exc, RoleUnavailable):  # nothing says when: look again after the default
            wait = timedelta(seconds=duration_seconds(self.cfg.availability.default_cooldown))
            retry_after = iso_utc(self.services.factory.now() + wait)
        if retry_after:
            context["retry_after"] = retry_after
            log.warning("%s: waiting_capacity, retry_after %s: %s", self.services.ref.id, retry_after, exc)
        else:
            log.warning("%s", exc)
        redact = self.services.app.redactor.redact_text
        self._exit_reason = redact(f"waiting_capacity: {exc}")[:300]
        app = self.services.app
        platform, environment = platform_of(self.cfg, app.environ, origin_url(app.repo, app.environ))
        section = capacity_section(
            exc, base=self.cfg.forge.base_branch, now=self.services.factory.now(), retry_after=retry_after,
            platform=platform, environment=environment,
        )  # fmt: skip
        self._notes = _sections(redact(section))  # before the phase change, which syncs the mirror
        edge = self._go(Trigger.REQUIRED_ROLE_UNAVAILABLE, **context)
        return ExitCode(edge.exit_code if edge.exit_code is not None else ExitCode.WAITING_CAPACITY)

    def _drive(self) -> ExitCode:
        while True:
            phase = Phase(self.state.phase) if self.state.phase else None
            if phase is None:
                rejected = self._discover()
                if rejected is not None:
                    return rejected
            elif phase is Phase.INTAKE:
                self._go(Trigger.INTAKE_ALL_PASS)
            elif phase is Phase.READY:
                self._select()
                self._go(Trigger.LEASE_ACQUIRED)
            elif phase is Phase.IMPLEMENTING:
                code = self._implement()
                if code is not None:
                    return code
            elif phase in (Phase.IMPLEMENTED, Phase.VERIFYING):
                code = self._verify(phase)
                if code is not None:
                    return code
            elif phase is Phase.VERIFIED:
                if self.state.open_fix_unit and self.services.hooks.fix is not None:
                    self._go(Trigger.MINOR_FINDINGS_FIX, fix=self.state.open_fix_unit)
                    continue
                return self._hand_off()
            elif phase is Phase.FIXING:
                code = self._fix()
                if code is not None:
                    return code
            elif phase is Phase.CLARIFYING:
                code = self._clarify()
                if code is not None:
                    return code
            elif phase is Phase.AWAITING_HUMAN:
                if ready := self._verdicts_ready():
                    self._notes = ()  # the question list is out of date once the verdicts are in
                    self._go(Trigger.VERDICTS_ANSWERED, questions=ready)
                    continue
                if self._reentry is None or not self._reentry.unblocks:
                    if (legacy := self._legacy_round()) is not None:
                        return self._raise_legacy_verdicts(legacy)
                    log.info("%s: awaiting a human: no submitted answer frees a task", self.services.ref.id)
                    section = awaiting_section(self._ctx, drafts=self._drafts())
                    self._notes = _sections(section or verdict_section(self._ctx, self.state.verdicts_consumed))
                    return ExitCode.AWAITING_HUMAN
                self._notes = ()  # the question list is out of date once answers are in
                self._go(Trigger.ANSWERS_SUBMITTED, questions=list(self._reentry.unblocks))
            elif phase is Phase.WAITING_CAPACITY:
                self._notes = ()  # the capacity note is out of date: a re-park writes it again
                self._go(Trigger.CAPACITY_RESTORED)
            elif phase is Phase.REJECTED:
                return ExitCode.REJECTED
            elif phase is Phase.IN_REVIEW:
                if not self._review():
                    log.info("%s is in_review: nothing to do", self.services.ref.id)
                    return ExitCode.OK
            elif phase in _NOTHING_TO_DO:
                log.info("%s is %s: nothing to do", self.services.ref.id, phase.value)
                return ExitCode.OK
            else:
                log.error("%s is %s", self.services.ref.id, _NEEDS_A_HUMAN[phase])
                self._exit_reason = f"{phase.value}: {_NEEDS_A_HUMAN[phase]}"[:300]
                return ExitCode.HALTED

    def _review(self) -> bool:
        """A unit in `in_review` (SPEC 12.0, M1.9): the worktree's HEAD is the remote branch head, so a commit after H
        that the harness did not make (G1), or the project's own CI recorded red on H (G2), takes the unit back to
        `verifying` (answers and spec edits to `implementing`) before anything else happens. False: it waits for the
        merge."""
        s = self.services
        unit_rel = s.ref.path.resolve().relative_to(s.worktree.resolve()).as_posix()
        found = review_trigger(after_handoff(s.git, "HEAD", s.ref.name, unit_rel), self.state)
        if found is None:
            return False
        self._notes = (review_note(found),)  # the mirror shows why the MR is a draft again, from the first sync on
        self._go(found.trigger, **found.context)
        return True

    def _discover(self) -> ExitCode | None:
        """A unit without a phase: intake, or straight to `implemented` when every task is already done."""
        reasons = []
        tasks = self.services.provider.tasks(self.services.ref)
        if not tasks:
            reasons.append("the unit has no tasks")
        if not self.cfg.gates.test.command.strip():
            reasons.append("gates.test.command is not configured: there is no test oracle")
        if reasons:
            self.services.ledger.append("unit.rejected", reasons=reasons)
            log.error("%s rejected: %s", self.services.ref.id, "; ".join(reasons))
            return ExitCode.REJECTED
        pending = any(not t.done for t in required(tasks))
        self._go(Trigger.UNIT_DISCOVERED_PENDING if pending else Trigger.UNIT_DISCOVERED_DONE)
        return None

    def _select(self) -> Selected:
        """Probe the implementer once per run; `RoleUnavailable` (exit 12) parks the unit."""
        if self._selected is None:
            self._selected = self.services.factory.for_role("implementer", self.services.ref.id)
        return self._selected

    def _workbench(self) -> Workbench:
        s = self.services
        wb = make_workbench(
            cfg=self.cfg, app=s.app, ref=s.ref, provider=s.provider, worktree=s.worktree, git=s.git, ledger=s.ledger,
            sandbox=s.sandbox, selected=self._select(), iteration=self.state.iteration, push=self.push,
        )  # fmt: skip
        wb.previous_attempt = self._previous_attempt
        return wb

    def _clarifier_available(self) -> bool:
        """The hook exists, the clarifier is on and `roles.clarifier` names a profile: with none configured the
        clarifier is absent and questions go straight to a human (no `clarifier unavailable` note on the MR)."""
        return self.services.hooks.clarify is not None and self.cfg.clarifier.enabled and bool(self.cfg.roles.clarifier)

    def _to_clarifier(self, ids: list[str]) -> None:
        self._sent.update(ids)
        self._go(Trigger.QUESTIONS_TO_CLARIFIER, questions=ids)

    def _await_human(self, ids: list[str], **context: object) -> ExitCode:
        self._notes = _sections(awaiting_section(self._ctx, drafts=self._drafts()))
        edge = self._go(Trigger.QUESTIONS_BLOCKING, questions=ids, **context)
        return ExitCode(edge.exit_code if edge.exit_code is not None else ExitCode.AWAITING_HUMAN)

    def _drafts(self) -> tuple[str, ...]:
        return self._reentry.drafts if self._reentry else ()

    def _clarify(self) -> ExitCode | None:
        """A unit in `clarifying`: run the hook, or send the unit to a human when there is none. The hook's outcome
        names the phase that follows; its sticky section goes to the mirror with the edge. None: the unit is back in
        `implementing`."""
        hook = self.services.hooks.clarify if self._clarifier_available() else None
        context: dict[str, object] = {}
        section: str | None = None
        trigger = Trigger.CLARIFIER_NEEDS_HUMAN
        if hook is not None:
            try:
                outcome = hook(self._ctx)
            except (RoleUnavailable, RoleLimit) as exc:  # L4-CLR-005: no clarifier is not exit 12, a human decides
                self._record_limit(exc)
                log.warning("%s: clarifier unavailable, a human must answer: %s", self.services.ref.id, exc)
                context = {"reason": f"clarifier unavailable: {str(exc)[:160]}"}
                section = awaiting_section(self._ctx, clarifier_unavailable=True, drafts=self._drafts())
            else:
                if outcome.next_phase == "implementing":
                    trigger = Trigger.CLARIFIER_ANSWERED_ALL
                else:
                    section = outcome.sticky_section
                    if not outcome.clarifier_available:
                        down = [r for r in outcome.results.values() if r.reply_status == "unavailable" and r.reasons]
                        why = down[0].reasons[0] if down else "no reason given"
                        context = {"reason": f"clarifier unavailable: {why[:160]}"}
        else:
            section = awaiting_section(self._ctx, drafts=self._drafts())
        if trigger is Trigger.CLARIFIER_NEEDS_HUMAN:
            self._notes = _sections(section)
        edge = self._go(trigger, **context)
        return None if edge.exit_code is None else ExitCode(edge.exit_code)

    def _questions(self) -> QuestionsFile | None:
        return QuestionsFile.load(self.services.ref.path / QUESTIONS_FILENAME)

    def _implement(self) -> ExitCode | None:
        """Task after task. None: the unit moved to another phase (`implemented`, `clarifying`) and the run goes on;
        otherwise the run's exit code."""
        wb = self._workbench()
        ledger = self.services.ledger
        while True:
            self._close_parents(wb)
            tasks = self.services.provider.tasks(self.services.ref)
            file = self._questions()
            open_ids = open_blocking_questions(file, tasks)
            if self._clarifier_available():
                done = clarified_ids(self._events())
                if fresh := [q for q in open_ids if q not in done and q not in self._sent]:
                    self._to_clarifier(fresh)
                    return None
            pending = [t.key for t in required(tasks) if not t.done]
            blocked = blocked_tasks(file.questions, pending, file.unreadable_ids) if file else frozenset()
            task = select_next_step(tasks, blocked)
            if task is None:
                stuck = unselectable(tasks)
                if stuck:
                    reason = f"task {stuck[0].key} cannot be selected: its checkbox is not an empty `[ ]`"
                    ledger.append("breaker.tripped", reason="unselectable_task", task=stuck[0].key)
                    return self._halt(reason)
                if questions_hold(tasks, blocked):
                    return self._await_human(open_ids)
                self._go(Trigger.ALL_LEAVES_DONE)
                return None
            try:
                outcome = run_task(wb, task)
            except BaselineFailed as exc:
                ledger.append("breaker.tripped", reason="baseline_failed", detail=str(exc))
                return self._halt(str(exc))
            except RoleLimit as exc:
                wb = self._fall_back(exc, wb, task.key)
                continue
            if outcome.status == "blocked":
                rounds = self._rounds[task.key] = self._rounds.get(task.key, 0) + 1
                if self._clarifier_available() and rounds <= MAX_CLARIFIER_ROUNDS_PER_TASK:
                    self._to_clarifier(outcome.question_ids)
                    return None
                if self._clarifier_available():  # M1: implementer-tdd-loop 1.24 replaces this with the real budgets
                    log.warning("%s: task %s blocked again after %d rounds", self.services.ref.id, task.key, rounds - 1)
                    return self._await_human(
                        outcome.question_ids, task=task.key, reason=f"clarifier rounds exhausted for task {task.key}"
                    )
                return self._await_human(outcome.question_ids, task=task.key)
            if outcome.status == "halt":
                return self._halt(outcome.reason)

    def switch_profile(self, limit: RunResult | LimitSignal, task: str | None = None) -> Selected:
        """The implementer hit a limit: cool it down and select the next profile. The one place `_selected` changes
        after the first selection, so a caller that saw the limit itself (M1.3's fix loop, the audit writer) goes
        through here and every later task and the outcome follow the new profile."""
        previous = self._select()
        try:
            self._selected = self.services.factory.on_limit(previous, limit)
        except WaitingCapacity as exc:
            self._selected = self._wait_in_run(exc)  # a short cool-down is waited out; else this raises `exc` again
        signal = limit if isinstance(limit, LimitSignal) else limit.limit
        kind = signal.kind if signal else limit.status if isinstance(limit, RunResult) else "rate_limit"
        self._previous_attempt = PreviousAttempt(previous.profile_name, kind, task)
        return self._selected

    def _job_remaining_s(self) -> float | None:
        """Seconds of the CI job left before the soft deadline; None when the budget is unknown (L4-IMP-012)."""
        s = self.services
        return job_remaining_s(self.cfg, s.app.environ, s.factory.now(), self._waits.began)

    def _wait_in_run(self, exc: WaitingCapacity) -> Selected:
        """L4-AVL-011: every implementer left is cooling and the earliest cool-down ends within
        `availability.wait_in_run`, so the run sleeps until then and selects again (the step goes on from its last
        checkpoint, like after a fallback). Not within `wait_in_run_max_total` of the run, nor the job's remaining time:
        `exc` is raised again and the unit parks (exit 12). A selection that fails again may be waited for too."""
        s, cfg = self.services, self.cfg.availability
        while True:
            now = s.factory.now()
            seconds = math.ceil((exc.retry_after - now).total_seconds())
            left = self._job_remaining_s()
            if (
                not 0 < seconds <= duration_seconds(cfg.wait_in_run)
                or self._waits.waited_s + seconds > duration_seconds(cfg.wait_in_run_max_total)
                or (left is not None and seconds > left)
            ):
                raise exc
            cooling = next(
                (c for c in s.factory.availability.cooldowns.entries(now) if c.until == exc.retry_after), None
            )
            profile, kind = (cooling.profile, cooling.kind) if cooling else (self._select().profile_name, "cooldown")
            logging.getLogger("l4").info("waiting %ds for %s (%s)", seconds, profile, kind)
            s.factory.sleep(seconds)
            self._waits.waited_s += seconds
            s.ledger.append("availability.wait_in_run", profile=profile, waited_s=seconds, kind=kind)
            try:
                return s.factory.for_role("implementer", s.ref.id)
            except WaitingCapacity as again:
                exc = again

    def _fall_back(self, exc: RoleLimit, wb: Workbench, task: str | None = None) -> Workbench:
        """A limit in the middle of a task (agent-factory 1.25, implementer-tdd-loop 2.25): the cool-down is recorded
        and the next profile of the chain is selected, or `WaitingCapacity` parks the unit. The task goes on from its
        last checkpoint in a fresh session: what the limited step left in the checkout is discarded, a red commit
        stays (`run_task` resumes at green). The workbench is rebuilt because the sandbox's visible login and the
        commit trailers follow the selected profile; the baselines are gate results and carry over."""
        self._record_limit(exc)
        wb.discard_changes()
        log.warning("%s: %s hit a limit (%s); moving on", self.services.ref.id, self._select().profile_name, exc)
        self.switch_profile(exc.result, task)
        fresh = self._workbench()
        fresh.baselines, fresh.static_baselines = wb.baselines, wb.static_baselines
        return fresh

    def _close_parents(self, wb: Workbench) -> None:
        """Only leaves run; a parent closes when no required descendant is open. One whose descendants are all
        optional is complete without any step, and is closed here, before the next step is selected, in a commit of
        its own (L4-KSP-001). Nothing happens when no parent is closable, which is the usual case."""
        s = self.services
        closed = tick_completed_parents(s.provider, s.ref)
        if not closed:
            return
        base = wb.head()
        for key in closed:  # before the commit, like `task.done`: a kill after it cannot lose the record
            s.ledger.append("task.done", task=key, base=base, parents=[], notes="", closed="no open required task")
        sha = wb.commit(
            f"chore({s.ref.name}): close {', '.join(closed)} with no required task open [skip ci]",
            task=closed[0], attempt=1, phase="close", tdd=None,
        )  # fmt: skip
        log.info("%s: closed %s (no required descendant open) at %s", s.ref.id, ", ".join(closed), sha[:8])
        wb.push()

    def _events(self) -> list[LedgerEvent]:
        return self._ledger().events

    def _stopped_section(self, phase: str, reason: str) -> str:
        """Redacted, like the capacity section: the reason can quote a test's error line, and the note goes to the
        forge as it is."""
        s = self.services
        section = halted_section(phase, reason, s.ref.id, f"{self.cfg.forge.labels_prefix}resume")
        return s.app.redactor.redact_text(section)

    def _halt(self, reason: str) -> ExitCode:
        log.error("%s halted: %s", self.services.ref.id, reason)
        self._exit_reason = self._exit_reason or f"halted: {reason}"[:300]
        self._notes = _sections(self._stopped_section("halted", reason))  # the halting run's last sync writes it
        edge = self._go(Trigger.BREAKER_OR_BUDGET, reason=reason[:300])
        return ExitCode(edge.exit_code if edge.exit_code is not None else ExitCode.HALTED)

    def _verify(self, phase: Phase) -> ExitCode | None:
        verify = self.services.hooks.verify
        if verify is None:
            log.info("%s: all tasks done; stopping at implemented (no verify hook; M1: verifier)", self.services.ref.id)
            return ExitCode.OK
        if phase is Phase.IMPLEMENTED:
            self._go(Trigger.VERIFICATION_STARTED)
        if consecutive_verifier_errors(self._events()) >= VERIFIER_ERROR_LIMIT:  # the escalation did not get written
            return self._escalate_verifier()
        try:
            trigger = verify(self._ctx)  # an exception leaves the phase at `verifying`
        except BaseMergeConflict as exc:  # step 0 could not merge the base (M1: exit 1 until a human merges it)
            self._notes = _sections(base_conflict_section(exc, self.services.names.branch))
            self._sync_mirror()
            # the unit's exit 1, not the run's: it repeats on every run until a human merges, and an exception here
            # would stop every unit sorted after this one (SPEC 2: several units give the most severe exit code)
            log.error("%s: %s", self.services.ref.id, exc)
            branch = self.services.names.branch
            self._exit_reason = f"base merge conflict: merge {exc.base} into {branch} by hand and push"
            return ExitCode.INTERNAL_ERROR
        except Exception as exc:
            if isinstance(exc, (RoleUnavailable, RoleLimit, SecretInPush, L4Exit)):
                raise  # a missing role is exit 12, a secret exit 13, an L4Exit has its own code: none is a crash
            first = (str(exc).splitlines() or [""])[0]
            self.services.ledger.append("verify.error", error=type(exc).__name__, message=first[:200])
            if consecutive_verifier_errors(self._events()) >= VERIFIER_ERROR_LIMIT:
                log.error("%s: the verifier failed again: %s: %s", self.services.ref.id, type(exc).__name__, first[:99])
                return self._escalate_verifier()
            raise
        if (notes := self._ctx.shared.pop("notes", None)) is not None:  # the verdict questions' sticky section
            self._notes = notes
        escalation = self._ctx.shared.pop("escalation", None)  # (reason, note): the feedback limit (L4-FBK-006)
        if trigger is Trigger.VERIFY_FAIL_EXHAUSTED:
            why = escalation[1] if escalation else "verification failed and no fix round is left (see verification.md)"
            self._notes = (self._stopped_section("escalated", why), *(self._notes or ()))
        edge = self._go(trigger, **({"reason": escalation[0]} if escalation else {}))
        if edge.target is Phase.ESCALATED:
            why = escalation[1] if escalation else "verification failed and no fix round is left (see verification.md)"
            self._exit_reason = f"escalated: {why}"
        if edge.target is Phase.FIXING and self.services.hooks.fix is not None:
            return None  # SPEC 12.0 "10 or 0": the fix loop goes on in this run (D2)
        return None if edge.exit_code is None else ExitCode(edge.exit_code)

    def _escalate_verifier(self) -> ExitCode:
        """L4-VER-010: the third internal verifier error in a row ends in `escalated` (exit 13); the verifier is not
        called a fourth time."""
        reason = f"escalated: {VERIFIER_ERROR_LIMIT} consecutive internal verifier errors (see the ledger)"
        self._notes = _sections(self._stopped_section("escalated", reason.removeprefix("escalated: ")))
        edge = self._go(Trigger.VERIFY_FAIL_EXHAUSTED, reason=reason)
        self._exit_reason = reason
        return ExitCode(edge.exit_code if edge.exit_code is not None else ExitCode.HALTED)

    def _fix(self) -> ExitCode | None:
        """A unit in `fixing`: run the open fix unit's tasks. None: they are done and the unit is `verifying` again."""
        hook = self.services.hooks.fix
        if hook is None:
            log.error("%s is fixing and there is no fix hook", self.services.ref.id)
            self._exit_reason = "halted: the unit is fixing and there is no fix hook"
            return ExitCode.HALTED
        outcome = hook(self._ctx)
        if outcome.status == "done":
            self._go(Trigger.FIX_UNIT_DONE)
            return None
        if outcome.status == "halt":
            return self._halt(outcome.reason)
        self._notes = _sections(outcome.section)
        self._refold()
        self._sync_mirror()
        log.info("%s: fix unit questions open: %s", self.services.ref.id, ", ".join(outcome.question_ids))
        return ExitCode.AWAITING_HUMAN

    def _legacy_round(self) -> int | None:
        return legacy_round(self.state, self._questions())

    def _raise_legacy_verdicts(self, round_no: int) -> ExitCode:
        """A NEEDS_HUMAN round that an older harness left without verdict questions (SCN-VER-47): raise them from the
        round's stored findings, commit them like any question, and wait for the human. No agent step, no judge."""
        from l4.verifier.legacy import raise_legacy_verdicts

        ids = raise_legacy_verdicts(self._ctx, round_no, self.state.verdicts_consumed)
        log.warning(
            "%s: round %d ended NEEDS_HUMAN without verdict questions (an earlier harness); raised %s",
            self.services.ref.id, round_no, ", ".join(ids) or "none",
        )  # fmt: skip
        self._refold()
        self._commit_questions("verdict questions")
        self._notes = _sections(verdict_section(self._ctx, self.state.verdicts_consumed))
        self._sync_mirror()
        return ExitCode.AWAITING_HUMAN

    def _verdicts_ready(self) -> list[str]:
        """The verdict questions to consume when every one of them is validly answered; none while one is still open
        or its answer is invalid (the sticky note asks for a fix)."""
        file = self._questions()
        status = verdict_status(file, self.state.verdicts_consumed)
        return list(status.ready) if status.ready and not status.open and not status.invalid else []

    def _hand_off(self) -> ExitCode:
        handoff = self.services.hooks.handoff
        if handoff is None:
            log.info("%s: verified; no handoff hook", self.services.ref.id)
            return ExitCode.OK
        if handoff(self._ctx) is False:
            log.warning("%s: verified; the hand-off hook did nothing, so the unit stays verified", self.services.ref.id)
            return ExitCode.OK
        self._notes = ()  # in review: nothing waits for an answer, and the note says how to ask for changes (D12)
        edge = self._go(Trigger.HAND_OFF_PUSHED)
        return ExitCode(edge.exit_code if edge.exit_code is not None else ExitCode.OK)

    # --- results ----------------------------------------------------------------------------------------------

    def _outcome(self, before: str) -> UnitOutcome:
        state = self._refold()
        tasks = self.services.provider.tasks(self.services.ref)
        profiles: dict[str, str] = {}
        fallback_from: str | None = None
        if self._selected:
            profiles["implementer"] = self._selected.profile_name
            fallback_from = self._selected.fallback_from
        elif used := state.profiles_used.get("implementer"):  # a run that selects none (it resumed at verifying)
            profiles["implementer"] = used[-1]
            fallback_from = state.fallback_from.get("implementer")
        profiles |= {role: used[-1] for role in ("clarifier", "s1_judge") if (used := state.profiles_used.get(role))}
        if fallback_from:
            profiles["fallback_from"] = fallback_from
        return UnitOutcome(
            unit=self.services.ref.id, phase_before=before, phase_after=state.phase or "none",
            tasks=TaskCounts(done=sum(t.done for t in required(tasks)), total=len(required(tasks))),
            open_questions=list(state.questions.open),
            verdict=state.last_verdict.verdict if state.last_verdict else None, profiles=profiles,
            cost_usd=state.cost_usd, iteration=state.iteration, retry_after=state.retry_after,
            pr_url=app_forge_urls(self.services.app, self.cfg).expand(state.pr) if state.pr else None,
            exit_reason=self._exit_reason,
        )  # fmt: skip

    def close(self, exit_code: int, *, failing: bool) -> None:
        """End the run's ledger and commit and push its last lines, so the unit branch always carries the full
        ledger. Once H is pushed the branch is the merge request head and stays at H: the run's file goes to the lock
        ref instead (SCN-CI-18). When the run is already failing, a push error must not hide the original one."""
        ledger = self.services.ledger
        if (tamper := ledger.restore_if_tampered()) is not None:  # an agent step that died early never restored
            ledger.append("guard.violation", path=self._ledger_rel(), rule="run ledger", action="restored",
                          **tamper.fields())  # fmt: skip
        if cancel.is_cancelled():  # W-D2: keep the evidence locally, push nothing, write nothing to the forge
            ledger.append("run.cancelled", signal=cancel.signum())
            ledger.append("lock.released")
            ledger.finish(exit_code)
            log.warning("%s: run cancelled; the final ledger is not pushed", self.services.ref.id)
            return
        ledger.append("lock.released")
        ledger.finish(exit_code)
        if self.state.phase in _AFTER_HAND_OFF or self._ctx.shared.get(H_PUSHED):  # H pushed, phase not yet moved
            self._publish_pending(failing=failing)
            return
        if self._push_failed:  # the branch push was refused during the run: a second attempt only repeats the error
            log.warning("final ledger not pushed: the push of the unit branch already failed in this run")
            return
        if not self._worth_pushing():
            return
        try:
            self._commit_ledger()
            self.push()
        except Exception as exc:
            if not failing:
                raise
            first = (str(exc).splitlines() or [type(exc).__name__])[0]  # one line: read the original error
            log.error("could not push the final ledger: %s", self.services.app.redactor.redact_text(first))

    def _pending_ledger(self, run_id: str) -> PendingLedger:
        s = self.services
        return PendingLedger(
            s.git, lock_ref=s.names.lock_ref, unit=s.ref.id, run_id=run_id,
            fetch_config=fetch_auth_config(self.cfg, s.app.environ),
            push_config=self._forge.push_config if self._forge else (),
        )  # fmt: skip

    def _unpublished(self) -> dict[str, Path]:
        s = self.services
        return unpublished_files(cache_root(s.app.environ, repo=s.app.repo), s.ref.framework.value, s.ref.name)

    def _publish_unpublished(self) -> None:
        """The tails that earlier runs could not publish (the lock ref refused the push) exist nowhere else, so they
        go first. A failure here is only logged: this run's own publish reports a lock ref that cannot be written."""
        for run_id, path in self._unpublished().items():
            try:
                self._pending_ledger(run_id).publish(path)
            except Exception as exc:  # noqa: BLE001 - kept for the next run, which tries again
                first = (str(exc).splitlines() or [type(exc).__name__])[0]
                redacted = self.services.app.redactor.redact_text(first)
                log.warning("the pending ledger of %s is still not published: %s", run_id, redacted[:200])
                continue
            path.unlink(missing_ok=True)

    def _publish_pending(self, *, failing: bool) -> None:
        s = self.services
        run_file = ledger_path(s.ref.path, s.app.run_id)
        try:
            self._pending_ledger(s.app.run_id).publish(run_file)
        except GitError as exc:  # one explained error (exit 3 for a credential problem), never a git traceback
            error: Exception = explain_push_failure(
                exc, branch=s.names.lock_ref, token_env=self.cfg.forge.token_env, environ=s.app.environ,
                redact=s.app.redactor.redact_text,
            )  # fmt: skip
        except Exception as exc:
            error = exc
        else:
            return
        try:
            keep_unpublished(cache_root(s.app.environ, repo=s.app.repo), s.ref.framework.value, s.ref.name, run_file)
        except OSError as exc:
            log.warning("the pending ledger of %s could not be kept for the next run: %s", s.app.run_id, exc)
        if not failing:
            raise error
        first = (str(error).splitlines() or [type(error).__name__])[0]
        log.error("could not publish the pending ledger: %s", s.app.redactor.redact_text(first))

    def _worth_pushing(self) -> bool:
        """A run that only got as far as intake, readiness or a capacity wait, changed nothing and has no branch yet
        must not create one: the branch would freeze today's copy of the spec (base merges are M1: state-vcs-locks
        1.27), and the unit would never see the human's next fix to it. The intake lint's own commit does not count:
        `_start` is moved past it."""
        git = self.services.git
        if git.rev_parse("HEAD") != self._start:
            return True
        if git.rev_parse(f"refs/remotes/origin/{self.services.names.branch}") is not None:
            return True
        return self.state.phase not in (None, Phase.INTAKE, Phase.READY, Phase.WAITING_CAPACITY, Phase.REJECTED)

    def _ledger_rel(self) -> str:
        s = self.services
        return ledger_path(s.ref.path, s.app.run_id).resolve().relative_to(s.worktree.resolve()).as_posix()

    def _commit_ledger(self) -> None:
        s = self.services
        rel = self._ledger_rel()
        s.git.run("add", "--", rel)
        if s.git.run("diff", "--cached", "--quiet", check=False).returncode == 0:
            return
        phase = self.state.phase or "intake"
        trailers = CommitTrailers(
            unit=s.ref.id, run_id=s.app.run_id, iteration=max(self.state.iteration, 1), phase=phase
        )
        subject = f"chore({s.ref.name}): {self._commit_what} [skip ci]"
        s.git.commit(subject, trailers)  # a checkpoint: never the head of a review


def _busy(snapshot_phase: str | None, ref: UnitRef) -> UnitRunResult:
    phase = snapshot_phase or "none"
    log.info("%s is locked by another run: skipped", ref.id)
    reason = "skipped: the unit is locked by another run"
    outcome = UnitOutcome(unit=ref.id, phase_before=phase, phase_after=phase, exit_reason=reason)
    return UnitRunResult(outcome, ExitCode.OK)


def run_unit_in_worktree(
    app: AppContext,
    cfg: L4Config,
    git: Git,
    provider: SpecProvider,
    ref: UnitRef,
    *,
    adapters: Mapping[str, AgentAdapter] | None = None,
    hooks: Hooks | None = None,
    resume_reason: str | None = None,
    resume_signal: str | None = None,
    resume_by: str | None = None,
    resume_extend_fix_rounds: int | None = None,
    resume_extend_feedback_rounds: int | None = None,
    waits: RunWaits | None = None,
) -> UnitRunResult:
    """Lease, worktree, ledger, services, `run_unit` (or `resume` when `resume_reason` is given), then the final
    ledger commit. Order matters: the worktree is deleted and recreated by `ensure`, so it is only touched once the
    lease is held. `waits`: what the run's earlier units waited for a cool-down (L4-AVL-011)."""
    preflight_run_config(app, cfg)  # exit 2 before the lease, the worktree and any probe
    names = UnitNames.for_unit(
        ref.id, branch_prefix=cfg.forge.branch_prefix, cache=cache_root(app.environ, repo=app.repo)
    )
    relative = provider.unit_dir(ref).resolve().relative_to(app.repo.resolve())
    snapshot = load_snapshot(provider, git, ref, branch_prefix=cfg.forge.branch_prefix)
    lease = LocalFileLease(names.flock_path, unit=ref.id, run_id=app.run_id, job=app.environ.get("CI_JOB_ID"))
    opened: dict[str, Path] = {}

    trace = ProgressTrace(project_web_url(app.environ, cfg.forge.gitlab.api_url, cfg.forge.gitlab.project))
    unit_git = git.at(app.repo)  # this unit's own listeners: the console shows its commits and pushes
    unit_git.on_commit, unit_git.on_push = trace.commit, trace.pushed

    def open_writer() -> LedgerWriter:
        manager = WorktreeManager(
            git, base_branch=cfg.forge.base_branch, branch_prefix=cfg.forge.branch_prefix,
            fetch_config=fetch_auth_config(cfg, app.environ),
        )  # fmt: skip
        tree = manager.ensure(names)
        unit_dir = tree.path / relative
        if not unit_dir.is_dir():
            raise UnknownUnit(f"{ref.id} is not in {cfg.forge.base_branch} or on its unit branch")
        opened["worktree"] = tree.path
        return LedgerWriter.open(
            unit_dir, ref.id, app.run_id, redactor=app.redactor, command="run", branch=names.branch,
            base=tree.head, source=tree.source, iteration=snapshot.state.iteration + 1,  # this run's own count (P6)
            observers=[trace], file_filter=app_forge_urls(app, cfg).scrub, **run_environment(app.environ),
        )  # fmt: skip

    writer = acquire_for_run(lease, open_writer)
    if writer is None:
        return _busy(snapshot.state.phase, ref)
    code: int = ExitCode.INTERNAL_ERROR
    failed = True
    orchestrator: Orchestrator | None = None
    try:
        services = build_services(
            app, cfg, git=unit_git, names=names, worktree=opened["worktree"], ledger=writer,
            adapters=adapters, hooks=hooks, sandbox=resume_reason is None,  # a resume runs no agent and no gate
        )  # fmt: skip
        orchestrator = Orchestrator(cfg, services, waits)
        result = (
            orchestrator.run_unit()
            if resume_reason is None
            else orchestrator.resume(
                resume_reason, signal=resume_signal, by=resume_by, extend_fix_rounds=resume_extend_fix_rounds,
                extend_feedback_rounds=resume_extend_feedback_rounds,
            )
        )
        code, failed = result.exit_code, False
        return result
    except BaseException as exc:
        code = classify_exception(exc)[0] if isinstance(exc, Exception) else ExitCode.INTERNAL_ERROR
        if isinstance(exc, cancel.RunCancelled):
            code = ExitCode.CANCELLED
        raise
    finally:
        try:
            if orchestrator is not None:
                orchestrator.close(code, failing=failed)
            else:  # no sandbox, or the unit is missing: nothing ran, so nothing is committed
                writer.append("lock.released")
                writer.finish(code)
        finally:
            lease.release()


def run_command(
    app: AppContext,
    *,
    units: tuple[str, ...] = (),
    max_units: int | None = None,
    time_budget: str | None = None,
    dry_run: bool = False,
    probe: bool = False,
    adapters: Mapping[str, AgentAdapter] | None = None,
) -> CommandResult:
    """`l4 run`: the named units, or every unit with something to do; sequential; the most severe exit code.
    `adapters` replaces registry entries by adapter name (`l4 simulate` runs the scripted agents this way)."""
    if time_budget:
        raise L4Exit(ExitCode.USAGE_ERROR, "run: --time-budget not yet implemented (M1: implementer-tdd-loop)")
    if probe and not dry_run:
        raise L4Exit(ExitCode.USAGE_ERROR, "run: --probe needs --dry-run")  # else a CI line would pass and do nothing
    if dry_run:
        from l4.sim.dryrun import run_dry  # imported here: the dry run imports this module's ACTIONABLE

        return run_dry(app, units=units, probe=probe)
    app, cfg = load_app_config(app)
    preflight_run_config(app, cfg)
    require_framework(cfg, app.repo)
    git = Git(app.repo, environ=app.environ)
    refresh_refs(app, cfg, git)
    providers = list(providers_for(cfg, app.repo, app.environ))
    found = discover(cfg, git, providers, units)
    made: list[FollowUpMade] = []
    failure: ExitCode | int = ExitCode.OK
    try:  # merged units' feedback becomes units (L4-FBK-010); a failure here is the next run's to retry, not the units'
        made = perform_follow_ups(app, cfg, git, [s for _, s in found])
    except Exception as exc:  # noqa: BLE001 - classified: the exit code of the run, after the other units ran
        failure = classify_exception(exc)[0]
    if made:
        found = discover(cfg, git, providers, units)  # the new units are on their own branches now
    snapshots = {s.ref.id: s for _, s in found}
    chosen = without_fix_units(
        [(p, s.ref) for p, s in found if s.source != "archive"], named=units
    )  # an archived unit is only ever a parent of a follow-up
    if not units:
        chosen = [
            (provider, ref) for provider, ref in chosen if next_action(facts_of(snapshots[ref.id]))[0] in ACTIONABLE
        ]
    if not chosen:
        log.info("nothing to do: no unit has a next step")  # before any lease, worktree or probe
        return CommandResult(failure, [_follow_up_outcome(m) for m in made])
    kiro = cfg.spec.kiro
    if (kiro.write_in_progress_marker or kiro.write_queued_marker) and any(
        ref.framework is Framework.KIRO for _, ref in chosen
    ):
        log.info("spec.kiro.write_in_progress_marker and write_queued_marker are ignored: only `x` is ever written")
    result = run_units(app, cfg, git, chosen[: max_units if max_units is not None else None], adapters=adapters)
    result = replace(
        result, code=most_severe([result.code, failure]), units=[*(_follow_up_outcome(m) for m in made), *result.units]
    )
    result = continue_left_units(app, cfg, result)
    log_artefacts(app.out_dir, app.run_id)
    return result


def _follow_up_outcome(made: FollowUpMade) -> UnitOutcome:
    """The merged parent, whose phase did not change, and the follow-up unit its feedback became."""
    reason = f"follow-up {made.follow_up} created on {made.branch} for {', '.join(made.items)}"
    return UnitOutcome(unit=made.parent, phase_before="merged", phase_after="merged", exit_reason=reason)


def continue_left_units(app: AppContext, cfg: L4Config, result: CommandResult) -> CommandResult:
    """github-parity D4 (L4-GHP-004): once per `l4 run`, when the run ends with exit 10 because units were left at the
    soft deadline, `ci.continuation` is `dispatch` and the run is in CI, ask the forge for one more run of the harness's
    CI on the base branch. The answer is logged and recorded in `outcome.json`. No forge, or a forge error, is a warning
    at most: the exit code does not change."""
    left = any((u.exit_reason or "").startswith("not started: soft deadline") for u in result.units)
    in_ci = app.environ.get("GITHUB_ACTIONS") == "true" or app.environ.get("GITLAB_CI") == "true"
    if result.code != ExitCode.CONTINUE or not left or cfg.ci.continuation != "dispatch" or not in_ci:
        return result
    base = cfg.forge.base_branch
    try:
        answer = make_forge(cfg, app.environ).dispatch_continuation(base)
    except ForgeUnavailable:
        return result  # a local run without credentials: nothing to ask
    except Exception as exc:  # noqa: BLE001 - a warning, never a failure of the run
        log.warning("continuation: not requested (%s)", app.redactor.redact_text(str(exc)))
        return result
    log.info("continuation: %s (l4.yml on %s)", answer, base)
    return replace(result, continuation=answer)


def job_remaining_s(cfg: L4Config, environ: Mapping[str, str], now: datetime, began: datetime | None) -> float | None:
    """Seconds of the CI job left before the soft deadline (L4-IMP-012): `ci.time_budget` minus
    `soft_deadline_margin`, minus what has passed since the job started; None when the budget is unknown (`auto`
    without GitLab's `CI_JOB_TIMEOUT` or GitHub's `L4_JOB_TIMEOUT_MINUTES`).
    The start is `CI_JOB_STARTED_AT` when set, else `began` (the run's start)."""
    budget = cfg.ci.time_budget
    if budget != "auto":
        total: int | None = duration_seconds(budget)
    else:
        raw = environ.get("CI_JOB_TIMEOUT", "")  # GitLab: seconds
        minutes = environ.get("L4_JOB_TIMEOUT_MINUTES", "")  # GitHub: the template's `timeout-minutes`, as a job env
        total = int(raw) if raw.isdigit() else int(minutes) * 60 if minutes.isdigit() else None
    if total is None:
        return None
    started = began or now
    with contextlib.suppress(ValueError):
        if environ.get("CI_JOB_STARTED_AT"):
            stamp = datetime.fromisoformat(environ["CI_JOB_STARTED_AT"])
            started = stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)
    return total - duration_seconds(cfg.ci.soft_deadline_margin) - (now - started).total_seconds()


def run_units(
    app: AppContext,
    cfg: L4Config,
    git: Git,
    chosen: Sequence[tuple[SpecProvider, UnitRef]],
    *,
    adapters: Mapping[str, AgentAdapter] | None,
) -> CommandResult:
    """The units one after the other. One that raises (HB-7, L4-CLI-001) ends with its own exit code and an
    `exit_reason`, and the units after it still run: its siblings must not lose their turn to it, and `outcome.json`
    lists every unit. The most severe code wins.

    L4-IMP-012, between units: once the soft deadline is known (`job_remaining_s`), no further unit starts when no time
    is left or the longest unit run so far (the estimate of the next) would not fit; the units left are listed with
    exit 10, untouched, for the next run. The first unit always starts."""
    codes: list[int] = []
    units: list[UnitOutcome] = []
    clock = services_module.SystemClock()  # looked up here so tests can control it
    waits = RunWaits()  # one wait budget for the whole run (L4-AVL-011)
    waits.began = clock.now()  # the run's start, even if the first unit fails before it builds its orchestrator
    longest = 0.0  # the longest wall-clock time one unit took in this run: the estimate for the next
    for index, (provider, ref) in enumerate(chosen):
        if index:
            left = job_remaining_s(cfg, app.environ, clock.now(), waits.began)
            if left is not None and (left <= 0 or longest > left):
                rest = chosen[index:]
                why = f"{left:.0f} s left" + (f", next unit estimated {longest:.0f} s" if longest else "")
                log.info("soft deadline: %d unit(s) left for the next run (%s)", len(rest), why)
                for left_provider, left_ref in rest:
                    phase = _phase_of(cfg, git, left_provider, left_ref)
                    units.append(
                        UnitOutcome(
                            unit=left_ref.id,
                            phase_before=phase,
                            phase_after=phase,
                            exit_reason=f"not started: soft deadline ({why})",
                        )
                    )
                codes.append(ExitCode.CONTINUE)
                break
        began = clock.now()
        before = _phase_of(cfg, git, provider, ref)
        try:
            done = run_unit_in_worktree(app, cfg, git, provider, ref, adapters=adapters, waits=waits)
        except Exception as exc:  # noqa: BLE001 - classified: the exit code and a redacted one-line reason
            done = _failed_unit(app, cfg, git, provider, ref, exc, before)
        longest = max(longest, (clock.now() - began).total_seconds())
        codes.append(done.exit_code)
        units.append(done.outcome)
    return CommandResult(most_severe(codes), units)


def _phase_of(cfg: L4Config, git: Git, provider: SpecProvider, ref: UnitRef) -> str:
    """Where the unit stands, best effort: the reason a unit failed is the point, its phase only context."""
    try:
        return load_snapshot(provider, git, ref, branch_prefix=cfg.forge.branch_prefix).state.phase or "none"
    except Exception:  # noqa: BLE001
        log.debug("%s: the phase could not be read", ref.id, exc_info=True)
        return "none"


def _failed_unit(
    app: AppContext, cfg: L4Config, git: Git, provider: SpecProvider, ref: UnitRef, exc: Exception, before: str
) -> UnitRunResult:
    code, message = classify_exception(exc)
    redacted = app.redactor.redact_text(message)
    first = (redacted.splitlines() or [type(exc).__name__])[0]
    log.error("%s: %s", ref.id, first)
    log.debug("traceback", exc_info=exc)
    if isinstance(exc, PushFailed) and exc.refused:
        first = f"push refused by the forge: {first}"
    after = _phase_of(cfg, git, provider, ref)  # whatever the failed run committed or pushed before it raised
    outcome = UnitOutcome(unit=ref.id, phase_before=before, phase_after=after, exit_reason=first[:300])
    return UnitRunResult(outcome, code)
