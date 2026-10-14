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
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

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
from l4.vcs.names import unit_branch
from l4.yolo.admit import admit, next_eligible
from l4.yolo.digest import plan_digest, unit_digest
from l4.yolo.model import (
    PLAN_ID,
    PLAN_REF_PREFIX,
    Admission,
    Plan,
    PlanEvent,
    PlanInvalid,
    PlanMoved,
    PlanState,
    UnitInfo,
)
from l4.yolo.plans import FINAL, PlanFile, active_on, plan_files, plan_files_at, unit_infos
from l4.yolo.readiness import review_plan_costed
from l4.yolo.state import fold_plan
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
    return _Units(infos, phases)


def _now_digest(ctx: _Ctx, rev: str, unit_id: str, folder: str) -> str:
    """The digest of a unit now (design D3): on its branch when it has one on origin, else on the target head."""
    ref = f"refs/remotes/origin/{unit_branch(unit_id, ctx.cfg.forge.branch_prefix)}"
    return unit_digest(ctx.git, ref if ctx.git.rev_parse(ref) else rev, folder)


def _digests(ctx: _Ctx, rev: str, plan: Plan, units: _Units) -> dict[str, str]:
    return {u: _now_digest(ctx, rev, u, units.infos[u].folder) for u in plan.unit_ids() if u in units.infos}


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

    @property
    def ready(self) -> bool:
        return self.kind == "current" and not self.problems


def _first_line(findings: Any) -> str:
    rows = [f for f in findings or [] if isinstance(f, dict)]
    rows.sort(key=lambda f: 0 if f.get("severity") == "blocking" else 1)
    if not rows:
        return "no finding recorded"
    text = str(rows[0].get("text") or "").strip().splitlines()
    criterion = rows[0].get("criterion")
    head = text[0] if text else "no text"
    return f"{criterion}: {head}" if criterion else head


def _review_view(
    plan: Plan, text: str, state: PlanState, events: Sequence[PlanEvent], now: Mapping[str, str]
) -> ReviewView:
    if state.review_plan_digest is None:
        return ReviewView("none")
    wanted = [u for u in plan.unit_ids()] + [f"batch:{b.id}" for b in plan.batches if len(b.units) > 1]
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


@dataclass(frozen=True)
class Limits:
    """The limits in force: those frozen at activation (or the plan file's before) plus what `resume` extended."""

    cost: float | None
    runs: int | None
    attempts: int
    deadline: datetime | None
    extra_attempts: Mapping[str, int] = field(default_factory=dict)  # unit or "*" -> added attempts

    def attempts_of(self, unit: str) -> int:
        return self.attempts + self.extra_attempts.get("*", 0) + self.extra_attempts.get(unit, 0)


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def limits_of(plan: Plan | None, state: PlanState, events: Sequence[PlanEvent]) -> Limits:
    frozen = state.limits or (plan.limits.model_dump(mode="json") if plan else {})
    cost, runs = frozen.get("max_cost_usd"), frozen.get("max_runs")
    deadline = _when(frozen.get("deadline"))
    for event in events:  # `Usage` has no deadline: the latest later one in `plan.resumed` wins
        later = _when((event.data.get("extend") or {}).get("deadline")) if event.type == "plan.resumed" else None
        if later is not None and (deadline is None or later > deadline):
            deadline = later
    return Limits(
        None if cost is None else float(cost) + state.extended.cost_usd,
        None if runs is None else int(runs) + state.extended.runs,
        int(frozen.get("max_unit_attempts", 2)),
        deadline,
        dict(state.extended.attempts),
    )


def _money(value: float | None) -> str:
    return "unlimited" if value is None else f"${value:.2f}"


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


def _limit_name(reason: str) -> str | None:
    name = reason.removeprefix("limit_")
    for key, word in (("cost", "cost"), ("runs", "run"), ("attempts", "attempt"), ("deadline", "deadline")):
        if word in name:
            return key
    return None


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
) -> Blocker | None:
    """The cause that is still there, per design D10's table; None when a resume may go."""
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
    if reason == "target_missing" and not target_present:
        return Blocker("the target branch is still missing on origin: push it again first", "push the target branch")
    if reason.startswith("limit_"):
        return _limit_blocker(plan_id, reason, state, events, plan, extend, now or _now())
    return None


def _limit_blocker(
    plan_id: str, reason: str, state: PlanState, events: Sequence[PlanEvent], plan: Plan | None, extend: Extend,
    now: datetime,
) -> Blocker | None:  # fmt: skip
    limits = limits_of(plan, state, events)
    used = state.used
    again = f"l4 yolo resume {plan_id} --reason TEXT"
    kind = _limit_name(reason)
    if kind == "cost" and limits.cost is not None:
        new = limits.cost + (extend.cost or 0.0)
        if used.cost_usd >= new:
            return Blocker(
                f"{reason}: the cost {_money(used.cost_usd)} has reached the limit {_money(new)}: "
                f"raise it with --extend-cost USD",
                f"{again} --extend-cost USD",
            )
    elif kind == "runs" and limits.runs is not None:
        new_runs = limits.runs + (extend.runs or 0)
        if used.runs >= new_runs:
            return Blocker(
                f"{reason}: {used.runs} runs have reached the limit {new_runs}: raise it with --extend-runs N",
                f"{again} --extend-runs N",
            )
    elif kind == "attempts":
        over = [state.stop_unit] if state.stop_unit else list(used.attempts)
        for unit in over:
            allowed = limits.attempts_of(unit) + (extend.attempts or 0)
            if used.attempts.get(unit, 0) > allowed:
                return Blocker(
                    f"{reason}: {unit} used {used.attempts[unit]} attempts, the limit is {allowed}: "
                    f"raise it with --extend-attempts N",
                    f"{again} --extend-attempts N",
                )
    elif kind == "deadline":
        new_deadline = extend.deadline or limits.deadline
        if new_deadline is not None and new_deadline <= now:
            return Blocker(
                f"{reason}: the deadline {new_deadline:%Y-%m-%dT%H:%M:%SZ} has passed: "
                f"set a later one with --extend-deadline ISO",
                f"{again} --extend-deadline ISO",
            )
    return None


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
    units = _read_units(ctx, rev, file.plan.unit_ids(), intake=True)
    admission = admit(file.plan, known_units=units.infos, cfg=ctx.cfg)
    if not admission.ok:
        ctx.say(f"{plan_id}: not admitted ({len(admission.findings)} finding(s))")
        _print_findings(ctx, _findings_text(admission, plan_id))
        return ExitCode.USAGE_ERROR
    ctx.say(f"{plan_id}: admitted at origin/{ctx.target} {rev[:10]}")
    ctx.say(f"order: {', '.join(admission.order)}")
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


def run_review(app: AppContext, *, plan: str, local: bool = False, no_run: bool = False) -> ExitCode:
    """Without `--local`: ask CI to review the plan (`start_run`); the review itself is the CI step's. With `--local`:
    admit and review here, recording `plan.admitted` and `plan.reviewed` (or `plan.refused`) as the CI step would."""
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
    units = _read_units(ctx, rev, parsed.unit_ids(), intake=True)
    admission = admit(parsed, known_units=units.infos, cfg=ctx.cfg)
    if not admission.ok:
        lines = _findings_text(admission, plan_id)
        if local:
            findings = [{"code": f.code, "subject": f.subject, "text": f.text} for f in admission.findings]
            _append(store, [_event("plan.refused", plan_digest=plan_digest(file.text), findings=findings)], read.head)
        ctx.say(f"{plan_id}: not admitted, nothing to review (run l4 yolo check {plan_id})")
        _print_findings(ctx, lines)
        return ExitCode.USAGE_ERROR
    now = _digests(ctx, rev, parsed, units)
    if not local:
        view = _review_view(parsed, file.text, state, read.events, now)
        if view.kind == "current":
            ctx.say(f"{plan_id}: already reviewed for these inputs ({'READY' if view.ready else 'not READY'})")
            _print_findings(ctx, view.problems)
            return ExitCode.OK
        ctx.say(f"{plan_id}: review requested; CI reviews it at the next run on {ctx.target}")
        if not no_run:
            ctx.say(start_run_line(ctx.app, ctx.cfg))
        return ExitCode.OK
    by_folder = {info.folder: uid for uid, info in units.infos.items()}
    try:
        result, cost = review_plan_costed(
            ctx.app, ctx.cfg, parsed, units.infos, git=ctx.git, rev=rev,
            digest_of=lambda _git, _rev, folder: _now_digest(ctx, rev, by_folder[folder], folder),
        )  # fmt: skip
    except RoleLimit as exc:
        raise L4Exit(ExitCode.WAITING_CAPACITY, f"review: the judge hit a usage limit: {exc}") from None
    digest = plan_digest(file.text)
    events = [
        _event("plan.admitted", plan_digest=digest, order=list(admission.order), merge=parsed.merge),
        _event(
            "plan.reviewed", plan_digest=digest, cost_usd=cost, by=ctx.who(),
            units={u: _verdict_json(v) for u, v in result.units.items()},
            batches={b: _verdict_json(v) for b, v in result.batches.items()},
        ),
    ]  # fmt: skip
    _append(store, events, read.head)
    ctx.say(f"{plan_id}: reviewed here (${cost:.2f})")
    for name, verdict in [*result.units.items(), *((f"batch {b}", v) for b, v in result.batches.items())]:
        line = f"  {name}: {verdict.verdict}"
        ctx.say(line if verdict.verdict == "READY" else f"{line}: {_first_line(verdict.findings)}")
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
    units = _read_units(ctx, rev, parsed.unit_ids(), intake=True)
    admission = admit(parsed, known_units=units.infos, cfg=ctx.cfg)
    if not admission.ok:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            "\n".join(
                [f"activate: {plan_id} is not admitted:", *(f"  {t}" for t in _findings_text(admission, plan_id))]
            ),
        )
    now = _digests(ctx, rev, parsed, units)
    view = _review_view(parsed, file.text, state, read.events, now)
    if view.kind == "none":
        raise L4Exit(ExitCode.USAGE_ERROR, f"activate: {plan_id} has not been reviewed: run l4 yolo review {plan_id}")
    if view.kind == "stale":
        raise L4Exit(ExitCode.USAGE_ERROR, f"activate: review is for other inputs: run l4 yolo review {plan_id}")
    if view.problems:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            "\n".join(
                [
                    f"activate: the review is not READY for {len(view.problems)} item(s):",
                    *(f"  {p}" for p in view.problems),
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
    event = _event(
        "plan.activated", plan_digest=plan_digest(file.text), digests=now, limits=parsed.limits.model_dump(mode="json"),
        merge=parsed.merge, by=ctx.who(), reason=reason.strip(),
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
        when = _when(deadline)
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
    if on_origin:
        rev = _sync(ctx, who="resume")
        file = next((f for f in plan_files_at(ctx.git, ctx.target_ref) if f.plan_id == plan_id), None)
        parsed = file.plan if file else None
        phases = _read_units(ctx, rev, parsed.unit_ids() if parsed else [], intake=False).phases
    blocker = resume_blocker(plan_id, state, read.events, parsed, phases, extend, target_present=on_origin, now=_now())
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
    if status in _BEFORE_ACTIVATION or (
        status == "stopped" and state.stop_reason in ("inputs_changed", "unit_rejected")
    ):
        if status == "refused":
            return f"fix the findings (l4 yolo check {plan_id}), push the plan, then l4 yolo review {plan_id}"
        if view is None or view.kind != "current":
            return f"l4 yolo review {plan_id}"
        if view.problems:
            return f"fix the specs named above, push them, then l4 yolo review {plan_id}"
        return f"l4 yolo activate {plan_id} --reason TEXT"
    if status in ("waiting", "stopped"):
        resume = f"l4 yolo resume {plan_id} --reason TEXT"
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
        out["problems"] = list(file.invalid.errors)
    if file is None:
        out["problems"] = [f"{pid}: no plan file on origin/{ctx.target}"]
    limits = limits_of(plan, state, read.events)
    out["usage"] = {
        "cost_usd": state.used.cost_usd, "cost_limit": limits.cost, "runs": state.used.runs, "runs_limit": limits.runs,
        "attempts": dict(state.used.attempts), "attempts_limit": limits.attempts,
        "deadline": limits.deadline.strftime("%Y-%m-%dT%H:%M:%SZ") if limits.deadline else None,
    }  # fmt: skip
    view = None
    if plan is not None and file is not None and rev is not None:
        view = _review_view(plan, file.text, state, read.events, _digests(ctx, rev, plan, units))
        out["review"] = {"state": view.kind, "problems": list(view.problems)}
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
    blocker = None
    if state.status in ("stopped", "waiting"):
        blocker = resume_blocker(pid, state, read.events, plan, units.phases, Extend(), now=_now())
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
        lines.append(f"  review: {d['review']['state']}")
        lines += [f"    {p}" for p in d["review"]["problems"]]
    if d.get("stop"):
        stop = d["stop"]
        unit = f" [{stop['unit']}]" if stop.get("unit") else ""
        lines.append(f"  stopped: {stop['reason']}{unit}" + (f": {stop['detail']}" if stop.get("detail") else ""))
    if d.get("wait"):
        lines.append(f"  waiting: {d['wait']}")
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


def plan_lines(repo: Path, git: Git, phases: Mapping[str, str | None]) -> list[str]:
    """`plan <id>: <status>[, unit U (<phase>)], <integrated>/<total> integrated, $<used>/$<limit>` for each plan with a
    ref in this checkout that is not final (L4-YOLO-015). `phases` is unit id -> phase."""
    try:
        files = {f.plan_id: f for f in plan_files(repo)}
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
        cost = limits_of(plan, state, ledgers[pid]).cost
        limit = "unlimited" if cost is None else f"${cost:.2f}"
        lines.append(
            f"plan {pid}: {state.status}{unit}, {len(state.integrated)}/{total} integrated, "
            f"${state.used.cost_usd:.2f}/{limit}"
        )
    return lines


def auto_merge_plan_active(repo: Path, git: Git) -> bool:
    """Is some plan with `merge: auto` active, waiting or stopped in this checkout's plan refs (L4-YOLO-008)? The merge
    mode is the plan file's in the working tree, else what the ledger recorded."""
    files = {f.plan_id: f for f in plan_files(repo)}
    for pid, events in local_plans(git).items():
        state = fold_plan(pid, events)
        if state.status not in _HOLDING:
            continue
        merge = files[pid].plan.merge if pid in files and files[pid].plan else state.merge
        if merge == "auto":
            return True
    return False


__all__ = [
    "Blocker",
    "Extend",
    "Limits",
    "PlanInvalid",
    "ReviewView",
    "auto_merge_plan_active",
    "limits_of",
    "local_plans",
    "plan_lines",
    "resume_blocker",
    "run_activate",
    "run_cancel",
    "run_check",
    "run_report",
    "run_resume",
    "run_review",
    "run_status",
]
