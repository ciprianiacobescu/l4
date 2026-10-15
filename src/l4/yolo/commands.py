"""`l4 yolo check|review|activate|status|cancel|resume|report` (yolo-mode design D6, D10, L4-YOLO-005, L4-YOLO-013,
L4-YOLO-015): the operator's side of a delivery plan. They run on a laptop, call no model (but `review --local`) and
read the plan the way CI does: the plan file at `origin/<forge.base_branch>` (`plans.plan_files_at`), the plan ledger
in `refs/l4/plans/<id>` (`PlanStore.read`), and the units of the target head.

**Where the units are read from.** Admission needs the units as the target head has them. When the checkout is at the
target tip and has no change to a tracked file, the checkout is read; otherwise a temporary detached worktree of
`origin/<target>` is made in the harness cache and removed after, so a stale or dirty checkout never changes what is
admitted. The configuration is the checkout's own `.l4/config.yaml`, as for every other command.

**Writes.** Every write is one `PlanStore.append(..., expect=head)` on the head this command read: a lost lease is
`the plan moved: run the command again` (exit 2) and nothing is overwritten. `check`, `status` and `report` write
nothing; `review` without `--local` only asks CI to review (`start_run`).

**Refusals** all exit 2 with the cause and the command that clears it. `activate` checks, in this order: the plan
file, a plan already active or finished, admission (which includes `target_mismatch` and `merge: auto` against
`forge.merge_policy: human`), a review that exists and is for the current plan and unit digests (a unit's digest is
taken on its branch when it has one, else on the target head: design D3), every unit and batch READY, the target on
`origin`, no other plan active, waiting or stopped on the target. `resume` follows design D10's table: it is refused
while the cause of the stop or the wait is still there, naming the command that clears it.

`l4 status` shows one line per plan that is not final (`plan_lines`); `l4 doctor` warns about `merge_policy: auto`
without an active `merge: auto` plan (`auto_merge_plan_active`), both from the plan refs the checkout already has: no
network.
"""

import contextlib
import json
import logging
import shutil
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

from l4.availability.errors import RoleUnavailable
from l4.config.defaults import cache_root
from l4.config.redaction import load_app_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import fetch_auth_config
from l4.forge.gitlab import push_auth_config
from l4.forge.urls import origin_url
from l4.implementer.tdd import RoleLimit
from l4.specs.providers import providers_for
from l4.state.retry import fetch_unit_refs, start_run_line
from l4.state.status import discover
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.yolo import accept as accepting
from l4.yolo import findings as fnd
from l4.yolo.admit import admit, done_units, next_eligible, unit_blocker
from l4.yolo.cycle import REVIEW_KEY, fetch_cause, plan_source, review_batches
from l4.yolo.digest import MISSING, FolderMissing, RevisionMissing, current_unit_digest, plan_digest
from l4.yolo.draft import Found, new_draft, update_draft
from l4.yolo.limits import (
    LIMIT_ATTEMPTS,
    LIMIT_COST,
    LIMIT_RUNS,
    attempt_refs,
    effective_limits,
    live_attempt,
    live_state,
    reached_at,
    resume_allows,
)
from l4.yolo.model import (
    PLAN_ID,
    PLAN_REF_PREFIX,
    PLANS_DIR,
    Admission,
    MergeMode,
    Plan,
    PlanEvent,
    PlanInvalid,
    PlanMoved,
    PlanState,
    UnitInfo,
)
from l4.yolo.plans import (
    FINAL,
    PlanFile,
    active_on,
    archived_at,
    held_by,
    plan_files,
    plan_files_at,
    readable_unit_ids,
    unit_infos,
)
from l4.yolo.readiness import PROMPT_VERSION, delivered_on_target, review_plan_costed
from l4.yolo.state import apply_extend, fold_plan, parse_time
from l4.yolo.store import LEDGER_FILE, PlanRead, PlanStore, list_plans, parse_ledger

log = logging.getLogger("l4.yolo.commands")

REPORT_FILE = "report.md"
_MOVED = "the plan moved: run the command again"
_BEFORE_ACTIVATION = ("new", "refused", "admitted", "reviewed")
_HOLDING = ("active", "waiting", "stopped")


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(kind: str, **data: Any) -> PlanEvent:
    return PlanEvent(type=kind, at=_stamp(), data=data)


# --- the context of one command ----------------------------------------------------------------------------------


@dataclass
class _Ctx:
    app: AppContext
    cfg: L4Config
    git: Git
    fetch_cfg: tuple[tuple[str, str], ...]
    push_cfg: tuple[tuple[str, str], ...]

    @property
    def target(self) -> str:
        return self.cfg.forge.base_branch

    @property
    def target_ref(self) -> str:
        return f"refs/remotes/origin/{self.target}"

    def store(self, plan_id: str) -> PlanStore:
        return PlanStore(
            self.git, plan_id, self.fetch_cfg, push_config=self.push_cfg, token_env=self.cfg.forge.token_env,
            environ=self.app.environ, redact=self.app.redactor.redact_text,
        )  # fmt: skip

    def say(self, text: str = "") -> None:
        click.echo(self.app.redactor.redact_text(text))

    def who(self) -> str:
        email = self.git.run("config", "user.email", check=False).stdout.strip()
        return email or self.app.environ.get("USER") or self.app.environ.get("USERNAME") or "unknown"


def _open(app: AppContext) -> _Ctx:
    app, cfg = load_app_config(app)
    git = Git(app.repo, environ=app.environ)
    origin = origin_url(app.repo, app.environ)
    return _Ctx(app, cfg, git, fetch_auth_config(cfg, app.environ, origin), push_auth_config(cfg, app.environ, origin))


def _plan_id(text: str) -> str:
    if not PLAN_ID.match(text):
        raise L4Exit(ExitCode.USAGE_ERROR, f"yolo: {text!r} is not a plan id (lower-case letters, digits and '-')")
    return text


def _branch_on_origin(ctx: _Ctx, branch: str) -> bool:
    done = ctx.git.run("ls-remote", "--exit-code", "origin", f"refs/heads/{branch}", check=False, config=ctx.fetch_cfg)
    if done.returncode == 0:
        return True
    if done.returncode == 2:  # git's "no matching ref"
        return False
    raise L4Exit(ExitCode.INTERNAL_ERROR, f"yolo: cannot reach origin: {done.stderr.strip()[:200]}")


def _sync(ctx: _Ctx, *, who: str) -> str:
    """Fetch the base branch and the unit refs; the target head's sha. The plan files are read from it."""
    if ctx.git.run("remote", "get-url", "origin", check=False).returncode != 0:
        raise L4Exit(ExitCode.USAGE_ERROR, f"{who}: this repository has no origin")
    if not _branch_on_origin(ctx, ctx.target):
        raise L4Exit(ExitCode.USAGE_ERROR, f"{who}: the base branch {ctx.target} is not on origin")
    fetch_unit_refs(ctx.app, ctx.cfg, ctx.git)
    sha = ctx.git.rev_parse(ctx.target_ref)
    if sha is None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"{who}: origin/{ctx.target} could not be fetched")
    return sha


def _file(ctx: _Ctx, plan_id: str, who: str) -> PlanFile:
    for file in plan_files_at(ctx.git, ctx.target_ref):
        if file.plan_id == plan_id:
            return file
    raise L4Exit(ExitCode.USAGE_ERROR, f"{who}: no plan file .l4/plans/{plan_id}.json on origin/{ctx.target}")


def _valid(ctx: _Ctx, file: PlanFile, who: str) -> Plan:
    """The plan of a file, or exit 2 with every problem of the file (nothing is recorded)."""
    if file.plan is None:
        assert file.invalid is not None
        raise L4Exit(ExitCode.USAGE_ERROR, "\n".join([*file.invalid.errors, f"{who}: {file.plan_id} is not a plan"]))
    return file.plan


@dataclass
class _Units:
    """The units of the target head: what admission needs, and every unit's phase."""

    infos: dict[str, UnitInfo] = field(default_factory=dict)
    phases: dict[str, str | None] = field(default_factory=dict)
    costs: dict[str, float] = field(default_factory=dict)  # unit id -> the cost its own ledger shows (this attempt)


@contextlib.contextmanager
def _workspace(ctx: _Ctx, rev: str) -> Iterator[tuple[Path, Git]]:
    """The checkout when it is the target head and unchanged, else a temporary detached worktree of `rev`."""
    clean = ctx.git.run("status", "--porcelain", "--untracked-files=no", check=False).stdout.strip() == ""
    if ctx.git.rev_parse("HEAD") == rev and clean:
        yield ctx.app.repo, ctx.git
        return
    area = cache_root(ctx.app.environ, repo=ctx.app.repo) / "yolo" / "check"
    area.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"{rev[:10]}-", dir=area))
    tree = work / "tree"
    try:
        ctx.git.run("worktree", "add", "--quiet", "--detach", str(tree), rev)
        yield tree, ctx.git.at(tree)
    finally:
        ctx.git.run("worktree", "remove", "--force", str(tree), check=False)
        shutil.rmtree(work, ignore_errors=True)
        ctx.git.run("worktree", "prune", check=False)


def _read_units(ctx: _Ctx, rev: str, wanted: Sequence[str], *, intake: bool) -> _Units:
    with _workspace(ctx, rev) as (path, git):
        found = discover(ctx.cfg, git, providers_for(ctx.cfg, path, ctx.app.environ))
        infos = unit_infos(path, found, wanted, check_intake=intake)
        phases = {snapshot.ref.id: snapshot.state.phase for _, snapshot in found}
        costs = {snapshot.ref.id: snapshot.state.cost_usd for _, snapshot in found}
    return _Units(infos, phases, costs)


def _now_digest(ctx: _Ctx, unit_id: str, folder: str) -> str:
    """The digest of a unit now (design D3, R3): on its branch when it has one on origin, else on the target head.
    `digest.current_unit_digest` is the one rule the review, the activation and the `inputs_changed` check share; a
    target that is not fetched raises `RevisionMissing`, which is never the digest of an empty folder."""
    try:
        return current_unit_digest(ctx.git, ctx.cfg, unit_id, folder, ctx.target_ref)
    except FolderMissing:  # the folder is gone: it equals no digest, so the review is stale (review #4)
        return MISSING


def _digests(ctx: _Ctx, plan: Plan, units: _Units) -> dict[str, str]:
    return {u: _now_digest(ctx, u, units.infos[u].folder) for u in plan.unit_ids() if u in units.infos}


def _append(store: PlanStore, events: Sequence[PlanEvent], head: str | None) -> str:
    try:
        return store.append(events, expect=head)
    except PlanMoved:
        raise L4Exit(ExitCode.USAGE_ERROR, _MOVED) from None


def _findings_text(admission: Admission, plan_id: str) -> list[str]:
    """`<code>: <text>`; the subject is added only when the text does not name it (the plan itself is the context)."""
    return [
        f"{f.code}: {f.text}" if f.subject in (plan_id, *f.text.split()) else f"{f.code}: {f.subject}: {f.text}"
        for f in admission.findings
    ]


# --- the review as the ledger holds it ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewView:
    """`none`: never reviewed; `stale`: for other plan or unit digests; `current`. `problems` are the units and batches
    whose latest verdict is not READY, one line each (name, verdict, the first line of the findings)."""

    kind: str
    problems: tuple[str, ...] = ()
    prompt_changed: bool = False  # stale because the review prompt changed since the review was made

    @property
    def ready(self) -> bool:
        return self.kind == "current" and not self.problems


def _rejected_at(events: Sequence[PlanEvent], state: PlanState) -> str | None:
    """The spec digest of the unit a plan was stopped with `unit_rejected` for: the one recorded by the stop, else the
    one frozen at the activation (R8). None for a plan that is not stopped for a rejected unit."""
    if state.status != "stopped" or state.stop_reason != "unit_rejected" or not state.stop_unit:
        return None
    unit = state.stop_unit
    stops = [
        e for e in events
        if e.type == "plan.stopped" and e.data.get("reason") == "unit_rejected" and e.data.get("unit") == unit
    ]  # fmt: skip
    return (stops[-1].data.get("digest") if stops else None) or state.digests.get(unit)


def _first_line(findings: Any) -> str:
    """The most severe finding (`findings.most_severe`: blocking, then major, then minor; the judge's order within a
    severity) as `<criterion>: <first line of its text>`."""
    rows = [f for f in findings or [] if isinstance(f, dict)]
    top = fnd.most_severe(rows)
    if top is None:
        return "no finding recorded"
    text = str(top.get("text") or "").strip().splitlines()
    criterion = top.get("criterion")
    head = text[0] if text else "no text"
    return f"{criterion}: {head}" if criterion else head


def _review_view(
    plan: Plan,
    text: str,
    state: PlanState,
    events: Sequence[PlanEvent],
    now: Mapping[str, str],
    *,
    prompt_matters: bool = True,
) -> ReviewView:
    """`prompt_matters` False: show the review as it was made (a plan that needs no new review)."""
    if state.review_plan_digest is None:
        return ReviewView("none")
    wanted = [u for u in plan.unit_ids()] + [f"batch:{b.id}" for b in plan.batches if len(b.units) > 1]
    if prompt_matters and state.review_prompt_version != PROMPT_VERSION:
        return ReviewView("stale", prompt_changed=True)
    stale = state.review_plan_digest != plan_digest(text)
    stale = stale or any(state.review_digests.get(u) != now.get(u) for u in plan.unit_ids())
    stale = stale or any(w not in state.review for w in wanted)
    if stale:
        return ReviewView("stale")
    latest: dict[str, Any] = next((e.data for e in reversed(events) if e.type == "plan.reviewed"), {})
    problems = []
    for name in wanted:
        verdict = state.review[name]
        if verdict == "READY":
            continue
        group, _, ident = name.partition(":") if name.startswith("batch:") else ("units", "", name)
        entry = (latest.get("batches" if group == "batch" else "units") or {}).get(ident) or {}
        label = f"batch {ident}" if group == "batch" else name
        problems.append(f"{label}: {verdict}: {_first_line(entry.get('findings'))}")
    return ReviewView("current", tuple(problems))


# --- limits -------------------------------------------------------------------------------------------------------


def _money(value: float | None) -> str:
    return "unlimited" if value is None else f"${value:.2f}"


def _live_usage(ctx: _Ctx, state: PlanState, events: Sequence[PlanEvent], units: _Units, unit: str | None) -> PlanState:
    """The state with the live figures the plan step checks the limits on (`limits.live_state`): the attempt `unit`
    is on (`limits.live_attempt` of its attempt refs on origin) and the cost its ledger shows now."""
    if unit is None or unit not in units.phases:
        return state
    attempt = live_attempt(state, unit, attempt_refs(ctx.git, unit, ctx.fetch_cfg))
    return live_state(state, events, unit, attempt, units.costs.get(unit, 0.0))


# --- what stops a resume ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Extend:
    cost: float | None = None
    runs: int | None = None
    attempts: int | None = None
    deadline: datetime | None = None

    def as_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.cost is not None:
            data["cost_usd"] = self.cost
        if self.runs is not None:
            data["runs"] = self.runs
        if self.attempts is not None:
            data["attempts"] = self.attempts
        if self.deadline is not None:
            data["deadline"] = self.deadline.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return data


@dataclass(frozen=True)
class Blocker:
    """Why a resume is refused: `message` follows `resume: `; `fix` is what clears it (the `Next:` line)."""

    message: str
    fix: str


def resume_blocker(
    plan_id: str,
    state: PlanState,
    events: Sequence[PlanEvent],
    plan: Plan | None,
    phases: Mapping[str, str | None],
    extend: Extend,
    *,
    target_present: bool = True,
    now: datetime | None = None,
    live: PlanState | None = None,
) -> Blocker | None:
    """The cause that is still there, per design D10's table; None when a resume may go. `live`: the state with the
    figures the plan step checks the limits on (`_live_usage`); the ledger's `state` when not given."""
    review_again = f"l4 yolo review {plan_id}, then l4 yolo activate {plan_id} --reason TEXT"
    if state.status == "waiting":
        unit = state.current
        phase = phases.get(unit) if unit else None
        if phase in ("awaiting_human", "clarifying"):
            return Blocker(
                f"{unit} is still {phase}: answer its questions first (l4 questions --unit {unit})",
                f"answer the questions of {unit} (l4 questions --unit {unit})",
            )
        if phase == "waiting_capacity":
            return Blocker(
                f"{unit} is still waiting_capacity: run l4 retry --unit {unit} first, or wait for the capacity",
                f"l4 retry --unit {unit} --reason TEXT",
            )
        return None
    reason, unit = state.stop_reason or "", state.stop_unit
    if reason == "unit_rejected" and unit:
        return Blocker(
            f"{unit} was rejected: fix the cause, its spec (push it; the next run stops the plan with inputs_changed "
            f"and CI reviews it) or the configuration, then l4 yolo activate {plan_id}",
            f"fix the cause of the rejection of {unit}: its spec (push it, wait for the review) or the configuration; "
            f"then l4 yolo activate {plan_id} --reason TEXT",
        )
    if reason in ("inputs_changed", "unit_rejected"):
        what = f"{unit} was rejected" if reason == "unit_rejected" and unit else f"{plan_id} stopped with {reason}"
        return Blocker(f"{what}: run l4 yolo review {plan_id}, then l4 yolo activate {plan_id}", review_again)
    if reason in ("unit_halted", "unit_escalated") and unit:
        phase = phases.get(unit)
        if phase in ("halted", "escalated"):
            return Blocker(
                f"{unit} is still {phase}: run l4 retry --unit {unit} first", f"l4 retry --unit {unit} --reason TEXT"
            )
    if reason == "unit_abandoned" and unit and phases.get(unit) == "abandoned":
        return Blocker(
            f"{unit} is still abandoned: reopen its pull request, or run l4 restart --unit {unit} --reason TEXT first",
            f"l4 restart --unit {unit} --reason TEXT",
        )
    if reason == "unit_missing" and unit and unit not in phases and unit not in state.merged:
        # a unit the ledger has merged may have moved to the archive: the step checks its head and integrates it
        return Blocker(
            f"{unit} is still not among the units of the target: push it back, or change the plan",
            f"get {unit} back on the target (or change the plan and run l4 yolo review {plan_id})",
        )
    if reason == "target_missing" and not target_present:
        return Blocker("the target branch is still missing on origin: push it again first", "push the target branch")
    if reason.startswith("limit_"):
        return _limit_blocker(plan_id, live or state, plan, extend, now or _now())
    return None


def _limit_blocker(plan_id: str, state: PlanState, plan: Plan | None, extend: Extend, now: datetime) -> Blocker | None:
    """The limit that `--extend-*` leaves reached, from `limits.resume_allows`, the rule the plan step stops on (R3), so
    a resume is refused for the very limit the step would stop on again."""
    fallback = plan.limits.model_dump(mode="json") if plan else None
    data = extend.as_data()
    in_plan = plan.unit_ids() if plan else None
    hit = resume_allows(state, data, now=now, fallback=fallback, units=in_plan)
    if hit is None:
        return None
    after = state.model_copy(deep=True)  # the same extension, to word the message with the figures it would leave
    apply_extend(after, data)
    limits, used = effective_limits(after, fallback), after.used
    again = f"l4 yolo resume {plan_id} --reason TEXT"
    code = hit[0]
    if code == LIMIT_COST:
        message, flag = (
            f"the cost {_money(used.cost_usd)} has reached the limit {_money(limits.cost_usd)}: raise it",
            "--extend-cost USD",
        )
    elif code == LIMIT_RUNS:
        message, flag = f"{used.runs} runs have reached the limit {limits.runs}: raise it", "--extend-runs N"
    elif code == LIMIT_ATTEMPTS:
        found = reached_at(after, now=now, fallback=fallback, units=in_plan)
        unit = found[2] if found and found[2] else "a unit"
        message = (
            f"{unit} used {used.attempts.get(unit, 0)} attempts, the limit is {limits.attempts_of(unit)}: raise it"
        )
        flag = "--extend-attempts N"
    else:
        stamp = limits.deadline.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if limits.deadline else "the deadline"
        message, flag = f"the deadline {stamp} has passed: set a later one", "--extend-deadline ISO"
    return Blocker(f"{code}: {message} with {flag}", f"{again} {flag}")


def _held(ctx: _Ctx, own: str, own_state: PlanState | None = None) -> dict[str, str]:
    """unit id -> the plan file that already lists it (`plans.held_by`, R8), for admission's `held_by_other_plan`. The
    states are the plan refs as origin has them: a cancelled plan still holds its units."""
    states = {pid: fold_plan(pid, ctx.store(pid).read().events) for pid in list_plans(ctx.git, ctx.fetch_cfg)}
    if own_state is not None:
        states[own] = own_state
    held = held_by(states, plan_files_at(ctx.git, ctx.target_ref))
    return {unit: plan_id for unit, (plan_id, _) in held.items()}


# --- l4 yolo check -------------------------------------------------------------------------------------------------


def _print_findings(ctx: _Ctx, lines: Sequence[str]) -> None:
    for line in lines:
        ctx.say(f"  {line}")


def run_check(app: AppContext, *, plan: str) -> ExitCode:
    """Admit the plan at the target head; print the findings and the order. Exit 0 admitted, 2 not. No write."""
    plan_id = _plan_id(plan)
    ctx = _open(app)
    rev = _sync(ctx, who="check")
    file = _file(ctx, plan_id, "check")
    if file.plan is None:
        assert file.invalid is not None
        for error in file.invalid.errors:
            ctx.say(error)
        ctx.say(f"{plan_id}: not admitted")
        return ExitCode.USAGE_ERROR
    units = _read_units(ctx, rev, file.plan.known_ids(), intake=True)
    state = fold_plan(plan_id, ctx.store(plan_id).read().events)  # read-only: the plan's own merged units are done
    admission = admit(
        file.plan,
        known_units=units.infos,
        cfg=ctx.cfg,
        held=_held(ctx, plan_id),
        state=state,
        archived=archived_at(ctx.git, rev, ctx.cfg),
    )
    if not admission.ok:
        ctx.say(f"{plan_id}: not admitted ({len(admission.findings)} finding(s))")
        _print_findings(ctx, _findings_text(admission, plan_id))
        return ExitCode.USAGE_ERROR
    ctx.say(f"{plan_id}: admitted at origin/{ctx.target} {rev[:10]}")
    ctx.say(f"order: {', '.join(admission.order)}")
    return ExitCode.OK


# --- l4 yolo draft ---------------------------------------------------------------------------------------------------


def _sync_phases(app: AppContext, cfg: L4Config, git: Git) -> None:
    """Fetch the base branch and the unit refs the phases are read from (as the other `l4 yolo` commands do), so a fresh
    clone does not take a unit in review or merged for new work. No `origin`, or a fetch that fails: go on with the
    refs the checkout has, and say so in one line."""
    if git.run("remote", "get-url", "origin", check=False).returncode != 0:
        click.echo("draft: no origin to fetch from: the phases may be old")
        return
    try:
        fetch_unit_refs(app, cfg, git)
    except GitError as exc:
        click.echo(f"draft: could not fetch from origin ({fetch_cause(app, exc)}): the phases may be old")


def run_draft(
    app: AppContext, *, plan: str, target: str | None = None, merge: str | None = None, update: bool = False
) -> ExitCode:
    """Write `.l4/plans/<plan>.json` in the working tree from the specs the providers find there (design D15,
    L4-YOLO-018): no commit, no push, no model; it fetches the unit refs first (`_sync_phases`). Exit 0 written (or
    nothing to add), 2 refused."""
    plan_id = _plan_id(plan)
    app, cfg = load_app_config(app)
    path = app.repo / PLANS_DIR / f"{plan_id}.json"
    exists = path.exists() or path.is_symlink()
    if exists and not update:
        raise L4Exit(
            ExitCode.USAGE_ERROR, f"draft: {PLANS_DIR}/{plan_id}.json exists: use --update to add the new specs"
        )
    if update and (target is not None or merge is not None):
        raise L4Exit(ExitCode.USAGE_ERROR, "draft: --target and --merge set a new file; --update changes nothing else")
    git = Git(app.repo, environ=app.environ)
    _sync_phases(app, cfg, git)
    files = plan_files(app.repo)
    own = next((f for f in files if f.plan_id == plan_id), None)
    data: dict[str, Any] = {}
    if update:
        if not exists or own is None:
            raise L4Exit(ExitCode.USAGE_ERROR, f"draft: --update needs {PLANS_DIR}/{plan_id}.json (it does not exist)")
        if own.plan is None:
            assert own.invalid is not None
            raise L4Exit(
                ExitCode.USAGE_ERROR, "\n".join([*own.invalid.errors, f"draft: {plan_id} is not a valid plan"])
            )
        data = json.loads(own.text)
    found = [
        Found(snapshot.ref.id, snapshot.state.phase)
        for _, snapshot in discover(cfg, git, providers_for(cfg, app.repo, app.environ))
    ]
    if update:
        assert own is not None
        result = update_draft(data, found, files, own)
    else:
        mode: MergeMode = "auto" if merge == "auto" else "human"
        result = new_draft(plan_id, target=target or cfg.forge.base_branch, merge=mode, found=found, files=files)
    say = click.echo
    for unit in result.gone:
        say(f"gone: {unit}")
    if result.text is None:
        say(f"{plan_id}: nothing to add: every spec is listed or covered")
        return ExitCode.OK
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.text, encoding="utf-8")
    for unit in result.added:
        say(f"added: {unit}")
    for unit, reason in result.excluded:
        say(f"added: {unit} (excluded: {reason})")
    say(f"wrote {PLANS_DIR}/{plan_id}.json (not committed)")
    status = fold_plan(plan_id, local_plans(git).get(plan_id, [])).status
    if status in ("active", "waiting"):
        say(f"warning: plan {plan_id} is {status} here: pushing this edit stops it (inputs_changed)")
    say("Next:")
    say(
        f"  1. edit {PLANS_DIR}/{plan_id}.json: the dependencies, batches and exclusions (a dependency only on evidence"
    )
    say("     in the specs: the draft added none)")
    say("  2. python3 scripts/validate_plan.py (the skill ships a copy), then commit and push the plan file")
    say("     (new specs in the same commit, or after the plan file: one that lands without a plan runs at once)")
    say(f"  3. l4 yolo check {plan_id}, then l4 yolo review {plan_id}")
    return ExitCode.OK


# --- l4 yolo review ------------------------------------------------------------------------------------------------


def _verdict_json(verdict: Any) -> dict[str, Any]:
    return {
        "verdict": verdict.verdict,
        "digest": verdict.digest,
        "findings": [dict(f) for f in verdict.findings],
        "assumptions": list(verdict.assumptions),
        "missing": list(verdict.missing),
    }


def run_review(
    app: AppContext,
    *,
    plan: str,
    local: bool = False,
    no_run: bool = False,
    worktree: bool = False,
    record: bool = False,
    fresh: Sequence[str] = (),
) -> ExitCode:
    """Without `--local`: ask CI to review the plan (`start_run`); the review itself is the CI step's. With `--local`:
    admit and review here, recording `plan.admitted` and `plan.reviewed` (or `plan.refused`) as the CI step would.
    With `--worktree`: review the working tree (`review_worktree`); `--record` and `--fresh` need it (exit 2)."""
    if not worktree and (record or fresh):
        raise L4Exit(ExitCode.USAGE_ERROR, "review: --record and --fresh need --worktree")
    if worktree:
        from l4.yolo.review_worktree import run_review_worktree  # late: that module reads this one

        return run_review_worktree(app, plan=plan, fresh=tuple(fresh), record=record, no_run=no_run)
    plan_id = _plan_id(plan)
    ctx = _open(app)
    rev = _sync(ctx, who="review")
    file = _file(ctx, plan_id, "review")
    parsed = _valid(ctx, file, "review")
    store = ctx.store(plan_id)
    read = store.read()
    state = fold_plan(plan_id, read.events)
    if state.status in ("active", "waiting", "cancelled", "completed"):
        raise L4Exit(
            ExitCode.USAGE_ERROR, f"review: {plan_id} is {state.status}: a plan is reviewed before it is activated"
        )
    units = _read_units(ctx, rev, parsed.known_ids(), intake=True)
    admission = admit(
        parsed,
        known_units=units.infos,
        cfg=ctx.cfg,
        held=_held(ctx, plan_id, state),
        state=state,
        archived=archived_at(ctx.git, rev, ctx.cfg),
    )
    if not admission.ok:
        lines = _findings_text(admission, plan_id)
        if local:
            findings = [{"code": f.code, "subject": f.subject, "text": f.text} for f in admission.findings]
            _append(store, [_event("plan.refused", plan_digest=plan_digest(file.text), findings=findings)], read.head)
        ctx.say(f"{plan_id}: not admitted, nothing to review (run l4 yolo check {plan_id})")
        _print_findings(ctx, lines)
        return ExitCode.USAGE_ERROR
    now = _digests(ctx, parsed, units)
    if not local:
        seen, unit = _rejected_at(read.events, state), state.stop_unit or "a unit"
        if seen is not None and now.get(unit) == seen:  # R8: CI reviews the plan once the spec has changed
            ctx.say(
                f"{plan_id}: {unit} was rejected and its spec has not changed: fix the cause. A spec: push it, "
                f"the next run on {ctx.target} then stops the plan with inputs_changed and CI reviews it. "
                f"The configuration: nothing to review. Then l4 yolo activate {plan_id} --reason TEXT, and the "
                f"unit's next run reads the corrected spec or configuration"
            )
            return ExitCode.OK
        view = _review_view(parsed, file.text, state, read.events, now)
        if view.kind == "current":
            ctx.say(f"{plan_id}: already reviewed for these inputs ({'READY' if view.ready else 'not READY'})")
            _print_findings(ctx, view.problems)
            if view.problems:
                ctx.say(f"Next: l4 yolo findings {plan_id}")
            return ExitCode.OK
        if seen is not None:
            ctx.say(
                f"{plan_id}: the spec of {unit} changed; the next run on {ctx.target} records inputs_changed and CI "
                f"reviews the plan"
            )
        else:
            ctx.say(f"{plan_id}: review requested; CI reviews it at the next run on {ctx.target}")
        if not no_run:
            ctx.say(start_run_line(ctx.app, ctx.cfg))
        return ExitCode.OK
    try:
        result, cost = review_plan_costed(
            ctx.app,
            ctx.cfg,
            parsed,
            units.infos,
            git=ctx.git,
            rev=rev,
            done=done_units(parsed, state),
            delivered=delivered_on_target(archived_at(ctx.git, rev, ctx.cfg), units.phases),
        )
    except RoleLimit as exc:
        raise L4Exit(ExitCode.WAITING_CAPACITY, f"review: the judge hit a usage limit: {exc}") from None
    except RoleUnavailable as exc:  # a judge that timed out or failed too (R9): no review happened, none is recorded
        raise L4Exit(ExitCode.WAITING_CAPACITY, f"review: no judge could answer, nothing was recorded: {exc}") from None
    except RevisionMissing as exc:
        raise L4Exit(ExitCode.USAGE_ERROR, f"review: {exc}") from None
    digest = plan_digest(file.text)
    batches = review_batches(parsed, result)
    events = [
        _event("plan.admitted", plan_digest=digest, order=list(admission.order), merge=parsed.merge),
        _event(
            "plan.reviewed", plan_digest=digest, prompt_version=PROMPT_VERSION, cost_usd=cost, by=ctx.who(),
            units={u: _verdict_json(v) for u, v in result.units.items()},
            batches={b: _verdict_json(v) for b, v in batches.items()},
        ),
    ]  # fmt: skip
    if cost > 0:  # the judge's cost is the plan's (R1): the running total of `plan:review`, attempt 0
        before = max(
            (float(e.data.get("cost_usd") or 0) for e in read.events
             if e.type == "plan.charged" and e.data.get("unit") == REVIEW_KEY),
            default=0.0,
        )  # fmt: skip
        events.append(_event("plan.charged", unit=REVIEW_KEY, attempt=0, cost_usd=round(before + cost, 6), runs=0))
    _append(store, events, read.head)
    ctx.say(f"{plan_id}: reviewed here (${cost:.2f})")
    for name, verdict in [*result.units.items(), *((f"batch {b}", v) for b, v in batches.items())]:
        line = f"  {name}: {verdict.verdict}"
        ctx.say(line if verdict.verdict == "READY" else f"{line}: {_first_line(verdict.findings)}")
    if any(v.verdict != "READY" for v in (*result.units.values(), *batches.values())):
        ctx.say(f"Next: l4 yolo findings {plan_id}")
    else:
        ctx.say(f"Next: l4 yolo activate {plan_id} --reason TEXT")
    return ExitCode.OK


# --- l4 yolo activate ----------------------------------------------------------------------------------------------


def _others(ctx: _Ctx, own: str) -> dict[str, PlanState]:
    states: dict[str, PlanState] = {}
    for other in list_plans(ctx.git, ctx.fetch_cfg):
        if other != own:
            states[other] = fold_plan(other, ctx.store(other).read().events)
    return states


def run_activate(app: AppContext, *, plan: str, reason: str, no_run: bool = False) -> ExitCode:
    """Record `plan.activated` (design D6), then start a run on the target. Refused with exit 2 and the cause unless
    every condition of L4-YOLO-005 holds; nothing is recorded then."""
    if not reason.strip():
        raise L4Exit(ExitCode.USAGE_ERROR, "activate: --reason must say why")
    plan_id = _plan_id(plan)
    ctx = _open(app)
    rev = _sync(ctx, who="activate")
    file = _file(ctx, plan_id, "activate")
    parsed = _valid(ctx, file, "activate")
    store = ctx.store(plan_id)
    read = store.read()
    state = fold_plan(plan_id, read.events)
    if state.status in FINAL:
        raise L4Exit(ExitCode.USAGE_ERROR, f"activate: {plan_id} is {state.status}: it cannot be activated again")
    if state.status in ("active", "waiting"):
        raise L4Exit(ExitCode.USAGE_ERROR, f"activate: {plan_id} is already {state.status}")
    if state.status == "stopped" and state.stop_reason not in ("inputs_changed", "unit_rejected"):
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"activate: {plan_id} is stopped ({state.stop_reason}): run l4 yolo status {plan_id}, "
            f"then l4 yolo resume {plan_id} --reason TEXT",
        )
    units = _read_units(ctx, rev, parsed.known_ids(), intake=True)
    seen, rejected = _rejected_at(read.events, state), state.stop_unit
    stays = seen is not None and rejected in units.infos and units.phases.get(rejected) == "rejected"
    if stays and _now_digest(ctx, rejected, units.infos[rejected].folder) == seen:  # a restarted unit has no phase
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"activate: {rejected} was rejected, is still rejected and its spec has not changed: fix the spec and "
            f"push it, then l4 yolo review {plan_id} and l4 yolo activate {plan_id} --reason TEXT; or, when the cause "
            f"is the configuration, restart the unit (l4 restart --unit {rejected} --reason TEXT)",
        )
    admission = admit(
        parsed,
        known_units=units.infos,
        cfg=ctx.cfg,
        held=_held(ctx, plan_id, state),
        state=state,
        archived=archived_at(ctx.git, rev, ctx.cfg),
    )
    if not admission.ok:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            "\n".join(
                [f"activate: {plan_id} is not admitted:", *(f"  {t}" for t in _findings_text(admission, plan_id))]
            ),
        )
    now = _digests(ctx, parsed, units)
    view = _review_view(parsed, file.text, state, read.events, now)
    if view.kind == "none":
        raise L4Exit(ExitCode.USAGE_ERROR, f"activate: {plan_id} has not been reviewed: run l4 yolo review {plan_id}")
    if view.kind == "stale":
        why = "was made with an older review prompt" if view.prompt_changed else "is for other inputs"
        raise L4Exit(ExitCode.USAGE_ERROR, f"activate: review {why}: run l4 yolo review {plan_id}")
    if view.problems:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            "\n".join(
                [
                    f"activate: the review is not READY for {len(view.problems)} item(s):",
                    *(f"  {p}" for p in view.problems),
                    f"Next: l4 yolo findings {plan_id}",
                ]
            ),
        )
    if not _branch_on_origin(ctx, parsed.target):
        raise L4Exit(ExitCode.USAGE_ERROR, f"activate: the target {parsed.target} is not on origin")
    other = active_on(_others(ctx, plan_id), plan_files_at(ctx.git, ctx.target_ref), parsed.target)
    if other is not None:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"activate: plan {other.plan_id} is already active, waiting or stopped on {parsed.target}: "
            f"let it finish, or run l4 yolo cancel {other.plan_id} --reason TEXT first",
        )
    base = {u: n for u in parsed.unit_ids() if (n := attempt_refs(ctx.git, u, ctx.fetch_cfg)) is not None}
    # the current unit goes on only when the new order holds it and nothing it now waits for is open (review z1, H2)
    current = state.current
    if current is not None and (current not in admission.order or unit_blocker(parsed, state, current) is not None):
        current = None
    event = _event(
        "plan.activated", plan_digest=plan_digest(file.text), digests=now, limits=parsed.limits.model_dump(mode="json"),
        merge=parsed.merge, by=ctx.who(), reason=reason.strip(), attempt_base=base, current=current,
    )  # fmt: skip
    _append(store, [event], read.head)
    ctx.say(f"{plan_id}: activated on {parsed.target} ({len(parsed.unit_ids())} unit(s), merge: {parsed.merge})")
    if not no_run:
        ctx.say(start_run_line(ctx.app, ctx.cfg))
    return ExitCode.OK


# --- l4 yolo cancel, resume, report --------------------------------------------------------------------------------


def run_cancel(app: AppContext, *, plan: str, reason: str) -> ExitCode:
    """`plan.cancelled{by, reason}`: no new dispatch or merge, for good. Refused for a plan that is already final."""
    if not reason.strip():
        raise L4Exit(ExitCode.USAGE_ERROR, "cancel: --reason must say why")
    plan_id = _plan_id(plan)
    ctx = _open(app)
    store = ctx.store(plan_id)
    read = store.read()
    if read.head is None:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"cancel: {plan_id} has no record yet: remove .l4/plans/{plan_id}.json from the target to drop it",
        )
    state = fold_plan(plan_id, read.events)
    if state.status in FINAL:
        raise L4Exit(ExitCode.USAGE_ERROR, f"cancel: {plan_id} is already {state.status}")
    _append(store, [_event("plan.cancelled", by=ctx.who(), reason=reason.strip())], read.head)
    ctx.say(f"{plan_id}: cancelled; nothing more is dispatched or merged. A unit already running finishes its run.")
    return ExitCode.OK


def _extend(cost: float | None, runs: int | None, attempts: int | None, deadline: str | None) -> Extend:
    for flag, value in (("cost", cost), ("runs", runs), ("attempts", attempts)):
        if value is not None and value <= 0:
            raise L4Exit(ExitCode.USAGE_ERROR, f"resume: --extend-{flag} must be more than 0")
    when = None
    if deadline is not None:
        when = parse_time(deadline)
        if when is None:
            raise L4Exit(ExitCode.USAGE_ERROR, f"resume: --extend-deadline {deadline!r} is not an ISO 8601 time")
    return Extend(cost, runs, attempts, when)


def run_resume(
    app: AppContext, *, plan: str, reason: str, extend_cost: float | None = None, extend_runs: int | None = None,
    extend_attempts: int | None = None, extend_deadline: str | None = None, no_run: bool = False,
) -> ExitCode:  # fmt: skip
    """`plan.resumed{by, reason, extend}` from `stopped` or `waiting`, refused while the cause is still there (design
    D10's table), then a run on the target."""
    if not reason.strip():
        raise L4Exit(ExitCode.USAGE_ERROR, "resume: --reason must say why")
    plan_id = _plan_id(plan)
    extend = _extend(extend_cost, extend_runs, extend_attempts, extend_deadline)
    ctx = _open(app)
    store = ctx.store(plan_id)
    read = store.read()
    state = fold_plan(plan_id, read.events)
    if state.status not in ("stopped", "waiting"):
        raise L4Exit(
            ExitCode.USAGE_ERROR, f"resume: {plan_id} is {state.status}: only a stopped or waiting plan resumes"
        )
    on_origin = _branch_on_origin(ctx, ctx.target)
    parsed: Plan | None = None
    phases: dict[str, str | None] = {}
    units = _Units()
    if on_origin:
        rev = _sync(ctx, who="resume")
        file = next((f for f in plan_files_at(ctx.git, ctx.target_ref) if f.plan_id == plan_id), None)
        parsed = file.plan if file else None
        units = _read_units(ctx, rev, parsed.unit_ids() if parsed else [], intake=False)
        phases = units.phases
    live = None
    if on_origin and state.stop_reason and state.stop_reason.startswith("limit_"):
        live = _live_usage(ctx, state, read.events, units, state.stop_unit or state.current)  # what the step checks
    blocker = resume_blocker(
        plan_id, state, read.events, parsed, phases, extend, target_present=on_origin, now=_now(), live=live
    )
    if blocker is not None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"resume: {blocker.message}")
    _append(store, [_event("plan.resumed", by=ctx.who(), reason=reason.strip(), extend=extend.as_data())], read.head)
    ctx.say(f"{plan_id}: resumed")
    if not no_run:
        ctx.say(start_run_line(ctx.app, ctx.cfg))
    return ExitCode.OK


def run_report(app: AppContext, *, plan: str) -> ExitCode:
    """Print `report.md` of the plan ref, or `no report yet`."""
    plan_id = _plan_id(plan)
    ctx = _open(app)
    text = ctx.store(plan_id).read().files.get(REPORT_FILE)
    ctx.say(text.rstrip("\n") if text else "no report yet")
    return ExitCode.OK


# --- l4 yolo status ------------------------------------------------------------------------------------------------


def _next_line(plan_id: str, state: PlanState, view: ReviewView | None, blocker: Blocker | None) -> str:
    status = state.status
    if status == "stopped" and state.stop_reason == "unit_rejected":  # R8: the person fixes the cause first
        return (
            f"fix the cause of the rejection of {state.stop_unit or 'the unit'}: its spec (push it; the next run "
            f"records inputs_changed and CI reviews the plan) or the configuration, then l4 yolo activate {plan_id} "
            f"--reason TEXT"
        )
    if status in _BEFORE_ACTIVATION or (
        status == "stopped" and state.stop_reason in ("inputs_changed", "unit_rejected")
    ):
        if status == "refused":
            return f"fix the findings (l4 yolo check {plan_id}), push the plan, then l4 yolo review {plan_id}"
        if view is None or view.kind != "current":
            return f"l4 yolo review {plan_id}"
        if view.problems:
            return (
                f"l4 yolo findings {plan_id}: fix the specs it names and push them, or review the working tree "
                f"first (l4 yolo review {plan_id} --worktree)"
            )
        return f"l4 yolo activate {plan_id} --reason TEXT"
    if status == "waiting" and state.wait_reason == "run_not_started":
        return (
            "fix the cause of the failed run named above (the configuration, the runner, the unit branch); the next "
            f"trigger, a cron run or a push, runs the unit once more (l4 yolo resume {plan_id} --reason TEXT wakes the "
            "plan at once)"
        )
    if status == "waiting" and state.wait_reason == "unit_not_started":
        return (
            "fix the unit on its branch (add the task, repair the ledger); the plan continues by itself at the next "
            f"run when the unit has something to run (l4 yolo resume {plan_id} --reason TEXT wakes it at once, but "
            "it waits again if the unit still has nothing to run)"
        )
    if status in ("waiting", "stopped"):
        resume = f"l4 yolo resume {plan_id} --reason TEXT"
        if blocker and blocker.fix.startswith(resume.split(" --")[0]):
            return blocker.fix  # a limit: the fix is the resume itself, with the flag
        return f"{blocker.fix}, then {resume}" if blocker else resume
    if status == "active":
        return f"nothing: CI advances the plan at each run (l4 yolo cancel {plan_id} --reason TEXT stops it)"
    if status == "completed":
        return f"the plan is complete: l4 yolo report {plan_id}; promotion is yours"
    return "none: the plan is cancelled"


def _describe(
    ctx: _Ctx, rev: str | None, file: PlanFile | None, read: PlanRead, pid: str, units: _Units
) -> dict[str, Any]:
    state = fold_plan(pid, read.events)
    plan = file.plan if file else None
    out: dict[str, Any] = {
        "plan_id": pid, "status": state.status, "target": plan.target if plan else None,
        "merge": plan.merge if plan else state.merge, "activated_by": state.activated_by,
    }  # fmt: skip
    if file is not None and file.invalid is not None:
        held = readable_unit_ids(file.text)  # R8: an invalid plan file still holds the units its JSON names
        out["problems"] = [
            *file.invalid.errors,
            "this file is not a JSON object: it holds no unit" if held is None
            else f"this file is not a plan, but it holds the units it names: {', '.join(held) or 'none'}",
        ]  # fmt: skip
    if file is None:
        out["problems"] = [f"{pid}: no plan file on origin/{ctx.target}"]
    limits = effective_limits(state, plan.limits.model_dump(mode="json") if plan else None)
    used = state.used
    if rev is not None and state.status in ("active", "waiting", "stopped") and state.current:
        used = _live_usage(ctx, state, read.events, units, state.current).used  # the figures the step checks
    out["usage"] = {
        "cost_usd": used.cost_usd, "cost_limit": limits.cost_usd, "runs": used.runs,
        "runs_limit": limits.runs,
        "attempts": dict(used.attempts), "attempts_limit": limits.attempts,
        "deadline": limits.deadline.strftime("%Y-%m-%dT%H:%M:%SZ") if limits.deadline else None,
    }  # fmt: skip
    view = None
    if plan is not None and file is not None and rev is not None:
        needs_review = state.status in _BEFORE_ACTIVATION or (
            state.status == "stopped" and state.stop_reason in ("inputs_changed", "unit_rejected")
        )  # only there a review under an older prompt means a new review
        view = _review_view(
            plan, file.text, state, read.events, _digests(ctx, plan, units), prompt_matters=needs_review
        )
        out["review"] = {"state": view.kind, "problems": list(view.problems)}
        if view.prompt_changed:
            out["review"]["prompt_changed"] = True
        waiting = next_eligible(plan, state, units.phases).waiting
        rows = []
        for uid in plan.unit_ids():
            phase = units.phases.get(uid)
            row: dict[str, Any] = {"id": uid, "phase": phase, "current": state.current == uid}
            if uid in state.integrated:
                row["integrated"] = state.integrated[uid]
            elif uid in state.merged:
                row["merged"] = state.merged[uid]
            if uid not in state.integrated and state.status in _BEFORE_ACTIVATION:
                row["waits"] = f"held by plan {pid} ({state.status})"
            elif uid not in state.integrated and uid in waiting:
                row["waits"] = waiting[uid]
            rows.append(row)
        out["units"] = rows
        out["excluded"] = [{"id": x.id, "reason": x.reason} for x in plan.exclude]
        out["batches"] = [
            {
                "id": b.id, "units": [u.id for u in b.units],
                "result": "accepted" if b.id in state.accepted_batches else "failed" if b.id in state.failed_batches
                else "pending",
                "revision": state.accepted_batches.get(b.id), "detail": state.failed_batches.get(b.id),
            }
            for b in plan.batches
        ]  # fmt: skip
    if state.status == "stopped":
        out["stop"] = {"reason": state.stop_reason, "detail": state.stop_detail, "unit": state.stop_unit}
    if state.status == "waiting":
        out["wait"] = state.wait_reason
        waiting = next((e for e in reversed(read.events) if e.type == "plan.waiting"), None)
        if waiting is not None and waiting.data.get("detail"):
            out["wait_detail"] = str(waiting.data["detail"])
    blocker = None
    if state.status in ("stopped", "waiting"):
        live = None
        if rev is not None and (state.stop_reason or "").startswith("limit_"):
            live = _live_usage(ctx, state, read.events, units, state.stop_unit or state.current)
        blocker = resume_blocker(pid, state, read.events, plan, units.phases, Extend(), now=_now(), live=live)
    out["next"] = _next_line(pid, state, view, blocker)
    return out


def _render(d: dict[str, Any]) -> str:
    head = f"plan {d['plan_id']}: {d['status']}"
    if d.get("target"):
        head += f" (target {d['target']}, merge: {d['merge']})"
    lines = [head, *(f"  {p}" for p in d.get("problems", []))]
    if d.get("activated_by"):
        lines.append(f"  activated by {d['activated_by']}")
    if "review" in d and d["status"] in (*_BEFORE_ACTIVATION, "stopped"):
        changed = " (the review prompt changed)" if d["review"].get("prompt_changed") else ""
        lines.append(f"  review: {d['review']['state']}{changed}")
        lines += [f"    {p}" for p in d["review"]["problems"]]
    if d.get("stop"):
        stop = d["stop"]
        unit = f" [{stop['unit']}]" if stop.get("unit") else ""
        lines.append(f"  stopped: {stop['reason']}{unit}" + (f": {stop['detail']}" if stop.get("detail") else ""))
    if d.get("wait"):
        lines.append(f"  waiting: {d['wait']}" + (f": {d['wait_detail']}" if d.get("wait_detail") else ""))
    if d.get("units"):
        lines.append("  units:")
        for u in d["units"]:
            state = u["phase"] or "not started"
            if "integrated" in u:
                state = f"integrated at {u['integrated'][:10]}"
            elif "merged" in u:
                state = f"merged at {u['merged'][:10]}, post-merge check pending"
            mark = " (current)" if u["current"] else ""
            wait = f"; {u['waits']}" if u.get("waits") else ""
            lines.append(f"    {u['id']}: {state}{mark}{wait}")
    lines += [f"  excluded: {x['id']} ({x['reason']})" for x in d.get("excluded", [])]
    multi = [b for b in d.get("batches", []) if len(b["units"]) > 0]
    if multi:
        lines.append("  batches:")
        for b in multi:
            tail = f" at {b['revision'][:10]}" if b.get("revision") else f": {b['detail']}" if b.get("detail") else ""
            lines.append(f"    {b['id']}: {b['result']}{tail}")
    use = d["usage"]
    attempts = ", ".join(f"{u} {n}" for u, n in use["attempts"].items()) or "none"
    lines.append(
        f"  usage: {_money(use['cost_usd'])} of {_money(use['cost_limit'])}; "
        f"runs {use['runs']} of {use['runs_limit'] if use['runs_limit'] is not None else 'unlimited'}; "
        f"attempts {attempts} (limit {use['attempts_limit']} each)"
        + (f"; deadline {use['deadline']}" if use["deadline"] else "")
    )
    lines.append(f"Next: {d['next']}")
    return "\n".join(lines)


def run_status(app: AppContext, *, plan: str | None = None, as_json: bool = False) -> ExitCode:
    """The status of one plan, or of every plan file on the target (and every plan ref without a file)."""
    wanted = _plan_id(plan) if plan else None
    ctx = _open(app)
    rev = _sync(ctx, who="status")
    files = {f.plan_id: f for f in plan_files_at(ctx.git, ctx.target_ref)}
    ids = [wanted] if wanted else sorted({*files, *list_plans(ctx.git, ctx.fetch_cfg)})
    if wanted and wanted not in files and wanted not in list_plans(ctx.git, ctx.fetch_cfg):
        raise L4Exit(ExitCode.USAGE_ERROR, f"status: no plan {wanted} on origin/{ctx.target}")
    every = [u for f in files.values() if f.plan for u in f.plan.unit_ids()]
    units = _read_units(ctx, rev, every, intake=False)
    described = [_describe(ctx, rev, files.get(pid), ctx.store(pid).read(), pid, units) for pid in ids]
    if as_json:
        ctx.say(json.dumps({"schema": "l4/yolo-status@1", "target": ctx.target, "plans": described}, indent=2))
    elif not described:
        ctx.say(f"no plan file on origin/{ctx.target}")
    else:
        ctx.say("\n\n".join(_render(d) for d in described))
    return ExitCode.OK


# --- `l4 status` and `l4 doctor`: from the plan refs this checkout already has ---------------------------------------


def local_plans(git: Git) -> dict[str, list[PlanEvent]]:
    """The ledgers of the plan refs in this checkout (`refs/l4/plans/*`), no network. A ref that cannot be read is
    left out."""
    names = git.run("for-each-ref", "--format=%(refname)", PLAN_REF_PREFIX, check=False).stdout.split()
    plans: dict[str, list[PlanEvent]] = {}
    for ref in names:
        plan_id = ref.removeprefix(PLAN_REF_PREFIX)
        shown = git.run("show", f"{ref}:{LEDGER_FILE}", check=False)
        if shown.returncode != 0 or not PLAN_ID.match(plan_id):
            continue
        try:
            plans[plan_id] = parse_ledger(shown.stdout)
        except ValueError as exc:
            log.warning("plan %s: %s", plan_id, exc)
    return plans


def plan_lines(repo: Path, git: Git, phases: Mapping[str, str | None], cfg: L4Config | None = None) -> list[str]:
    """`plan <id>: <status>[, unit U (<phase>)], <integrated>/<total> integrated, $<used>/$<limit>` for each plan with a
    ref in this checkout that is not final (L4-YOLO-015). `phases` is unit id -> phase. The plan files are the target's
    (`cfg` given, as the plan step reads them), else the working tree's."""
    try:
        files = {f.plan_id: f for f in _plan_files_of(repo, git, cfg)}
        ledgers = local_plans(git)
    except GitError:
        return []
    lines = []
    for pid in sorted(ledgers):
        state = fold_plan(pid, ledgers[pid])
        if state.status in FINAL:
            continue
        plan = files[pid].plan if pid in files else None
        total = len(plan.unit_ids()) if plan else len(state.order)
        unit = f", unit {state.current} ({phases.get(state.current) or '-'})" if state.current else ""
        cost = effective_limits(state, plan.limits.model_dump(mode="json") if plan else None).cost_usd
        limit = "unlimited" if cost is None else f"${cost:.2f}"
        lines.append(
            f"plan {pid}: {state.status}{unit}, {len(state.integrated)}/{total} integrated, "
            f"${state.used.cost_usd:.2f}/{limit}"
        )
    return lines


def _plan_files_of(repo: Path, git: Git, cfg: L4Config | None) -> list[PlanFile]:
    """The plan files the plan step reads (`cycle.target_plan_files`) when the configuration is known, else the
    working tree's."""
    if cfg is None:
        return plan_files(repo)
    ref = plan_source(cfg, git)
    return plan_files(repo) if ref is None else plan_files_at(git, ref)


def auto_merge_plan_active(repo: Path, git: Git, cfg: L4Config | None = None) -> bool:
    """Is some plan with `merge: auto` active, waiting or stopped in this checkout's plan refs (L4-YOLO-008)? The merge
    mode is the plan file's (the target's when `cfg` is given, else the working tree's), else what the ledger
    recorded."""
    files = {f.plan_id: f for f in _plan_files_of(repo, git, cfg)}
    for pid, events in local_plans(git).items():
        state = fold_plan(pid, events)
        if state.status not in _HOLDING:
            continue
        merge = files[pid].plan.merge if pid in files and files[pid].plan else state.merge
        if merge == "auto":
            return True
    return False


# --- l4 yolo findings ----------------------------------------------------------------------------------------------


def _stdin_tty() -> bool:
    return bool(sys.stdin is not None and sys.stdin.isatty())


def _latest_review(events: Sequence[PlanEvent]) -> dict[str, Any] | None:
    return next((dict(e.data) for e in reversed(events) if e.type == "plan.reviewed"), None)


def _entry_of(review: Mapping[str, Any], subject: str) -> dict[str, Any] | None:
    """The subject's entry (`<unit id>` or `batch:<id>`) in the data of a `plan.reviewed` event."""
    if subject.startswith("batch:"):
        entry = (review.get("batches") or {}).get(subject[len("batch:") :])
    else:
        entry = (review.get("units") or {}).get(subject)
    return entry if isinstance(entry, dict) and entry.get("verdict") is not None else None


def _subject_infos(plan: Plan | None, units: _Units | None) -> dict[str, fnd.UnitInfo]:
    """What `findings.render` needs to write the `Resolve:` lines: the folder, the batch and the `depends_on` of each
    unit, and the batch of a `batch:<id>` subject."""
    infos: dict[str, fnd.UnitInfo] = {}
    if plan is None:
        return infos
    for batch in plan.batches:
        infos[f"batch:{batch.id}"] = fnd.UnitInfo(batch=batch.id)
        for unit in batch.units:
            known = units.infos.get(unit.id) if units else None
            infos[unit.id] = fnd.UnitInfo(
                folder=known.folder if known else None, batch=batch.id, depends_on=tuple(unit.depends_on)
            )
    return infos


def _acceptor(ctx: _Ctx, state: PlanState, events: Sequence[PlanEvent], review: Mapping[str, Any]) -> Any:
    """`can_accept(subject)` for `findings.render`: would `accept.check` let this caller accept the subject now?"""
    who = accepting.actor(ctx.app.environ, _stdin_tty())
    target = accepting.target_config(ctx.git, ctx.target_ref)

    def can_accept(subject: str) -> bool:
        entry = _entry_of(review, subject)
        if entry is None:
            return False
        judged = fnd.judged(fnd.history(events, subject, PROMPT_VERSION))
        return accepting.check(state, judged, subject, entry, target, who) is None

    return can_accept


def run_findings(app: AppContext, *, plan: str, subject: str | None, show_all: bool, as_json: bool) -> ExitCode:
    """`l4 yolo findings PLAN [SUBJECT] [--all] [--json]`: the findings of the latest review, each with how to resolve
    it (L4-YOLO-021). Reads the ledger and the plan file; calls no model and writes nothing. Exit 2 for an unknown plan
    or subject, else 0 (a plan with no review included)."""
    plan_id = _plan_id(plan)
    ctx = _open(app)
    rev = _sync(ctx, who="findings")
    file = next((f for f in plan_files_at(ctx.git, ctx.target_ref) if f.plan_id == plan_id), None)
    read = ctx.store(plan_id).read()
    if file is None and read.head is None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"findings: no plan {plan_id} on origin/{ctx.target}")
    state = fold_plan(plan_id, read.events)
    review = _latest_review(read.events)
    if review is None:
        if as_json:
            empty = {"schema": fnd.SCHEMA, "plan": plan_id, "base": ctx.target, "plan_digest": None, "subjects": []}
            ctx.say(json.dumps(empty, indent=2))
        else:
            ctx.say(f"{plan_id}: no review yet (l4 yolo review {plan_id}, or --worktree before the push)")
        return ExitCode.OK
    if subject is not None and _entry_of(review, subject) is None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"findings: {subject} is not in the latest review of {plan_id}")
    parsed = file.plan if file is not None else None
    units = _read_units(ctx, rev, parsed.known_ids(), intake=False) if parsed is not None else None
    options: dict[str, Any] = {
        "show_all": show_all,
        "units": _subject_infos(parsed, units),
        "accepted": state.accepted,
        "holds": accepting.holds(state, review),
        "can_accept": _acceptor(ctx, state, read.events, review),
        "only": subject,
    }

    def history_of(name: str) -> list[dict[str, Any]]:
        return fnd.history(read.events, name, PROMPT_VERSION)

    if as_json:
        ctx.say(json.dumps(fnd.render_json(plan_id, ctx.target, review, history_of, **options), indent=2))
        return ExitCode.OK
    lines = fnd.render(plan_id, ctx.target, review, history_of, **options)
    if lines:
        for line in lines:
            ctx.say(line)
    else:
        ctx.say(f"{plan_id}: every subject of the latest review is READY (--all lists them)")
    return ExitCode.OK


MAX_REASON = 1000


def _digests_of(entry: Mapping[str, Any]) -> dict[str, str]:
    """The digests an entry judged: a batch's `digests`, else the unit's own."""
    digests = entry.get("digests")
    if isinstance(digests, Mapping):
        return {str(k): str(v) for k, v in digests.items()}
    return {}


def run_accept(app: AppContext, *, plan: str, subject: str, reason: str, withdraw: bool, yes: bool) -> ExitCode:
    """`l4 yolo accept PLAN SUBJECT --reason TEXT [--withdraw] [--yes]`: record that a person (or, when the target's
    configuration allows it, an agent) accepts the latest verdict of one subject as it is (L4-YOLO-027, design D7).
    Reads as `activate` does and writes one event with the lease. A person sees every finding of the subject and
    types the plan id; `--yes` replaces that only for an agent that `yolo.review.accept_by_agents` lets accept.
    Exit 2 for every refusal, with the cause and the fix; nothing is recorded then."""
    text = reason.strip()
    if not text:
        raise L4Exit(ExitCode.USAGE_ERROR, "accept: --reason must say why (what the implementer should do)")
    if len(text) > MAX_REASON:
        raise L4Exit(ExitCode.USAGE_ERROR, f"accept: --reason has {len(text)} characters; at most {MAX_REASON}")
    plan_id = _plan_id(plan)
    ctx = _open(app)
    _sync(ctx, who="accept")
    _valid(ctx, _file(ctx, plan_id, "accept"), "accept")
    store = ctx.store(plan_id)
    read = store.read()
    state = fold_plan(plan_id, read.events)
    who = accepting.actor(ctx.app.environ, _stdin_tty())
    if withdraw:
        if subject not in state.accepted:
            raise L4Exit(ExitCode.USAGE_ERROR, f"accept: {subject} has no acceptance: nothing to withdraw")
        event = _event("plan.acceptance_withdrawn", subject=subject, reason=text, by=ctx.who(), actor=who[0])
        _append(store, [event], read.head)
        ctx.say(f"{plan_id}: the acceptance of {subject} is withdrawn")
        ctx.say(f"Next: l4 yolo review {plan_id}")
        return ExitCode.OK
    review = _latest_review(read.events)
    if review is None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"accept: {plan_id} has no review yet: run l4 yolo review {plan_id}")
    latest = _entry_of(review, subject)
    if latest is None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"accept: {subject} is not in the latest review of {plan_id}")
    judged = fnd.judged(fnd.history(read.events, subject, PROMPT_VERSION))
    refusal = accepting.check(state, judged, subject, latest, accepting.target_config(ctx.git, ctx.target_ref), who)
    if refusal is not None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"accept: {refusal.message}\nFix: {refusal.fix}")
    if latest.get("material") is None:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"accept: the review of {subject} predates material keys, so an acceptance could not be bound to it\n"
            f"Fix: l4 yolo review {plan_id}",
        )
    if who[0] == "person":
        _show_and_confirm(ctx, plan_id, subject, review, read.events, state)
    elif not yes:
        raise L4Exit(
            ExitCode.USAGE_ERROR, "accept: no terminal to ask the plan id on: an agent that may accept passes --yes"
        )
    found = [dict(f) for f in latest.get("findings") or []]
    event = _event(
        "plan.accepted", subject=subject, material=latest["material"], prompt_version=PROMPT_VERSION,
        plan_digest=review.get("plan_digest"), digests=_digests_of(latest) or ({subject: latest.get("digest")}),
        verdict=latest["verdict"], findings=found, findings_sha=fnd.findings_sha(found), reason=text, by=ctx.who(),
        actor=who[0], marker=who[1], rounds=fnd.rounds_not_ready(read.events, subject),
    )  # fmt: skip
    _append(store, [event], read.head)
    ctx.say(f"accepted: {subject} by {event.data['by']} ({who[0]}): {text}")
    ctx.say(f"Next: l4 yolo status {plan_id}")
    return ExitCode.OK


def _show_and_confirm(
    ctx: _Ctx, plan_id: str, subject: str, review: Mapping[str, Any], events: Sequence[PlanEvent], state: PlanState
) -> None:
    """Print every finding of the subject, then ask for the plan id; any other answer exits 2 with nothing recorded."""
    lines = fnd.render(
        plan_id, ctx.target, review, lambda name: fnd.history(events, name, PROMPT_VERSION), show_all=True,
        only=subject, accepted=state.accepted, holds=accepting.holds(state, review),
    )  # fmt: skip
    for line in lines:
        ctx.say(line)
    answer = click.prompt(
        f"Type the plan id ({plan_id}) to accept the findings of {subject} as they are", default="", show_default=False
    )
    if str(answer).strip() != plan_id:
        raise L4Exit(ExitCode.USAGE_ERROR, "accept: the plan id was not typed: nothing was recorded")


__all__ = [
    "Blocker",
    "Extend",
    "PlanInvalid",
    "ReviewView",
    "auto_merge_plan_active",
    "local_plans",
    "plan_lines",
    "resume_blocker",
    "run_activate",
    "run_cancel",
    "run_check",
    "run_accept",
    "run_draft",
    "run_findings",
    "run_report",
    "run_resume",
    "run_review",
    "run_status",
]
