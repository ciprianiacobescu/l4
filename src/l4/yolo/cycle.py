"""The plan step of `l4 run` (openspec/changes/yolo-mode, design D10, D11, D12; requirements L4-YOLO-009..015).

`yolo_step(app, cfg, git, found)` runs once per `l4 run`, after `discover` and the follow-ups and before the run decides
what is left to do. It does at most one thing (L4-YOLO-012), records it in the plan ledger (`refs/l4/plans/<id>`, one
leased commit: a lost lease reads the ref again and decides once more, a second one ends the step for this run), and
returns which units `l4 run` may dispatch (`allow`).

With no plan file on the target nothing changes: `allow` is None and no plan ref is read or written. With plan files, a
unit listed in a plan that is not final is held by it: only the plan's own step dispatches it, and only while the plan
is active (L4-YOLO-010). While a plan is active, units outside every plan get no new agent work.

The first thing that applies is done, in this order:

1. A valid plan with no review for its current plan and unit digests, that has not started (or was stopped by
   `inputs_changed`): admit it (`plan.admitted` or `plan.refused`) and review it (`plan.reviewed`, and `plan.charged`
   for the judge's cost, under the key `plan:review` whose figure is the running total, because the fold keeps the
   maximum per key). An invalid plan file gets `plan.refused` once per file content. A judge that cannot run
   (`RoleLimit`, `RoleUnavailable`) records nothing: a scheduled run tries again.
2. The active plan: target missing; a frozen digest changed for a unit that is not integrated (never an integrated or a
   merged unit: the archive moves its folder); a limit (D11); the current unit halted, escalated, abandoned or rejected;
   the current unit waiting for a person or for capacity; the guarded merge of an `in_review` unit with a PASS under
   `merge: auto` and its post-merge profile (D8, D9); a merged unit's profile; a finished batch's profile; completion;
   else the dispatch of the one eligible unit.
3. Every stop and the completion write `report.md` into the plan ref and `.l4-out/yolo/<plan>.md` (D12).

A `stopped` plan does nothing in its step: `l4 yolo resume` is how it goes on (D10's table). A `waiting` plan goes on
by itself when the cause is gone: each step reads its current unit again, and when that unit is no longer waiting for a
person or for capacity the step records `plan.resumed{by: "harness"}` and carries on in the same step (the dispatch or
the merge). `l4 yolo resume` stays available for a waiting plan too. The units of a waiting or stopped plan stay held.
The facts of a push that already happened (the merge) are appended again with a fresh lease when the ref moved, because
they are true whatever the plan now says; the request to merge is recorded BEFORE the push, under the lease, and only
while the plan, read again, is still active (R5).

The usage is charged per attempt (R1): `plan.charged{unit, attempt, cost_usd, runs}` where the attempt is 1 + the number
of the unit's `refs/l4/attempts/<fw>/<name>/*` refs on origin. The judge's cost is `plan.charged{unit: "plan:review",
attempt: 0}`. The limits are `limits.reached_at` on the folded state, with the cost and the attempt of the unit that is
running now added (R3). The plan file is frozen at the activation (R2): a file whose digest differs, or that is no
longer a plan, stops the plan with `inputs_changed` (subject `plan`). Every merged unit that is not integrated is
post-checked before anything is dispatched, a person's merges included (R10).
"""

import logging
import re
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from l4.agents.base import AgentAdapter
from l4.availability.errors import RoleUnavailable
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import L4Exit
from l4.forge.base import Forge, ForgeError, ForgeUnavailable, fetch_auth_config, make_forge
from l4.forge.gitlab import push_auth_config
from l4.forge.urls import origin_url
from l4.implementer.tdd import RoleLimit
from l4.sandbox.base import Sandbox
from l4.specs.base import SpecProvider, UnitRef, parse_unit_id
from l4.state.fold import UnitState
from l4.state.status import UnitSnapshot
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.yolo.admit import FINISHED_PHASES, admit, done_units, merged_not_integrated, next_eligible, unit_blocker
from l4.yolo.digest import MISSING, FolderMissing, RevisionMissing, current_unit_digest, plan_digest
from l4.yolo.limits import attempt_refs, charged_of, live_attempt, live_state, reached_at
from l4.yolo.merge import NO_LONGER_ALLOWED, _is_ancestor, confirm_merged, merge_guarded, remote_tip
from l4.yolo.model import (
    PLAN_ID,
    PLAN_REF_PREFIX,
    PLANS_DIR,
    Eligibility,
    MergeOutcome,
    Plan,
    PlanEvent,
    PlanMoved,
    PlanState,
    ProfileResult,
    ReviewResult,
    Verdict,
    YoloStep,
)
from l4.yolo.plans import PlanFile, archived_at, holds_of, plan_files, plan_files_at, unit_infos
from l4.yolo.postcheck import run_profile
from l4.yolo.readiness import PROMPT_VERSION, review_plan_costed
from l4.yolo.report import render_report
from l4.yolo.state import fold_plan, is_unit_key
from l4.yolo.store import PlanRead, PlanStore, list_plans, parse_ledger, plan_ref

log = logging.getLogger("l4.yolo.cycle")

REVIEW_KEY = "plan:review"  # the `plan.charged` key of the judge's cost
STOPPED_PHASES = ("halted", "escalated", "abandoned", "rejected")
WAIT_PHASES = ("awaiting_human", "clarifying", "waiting_capacity")
RUN_NOT_STARTED = "run_not_started"  # the `plan.waiting` reason of a current unit whose last run never started it
MERGE_NOT_READY = "merge_not_ready"  # the `plan.waiting` reason of a `merge: auto` plan whose merge is not ready
_ACTIONABLE = frozenset({"implement", "clarify", "verify", "hand_off"})  # `orchestrator.ACTIONABLE`, not imported here
_BEFORE_ACTIVATION = ("new", "refused", "admitted", "reviewed")
_USERINFO = re.compile(r"(?<=//)[^/@\s]+@")


@dataclass(frozen=True)
class PlanStep(YoloStep):
    """`YoloStep` and, for `l4 run --unit`, why each unit that is not in `allow` is not dispatched: the end of the
    sentence `run: <unit> <refusal>` (L4-YOLO-010, SCN-YOLO-21)."""

    refusals: Mapping[str, str] = field(default_factory=dict)
    pending_starts: frozenset[str] = frozenset()  # current units of a plan with a `unit.not_started` record pending


@dataclass(frozen=True)
class Hold:
    """Why a unit gets no agent work from the plan: `reason` for `l4 plan`, `refusal` for `l4 run --unit`."""

    reason: str
    refusal: str


# --- reading plan state without writing (the planner and the sweeper) ------------------------------------------------


def local_states(git: Git, files: Sequence[PlanFile]) -> dict[str, PlanState]:
    """The folded state of every plan file's ledger as the local `refs/l4/plans/*` hold it (no fetch, no write): the
    ref is `new` when it is not there. A ledger that cannot be read is logged and the plan counts as `new`."""
    states: dict[str, PlanState] = {}
    for file in files:
        if not PLAN_ID.match(file.plan_id):
            continue
        shown = git.run("show", f"{plan_ref(file.plan_id)}:ledger.jsonl", check=False)
        try:
            events = parse_ledger(shown.stdout) if shown.returncode == 0 else []
        except ValueError as exc:
            log.warning("plan %s: its ledger cannot be read: %s", file.plan_id, exc)
            events = []
        states[file.plan_id] = fold_plan(file.plan_id, events)
    return states


def live_plan(files: Sequence[PlanFile], states: Mapping[str, PlanState], target: str) -> PlanFile | None:
    """The plan whose step may dispatch and merge now: the first valid file on `target` whose status is `active`."""
    for file in files:
        state = states.get(file.plan_id)
        if file.plan is not None and file.plan.target == target and state is not None and state.status == "active":
            return file
    return None


def plan_holds(
    files: Sequence[PlanFile],
    states: Mapping[str, PlanState],
    phases: Mapping[str, str | None],
    target: str,
) -> dict[str, Hold]:
    """The units that get no new agent work from the plans, with the reason (design D10): a unit listed in a plan that
    is not final is held (`held by plan p1 (reviewed)`); in the active plan only the current or eligible unit is
    free and the others wait for what `next_eligible` says; while a plan is active a unit outside every plan is
    `not in the active plan p1`. A unit the plan has integrated is no hold. A cancelled plan still holds its units, and
    a plan file that is not a plan holds the ids its JSON names, shown as `invalid` (R8)."""
    invalid = {f.plan_id for f in files if f.plan is None}
    held = {
        unit: (pid, "invalid" if pid in invalid else status)
        for unit, (pid, status) in holds_of(states, files).held.items()
    }
    live = live_plan(files, states, target)
    eligibility: Eligibility | None = None
    if live is not None and live.plan is not None:
        eligibility = next_eligible(live.plan, states[live.plan_id], phases)
    holds: dict[str, Hold] = {}
    for unit in phases:
        if unit in held:
            plan_id, status = held[unit]
            if live is not None and plan_id == live.plan_id and eligibility is not None:
                state = states[plan_id]
                if unit in state.integrated or unit == eligibility.unit or unit == state.current:
                    continue
                reason = eligibility.waiting.get(unit)
                if reason:
                    holds[unit] = Hold(reason, f"{reason} (plan {plan_id})")
                    continue
            holds[unit] = Hold(f"held by plan {plan_id} ({status})", f"is held by plan {plan_id} ({status})")
        elif live is not None:
            holds[unit] = Hold(f"not in the active plan {live.plan_id}", f"is not in the active plan {live.plan_id}")
    return holds


def review_batches(plan: Plan, result: ReviewResult) -> dict[str, Verdict]:
    """The batch verdicts of a review, with an entry for EVERY batch of more than one unit (R11): the activation wants
    one for each, so a batch the judge could not read (a unit with no folder) is recorded as BLOCKED, never left out."""
    batches = dict(result.batches)
    for batch in plan.batches:
        if len(batch.units) > 1 and batch.id not in batches:
            finding = {
                "criterion": "completeness",
                "severity": "blocking",
                "text": f"batch {batch.id} was not reviewed: a unit of it has no folder to read",
            }
            batches[batch.id] = Verdict("BLOCKED", (finding,))
    return batches


def unreadable_plan_files(files: Sequence[PlanFile]) -> list[str]:
    """One line per plan file that is not a JSON object: it holds no unit, so `l4 plan` and `l4 yolo status` say so
    instead of leaving its units to start on their own unnoticed (R8)."""
    return [
        f"plan file {f.path} is not a JSON object and holds no unit: {'; '.join(f.invalid.errors) if f.invalid else ''}"
        for f in holds_of({}, files).unreadable
    ]


def plan_source(cfg: L4Config, git: Git) -> str | None:
    """The revision the plan step reads the plan files from: `refs/remotes/origin/<forge.base_branch>` when that ref
    exists and the checkout is not that commit, or is that commit with a changed plan file (a laptop with its own
    edits, a branch, a tree without the file: the commands read the target too); else None, the working tree. In CI the
    job checks out the target head with no change, so both are the same. A local read, no network."""
    ref = f"refs/remotes/origin/{cfg.forge.base_branch}"
    tip = git.rev_parse(ref)
    if tip is None:
        return None
    if tip == git.rev_parse("HEAD"):
        changed = git.run("status", "--porcelain", "--", PLANS_DIR, check=False)
        return ref if changed.returncode == 0 and changed.stdout.strip() else None
    return ref


def target_plan_files(app: AppContext, cfg: L4Config, git: Git) -> list[PlanFile]:
    """The plan files the step, the holds and the merge-policy listing use: those of `plan_source`."""
    ref = plan_source(cfg, git)
    return plan_files(app.repo) if ref is None else plan_files_at(git, ref)


def auto_plan_units(app: AppContext, cfg: L4Config, git: Git) -> frozenset[str]:
    """The units of the active `merge: auto` plans on the base branch, for the sweep that merges their archive pull
    requests (L4-YOLO-009). The plan refs are fetched; any failure to read them is logged and means no unit."""
    files = [f for f in target_plan_files(app, cfg, git) if f.plan is not None and f.plan.merge == "auto"]
    units: set[str] = set()
    for file in files:
        assert file.plan is not None
        if not PLAN_ID.match(file.plan_id) or file.plan.target != cfg.forge.base_branch:
            continue
        try:
            store = _store(app, cfg, git, file.plan_id)
            state = fold_plan(file.plan_id, store.read().events)
        except (GitError, ValueError, L4Exit) as exc:
            log.warning("plan %s: its state could not be read, its archive pull requests are left to people: %s",
                        file.plan_id, exc)  # fmt: skip
            continue
        if state.status == "active":
            units.update(file.plan.unit_ids())
    return frozenset(units)


def fetch_cause(app: AppContext, exc: GitError, limit: int = 160) -> str:
    """Why a git fetch failed, for one line: what git said (its `fatal:` or `error:` line, else the first line of its
    stderr), then the exit status; the command line, which is long and says nothing, is left out so that a cut keeps
    the cause."""
    said = [x.strip() for x in str(getattr(exc, "stderr", "") or "").splitlines() if x.strip()]
    cause = next((x for x in said if x.startswith(("fatal:", "error:"))), said[0] if said else None)
    text = cause if cause else (str(exc).splitlines() or [type(exc).__name__])[0]
    code = getattr(exc, "returncode", None)
    text = app.redactor.redact_text(text)
    if len(text) > limit:  # a long path in the middle goes, not the end of the sentence
        text = f"{text[:50]}...{text[-(limit - 55) :]}"
    return text + (f" (git exit {code})" if code is not None else "")


def _fetch_failure(app: AppContext, cfg: L4Config, git: Git) -> str | None:
    """Outside CI, fetch the target into its tracking ref before the plan files are read from it: a laptop clone does
    not fetch on its own, and plan files read from an old tip would make the step stop a plan that was edited and
    activated again since (the `l4 yolo` commands fetch the same way). None when it was fetched, in CI (the job checks
    out the target head: no network call), when the clone has no origin and when origin answers that the branch is not
    there (the step stops the plan as `target_missing`, a fact); else one line saying why not."""
    if app.environ.get("GITHUB_ACTIONS") == "true" or app.environ.get("GITLAB_CI") == "true":
        return None
    if git.run("remote", "get-url", "origin", check=False).returncode != 0:
        return None
    target = cfg.forge.base_branch
    spec = f"+refs/heads/{target}:refs/remotes/origin/{target}"
    try:
        git.fetch("origin", refspecs=(spec,), config=fetch_auth_config(cfg, app.environ))
    except GitError as exc:
        try:
            if remote_tip(git, cfg, app.environ, target) is None:
                return None
        except GitError:
            pass
        return f"the target {target} could not be fetched ({fetch_cause(app, exc)})"
    return None


def _store(app: AppContext, cfg: L4Config, git: Git, plan_id: str) -> PlanStore:
    return PlanStore(
        git, plan_id, fetch_auth_config(cfg, app.environ), push_config=push_auth_config(cfg, app.environ),
        token_env=cfg.forge.token_env, environ=app.environ, redact=app.redactor.redact_text,
    )  # fmt: skip


# --- the step --------------------------------------------------------------------------------------------------------


@dataclass
class _Ctx:
    file: PlanFile
    store: PlanStore
    read: PlanRead
    state: PlanState

    @property
    def plan_id(self) -> str:
        return self.file.plan_id

    def refresh(self, read: PlanRead) -> None:
        self.read = read
        self.state = fold_plan(self.plan_id, read.events)


def yolo_step(
    app: AppContext,
    cfg: L4Config,
    git: Git,
    found: Sequence[tuple[SpecProvider, UnitSnapshot]],
    *,
    forge: Forge | None = None,
    adapters: Mapping[str, AgentAdapter] | None = None,
    profiles: Mapping[str, Sequence[str]] | None = None,
    sandbox: Sandbox | None = None,
    now: Callable[[], datetime] | None = None,
    confirm_wait_s: float = 30.0,
    all_units: Callable[[], Sequence[tuple[SpecProvider, UnitSnapshot]]] | None = None,
    read_only: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> PlanStep:
    """The plan step of this run (module text). `forge`, `adapters`, `profiles`, `sandbox` and `now` replace what the
    run would build (tests and `l4 simulate`); `confirm_wait_s` is how long the step waits for the forge to show a
    merged pull request. `all_units` discovers every unit when `found` holds only the units a command named
    (`l4 run --unit`): the plan needs them all, and is read only when a plan file exists. `read_only` (a run that names
    units): which units may run is answered from the plan's state, and nothing is reviewed, recorded or started
    (but the charge of a run of the current unit, L4-YOLO-012). `sleep` waits between the reads of a PR head that
    the forge shows late (tests pass a no-op). The plan files are those of the target (`plan_source`). Outside CI the
    target is fetched first; when that fails the step reads nothing from a tracking ref that may be stale, writes
    nothing and lets no unit of a plan run (L4-YOLO-013)."""
    source = plan_source(cfg, git)
    files = plan_files(app.repo) if source is None else plan_files_at(git, source)
    unconfirmed = None
    # a repository that never had a plan file is left alone: no network call for it
    if files or (not read_only and _had_plan_files(git, source or "HEAD")):
        unconfirmed = _fetch_failure(app, cfg, git)
        source = plan_source(cfg, git)
        files = plan_files(app.repo) if source is None else plan_files_at(git, source)
    ledgers: list[str] | None = None
    if not files:  # no plan file: only a repository that once had plan files can hold a plan whose file was deleted
        had = not read_only and _had_plan_files(git, source or "HEAD")
        if unconfirmed is None:
            ledgers = _ledger_plans(app, cfg, git) if had else []
            if not ledgers:
                return PlanStep(allow=None)
        elif not had:
            return PlanStep(allow=None)
    named = frozenset(s.ref.id for _, s in found) if read_only else None  # the units `l4 run --unit` names
    if all_units is not None:
        found = all_units()
    step = _Step(app, cfg, git, found, files, forge, adapters, profiles, sandbox, now, confirm_wait_s)
    step.ledgers, step.sleep, step.named, step.unconfirmed = ledgers, sleep, named, unconfirmed
    return step.preview() if read_only else step.run()


def _had_plan_files(git: Git, rev: str = "HEAD") -> bool:
    """True when the history of `rev` (the revision the plan files are read from) ever held a file under
    `.l4/plans`. A local read, no network: a repository that never had a plan file takes no plan step at all
    (design: no change without a plan file)."""
    shown = git.run("log", "-1", "--format=%H", rev, "--", PLANS_DIR, check=False)
    return shown.returncode == 0 and bool(shown.stdout.strip())


def _ledger_plans(app: AppContext, cfg: L4Config, git: Git) -> list[str]:
    """The plan ids that have a ledger ref on origin; [] when origin cannot be asked (no plan step then)."""
    try:
        return list_plans(git, fetch_auth_config(cfg, app.environ))
    except GitError as exc:
        log.warning("the plan refs could not be listed: %s", str(exc).splitlines()[0][:200] if str(exc) else exc)
        return []


class _Step:
    ledgers: list[str] | None = None  # the plan ids with a ledger ref on origin, when `yolo_step` has listed them

    def __init__(
        self, app: AppContext, cfg: L4Config, git: Git, found: Sequence[tuple[SpecProvider, UnitSnapshot]],
        files: Sequence[PlanFile], forge: Forge | None, adapters: Mapping[str, AgentAdapter] | None,
        profiles: Mapping[str, Sequence[str]] | None, sandbox: Sandbox | None, now: Callable[[], datetime] | None,
        confirm_wait_s: float,
    ) -> None:  # fmt: skip
        self.app, self.cfg, self.git, self.files = app, cfg, git, files
        self.found = list(found)
        self.snaps = {s.ref.id: s for _, s in self.found}
        self.providers = {s.ref.id: p for p, s in self.found}
        self._forge, self.adapters, self.profiles, self.sandbox = forge, adapters, profiles, sandbox
        self._now, self.confirm_wait_s = now or (lambda: datetime.now(UTC)), confirm_wait_s
        self.target = cfg.forge.base_branch
        self.ctxs: dict[str, _Ctx] = {}
        self.actions: list[str] = []
        self._judge_down = False  # a judge failed in this run: the plans still to review wait for a later run
        self._attempts: dict[str, int | None] = {}  # unit id -> its attempt refs on origin (None: not readable)
        self.sleep: Callable[[float], None] = time.sleep  # between the reads of a PR head the forge shows late
        self.named: frozenset[str] | None = None  # the units a `l4 run --unit` names (a read-only step)
        self.unconfirmed: str | None = None  # why the target could not be fetched: the plan files may be stale
        self._merge_not_ready: dict[str, str] = {}  # unit id -> why its merge was not ready in this step
        self._merge_heads: dict[str, str | None] = {}  # unit id -> the head that merge was not ready for
        self._head_asked: set[str] = set()  # units whose PR head the forge was asked about in this run (LOW-1)

    # --- loading ----------------------------------------------------------------------------------------------------

    def _load(self) -> None:
        self.ctxs = {}
        for file in self.files:
            if not PLAN_ID.match(file.plan_id):
                log.warning("plan file %s: %r is not a plan id, it is left alone", file.path, file.plan_id)
                continue
            store = _store(self.app, self.cfg, self.git, file.plan_id)
            read = store.read()
            self.ctxs[file.plan_id] = _Ctx(file, store, read, fold_plan(file.plan_id, read.events))

    def _file_deleted(self) -> None:
        """An activated plan (active, waiting or stopped) whose plan file is no longer on the target is stopped as
        `inputs_changed`, subject `plan`, once (R2, review #10): `l4 status` and the doctor stop counting it as
        active, and a restored file needs a new review and a new activation, the old one never revives. A plan that
        was never activated has nothing to stop."""
        ids = self.ledgers if self.ledgers is not None else _ledger_plans(self.app, self.cfg, self.git)
        for plan_id in ids:
            if plan_id in self.ctxs or not PLAN_ID.match(plan_id):
                continue
            store = _store(self.app, self.cfg, self.git, plan_id)
            try:
                read = store.read()
                state = fold_plan(plan_id, read.events)
            except ValueError as exc:  # a ledger that is no ledger: left to `l4 yolo` to report
                log.warning("plan %s: its ledger cannot be read: %s", plan_id, exc)
                continue
            gone = state.status in ("active", "waiting") or (
                state.status == "stopped" and not (state.stop_reason == "inputs_changed" and state.stop_unit == "plan")
            )
            if gone:
                ctx = _Ctx(PlanFile(plan_id, f"{PLANS_DIR}/{plan_id}.json", "", None, None), store, read, state)
                self._stop(ctx, "inputs_changed", "the plan file was deleted", "plan")

    def _states(self) -> dict[str, PlanState]:
        return {pid: c.state for pid, c in self.ctxs.items()}

    def _phases(self) -> dict[str, str | None]:
        return {uid: s.state.phase for uid, s in self.snaps.items()}

    def _at(self) -> str:
        return self._now().strftime("%Y-%m-%dT%H:%M:%SZ")

    def _event(self, kind: str, **data: object) -> PlanEvent:
        return PlanEvent(kind, self._at(), {k: v for k, v in data.items() if v is not None})

    def _line(self, plan_id: str, text: str) -> None:
        self.actions.append(f"plan {plan_id}: {text}")
        log.info("plan %s: %s", plan_id, text)

    # --- run --------------------------------------------------------------------------------------------------------

    def preview(self) -> PlanStep:
        """What `l4 run --unit` may run: the current or eligible unit of the active plan, else every unit no plan holds
        (L4-YOLO-010). Nothing is reviewed or started and no stop is recorded; only the run of the current unit is
        charged (`_charge_named_run`)."""
        if self.unconfirmed is not None:
            return self._skipped(self.unconfirmed)
        self._load()
        live = live_plan(self.files, self._states(), self.target)
        if live is None or live.plan is None:
            for (
                ctx
            ) in self.ctxs.values():  # a waiting plan whose cause is gone goes on at the next run: its unit may run
                if ctx.file.plan is not None and ctx.file.plan.target == self.target and self._cause_gone(ctx):
                    return self._previewed(ctx)
            return self._result(None, start_next_run=False)
        return self._previewed(self.ctxs[live.plan_id])

    def _previewed(self, ctx: _Ctx) -> PlanStep:
        """Only the current unit of the plan may run by name, and only while the step would let it go on: the plan file
        is the one that was activated and no limit is reached (review #11). A unit the plan has not dispatched is the
        step's to dispatch: it records the dispatch and the charge that a named run would escape."""
        why = self._preview_refusal(ctx)
        current = ctx.state.current if ctx.file.plan and ctx.state.current in ctx.file.plan.unit_ids() else None
        allow = frozenset({current}) if current and why is None else frozenset()
        tail = why or f"is not the current unit of plan {ctx.plan_id}: only the plan's step dispatches it"
        if allow and current in (self.named or ()) and not self._charge_named_run(ctx, current):
            allow, tail = frozenset(), "waits for the plan step: the charge of this run could not be recorded"
        return self._result(allow, start_next_run=False, plan_id=ctx.plan_id, reason=tail)

    def _charge_named_run(self, ctx: _Ctx, unit: str) -> bool:
        """A named run of the current unit is charged like the run of the plan step: `plan.charged` with one more run,
        so `l4 run --unit <current>` cannot escape `max_runs` (L4-YOLO-012). There is no `unit.dispatched`: the step
        did not dispatch, and a waiting plan stays waiting. Only a unit with something to run is charged. False when
        the record was not written (the ref moved twice)."""
        snap = self.snaps.get(unit)
        if snap is None or self._unit_action(snap) not in _ACTIONABLE:
            return True
        for _ in range(2):
            try:
                self._write(ctx, [self._charged(ctx, unit, snap, extra_run=1)])
            except PlanMoved:
                ctx.refresh(ctx.store.read())
                continue
            self._line(ctx.plan_id, f"{unit}: a named run, charged to the plan")
            return True
        return False

    def _preview_refusal(self, ctx: _Ctx) -> str | None:
        """Why the step would not let the current unit go on (the checks `_live` makes, none of them writes)."""
        assert ctx.file.plan is not None
        plan, state, pid = ctx.file.plan, ctx.state, ctx.plan_id
        if state.activated_digest is None or plan_digest(ctx.file.text) != state.activated_digest:
            return f"waits for the plan step: the plan file of plan {pid} changed after the activation"
        if (unit := self._inputs_changed(ctx)) is not None:
            return f"waits for the plan step: the spec of {unit} changed after the activation (plan {pid})"
        current = state.current if state.current in plan.unit_ids() else None
        blocker = unit_blocker(plan, state, current) if current else None  # an older ledger can hold a blocked one
        if blocker is not None:
            return f"waits for the plan step: {current} {blocker} (plan {pid})"
        if current and rejection_pending(ctx.read.events, current) is not None:
            return f"waits for the plan step: {current} was rejected by its last run (plan {pid})"
        if (limit := self._limit_reached(ctx, current)) is not None:
            return f"waits for the plan step: plan {pid} reached a limit ({limit[0]}: {limit[1]})"
        if pending := merged_not_integrated(plan, state, self._phases()):
            return f"waits for the post-merge check of {pending[0]} (plan {pid})"
        return None

    def _skipped(self, why: str) -> PlanStep:
        """No plan step in this run, and nothing written to a plan ledger. The target could not be fetched, so the plan
        files may be old and no ledger can be read from origin: what the clone last fetched decides. While a plan
        file's ledger says the plan is open (active, waiting or stopped) no unit runs; else the units the plan files
        list stay held and the units that no plan lists run, as they do when the step fails (`failed_plan_step`)."""
        log.warning("no plan step in this run: %s", why)
        extra = (f"plan step skipped: {why}",)
        if not self.files:  # this clone sees no plan file: the ledgers it holds say whether a plan is still open
            try:
                if not self._open_plan_in_clone():
                    return PlanStep(allow=None, actions=extra)  # no plan lists a unit: the units run as ever
            except Exception as exc:  # noqa: BLE001 - the ledgers cannot be read: no unit runs
                log.warning("plan step skipped: the plan ledgers cannot be read (%s)", type(exc).__name__)
            return self._result(frozenset(), start_next_run=False, extra=extra, reason=why)
        try:
            held = holds_of({}, self.files).held
            open_plan = any(
                (read := _store(self.app, self.cfg, self.git, f.plan_id).read_local()) is not None
                and fold_plan(f.plan_id, read.events).status in ("active", "waiting", "stopped")
                for f in self.files
                if f.plan is not None and f.plan.target == self.target and PLAN_ID.match(f.plan_id)
            )
        except Exception as exc:  # noqa: BLE001 - the holds cannot be known: no unit runs
            log.warning("plan step skipped: the plan files or ledgers cannot be read (%s)", type(exc).__name__)
            return self._result(frozenset(), start_next_run=False, extra=extra, reason=why)
        if open_plan:
            return self._result(frozenset(), start_next_run=False, extra=extra, reason=why)
        return self._result(
            frozenset(u for u in self.snaps if u not in held), start_next_run=False, extra=extra, reason=why
        )

    def _open_plan_in_clone(self) -> bool:
        """Whether a plan ref this clone holds (`refs/l4/plans/*`, no network) has a ledger that is active, waiting or
        stopped, or cannot be read."""
        refs = self.git.run("for-each-ref", "--format=%(refname)", PLAN_REF_PREFIX).stdout.split()
        for ref in refs:
            plan_id = ref.removeprefix(PLAN_REF_PREFIX)
            if not PLAN_ID.match(plan_id):
                continue
            read = _store(self.app, self.cfg, self.git, plan_id).read_local()
            if read is None or fold_plan(plan_id, read.events).status in ("active", "waiting", "stopped"):
                return True
        return False

    def run(self) -> PlanStep:
        if self.unconfirmed is not None:
            return self._skipped(self.unconfirmed)
        for attempt in (1, 2):
            try:
                self._load()
                self.actions = []
                self._merge_not_ready, self._merge_heads, self._head_asked = {}, {}, set()
                self._file_deleted()
                if not self.files:  # every plan file is gone: the units are ordinary units again
                    return PlanStep(allow=None, actions=tuple(self.actions))
                self._rejected_fixed()
                done = self._reviews()
                if done is not None:
                    return done
                self._wake()
                live = live_plan(self.files, self._states(), self.target)
                if live is not None and live.plan_id in self.ctxs:
                    return self._live(self.ctxs[live.plan_id])
                stopped = self._file_changed()
                if stopped is not None:
                    return stopped
                return self._result(None, start_next_run=False)
            except PlanMoved:
                log.info("the plan ref moved (attempt %d): reading it again", attempt)
            except RevisionMissing as exc:
                log.warning("no plan step in this run: %s", exc)
                return self._result(frozenset(), start_next_run=False, extra=(f"plan step skipped: {exc}",))
        log.warning("the plan ref moved twice: no plan step in this run")
        return self._result(frozenset(), start_next_run=False, extra=("plan step skipped: the plan ref moved twice",))

    def _result(
        self, allow: frozenset[str] | None, *, start_next_run: bool, plan_id: str | None = None,
        extra: Sequence[str] = (), reason: str | None = None,
    ) -> PlanStep:  # fmt: skip
        """`allow` None: every unit that no plan holds (and, while a plan is active, none unless the step names it)."""
        states = self._states()
        holds = plan_holds(self.files, states, self._phases(), self.target)
        live = live_plan(self.files, states, self.target)
        if allow is None:
            allow = frozenset(u for u in self.snaps if u not in holds)
        refusals = {}
        for unit in self.snaps:
            if unit in allow:
                continue
            if unit in holds:
                refusals[unit] = holds[unit].refusal
            else:
                refusals[unit] = (
                    reason or f"waits for the plan step of this run (plan {live.plan_id if live else plan_id})"
                )
        pending = frozenset(
            ctx.state.current
            for ctx in self.ctxs.values()
            if ctx.state.current and not_started_pending(ctx.read.events, ctx.state.current) is not None
        )  # what the step read: the run clears these without reading the plan ledger again
        return PlanStep(
            allow=allow, actions=(*self.actions, *extra), start_next_run=start_next_run,
            plan_id=plan_id or (live.plan_id if live else None), refusals=refusals, pending_starts=pending,
        )  # fmt: skip

    # --- writing ----------------------------------------------------------------------------------------------------

    def _write(
        self, ctx: _Ctx, events: Sequence[PlanEvent], *, files: Mapping[str, str] | None = None,
        receipt: Mapping[str, object] | None = None, facts: bool = False,
    ) -> None:  # fmt: skip
        """One leased commit on the ref. `facts`: the events record something that already happened (a push), so a lost
        lease reads again and appends once more instead of ending the step."""
        for attempt in (1, 2, 3):
            try:
                if receipt is not None:
                    head = ctx.store.write_receipt(receipt, expect=ctx.read.head, events=events)
                else:
                    head = ctx.store.append(events, files=files, expect=ctx.read.head)
                break
            except PlanMoved:
                if not facts or attempt == 3:
                    raise
                ctx.refresh(ctx.store.read())
        else:  # pragma: no cover - the loop returns or raises
            raise PlanMoved(ctx.store.ref)
        read = ctx.store.read() if receipt is not None else None
        ctx.refresh(
            read or PlanRead(head, [*ctx.read.events, *events], {**ctx.read.files, **(dict(files) if files else {})})
        )

    def _repository(self) -> str:
        url = origin_url(self.app.repo, self.app.environ) or "unknown"
        return self.app.redactor.redact_text(_USERINFO.sub("", url))

    def _fetch_target(self) -> str | None:
        """The target tip, fetched into `refs/remotes/origin/<target>` so that it can be checked out and described."""
        spec = f"+refs/heads/{self.target}:refs/remotes/origin/{self.target}"
        try:
            self.git.fetch("origin", refspecs=(spec,), config=fetch_auth_config(self.cfg, self.app.environ))
        except GitError as exc:
            log.warning("the target %s could not be fetched: %s", self.target, fetch_cause(self.app, exc))
            return None
        return self.git.rev_parse(f"refs/remotes/origin/{self.target}")

    def _target_rev(self) -> str:
        return self.git.rev_parse(f"refs/remotes/origin/{self.target}") or "HEAD"

    def _target_ref(self) -> str:
        """The target as a revision name: the tracking ref, else the checkout (CI checks out the target head)."""
        ref = f"refs/remotes/origin/{self.target}"
        return ref if self.git.rev_parse(ref) else "HEAD"

    def _digest(self, unit: str, folder: str) -> str:
        """The digest of a unit now: on its branch when it has one on origin, else on the target (D3, R3)."""
        try:
            return current_unit_digest(self.git, self.cfg, unit, folder, self._target_ref())
        except FolderMissing:  # the folder is gone: it equals no digest, so it reads as a change (review #4)
            return MISSING

    def _report(self, ctx: _Ctx, events: Sequence[PlanEvent]) -> str:
        assert ctx.file.plan is not None
        state = fold_plan(ctx.plan_id, [*ctx.read.events, *events])
        revision = self._fetch_target() or self.git.rev_parse(f"refs/remotes/origin/{self.target}")
        units: dict[str, UnitState] = {uid: s.state for uid, s in self.snaps.items()}
        return render_report(
            repository=self._repository(), plan=ctx.file.plan, state=state, events=[*ctx.read.events, *events],
            target_revision=revision, units=units, generated_at=self._at(),
        )  # fmt: skip

    def _with_report(self, ctx: _Ctx, events: Sequence[PlanEvent]) -> None:
        if ctx.file.plan is None:  # a file that is no plan has nothing to report on: only the stop is recorded
            self._write(ctx, events, facts=True)
            return
        text = self._report(ctx, events)
        self._write(ctx, events, files={"report.md": text}, facts=True)
        out = self.app.out_dir / "yolo" / f"{ctx.plan_id}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")

    def _live_charge(self, ctx: _Ctx, unit: str | None) -> list[PlanEvent]:
        """The `plan.charged` of the unit's current attempt, when the ledger does not hold its live figures yet (R1,
        R3): the cost its ledger shows now and its attempt. Every stop writes it before `plan.stopped`, so the plan
        ledger holds what the step read, whatever a `l4 restart` does to the unit's own ledger afterwards."""
        snap = self.snaps.get(unit) if unit else None
        if unit is None or snap is None or unit in ctx.state.integrated or not is_unit_key(unit):
            return []
        charge = self._charged(ctx, unit, snap)
        attempt, cost = int(charge.data["attempt"]), float(charge.data["cost_usd"])
        if ctx.state.used.attempts.get(unit, 0) >= attempt and cost <= self._charged_of(ctx, unit, attempt)[0]:
            return []
        return [charge]

    def _stop(
        self, ctx: _Ctx, reason: str, detail: str | None = None, unit: str | None = None,
        before: Sequence[PlanEvent] = (), charge: str | None = None, digest: str | None = None,
    ) -> PlanStep:  # fmt: skip
        """`plan.stopped`, after the live charge of `charge` (default: the plan's current unit) and the events `before`.
        `digest`: the spec digest of the stop's unit when the stop depends on it (`unit_rejected`, R8)."""
        shown = self.app.redactor.redact_text(detail) if detail else None
        stopped = self._event("plan.stopped", reason=reason, detail=shown, unit=unit, digest=digest)
        self._with_report(ctx, [*self._live_charge(ctx, charge or ctx.state.current), *before, stopped])
        self._line(ctx.plan_id, f"stopped ({reason}{f', {unit}' if unit else ''}){f': {shown}' if shown else ''}")
        return self._result(frozenset(), start_next_run=False, plan_id=ctx.plan_id)

    def _after_review(self, ctx: _Ctx, *, start_next_run: bool = False) -> PlanStep:
        """The step was a review (or a refusal): one plan step per run, so while another plan is active nothing of it
        is dispatched in this run. That plan goes on in the next run, which this run asks for (R9)."""
        live = live_plan(self.files, self._states(), self.target)
        return self._result(
            frozenset() if live is not None else None,
            start_next_run=start_next_run or live is not None,
            plan_id=ctx.plan_id,
        )

    # --- 1. reviews -------------------------------------------------------------------------------------------------

    def _reviews(self) -> PlanStep | None:
        for ctx in self.ctxs.values():
            step = self._review(ctx)
            if step is not None:
                return step
        return None

    def _reviewable(self, state: PlanState) -> bool:
        if state.status in _BEFORE_ACTIVATION:
            return True
        return state.status == "stopped" and state.stop_reason == "inputs_changed"

    def _review(self, ctx: _Ctx) -> PlanStep | None:
        file, state = ctx.file, ctx.state
        if not self._reviewable(state):
            return None
        digest = plan_digest(file.text)
        if file.plan is None:
            assert file.invalid is not None
            last = _last(ctx.read.events, "plan.refused")
            if last is not None and last.data.get("plan_digest") == digest:
                return None
            findings = [{"code": "invalid", "subject": ctx.plan_id, "text": e} for e in file.invalid.errors]
            self._write(ctx, [self._event("plan.refused", plan_digest=digest, findings=findings)])
            self._line(ctx.plan_id, f"refused: {'; '.join(file.invalid.errors)}")
            return self._after_review(ctx)
        plan = file.plan
        if self._judge_down:
            return None
        rev = self._target_rev()
        folders = unit_infos(self.app.repo, self.found, plan.unit_ids(), check_intake=False)
        current = {u: self._digest(u, i.folder) for u, i in folders.items()}
        if self._reviewed_current(state, digest, current):
            return None
        infos = unit_infos(self.app.repo, self.found, plan.known_ids())
        held = {unit: pid for unit, (pid, _) in holds_of(self._states(), self.files).held.items()}
        admission = admit(
            plan,
            known_units=infos,
            cfg=self.cfg,
            held=held,
            state=state,
            archived=archived_at(self.git, rev, self.cfg),
        )
        if not admission.ok:
            findings = [{"code": f.code, "subject": f.subject, "text": f.text} for f in admission.findings]
            last = _last(ctx.read.events, "plan.refused")
            if state.status == "refused" and last is not None and last.data.get("findings") == findings:
                return None
            self._write(ctx, [self._event("plan.refused", plan_digest=digest, findings=findings)])
            self._line(ctx.plan_id, f"refused: {len(findings)} finding(s): {findings[0]['text']}")
            return self._after_review(ctx)
        try:
            result, cost = review_plan_costed(
                self.app,
                self.cfg,
                plan,
                infos,
                git=self.git,
                rev=rev,
                adapters=self.adapters,
                sandbox=self.sandbox,
                done=done_units(plan, state),
            )
        except (RoleLimit, RoleUnavailable) as exc:  # `JudgeFailed` is a `RoleUnavailable`: nothing is recorded (R9)
            reason = self.app.redactor.redact_text(str(exc) or type(exc).__name__).splitlines()[0][:200]
            self._line(ctx.plan_id, f"the review waits, no judge could run ({reason}); a later run tries again")
            self._judge_down = True  # no other plan goes to the judge in this run; the active plan goes on (review #4)
            return None
        events = []
        order = list(admission.order)
        if not (state.status in ("admitted", "reviewed") and state.plan_digest == digest and state.order == order):
            events.append(self._event("plan.admitted", plan_digest=digest, order=order, merge=plan.merge))
        units = {
            uid: {"verdict": v.verdict, "digest": v.digest, "findings": list(v.findings)}
            for uid, v in result.units.items()
        }
        batches = {
            bid: {"verdict": v.verdict, "findings": list(v.findings)} for bid, v in review_batches(plan, result).items()
        }
        events.append(
            self._event(
                "plan.reviewed", plan_digest=digest, prompt_version=PROMPT_VERSION, units=units, batches=batches
            )
        )
        if cost > 0:
            total = cost + max(
                (float(e.data.get("cost_usd") or 0) for e in ctx.read.events
                 if e.type == "plan.charged" and e.data.get("unit") == REVIEW_KEY),
                default=0.0,
            )  # fmt: skip
            events.append(self._event("plan.charged", unit=REVIEW_KEY, attempt=0, cost_usd=round(total, 6), runs=0))
        self._write_review(ctx, events, digest)
        verdicts = ", ".join(f"{u}={v.verdict}" for u, v in result.units.items())
        self._line(ctx.plan_id, f"reviewed ({verdicts})")
        return self._after_review(ctx)

    def _write_review(self, ctx: _Ctx, events: Sequence[PlanEvent], digest: str) -> None:
        """The review is paid for: when the lease is lost, the ref is read again and the same facts are appended once
        more, with no second judge call, unless the plan moved in a way that makes this review stale (another review,
        refusal or admission, a new plan digest, or a plan that can no longer be reviewed) (review #16)."""
        try:
            self._write(ctx, events)
        except PlanMoved:
            seen = len(ctx.read.events)
            fresh = ctx.store.read()
            ctx.refresh(fresh)
            since = fresh.events[seen:]
            newer = any(
                e.type in ("plan.reviewed", "plan.refused")
                or (e.type == "plan.admitted" and e.data.get("plan_digest") != digest)
                for e in since
            )
            if newer or not self._reviewable(ctx.state):
                log.info("plan %s: the ref moved during the review and the review is stale: it is dropped", ctx.plan_id)
                raise
            self._write(ctx, events, facts=True)

    @staticmethod
    def _reviewed_current(state: PlanState, digest: str, current: Mapping[str, str]) -> bool:
        if state.review_plan_digest != digest or not state.review or state.review_prompt_version != PROMPT_VERSION:
            return False  # a review made with an older review prompt is stale (L4-YOLO-004)
        return all(state.review_digests.get(unit) == value for unit, value in current.items())

    # --- 2. the active plan -----------------------------------------------------------------------------------------

    # --- attempts, limits (R1, R3) ----------------------------------------------------------------------------------

    def _attempt(self, ctx: _Ctx, snap: UnitSnapshot) -> int:
        """The attempt the unit is on in this plan: `limits.live_attempt` of the unit's attempt refs on origin (`l4
        restart` keeps each old head there, R1) less the refs it had at the activation (R13). When origin cannot be
        asked, the highest attempt already charged stands: an attempt number never goes down."""
        unit = snap.ref.id
        if unit not in self._attempts:
            self._attempts[unit] = attempt_refs(self.git, unit, fetch_auth_config(self.cfg, self.app.environ))
        return live_attempt(ctx.state, unit, self._attempts[unit])

    @staticmethod
    def _charged_of(ctx: _Ctx, unit: str, attempt: int) -> tuple[float, int]:
        """The cost and the runs `plan.charged` already holds for one attempt of a unit (the fold's maximum)."""
        return charged_of(ctx.read.events, unit, attempt)

    def _limit_state(self, ctx: _Ctx, unit: str | None) -> PlanState:
        """The folded state with what `unit` has used and the ledger does not hold yet: the cost its ledger shows now
        and the attempt it is on (`limits.live_state`, the figures `l4 yolo resume` and `status` read too). Only that
        unit runs (the plan is serial), and its charge is written at its next dispatch, integration or stop."""
        snap = self.snaps.get(unit) if unit else None
        if unit is None or snap is None:
            return ctx.state
        return live_state(ctx.state, ctx.read.events, unit, self._attempt(ctx, snap), snap.state.cost_usd)

    def _limit_reached(self, ctx: _Ctx, unit: str | None) -> tuple[str, str, str | None] | None:
        """(stop reason, detail, unit) of the first limit reached (D11, R3): `limits.reached_at` on the state."""
        assert ctx.file.plan is not None
        return reached_at(
            self._limit_state(ctx, unit),
            now=self._now(),
            fallback=ctx.file.plan.limits.model_dump(mode="json"),
            units=ctx.file.plan.unit_ids(),
        )

    def _inputs_changed(self, ctx: _Ctx) -> str | None:
        """The first plan unit, not integrated and not merged, whose folder differs from its digest frozen at the
        activation. A unit is read on its branch when it has one, else at the target head (D3, R3)."""
        assert ctx.file.plan is not None
        state = ctx.state
        pending = [u for u in ctx.file.plan.unit_ids() if u not in state.integrated and state.digests.get(u)]
        infos = unit_infos(self.app.repo, self.found, pending, check_intake=False)
        for unit in pending:
            snap, info = self.snaps.get(unit), infos.get(unit)
            if snap is None or info is None or unit in state.merged or snap.state.phase in FINISHED_PHASES:
                continue
            if self._digest(unit, info.folder) != state.digests[unit]:
                return unit
        return None

    def _file_changed(self) -> PlanStep | None:
        """An active plan that `live_plan` does not pick because its file is no longer a plan, or no longer aims at this
        target (R2): stopped as `inputs_changed`, subject `plan`. A valid file on this target is checked in `_live`."""
        for ctx in self.ctxs.values():
            if ctx.state.status != "active":
                continue
            if ctx.file.plan is None:
                detail = f"the plan file {ctx.file.path} is no longer a valid plan"
            elif ctx.file.plan.target != self.target and plan_digest(ctx.file.text) != ctx.state.activated_digest:
                detail = f"the plan file {ctx.file.path} changed after the activation"
            else:
                continue
            return self._stop(ctx, "inputs_changed", detail, "plan")
        return None

    def _unit_action(self, snap: UnitSnapshot) -> str:
        from l4.planner import facts_of, next_action  # the planner is imported late: it imports this module

        return next_action(facts_of(snap))[0]

    def _live(self, ctx: _Ctx) -> PlanStep:
        assert ctx.file.plan is not None
        plan, state = ctx.file.plan, ctx.state
        if remote_tip(self.git, self.cfg, self.app.environ, self.target) is None:
            return self._stop(ctx, "target_missing", f"the target branch {self.target} does not exist on origin")
        if state.activated_digest is not None and plan_digest(ctx.file.text) != state.activated_digest:
            return self._stop(
                ctx, "inputs_changed", f"the plan file {ctx.file.path} changed after the activation", "plan"
            )
        if (unit := self._inputs_changed(ctx)) is not None:
            return self._stop(ctx, "inputs_changed", f"the spec of {unit} changed after the activation", unit)
        current = state.current if state.current in plan.unit_ids() else None  # a unit out of the plan is nobody's
        if (limit := self._limit_reached(ctx, current)) is not None:
            return self._stop(ctx, limit[0], limit[1], limit[2])
        snap = self.snaps.get(current) if current else None
        if current and snap is None and self._archived(ctx, current) is None:
            return self._stop(ctx, "unit_missing", f"{current} is not among the units of the target", current)
        if current and snap is not None:
            phase = snap.state.phase or ""
            if phase == "rejected" or rejection_pending(ctx.read.events, current) is not None:
                return self._rejected(ctx, snap)
            if phase in STOPPED_PHASES:
                return self._stop(ctx, f"unit_{phase}", snap.state.halt_detail or snap.state.halt_reason, current)
            ended = not_started_pending(ctx.read.events, current)
            if ended is not None and self._unit_action(snap) in _ACTIONABLE:
                return self._not_started(ctx, snap, ended)
            if phase not in FINISHED_PHASES and phase in WAIT_PHASES and self._unit_action(snap) not in _ACTIONABLE:
                return self._wait(ctx, phase, current, snap)
        pending = merged_not_integrated(plan, state, self._phases())  # R10: every merged unit is post-checked first
        for unit in pending:
            merged = self.snaps.get(unit) or self._archived(ctx, unit)  # moved to the archive after its merge (#3)
            if merged is None:
                return self._stop(ctx, "unit_missing", f"{unit} is not among the units of the target", unit)
            return self._integrate(ctx, unit, merged, via_merge=None)
        if current and snap is not None and (snap.state.phase or "") == "in_review" and plan.merge == "auto":
            step = self._merge(ctx, snap)
            if step is not None:
                return step
        batch = self._batch(ctx)
        if batch is not None:
            return batch
        if self._complete(ctx):
            return self._completed(ctx)
        return self._dispatch(ctx)

    def _archived(self, ctx: _Ctx, unit: str) -> UnitSnapshot | None:
        """A stand-in snapshot for a plan unit the providers no longer list (its folder moved to the archive) that the
        ledger has merged and whose merged head is in the target: it is post-checked and integrated like any merged
        unit. None for a unit that is not merged, or whose head the target does not hold (review #3)."""
        head = ctx.state.merged.get(unit)
        if not head:
            return None
        tip = remote_tip(self.git, self.cfg, self.app.environ, self.target)
        if tip is None or (tip != head and not _is_ancestor(self.git, self.cfg, self.app.environ, head, tip)):
            return None
        try:
            framework, name = parse_unit_id(unit)
        except ValueError:
            return None
        return UnitSnapshot(
            ref=UnitRef(framework, name, self.app.repo), state=UnitState(unit=unit, phase="archived"), tasks=[],
            source="archive",
        )  # fmt: skip

    def _adoptable(self, snap: UnitSnapshot) -> bool:
        """A unit that is past implementation with nothing for an agent to do: in review with a PASS verdict. The plan
        adopts it as its current unit (review #2)."""
        verdict = snap.state.last_verdict
        return (snap.state.phase or "") == "in_review" and verdict is not None and verdict.verdict == "PASS"

    def _rejected(self, ctx: _Ctx, snap: UnitSnapshot) -> PlanStep:
        """The current unit is `rejected` (R8). The stop records the spec digest the unit was rejected at. `retry`
        never moves a rejected unit (`retry.refuse`), so the step does not ask it: the person fixes the cause.
        A corrected spec: the next run records `inputs_changed`, CI reviews, `l4 yolo activate` freezes the new digest.
        A corrected configuration: `l4 yolo activate` alone (`rejection_pending` ends at an activation). Then the
        unit's own next run reads it (L4-YOLO-012). That run is dispatched here, with its charge, once per
        activation; a unit that is still rejected after it stops the plan again."""
        unit, state = snap.ref.id, ctx.state
        rejections = [
            e for e in ctx.read.events
            if e.type == "plan.stopped" and e.data.get("reason") == "unit_rejected" and e.data.get("unit") == unit
        ]  # fmt: skip
        seen = rejections[-1].data.get("digest") if rejections else None
        now = state.digests.get(unit)
        if seen is not None and seen != now and not self._dispatched_since_activation(ctx, unit):
            self._write(ctx, self._dispatch_events(ctx, unit, snap))
            self._line(ctx.plan_id, f"{unit}: its spec was fixed after it was rejected, its next run reads it")
            return self._result(frozenset({unit}), start_next_run=True, plan_id=ctx.plan_id)
        refused = rejection_pending(ctx.read.events, unit)  # the reasons its own run gave (no phase records them)
        detail = (str(refused.data.get("detail") or "") if refused else "") or snap.state.halt_detail
        detail = detail or snap.state.halt_reason
        if seen is not None and seen != now:
            detail = (
                f"{unit} is still rejected after its spec was fixed: fix the cause (its spec or the configuration), "
                f"or run l4 restart --unit {unit} --reason TEXT, then l4 yolo resume {ctx.plan_id} --reason TEXT"
            )
        return self._stop(ctx, "unit_rejected", detail, unit, digest=now)

    @staticmethod
    def _dispatched_since_activation(ctx: _Ctx, unit: str) -> bool:
        """True when `unit.dispatched` for `unit` is on the ledger after the latest `plan.activated`."""
        for event in reversed(ctx.read.events):
            if event.type == "plan.activated":
                return False
            if event.type == "unit.dispatched" and event.data.get("unit") == unit:
                return True
        return False

    def _rejected_fixed(self) -> None:
        """A plan stopped with `unit_rejected` whose unit now has another spec digest than the one it was rejected at:
        the person fixed it, so the plan is stopped again as `inputs_changed{unit}`. CI then reviews the plan again, and
        a person activates it again (R8)."""
        for ctx in list(self.ctxs.values()):
            state = ctx.state
            if state.status != "stopped" or state.stop_reason != "unit_rejected" or not state.stop_unit:
                continue
            if ctx.file.plan is None or ctx.file.plan.target != self.target:
                continue
            unit = state.stop_unit
            info = unit_infos(self.app.repo, self.found, [unit], check_intake=False).get(unit)
            stopped = _last(ctx.read.events, "plan.stopped", unit)
            seen = (stopped.data.get("digest") if stopped is not None else None) or state.digests.get(unit)
            if info is not None and seen is not None and self._digest(unit, info.folder) != seen:
                self._stop(ctx, "inputs_changed", f"the spec of {unit} changed after it was rejected", unit)

    def _cause_gone(self, ctx: _Ctx) -> str | None:
        """For a waiting plan: why it may go on (`the cause is gone: <unit> is <phase>`), None while its current unit
        still waits for a person or for capacity with nothing to run. The unit's phase and next action are read again
        here, so an answered question or a capacity that is back wakes the plan without a person."""
        state = ctx.state
        if state.status != "waiting":
            return None
        unit = state.current
        if state.wait_reason == MERGE_NOT_READY:
            return self._merge_wait_gone(ctx, unit)
        if state.wait_reason == RUN_NOT_STARTED:
            # (`unit_not_started`, the wait of a unit with nothing to run, is not this one: it is read below, as ever)
            if unit is None or not_started_pending(ctx.read.events, unit) is None:
                return "the cause is gone: a run started the unit, or the plan was activated or resumed since"
            return "the cause is gone: this trigger runs the unit"  # the wait ends so that the step runs it
        if unit is None and ctx.file.plan is not None:  # waiting on the unit the plan would dispatch (review #2)
            unit = next_eligible(ctx.file.plan, state, self._phases()).unit
            nxt = self.snaps.get(unit) if unit else None
            if nxt is not None and self._unit_action(nxt) not in _ACTIONABLE and not self._adoptable(nxt):
                return None
        snap = self.snaps.get(unit) if unit else None
        if snap is None:
            return f"the cause is gone: {unit or 'the current unit'} is not among the units of the target"
        phase = snap.state.phase or ""
        if phase in WAIT_PHASES and phase not in FINISHED_PHASES and self._unit_action(snap) not in _ACTIONABLE:
            return None
        return f"the cause is gone: {unit} is {phase or 'not started'}"

    def _wake(self) -> None:
        """A waiting plan on this target whose cause is gone records `plan.resumed{by: harness}` and the step goes on
        in the same run (D10, the orchestrator's decision on the docs: the plan continues by itself)."""
        for ctx in list(self.ctxs.values()):
            if ctx.file.plan is None or ctx.file.plan.target != self.target:
                continue
            why = self._cause_gone(ctx)
            if why is None:
                continue
            self._write(ctx, [self._event("plan.resumed", by="harness", reason=why)])
            self._line(ctx.plan_id, f"resumed: {why}")

    def _wait(self, ctx: _Ctx, phase: str, unit: str, snap: UnitSnapshot) -> PlanStep:
        from l4.planner import facts_of, next_action

        detail = next_action(facts_of(snap))[1]
        reason = f"unit_{phase}"
        self._write(ctx, [self._event("plan.waiting", reason=reason, unit=unit, detail=detail)])
        self._line(ctx.plan_id, f"waiting ({reason}, {unit}): {detail}")
        return self._result(frozenset({unit}), start_next_run=False, plan_id=ctx.plan_id)

    def _not_started(self, ctx: _Ctx, snap: UnitSnapshot, ended: PlanEvent) -> PlanStep:
        """The last run of the current unit ended before it started the unit (L4-YOLO-013). The plan waits with
        `run_not_started` and the run's exit and reason on record, once per failed run, and chains no run: the next
        trigger (cron or push) runs the unit again, once. This run still runs it, and is charged like a dispatch, so
        `max_runs` bounds a unit that never starts. A run that starts the unit clears the wait (`record_run_starts`)."""
        unit = snap.ref.id
        recorded = next(
            (
                e for e in reversed(ctx.read.events)
                if e is ended or (e.type == "plan.waiting" and e.data.get("reason") == RUN_NOT_STARTED)
            ),
            None,
        )  # fmt: skip
        events = [self._charged(ctx, unit, snap, extra_run=1)]
        if recorded is ended:
            detail = (
                f"its run {ended.data.get('run')} ended before it started the unit "
                f"(exit {ended.data.get('exit')}): {ended.data.get('detail')}"
            )
            events.insert(0, self._event("plan.waiting", reason=RUN_NOT_STARTED, unit=unit, detail=detail[:400]))
            self._line(ctx.plan_id, f"waiting ({RUN_NOT_STARTED}, {unit}): {detail}")
        self._write(ctx, events)
        return self._result(frozenset({unit}), start_next_run=False, plan_id=ctx.plan_id)

    def _wait_merge(self, ctx: _Ctx, unit: str) -> PlanStep:
        """The current unit is in review with a PASS and its merge is not ready (no open PR, a PR aimed at another
        branch, a PR head that differs from the branch tip, ...): nothing but a person changes that, so the plan waits
        with `merge_not_ready` and the detail on record, once. `_cause_gone` wakes it when the merge changes."""
        detail = self._merge_not_ready[unit]
        head = self._merge_heads.get(unit)  # recorded: the next runs ask the forge about this head once, not again
        self._write(ctx, [self._event("plan.waiting", reason=MERGE_NOT_READY, unit=unit, detail=detail, head=head)])
        self._line(ctx.plan_id, f"waiting ({MERGE_NOT_READY}, {unit}): {detail}")
        return self._result(frozenset({unit}), start_next_run=False, plan_id=ctx.plan_id)

    def _merge_wait_gone(self, ctx: _Ctx, unit: str | None) -> str | None:
        """Why a plan waiting with `merge_not_ready` may go on, None while the merge is not ready for the same reason
        (the detail on record). The unit leaves review or has work to do again: gone. Else the merge guard is asked
        without a push (`before_push` answers no): the detail it gives now is compared with the recorded one."""
        snap = self.snaps.get(unit) if unit else None
        if snap is None:
            return f"the cause is gone: {unit or 'the current unit'} is not among the units of the target"
        phase = snap.state.phase or ""
        if phase != "in_review" or self._unit_action(snap) in _ACTIONABLE:
            return f"the cause is gone: {unit} is {phase or 'not started'}"
        waiting = _last(ctx.read.events, "plan.waiting", unit)
        recorded = str(waiting.data.get("detail") or "") if waiting is not None else ""
        try:
            probe = merge_guarded(
                self.app, self.cfg, self.git, self._forge_for_merge(), snap, before_push=lambda _: False,
                sleep=self.sleep, **self._reread(ctx, unit),
            )  # fmt: skip
        except (ForgeError, ForgeUnavailable, GitError) as exc:
            log.info("%s: the merge could not be asked about: %s", unit, exc)
            return None
        if probe.status == "not_ready" and probe.detail != NO_LONGER_ALLOWED and probe.detail == recorded:
            return None
        if probe.status == "not_ready" and probe.detail != NO_LONGER_ALLOWED:
            return f"the cause is gone: the merge of {unit} is not ready for another reason ({probe.detail})"
        return f"the cause is gone: the merge of {unit} can go on"

    # --- the guarded merge, post-merge profile, batches, completion ------------------------------------------------

    def _reread(self, ctx: _Ctx, unit: str | None) -> dict[str, object]:
        """How `merge_guarded` may ask the forge again for a PR head that differs from the branch tip (LOW-1): only
        in the run that would record the wait for the first time, so not in a preview, not in a run where the wait of
        this unit and head is on record (the latest wait with its `head`; an older ledger has none, so it is asked
        once more and recorded with it), and once per unit in a run."""
        waiting = _last(ctx.read.events, "plan.waiting", unit)
        recorded = waiting.data.get("head") if waiting and waiting.data.get("reason") == MERGE_NOT_READY else None
        first = unit is not None and unit not in self._head_asked and self.named is None
        if unit is not None:
            self._head_asked.add(unit)
        return {"reread": first, "waited_head": str(recorded) if recorded else None}

    def _forge_for_merge(self) -> Forge:
        return self._forge or make_forge(self.cfg, self.app.environ, repo=self.app.repo)

    def _merge(self, ctx: _Ctx, snap: UnitSnapshot) -> PlanStep | None:
        """D8 and D9 in one step. None: the unit is not ready to merge, the step goes on to the dispatch."""
        unit = snap.ref.id
        verdict = snap.state.last_verdict
        if verdict is None or verdict.verdict != "PASS":
            return None
        assert ctx.file.plan is not None
        if (why := unit_blocker(ctx.file.plan, ctx.state, unit)) is not None:  # never out of order (review z1, H2)
            self._line(ctx.plan_id, f"{unit} is not merged: it {why}")
            return None
        if self.cfg.forge.merge_policy != "auto":
            return self._stop(ctx, "merge_refused", "forge.merge_policy is not auto", unit)
        try:
            forge = self._forge_for_merge()
        except ForgeUnavailable as exc:
            return self._stop(ctx, "merge_refused", f"no forge to ask: {exc}", unit)
        out = merge_guarded(
            self.app, self.cfg, self.git, forge, snap, sleep=self.sleep, **self._reread(ctx, unit),
            before_push=lambda to_be: self._merge_requested(ctx, unit, to_be),
        )  # fmt: skip
        if out.status == "not_ready":
            if out.detail == NO_LONGER_ALLOWED:  # the plan, read again under the lease, is not active (R5)
                ctx.refresh(ctx.store.read())
                self._line(ctx.plan_id, f"{unit} is not merged: {NO_LONGER_ALLOWED}")
                return self._result(frozenset(), start_next_run=False, plan_id=ctx.plan_id)
            if "does not exist on origin" in out.detail:
                return self._stop(ctx, "target_missing", out.detail)
            self._line(ctx.plan_id, f"{unit} is not ready to merge: {out.detail}")
            self._merge_not_ready[unit] = out.detail
            self._merge_heads[unit] = out.head
            return None
        if out.status == "refused":
            return self._stop(ctx, "merge_refused", out.detail, unit)
        if out.status == "stale":
            return self._stale(ctx, snap, out.detail)
        assert out.head is not None and out.pr is not None
        if not confirm_merged(forge, self.git, self.cfg, out.pr, out.head, wait_s=self.confirm_wait_s):
            log.warning("%s: %s was pushed to %s, but the target does not show it as its tip", unit, out.head[:10],
                        self.target)  # fmt: skip
        merged = [self._event("unit.merged", unit=unit, head=out.head, pr=out.pr, merge_commit=out.head)]
        self._write(ctx, merged, facts=True)
        self._line(ctx.plan_id, f"{unit} merged into {self.target} at {out.head[:10]}")
        return self._integrate(ctx, unit, snap, via_merge=out.head)

    def _merge_requested(self, ctx: _Ctx, unit: str, to_be: MergeOutcome) -> bool:
        """The `before_push` of the guarded merge (D8, R5): read the plan ref again and push only while the plan is
        still active on this unit; record `unit.merge_requested` with the lease first, so a plan cancelled or stopped
        after the step read it never merges, and a push that happens is always preceded by its request. A lost lease
        answers False: the next run decides again."""
        fresh = ctx.store.read()
        state = fold_plan(ctx.plan_id, fresh.events)
        if state.status != "active" or state.current not in (None, unit):
            return False
        request = self._event("unit.merge_requested", unit=unit, head=to_be.head, target_before=to_be.target_before,
                              pr=to_be.pr)  # fmt: skip
        try:
            head = ctx.store.append([request], expect=fresh.head)
        except PlanMoved:
            return False
        ctx.refresh(PlanRead(head, [*fresh.events, request], dict(fresh.files)))
        return True

    def _stale(self, ctx: _Ctx, snap: UnitSnapshot, detail: str) -> PlanStep:
        from l4.state.retry import retry_unit  # retry imports the orchestrator, which imports this module

        unit = snap.ref.id
        if ctx.state.stale_merges.get(unit, 0) >= 1:
            return self._stop(ctx, "merge_refused", f"the target moved again after a retry: {detail}", unit)
        reason = f"the target moved; verify again (plan {ctx.plan_id})"
        try:
            result = retry_unit(self.app, self.cfg, self.git, self.providers[unit], snap.ref, reason=reason, by="plan")
        except L4Exit as exc:
            self._line(ctx.plan_id, f"{unit}: the target moved, the retry was refused: {exc}")
            return self._result(frozenset(), start_next_run=False, plan_id=ctx.plan_id)
        if result.outcome.phase_after != "verifying":
            self._line(ctx.plan_id, f"{unit}: the target moved, the unit did not go back to verifying "
                       f"({result.outcome.exit_reason or result.outcome.phase_after})")  # fmt: skip
            return self._result(frozenset(), start_next_run=False, plan_id=ctx.plan_id)
        self._write(ctx, [self._event("unit.merge_refused", unit=unit, reason="stale", detail=detail)], facts=True)
        self._line(ctx.plan_id, f"{unit}: the target moved, verifying again")
        return self._result(frozenset(), start_next_run=True, plan_id=ctx.plan_id)

    def _integrate(self, ctx: _Ctx, unit: str, snap: UnitSnapshot, *, via_merge: str | None) -> PlanStep:
        """The unit's acceptance profile on the merged target revision, then `unit.integrated` and its receipt (D9,
        D12), or `plan.stopped{postcheck_failed}`. `via_merge`: the head this step pushed; None for a merge by a person
        (the PR merge commit is not in the unit's state, so the target tip is checked)."""
        assert ctx.file.plan is not None
        plan, state = ctx.file.plan, ctx.state
        entry = next((u for u in plan.units() if u.id == unit), None)
        if entry is None:  # a unit the plan does not hold is none of its business: nothing is recorded
            self._line(ctx.plan_id, f"{unit} is not a unit of the plan: nothing recorded")
            return self._result(frozenset(), start_next_run=False, plan_id=ctx.plan_id)
        revision = via_merge or self._fetch_target()
        result = (
            run_profile(
                self.app,
                self.cfg,
                self.git,
                revision,
                entry.acceptance_profile,
                profiles=self.profiles,
                sandbox=self.sandbox,
            )  # fmt: skip
            if revision
            else ProfileResult("error", "", entry.acceptance_profile, detail="the target branch could not be fetched")
        )
        before: list[PlanEvent] = []
        if via_merge is None and unit not in state.merged:
            before.append(self._event("unit.merged", unit=unit, head=None, pr=snap.state.pr, merge_commit=revision,
                                      by="person"))  # fmt: skip
        post = self._event(
            "unit.postcheck", unit=unit, revision=result.revision or revision, profile=entry.acceptance_profile,
            status=result.status, detail=result.detail,
        )  # fmt: skip
        if result.status != "pass":
            self._line(ctx.plan_id, f"{unit}: the post-merge check {result.status}: {result.detail}")
            return self._stop(ctx, "postcheck_failed", result.detail or result.status, unit, before=[*before, post])
        integrated_at = result.revision or revision or ""
        charged = self._charged(ctx, unit, snap)
        events = [*before, post, self._event("unit.integrated", unit=unit, revision=integrated_at), charged]
        receipt = self._receipt(ctx, unit, snap, integrated_at, via_merge, result)
        self._write(ctx, events, receipt=receipt, facts=True)
        self._line(ctx.plan_id, f"{unit} integrated at {integrated_at[:10]}")
        return self._result(frozenset(), start_next_run=True, plan_id=ctx.plan_id)

    def _receipt(
        self, ctx: _Ctx, unit: str, snap: UnitSnapshot, revision: str, head: str | None, result: ProfileResult
    ) -> dict[str, object]:  # fmt: skip
        merged = _last(ctx.read.events, "unit.merged", unit)
        merge_commit = head or (str(merged.data.get("merge_commit")) if merged else None) or revision
        return {
            "receipt_id": f"{ctx.plan_id}/{unit}/{self._attempt(ctx, snap)}",
            "unit_id": unit,
            "plan_id": ctx.plan_id,
            "repository": self._repository(),
            "target": self.target,
            "plan_digest": ctx.state.plan_digest,
            "spec_digest": ctx.state.digests.get(unit),
            "pr": (merged.data.get("pr") if merged else None) or snap.state.pr,
            "reviewed_head": snap.review.head if snap.review is not None else head,
            "merge_commit": merge_commit,
            "integrated_revision": revision,
            "postcheck": result.status,
            "confirmed_at": self._at(),
        }

    def _charged(self, ctx: _Ctx, unit: str, snap: UnitSnapshot, *, extra_run: int = 0) -> PlanEvent:
        """`plan.charged{unit, attempt, cost_usd, runs}` carries the totals of the unit's current attempt (R1): its
        folded cost (a restart starts a new unit ledger, so that is this attempt's), and the runs the plan dispatched
        it for in this attempt. The fold keeps the maximum per (unit, attempt) and sums the attempts."""
        attempt = self._attempt(ctx, snap)
        cost, runs = self._charged_of(ctx, unit, attempt)
        return self._event(
            "plan.charged", unit=unit, attempt=attempt, cost_usd=max(cost, snap.state.cost_usd), runs=runs + extra_run
        )  # fmt: skip

    def _batch(self, ctx: _Ctx) -> PlanStep | None:
        """A batch whose units are all integrated and that is not accepted: a `none` profile is accepted without a run
        (every such batch at once); otherwise the first one's profile runs on the target tip (L4-YOLO-011)."""
        assert ctx.file.plan is not None
        plan, state = ctx.file.plan, ctx.state
        ready = [
            b for b in plan.batches
            if b.id not in state.accepted_batches and all(u.id in state.integrated for u in b.units)
        ]  # fmt: skip
        if not ready:
            return None
        none = [b for b in ready if b.acceptance_profile == "none"]
        tip = self._fetch_target() or ""
        if none:
            events = [self._event("batch.accepted", batch=b.id, revision=tip, profile="none") for b in none]
            self._write(ctx, events, facts=True)
            self._line(ctx.plan_id, f"batch(es) {', '.join(b.id for b in none)} accepted without a check")
            return self._result(frozenset(), start_next_run=True, plan_id=ctx.plan_id)
        batch = ready[0]
        result = (
            run_profile(
                self.app,
                self.cfg,
                self.git,
                tip,
                batch.acceptance_profile,
                profiles=self.profiles,
                sandbox=self.sandbox,
            )  # fmt: skip
            if tip
            else ProfileResult("error", "", batch.acceptance_profile, detail="the target branch could not be fetched")
        )
        if result.status == "pass":
            accepted = self._event("batch.accepted", batch=batch.id, revision=tip, profile=batch.acceptance_profile)
            self._write(ctx, [accepted], facts=True)
            self._line(ctx.plan_id, f"batch {batch.id} accepted at {tip[:10]}")
            return self._result(frozenset(), start_next_run=True, plan_id=ctx.plan_id)
        detail = result.detail or result.status
        failed = self._event("batch.failed", batch=batch.id, revision=tip, detail=detail)
        return self._stop(ctx, "batch_failed", f"batch {batch.id}: {detail}", None, before=[failed])

    def _complete(self, ctx: _Ctx) -> bool:
        assert ctx.file.plan is not None
        plan, state = ctx.file.plan, ctx.state
        return all(u in state.integrated for u in plan.unit_ids()) and all(
            b.id in state.accepted_batches for b in plan.batches
        )

    def _completed(self, ctx: _Ctx) -> PlanStep:
        tip = self._fetch_target() or self._target_rev()
        self._with_report(ctx, [self._event("plan.completed", revision=tip)])
        self._line(ctx.plan_id, f"completed at {tip[:10]}")
        return self._result(frozenset(), start_next_run=False, plan_id=ctx.plan_id)

    # --- the dispatch -----------------------------------------------------------------------------------------------

    def _dispatch(self, ctx: _Ctx) -> PlanStep:
        assert ctx.file.plan is not None
        plan, state = ctx.file.plan, ctx.state
        eligibility = next_eligible(plan, state, self._phases())
        unit = eligibility.unit
        if unit is None:  # a unit merged and not integrated was post-checked before (R10): nothing else is eligible
            reason = next(iter(eligibility.waiting.values()), "no unit is eligible")
            self._line(ctx.plan_id, f"nothing to dispatch: {reason}")
            return self._result(frozenset(), start_next_run=False, plan_id=ctx.plan_id)
        snap = self.snaps.get(unit)
        if snap is None:
            return self._stop(ctx, "unit_missing", f"{unit} is not among the units of the target", unit)
        actionable = self._unit_action(snap) in _ACTIONABLE
        phase = snap.state.phase or ""
        adopt = not actionable and unit != state.current and self._adoptable(snap)
        if not actionable and not adopt:
            if unit == state.current:
                if unit in self._merge_not_ready:  # a merge that is not ready is a wait, with its reason on record
                    return self._wait_merge(ctx, unit)
                self._line(ctx.plan_id, f"{unit} ({phase or 'not started'}) has nothing to run now")
                return self._result(frozenset({unit}), start_next_run=False, plan_id=ctx.plan_id)
            return self._wait(ctx, phase or "not_started", unit, snap)  # it cannot run and cannot be adopted (#2)
        if (limit := self._limit_reached(ctx, unit)) is not None:
            return self._stop(ctx, limit[0], limit[1], limit[2], charge=unit)
        # the charge first: the fold gives a new attempt its own stale retry when it sees the dispatch (D8)
        self._write(ctx, self._dispatch_events(ctx, unit, snap, adopted=adopt))
        if not adopt:
            self._line(ctx.plan_id, f"dispatched {unit} ({phase or 'not started'})")
            return self._result(frozenset({unit}), start_next_run=True, plan_id=ctx.plan_id)
        self._line(ctx.plan_id, f"adopted {unit} ({phase}): it is past implementation")
        if plan.merge == "auto":  # a person merges under `merge: human`; the plan waits for it as for any current unit
            merged = self._merge(ctx, snap)
            if merged is not None:
                return merged
            if unit in self._merge_not_ready:
                return self._wait_merge(ctx, unit)
        return self._result(frozenset({unit}), start_next_run=False, plan_id=ctx.plan_id)

    def _dispatch_events(self, ctx: _Ctx, unit: str, snap: UnitSnapshot, *, adopted: bool = False) -> list[PlanEvent]:
        """The charge of the attempt and `unit.dispatched`; `adopted`: the unit was already past implementation."""
        data: dict[str, object] = {"unit": unit, "run": self.app.run_id}
        if adopted:
            data.update(attempt=self._attempt(ctx, snap), adopted=True)
        return [self._charged(ctx, unit, snap, extra_run=1), self._event("unit.dispatched", **data)]


def rejection_pending(events: Sequence[PlanEvent], unit: str) -> PlanEvent | None:
    """The `unit.rejected` record of `unit` when its latest run, the one the plan dispatched, rejected it: no
    `unit.dispatched` came after it. A rejection leaves the unit with no phase and its ledger stays in the job's
    worktree, so this record is how the next run's plan step knows (M2, L4-YOLO-013). A later `plan.activated` ends
    it: the person fixed the cause (the spec or the configuration) and the unit's next run reads it."""
    for event in reversed(events):
        if event.type == "plan.activated":
            return None
        if event.data.get("unit") != unit:
            continue
        if event.type == "unit.rejected":
            return event
        if event.type in ("unit.dispatched", "unit.integrated"):
            return None
    return None


def not_started_pending(events: Sequence[PlanEvent], unit: str) -> PlanEvent | None:
    """The `unit.not_started` record of `unit` when the latest run of it that the plan dispatched ended before the unit
    started and no run has started it since (L4-YOLO-013). `unit.dispatched` does not end it (the step dispatches
    before the run); `unit.started`, an integration, a new activation and a person's resume do."""
    for event in reversed(events):
        if event.type == "plan.activated" or (event.type == "plan.resumed" and event.data.get("by") != "harness"):
            return None
        if event.data.get("unit") != unit:
            continue
        if event.type == "unit.not_started":
            return event
        if event.type in ("unit.started", "unit.integrated"):
            return None
    return None


def record_run_starts(
    app: AppContext, cfg: L4Config, git: Git, step: PlanStep, not_started: Mapping[str, tuple[int, str]],
    began: Collection[str],
) -> bool:  # fmt: skip
    """After the run: the current unit of the active plan that the step let run and whose run ended before the unit
    started (no `run.started`: a usage error, a lease or worktree failure, a missing CLI) gets `unit.not_started{unit,
    run, exit, detail}`, so the next plan step waits instead of chaining one more run (L4-YOLO-013); the unit's run
    that did begin gets `unit.started{unit, run}` when such a record is pending. True when a pending record was
    cleared: the caller chains the next run as the dispatch would have. A failure is a warning: the run limit is the
    brake."""
    units = [
        u for u in (*not_started, *(b for b in began if b in step.pending_starts))
        if step.plan_id and step.allow and u in step.allow
    ]  # fmt: skip
    if not units:
        return False
    assert step.plan_id is not None
    store = _store(app, cfg, git, step.plan_id)
    try:
        for _ in range(3):
            read = store.read()
            state = fold_plan(step.plan_id, read.events)
            if state.status not in ("active", "waiting") or state.current not in units:
                return False
            unit = state.current
            at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            pending = not_started_pending(read.events, unit)
            if unit in not_started:
                if pending is not None and pending.data.get("run") == app.run_id:
                    return False  # recorded already
                code, detail = not_started[unit]
                data = {"unit": unit, "run": app.run_id, "exit": code, "detail": detail[:300]}
                events, cleared = [PlanEvent("unit.not_started", at, data)], False
            elif pending is not None:
                events, cleared = [PlanEvent("unit.started", at, {"unit": unit, "run": app.run_id})], True
            else:
                return False
            try:
                store.append(events, expect=read.head)
            except PlanMoved:
                continue
            log.info("plan %s: %s %s", step.plan_id, unit, "started" if cleared else "did not start in its run")
            return cleared
        log.warning("plan %s: the start of %s was not recorded (the ref moved)", step.plan_id, ", ".join(units))
    except (GitError, ValueError, L4Exit) as exc:
        log.warning("plan %s: the start of %s was not recorded: %s", step.plan_id, ", ".join(units), exc)
    return False


def record_rejections(app: AppContext, cfg: L4Config, git: Git, step: PlanStep, rejected: Mapping[str, str]) -> None:
    """After the run: a unit of the plan that the run rejected (exit 14, no phase to show it) gets `unit.rejected{unit,
    run, detail}` on the plan ledger, so the next plan step stops the plan with `unit_rejected` instead of dispatching
    the unit again (M2). Only the current unit of an active plan that the step let run is recorded. A failure is a
    warning: the run's own result stands, and the run limit is the brake."""
    units = [u for u in rejected if step.plan_id and step.allow and u in step.allow]
    if not units:
        return
    assert step.plan_id is not None
    store = _store(app, cfg, git, step.plan_id)
    try:
        for _ in range(3):
            read = store.read()
            state = fold_plan(step.plan_id, read.events)
            at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            open_plan = state.status in ("active", "waiting")
            events = [
                PlanEvent("unit.rejected", at, {"unit": u, "run": app.run_id, "detail": rejected[u][:300]})
                for u in units
                if open_plan and state.current == u and rejection_pending(read.events, u) is None
            ]
            if not events:
                return
            try:
                store.append(events, expect=read.head)
            except PlanMoved:
                continue
            log.info("plan %s: %s was rejected by its run", step.plan_id, ", ".join(units))
            return
        log.warning("plan %s: the rejection of %s was not recorded (the ref moved)", step.plan_id, ", ".join(units))
    except (GitError, ValueError, L4Exit) as exc:
        log.warning("plan %s: the rejection of %s was not recorded: %s", step.plan_id, ", ".join(units), exc)


def failed_plan_step(
    app: AppContext,
    found: Sequence[tuple[SpecProvider, UnitSnapshot]],
    error: Exception,
    *,
    cfg: L4Config | None = None,
    git: Git | None = None,
) -> PlanStep:
    """The plan step of a run whose step failed unexpectedly (review #12): nothing is recorded, the failure is logged,
    and the units that no plan file lists run as before while every unit a plan file lists stays held. Should the plan
    files themselves be unreadable, no unit runs: a plan unit must never start by accident."""
    text = app.redactor.redact_text(f"{type(error).__name__}: {error}".strip()).splitlines()[0][:300]
    log.warning("plan step failed: %s", text)
    try:
        files = plan_files(app.repo) if cfg is None or git is None else target_plan_files(app, cfg, git)
        held = holds_of({}, files).held
    except Exception as exc:  # noqa: BLE001 - the holds cannot be known: hold everything
        log.warning("plan step failed: the plan files cannot be read either (%s): no unit runs", type(exc).__name__)
        return PlanStep(allow=frozenset(), refusals={s.ref.id: "waits for the plan step (it failed)" for _, s in found})
    refusals = {
        s.ref.id: f"is held by plan {held[s.ref.id][0]} ({held[s.ref.id][1]}; the plan step failed in this run)"
        for _, s in found
        if s.ref.id in held
    }
    return PlanStep(allow=frozenset(s.ref.id for _, s in found if s.ref.id not in held), refusals=refusals)


def _last(events: Sequence[PlanEvent], kind: str, unit: str | None = None) -> PlanEvent | None:
    found = None
    for event in events:
        if event.type == kind and (unit is None or event.data.get("unit") == unit):
            found = event
    return found


__all__ = [
    "Hold",
    "PlanStep",
    "REVIEW_KEY",
    "auto_plan_units",
    "failed_plan_step",
    "fetch_cause",
    "live_plan",
    "local_states",
    "not_started_pending",
    "plan_holds",
    "record_rejections",
    "record_run_starts",
    "rejection_pending",
    "review_batches",
    "unreadable_plan_files",
    "yolo_step",
]
