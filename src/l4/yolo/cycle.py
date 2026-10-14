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

A `waiting` or `stopped` plan does nothing in its step: `l4 yolo resume` is how it goes on (D10's table). Its units
stay held. The facts of a push that already happened (the merge) are appended again with a fresh lease when the ref
moved, because they are true whatever the plan now says.
"""

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from l4.agents.base import AgentAdapter
from l4.availability.errors import RoleUnavailable
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import L4Exit
from l4.forge.base import Forge, ForgeUnavailable, fetch_auth_config, make_forge
from l4.forge.gitlab import push_auth_config
from l4.forge.urls import origin_url
from l4.implementer.tdd import RoleLimit
from l4.sandbox.base import Sandbox
from l4.specs.base import SpecProvider
from l4.state.fold import UnitState
from l4.state.status import UnitSnapshot
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.vcs.names import unit_branch
from l4.yolo.admit import FINISHED_PHASES, admit, next_eligible
from l4.yolo.digest import plan_digest, unit_digest
from l4.yolo.merge import confirm_merged, merge_guarded, remote_tip
from l4.yolo.model import (
    PLAN_ID,
    Eligibility,
    PlanEvent,
    PlanMoved,
    PlanState,
    ProfileResult,
    YoloStep,
)
from l4.yolo.plans import PlanFile, held_by, plan_files, unit_infos
from l4.yolo.postcheck import run_profile
from l4.yolo.readiness import review_plan_costed
from l4.yolo.report import render_report
from l4.yolo.state import fold_plan
from l4.yolo.store import PlanRead, PlanStore, parse_ledger, plan_ref

log = logging.getLogger("l4.yolo.cycle")

REVIEW_KEY = "plan:review"  # the `plan.charged` key of the judge's cost
STOPPED_PHASES = ("halted", "escalated", "abandoned", "rejected")
WAIT_PHASES = ("awaiting_human", "clarifying", "waiting_capacity")
_ACTIONABLE = frozenset({"implement", "clarify", "verify", "hand_off"})  # `orchestrator.ACTIONABLE`, not imported here
_BEFORE_ACTIVATION = ("new", "refused", "admitted", "reviewed")
_USERINFO = re.compile(r"(?<=//)[^/@\s]+@")


@dataclass(frozen=True)
class PlanStep(YoloStep):
    """`YoloStep` and, for `l4 run --unit`, why each unit that is not in `allow` is not dispatched: the end of the
    sentence `run: <unit> <refusal>` (L4-YOLO-010, SCN-YOLO-21)."""

    refusals: Mapping[str, str] = field(default_factory=dict)


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
    `not in the active plan p1`. A unit the plan has integrated is no hold."""
    held = held_by(states, files)
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


def auto_plan_units(app: AppContext, cfg: L4Config, git: Git) -> frozenset[str]:
    """The units of the active `merge: auto` plans on the base branch, for the sweep that merges their archive pull
    requests (L4-YOLO-009). The plan refs are fetched; any failure to read them is logged and means no unit."""
    files = [f for f in plan_files(app.repo) if f.plan is not None and f.plan.merge == "auto"]
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
) -> PlanStep:
    """The plan step of this run (module text). `forge`, `adapters`, `profiles`, `sandbox` and `now` replace what the
    run would build (tests and `l4 simulate`); `confirm_wait_s` is how long the step waits for the forge to show a
    merged pull request. `all_units` discovers every unit when `found` holds only the units a command named
    (`l4 run --unit`): the plan needs them all, and is read only when a plan file exists."""
    files = plan_files(app.repo)
    if not files:
        return PlanStep(allow=None)
    if all_units is not None:
        found = all_units()
    step = _Step(app, cfg, git, found, files, forge, adapters, profiles, sandbox, now, confirm_wait_s)
    return step.run()


class _Step:
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

    def run(self) -> PlanStep:
        for attempt in (1, 2):
            try:
                self._load()
                self.actions = []
                done = self._reviews()
                if done is not None:
                    return done
                live = live_plan(self.files, self._states(), self.target)
                if live is not None and live.plan_id in self.ctxs:
                    return self._live(self.ctxs[live.plan_id])
                return self._result(None, start_next_run=False)
            except PlanMoved:
                log.info("the plan ref moved (attempt %d): reading it again", attempt)
        log.warning("the plan ref moved twice: no plan step in this run")
        return self._result(frozenset(), start_next_run=False, extra=("plan step skipped: the plan ref moved twice",))

    def _result(
        self, allow: frozenset[str] | None, *, start_next_run: bool, plan_id: str | None = None,
        extra: Sequence[str] = (),
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
                refusals[unit] = f"waits for the plan step of this run (plan {live.plan_id if live else plan_id})"
        return PlanStep(
            allow=allow, actions=(*self.actions, *extra), start_next_run=start_next_run,
            plan_id=plan_id or (live.plan_id if live else None), refusals=refusals,
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
            log.warning("the target %s could not be fetched: %s", self.target, str(exc).splitlines()[0][:200])
            return None
        return self.git.rev_parse(f"refs/remotes/origin/{self.target}")

    def _target_rev(self) -> str:
        return self.git.rev_parse(f"refs/remotes/origin/{self.target}") or "HEAD"

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
        text = self._report(ctx, events)
        self._write(ctx, events, files={"report.md": text}, facts=True)
        out = self.app.out_dir / "yolo" / f"{ctx.plan_id}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")

    def _stop(
        self, ctx: _Ctx, reason: str, detail: str | None = None, unit: str | None = None,
        before: Sequence[PlanEvent] = (),
    ) -> PlanStep:  # fmt: skip
        shown = self.app.redactor.redact_text(detail) if detail else None
        stopped = self._event("plan.stopped", reason=reason, detail=shown, unit=unit)
        self._with_report(ctx, [*before, stopped])
        self._line(ctx.plan_id, f"stopped ({reason}{f', {unit}' if unit else ''}){f': {shown}' if shown else ''}")
        return self._result(frozenset(), start_next_run=False, plan_id=ctx.plan_id)

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
            return self._result(None, start_next_run=False, plan_id=ctx.plan_id)
        plan = file.plan
        rev = self._target_rev()
        folders = unit_infos(self.app.repo, self.found, plan.unit_ids(), check_intake=False)
        current = {u: unit_digest(self.git, rev, i.folder) for u, i in folders.items()}
        if self._reviewed_current(state, digest, current):
            return None
        infos = unit_infos(self.app.repo, self.found, plan.unit_ids())
        admission = admit(plan, known_units=infos, cfg=self.cfg)
        if not admission.ok:
            findings = [{"code": f.code, "subject": f.subject, "text": f.text} for f in admission.findings]
            last = _last(ctx.read.events, "plan.refused")
            if state.status == "refused" and last is not None and last.data.get("findings") == findings:
                return None
            self._write(ctx, [self._event("plan.refused", plan_digest=digest, findings=findings)])
            self._line(ctx.plan_id, f"refused: {len(findings)} finding(s): {findings[0]['text']}")
            return self._result(None, start_next_run=False, plan_id=ctx.plan_id)
        try:
            result, cost = review_plan_costed(
                self.app, self.cfg, plan, infos, git=self.git, rev=rev, adapters=self.adapters, sandbox=self.sandbox
            )
        except (RoleLimit, RoleUnavailable) as exc:
            reason = self.app.redactor.redact_text(str(exc) or type(exc).__name__).splitlines()[0][:200]
            self._line(ctx.plan_id, f"the review waits, no judge could run ({reason}); a later run tries again")
            return self._result(None, start_next_run=False, plan_id=ctx.plan_id)
        events = []
        order = list(admission.order)
        if not (state.status in ("admitted", "reviewed") and state.plan_digest == digest and state.order == order):
            events.append(self._event("plan.admitted", plan_digest=digest, order=order, merge=plan.merge))
        units = {
            uid: {"verdict": v.verdict, "digest": v.digest, "findings": list(v.findings)}
            for uid, v in result.units.items()
        }
        batches = {bid: {"verdict": v.verdict, "findings": list(v.findings)} for bid, v in result.batches.items()}
        events.append(self._event("plan.reviewed", plan_digest=digest, units=units, batches=batches))
        if cost > 0:
            total = cost + max(
                (float(e.data.get("cost_usd") or 0) for e in ctx.read.events
                 if e.type == "plan.charged" and e.data.get("unit") == REVIEW_KEY),
                default=0.0,
            )  # fmt: skip
            events.append(self._event("plan.charged", unit=REVIEW_KEY, cost_usd=round(total, 6), runs=0, attempts=0))
        self._write(ctx, events)
        verdicts = ", ".join(f"{u}={v.verdict}" for u, v in result.units.items())
        self._line(ctx.plan_id, f"reviewed ({verdicts})")
        return self._result(None, start_next_run=False, plan_id=ctx.plan_id)

    @staticmethod
    def _reviewed_current(state: PlanState, digest: str, current: Mapping[str, str]) -> bool:
        if state.review_plan_digest != digest or not state.review:
            return False
        return all(state.review_digests.get(unit) == value for unit, value in current.items())

    # --- 2. the active plan -----------------------------------------------------------------------------------------

    def _limits(self, ctx: _Ctx) -> dict[str, object]:
        assert ctx.file.plan is not None
        return dict(ctx.state.limits) if ctx.state.limits else ctx.file.plan.limits.model_dump(mode="json")

    def _deadline(self, ctx: _Ctx) -> datetime | None:
        raw: object = self._limits(ctx).get("deadline")
        for event in ctx.read.events:
            extend = event.data.get("extend") if event.type == "plan.resumed" else None
            if isinstance(extend, dict) and extend.get("deadline"):
                raw = extend["deadline"]  # the latest extension replaces the frozen deadline
        if not raw:
            return None
        try:
            stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)

    def _limit_reached(self, ctx: _Ctx, *, dispatching: bool) -> tuple[str, str, str | None] | None:
        """(stop reason, detail, unit) of the first limit reached (D11): cost, runs, attempts per unit, deadline."""
        assert ctx.file.plan is not None
        state, limits = ctx.state, self._limits(ctx)
        plan_units = ctx.file.plan.unit_ids()
        review = max((float(e.data.get("cost_usd") or 0) for e in ctx.read.events
                      if e.type == "plan.charged" and e.data.get("unit") == REVIEW_KEY), default=0.0)  # fmt: skip
        live_cost = sum(self.snaps[u].state.cost_usd for u in plan_units if u in self.snaps)
        cost = max(state.used.cost_usd, live_cost + review)
        max_cost = limits.get("max_cost_usd")
        if isinstance(max_cost, int | float) and cost >= float(max_cost) + state.extended.cost_usd:
            return "limit_cost", f"${cost:.2f} spent of ${float(max_cost) + state.extended.cost_usd:.2f}", None
        runs = sum(1 for e in ctx.read.events if e.type == "unit.dispatched")
        max_runs = limits.get("max_runs")
        if isinstance(max_runs, int) and not isinstance(max_runs, bool):
            allowed = max_runs + state.extended.runs
            if runs > allowed or (dispatching and runs >= allowed):
                return "limit_runs", f"{runs} run(s) dispatched of {allowed}", None
        max_attempts = limits.get("max_unit_attempts")
        if isinstance(max_attempts, int) and not isinstance(max_attempts, bool):
            for unit in plan_units:
                snap = self.snaps.get(unit)
                if snap is None or unit in state.integrated:
                    continue
                extra = state.extended.attempts.get("*", 0) + state.extended.attempts.get(unit, 0)
                attempts = 1 + snap.state.restarts
                if attempts > max_attempts + extra:
                    return "limit_attempts", f"{unit} is on attempt {attempts} of {max_attempts + extra}", unit
        deadline = self._deadline(ctx)
        if deadline is not None and self._now() >= deadline:
            return "limit_deadline", f"the deadline {deadline.strftime('%Y-%m-%dT%H:%M:%SZ')} has passed", None
        return None

    def _inputs_changed(self, ctx: _Ctx) -> str | None:
        """The first plan unit, not integrated and not merged, whose folder differs from its digest frozen at the
        activation. The current unit is read on its branch when it has one, the others at the target head (D3, D10)."""
        assert ctx.file.plan is not None
        state, rev = ctx.state, self._target_rev()
        pending = [u for u in ctx.file.plan.unit_ids() if u not in state.integrated and state.digests.get(u)]
        infos = unit_infos(self.app.repo, self.found, pending, check_intake=False)
        for unit in pending:
            snap, info = self.snaps.get(unit), infos.get(unit)
            if snap is None or info is None or unit in state.merged or snap.state.phase in FINISHED_PHASES:
                continue
            where = rev
            if unit == state.current:
                branch = self.git.rev_parse(f"refs/remotes/origin/{unit_branch(unit, self.cfg.forge.branch_prefix)}")
                where = branch or rev
            if unit_digest(self.git, where, info.folder) != state.digests[unit]:
                return unit
        return None

    def _unit_action(self, snap: UnitSnapshot) -> str:
        from l4.planner import facts_of, next_action  # the planner is imported late: it imports this module

        return next_action(facts_of(snap))[0]

    def _live(self, ctx: _Ctx) -> PlanStep:
        assert ctx.file.plan is not None
        plan, state = ctx.file.plan, ctx.state
        if remote_tip(self.git, self.cfg, self.app.environ, self.target) is None:
            return self._stop(ctx, "target_missing", f"the target branch {self.target} does not exist on origin")
        if (unit := self._inputs_changed(ctx)) is not None:
            return self._stop(ctx, "inputs_changed", f"the spec of {unit} changed after the activation", unit)
        if (limit := self._limit_reached(ctx, dispatching=False)) is not None:
            return self._stop(ctx, limit[0], limit[1], limit[2])
        current = state.current
        snap = self.snaps.get(current) if current else None
        if current and snap is None:
            return self._stop(ctx, "unit_missing", f"{current} is not among the units of the target", current)
        if current and snap is not None:
            phase = snap.state.phase or ""
            if phase in STOPPED_PHASES:
                return self._stop(ctx, f"unit_{phase}", snap.state.halt_detail or snap.state.halt_reason, current)
            if phase not in FINISHED_PHASES and phase in WAIT_PHASES and self._unit_action(snap) not in _ACTIONABLE:
                return self._wait(ctx, phase, current, snap)
            if phase == "in_review" and plan.merge == "auto":
                step = self._merge(ctx, snap)
                if step is not None:
                    return step
            if phase in FINISHED_PHASES and current not in state.integrated:
                return self._integrate(ctx, current, snap, via_merge=None)
        batch = self._batch(ctx)
        if batch is not None:
            return batch
        if self._complete(ctx):
            return self._completed(ctx)
        return self._dispatch(ctx)

    def _wait(self, ctx: _Ctx, phase: str, unit: str, snap: UnitSnapshot) -> PlanStep:
        from l4.planner import facts_of, next_action

        detail = next_action(facts_of(snap))[1]
        reason = f"unit_{phase}"
        self._write(ctx, [self._event("plan.waiting", reason=reason, unit=unit, detail=detail)])
        self._line(ctx.plan_id, f"waiting ({reason}, {unit}): {detail}")
        return self._result(frozenset({unit}), start_next_run=False, plan_id=ctx.plan_id)

    # --- the guarded merge, post-merge profile, batches, completion ------------------------------------------------

    def _forge_for_merge(self) -> Forge:
        return self._forge or make_forge(self.cfg, self.app.environ, repo=self.app.repo)

    def _merge(self, ctx: _Ctx, snap: UnitSnapshot) -> PlanStep | None:
        """D8 and D9 in one step. None: the unit is not ready to merge, the step goes on to the dispatch."""
        unit = snap.ref.id
        verdict = snap.state.last_verdict
        if verdict is None or verdict.verdict != "PASS":
            return None
        if self.cfg.forge.merge_policy != "auto":
            return self._stop(ctx, "merge_refused", "forge.merge_policy is not auto", unit)
        try:
            forge = self._forge_for_merge()
        except ForgeUnavailable as exc:
            return self._stop(ctx, "merge_refused", f"no forge to ask: {exc}", unit)
        out = merge_guarded(self.app, self.cfg, self.git, forge, snap)
        if out.status == "not_ready":
            if "does not exist on origin" in out.detail:
                return self._stop(ctx, "target_missing", out.detail)
            self._line(ctx.plan_id, f"{unit} is not ready to merge: {out.detail}")
            return None
        if out.status == "refused":
            return self._stop(ctx, "merge_refused", out.detail, unit)
        if out.status == "stale":
            return self._stale(ctx, snap, out.detail)
        assert out.head is not None and out.pr is not None
        if not confirm_merged(forge, self.git, self.cfg, out.pr, out.head, wait_s=self.confirm_wait_s):
            log.warning("%s: %s was pushed to %s, but the target does not show it as its tip", unit, out.head[:10],
                        self.target)  # fmt: skip
        merged = [
            self._event("unit.merge_requested", unit=unit, head=out.head, target_before=out.target_before),
            self._event("unit.merged", unit=unit, head=out.head, pr=out.pr, merge_commit=out.head),
        ]
        self._write(ctx, merged, facts=True)
        self._line(ctx.plan_id, f"{unit} merged into {self.target} at {out.head[:10]}")
        return self._integrate(ctx, unit, snap, via_merge=out.head)

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
        entry = next(u for u in plan.units() if u.id == unit)
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
            "receipt_id": f"{ctx.plan_id}/{unit}/{snap.state.restarts + 1}",
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
        """`plan.charged` carries the unit's totals (the fold keeps the maximum per unit): its folded cost, the runs the
        plan dispatched it for, and 1 + restarts attempts."""
        runs = sum(1 for e in ctx.read.events if e.type == "unit.dispatched" and e.data.get("unit") == unit)
        return self._event(
            "plan.charged", unit=unit, cost_usd=snap.state.cost_usd, runs=runs + extra_run,
            attempts=1 + snap.state.restarts,
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
        if unit is None:
            finished = next((u for u, why in eligibility.waiting.items() if "post-merge check" in why), None)
            if finished is not None and finished in self.snaps:  # merged by a person before the plan got to it
                return self._integrate(ctx, finished, self.snaps[finished], via_merge=None)
            reason = next(iter(eligibility.waiting.values()), "no unit is eligible")
            self._line(ctx.plan_id, f"nothing to dispatch: {reason}")
            return self._result(frozenset(), start_next_run=False, plan_id=ctx.plan_id)
        snap = self.snaps.get(unit)
        if snap is None:
            return self._stop(ctx, "unit_missing", f"{unit} is not among the units of the target", unit)
        actionable = self._unit_action(snap) in _ACTIONABLE
        if not actionable:
            self._line(ctx.plan_id, f"{unit} ({snap.state.phase or 'not started'}) has nothing to run now")
            return self._result(frozenset({unit}), start_next_run=False, plan_id=ctx.plan_id)
        if (limit := self._limit_reached(ctx, dispatching=True)) is not None:
            return self._stop(ctx, limit[0], limit[1], limit[2])
        events = [
            self._event("unit.dispatched", unit=unit, run=self.app.run_id),
            self._charged(ctx, unit, snap, extra_run=1),
        ]
        self._write(ctx, events)
        self._line(ctx.plan_id, f"dispatched {unit} ({snap.state.phase or 'not started'})")
        return self._result(frozenset({unit}), start_next_run=True, plan_id=ctx.plan_id)


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
    "live_plan",
    "local_states",
    "plan_holds",
    "yolo_step",
]
