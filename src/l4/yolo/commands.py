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
import math
import re
import shutil
import sys
import tempfile
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

from l4.agents.activity import ago
from l4.availability.errors import RoleUnavailable
from l4.ci.detect import ci_like
from l4.ci.github import WORKFLOW_RELPATH
from l4.config.defaults import cache_root
from l4.config.redaction import load_app_config
from l4.config.schema import L4Config, YoloReviewCfg, effective_delivery
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import fetch_auth_config, forge_platform, make_forge
from l4.forge.gitlab import push_auth_config
from l4.forge.pushfail import push_platform
from l4.forge.urls import app_forge_urls, origin_url
from l4.implementer.tdd import RoleLimit
from l4.init.upgrade import _branch_pin, _default_branch
from l4.planner import facts_of
from l4.specs.detect import collect_units
from l4.specs.providers import providers_for
from l4.state.ledger import LedgerEvent
from l4.state.liveness import LazyForge, ended_why
from l4.state.next_step import next_step, way_out
from l4.state.retry import fetch_unit_refs, how_to_start, start_run_line
from l4.state.status import Activity, OpenRun, _where, discover, open_question_kinds
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.yolo import accept as accepting
from l4.yolo import findings as fnd
from l4.yolo import judge_sandbox, staleness
from l4.yolo.admit import admit, done_units, next_eligible, unit_blocker
from l4.yolo.coverage import coverage_findings
from l4.yolo.cycle import REVIEW_KEY, fetch_cause, plan_source, review_batches, still_waits
from l4.yolo.digest import MISSING, FolderMissing, RevisionMissing, current_unit_digest, plan_digest
from l4.yolo.draft import Found, new_draft, update_draft
from l4.yolo.forbidden import tracked_tree
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
    ReviewResult,
    UnitInfo,
)
from l4.yolo.plans import (
    FINAL,
    PlanFile,
    active_on,
    archived_at,
    held_by,
    holds_of,
    plan_files,
    plan_files_at,
    readable_unit_ids,
    unit_infos,
)
from l4.yolo.readiness import PROMPT_VERSION, Budgets, delivered_on_target, read_folder, review_plan_costed
from l4.yolo.state import apply_extend, fold_plan, parse_time
from l4.yolo.store import LEDGER_FILE, PlanRead, PlanStore, list_plans, parse_ledger
from l4.yolo.worktree import snapshot as worktree_snapshot

log = logging.getLogger("l4.yolo.commands")

REPORT_FILE = "report.md"
_MOVED = "the plan moved: run the command again"
_BEFORE_ACTIVATION = ("new", "refused", "admitted", "reviewed")
_HOLDING = ("active", "waiting", "stopped")
ANSWER_RECORDED = "the answer is recorded and the next run reads it"  # the live reason of a wait whose answer is pushed


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
            platform=push_platform(self.cfg, self.app.environ, self.app.repo),
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
    rel = f".l4/plans/{plan_id}.json"
    sha = (ctx.git.rev_parse(ctx.target_ref) or "")[: staleness.SHA_CHARS]
    lines = [f"{who}: no plan file {rel} on origin/{ctx.target}" + (f" ({sha})" if sha else "")]
    if ctx.git.run("cat-file", "-e", f"HEAD:{rel}", check=False).returncode == 0:
        d = staleness.divergence(ctx.git, ctx.target_ref)
        if d is not None and d.ahead > 0:
            lines.append(f"Fix: {staleness.divergence_fix(d, ctx.target, 'run the command again')}")
    elif (ctx.app.repo / rel).is_file():
        lines.append(f"Fix: commit and push {rel}, then run the command again")
    raise L4Exit(ExitCode.USAGE_ERROR, "\n".join(lines))


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
    activity: dict[str, tuple[Activity | None, OpenRun | None]] = field(default_factory=dict)  # unit id -> (L4-OPS-020)
    # the units in awaiting_human or clarifying whose answers are pushed and no run has read (L4-YOLO-052)
    answered: set[str] = field(default_factory=set)
    halt_reasons: dict[str, str | None] = field(default_factory=dict)  # unit id -> the code its stop recorded
    answer_fixes: dict[str, str] = field(
        default_factory=dict
    )  # unit id -> what to do about an answer that is not valid
    # unit id -> the events that tell what the delegate decided and spent on it (L4-DLG-011); only units that have a
    # `delegate.result`, so a repository without the delegate reads nothing more
    delegate: dict[str, tuple[LedgerEvent, ...]] = field(default_factory=dict)
    # unit id -> the kinds of its open questions (and its fix units'), for the units that wait (L4-DLG-021)
    open_kinds: dict[str, tuple[str, ...]] = field(default_factory=dict)


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


def answered_units(snapshots: Iterable[Any]) -> set[str]:
    """The ids of the units in `awaiting_human` or `clarifying` that no longer wait (`cycle.still_waits`) because an
    answer is recorded: the planner's own reason is an answer that unblocks a task (`answers_unblock`) or verdict
    answers not yet consumed (`verdicts_ready`). A clarifying unit with nothing answered is not one (review N5)."""
    found = set()
    for s in snapshots:
        if (s.state.phase or "") not in ("awaiting_human", "clarifying") or still_waits(s):
            continue
        facts = facts_of(s)
        if facts.answers_unblock or facts.verdicts_ready:
            found.add(s.ref.id)
    return found


def answer_fix_of(snapshot: Any, repo: Path, branch_prefix: str) -> str:
    """For a unit whose answer is invalid, dismissed or only a draft: the step `l4 status` gives, and how to replace a
    recorded answer; empty for a unit whose question is plainly open (review N7)."""
    facts = facts_of(snapshot)
    if not (facts.verdicts_invalid or facts.verdicts_dismissed or facts.drafts):
        return ""
    branch, questions_path = _where(snapshot, repo, branch_prefix)
    step = next_step(facts, branch=branch, questions_path=questions_path)
    replace = f'l4 questions answer Q-NNN --unit {snapshot.ref.id} --text "accept ..." --replace'
    return f"{step} (to change a recorded answer: {replace})"


def _read_units(ctx: _Ctx, rev: str, wanted: Sequence[str], *, intake: bool) -> _Units:
    with _workspace(ctx, rev) as (path, git):
        found = discover(ctx.cfg, git, providers_for(ctx.cfg, path, ctx.app.environ))
        forbidden = ctx.cfg.odd.forbidden_paths if intake else ()  # the intake rule runs with the intake checks only
        tree = tracked_tree(git, rev) if intake else None
        infos = unit_infos(path, found, wanted, check_intake=intake, target=ctx.target, forbidden=forbidden, tree=tree)
        phases = {snapshot.ref.id: snapshot.state.phase for _, snapshot in found}
        costs = {snapshot.ref.id: snapshot.state.cost_usd for _, snapshot in found}
        activity = {snapshot.ref.id: (snapshot.last_activity, snapshot.open_run) for _, snapshot in found}
        answered = answered_units(snapshot for _, snapshot in found)
        fixes = {
            snapshot.ref.id: fix
            for _, snapshot in found
            if (snapshot.state.phase or "") == "awaiting_human"
            and (fix := answer_fix_of(snapshot, ctx.app.repo, ctx.cfg.forge.branch_prefix))
        }
        halts = {  # the code of a stop, for the units a plan can be stopped on (L4-YOLO-055)
            snapshot.ref.id: snapshot.state.halt_reason
            for _, snapshot in found
            if snapshot.state.phase in ("halted", "escalated")
        }
    kinds = {  # the kinds of the open questions of a unit that waits: the delegate's hint reads them
        snapshot.ref.id: open_question_kinds(snapshot)
        for _, snapshot in found
        if (snapshot.state.phase or "") in ("awaiting_human", "fixing")
    }
    delegate = {}
    for _, snapshot in found:
        events = getattr(snapshot, "events", ())  # a unit the delegate never saw has no `delegate.result`
        if any(e.type == "delegate.result" for e in events):
            delegate[snapshot.ref.id] = tuple(
                e for e in events
                if e.type in ("question.raised", "delegate.result")
                or (e.type == "budget.cost" and e.data.get("role") == "delegate")
            )  # fmt: skip
    return _Units(infos, phases, costs, activity, answered, halts, fixes, delegate, kinds)


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


def _folders(plan: Plan, units: _Units) -> dict[str, str]:
    return {u: units.infos[u].folder for u in plan.unit_ids() if u in units.infos}


def _revs(ctx: _Ctx, plan: Plan, units: _Units) -> dict[str, Any]:
    """The two keys every `plan.reviewed` carries (L4-YOLO-068): the target revision and each unit's revision."""
    return {
        "target_rev": ctx.git.rev_parse(ctx.target_ref) or "",
        "unit_revs": staleness.unit_revs(ctx.git, ctx.cfg, plan.unit_ids(), ctx.target_ref, _folders(plan, units)),
    }


def _stale_lines(
    ctx: _Ctx,
    plan: Plan,
    file: PlanFile,
    state: PlanState,
    events: Sequence[PlanEvent],
    now: Mapping[str, str],
    units: _Units,
    *,
    prompt_matters: bool = True,
) -> list[str]:
    return staleness.stale_reasons(
        ctx.git, ctx.cfg, plan, file.text, file.path, state, events, now, ctx.target_ref, _folders(plan, units),
        prompt_matters=prompt_matters,
    )  # fmt: skip


def _stale_header(ctx: _Ctx, lead: str) -> str:
    sha = (ctx.git.rev_parse(ctx.target_ref) or "")[: staleness.SHA_CHARS]
    return f"{lead} is stale against origin/{ctx.target} ({sha}):"


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
    accepted: tuple[dict[str, Any], ...] = ()  # the acceptances of items that are not READY: subject, by, actor, ...
    # the subjects a force acceptance overrode (its recorded `skipped` is not empty): subject, by, actor, reason,
    # holds, skipped (design D5); `covered`: a force acceptance holds for every subject of the plan
    force: tuple[dict[str, Any], ...] = ()
    covered: bool = False
    problem_subjects: tuple[str, ...] = ()  # the subject of each line of `problems`, in the same order (`l4 yolo go`)

    @property
    def forced(self) -> list[dict[str, Any]]:
        """The force items that hold: their subjects are cleared whatever a current review says of them."""
        return [f for f in self.force if f["holds"]]

    @property
    def cleared(self) -> list[dict[str, Any]]:
        """The acceptances that hold (`accept.holds`): their items no longer stop the activation."""
        return [a for a in self.accepted if a["holds"]]

    @property
    def ready(self) -> bool:
        """A force acceptance waives a missing or stale review, never findings of a current one."""
        if self.kind == "current":
            return not self.problems
        return self.covered


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
    wanted = [u for u in plan.unit_ids()] + [f"batch:{b.id}" for b in plan.batches if len(b.units) > 1]
    force_data = state.force_accepted
    holding = accepting.force_holds(force_data, plan_digest(text), now)
    force = tuple(
        {
            "subject": name, "by": force_data.get("by"), "actor": force_data.get("actor"),
            "reason": force_data.get("reason"), "holds": holding.get(name, False),
            "skipped": list(force_data["subjects"][name].get("skipped") or []),
        }
        for name in wanted
        if force_data is not None and name in (force_data.get("subjects") or {})
        and (force_data["subjects"][name].get("skipped") or [])
    )  # fmt: skip
    covered = force_data is not None and all(holding.get(name, False) for name in wanted)
    cleared_by_force = {f["subject"] for f in force if f["holds"]}
    if state.review_plan_digest is None:
        return ReviewView("none", force=force, covered=covered)
    if prompt_matters and state.review_prompt_version != PROMPT_VERSION:
        return ReviewView("stale", prompt_changed=True, force=force, covered=covered)
    stale = state.review_plan_digest != plan_digest(text)
    stale = stale or any(state.review_digests.get(u) != now.get(u) for u in plan.unit_ids())
    stale = stale or any(w not in state.review for w in wanted)
    if stale:
        return ReviewView("stale", force=force, covered=covered)
    latest_event = next((e for e in reversed(events) if e.type == "plan.reviewed"), None)
    latest: dict[str, Any] = latest_event.data if latest_event is not None else {}
    review_at = latest_event.at if latest_event is not None else None
    problems = []
    subjects: list[str] = []
    accepted: list[dict[str, Any]] = []
    held = accepting.holds(state, latest)
    for name in wanted:
        verdict = state.review[name]
        if name in cleared_by_force or verdict == "READY":  # a subject a force acceptance overrode is cleared (D5)
            continue
        given = state.accepted.get(name)
        if given is not None:
            holds = bool(held.get(name)) and verdict == "NEEDS_REVISION"
            accepted.append(
                {
                    "subject": name, "by": given.get("by"), "actor": given.get("actor"),
                    "reason": given.get("reason"), "findings": list(given.get("findings") or []), "holds": holds,
                }
            )  # fmt: skip
            if holds:
                continue
        group, _, ident = name.partition(":") if name.startswith("batch:") else ("units", "", name)
        entry = (latest.get("batches" if group == "batch" else "units") or {}).get(ident) or {}
        label = f"batch {ident}" if group == "batch" else name
        line = f"{label}: {verdict}: {_first_line(entry.get('findings'))}"
        if given is not None:
            why = accepting.why_not_holds(given, accepting.entry_of(latest, name), review_at)
            line += f" (the acceptance by {given.get('by')} was for {why})"
        problems.append(line)
        subjects.append(name)
    return ReviewView(
        "current", tuple(problems), accepted=tuple(accepted), force=force, covered=covered,
        problem_subjects=tuple(subjects),
    )  # fmt: skip


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
    answered: Collection[str] = (),
    halt_reasons: Mapping[str, str | None] | None = None,
) -> Blocker | None:
    """The cause that is still there, per design D10's table; None when a resume may go. `live`: the state with the
    figures the plan step checks the limits on (`_live_usage`); the ledger's `state` when not given. `answered`: the
    units whose answers are pushed and no run has read (L4-YOLO-052); `halt_reasons`: the code each stopped unit's
    ledger recorded (a unit with its own way out is not told `l4 retry` first)."""
    review_again = f"l4 yolo review {plan_id}, then l4 yolo activate {plan_id} --reason TEXT"
    if state.status == "waiting":
        unit = state.current
        phase = phases.get(unit) if unit else None
        if phase in ("awaiting_human", "clarifying"):
            if unit in answered:  # the answer is pushed: no cause is left, the resume starts the run that reads it
                return None
            return Blocker(
                f"{unit} is still {phase}: answer its questions first (l4 questions --unit {unit}); a waiting plan "
                "continues by itself at the run that reads the answer, so no resume is needed after it",
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
            own = way_out(unit, (halt_reasons or {}).get(unit)) if phase == "escalated" else None
            if (
                own is not None
            ):  # a unit escalated for a reason with its own way out: the retry alone repeats the verdict
                return Blocker(f"{unit} is still {phase}: {own}", own)
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


def budget_overruns(git: Git, cfg: L4Config, plan: Plan, units: Mapping[str, UnitInfo], rev: str) -> list[str]:
    """`material_over_budget` lines for the files the readiness review would cut or leave out (L4-ADO-010), read as the
    review reads them (`read_folder`): a planned unit's own folder at the folder budget, a unit named in a `depends_on`
    at the dependency budget, in the prerequisite order. A dependency's line starts with `warning: ` (the review lists
    it as not shown in full without blocking). Units are read at `rev`, not on their branches."""
    limits = Budgets.of(cfg)

    def lines(folder: str, *, budget: int, order: str) -> list[tuple[str, str]]:
        text = read_folder(git, rev, folder, budget=budget, file_budget=limits.file, order=order)
        sizes = dict(text.sizes)
        found = [(path, f"{n} characters cut") for path, n in text.cut]
        found += [
            (o.path, f"omitted: the folder budget is spent ({sizes.get(o.path, 0)} characters)")
            for o in text.omitted
            if o.size_limit
        ]
        return found

    out: list[str] = []
    dependents: dict[str, list[str]] = {}
    for unit in plan.units():
        if unit.id in units:
            out += [
                f"material_over_budget: {unit.id}: {path}: {what}"
                for path, what in lines(units[unit.id].folder, budget=limits.folder, order="sorted")
            ]
        for dep in unit.depends_on:
            if dep != unit.id and unit.id not in dependents.setdefault(dep, []):
                dependents[dep].append(unit.id)
    for dep, by in dependents.items():
        if dep in units:
            out += [
                f"warning: material_over_budget: {dep}: {path}: {what} (as a dependency of {', '.join(by)})"
                for path, what in lines(units[dep].folder, budget=limits.dependency, order="prerequisite")
            ]
    return out


def intake_warnings(units: Mapping[str, UnitInfo], order: Sequence[str]) -> list[str]:
    """The `warning: forbidden_path: ...` lines of the admitted units, in admission order (L4-YOLO-092): they never
    refuse the plan, so `check` and `go` print them after the order."""
    return [line for unit in order if unit in units for line in units[unit].warnings]


@dataclass
class _WorktreeAdmission:
    found: list[tuple[Any, Any]]  # `discover`'s pairs, for the callers that need the phases
    infos: dict[str, UnitInfo]
    admission: Admission
    archived: frozenset[str]


def _admit_worktree(ctx: _Ctx, plan: Plan, plan_id: str, state: PlanState, rev: str) -> _WorktreeAdmission:
    """The admission of a plan read from the WORKING TREE (`check --worktree`, `review --worktree`): the units are the
    ones the providers find in the checkout, the other plans, the archived changes and the target are those of `rev`."""
    found = discover(ctx.cfg, ctx.git, providers_for(ctx.cfg, ctx.app.repo, ctx.app.environ))
    tree = tracked_tree(ctx.git)  # the index: a staged file counts, an untracked one does not
    infos = unit_infos(
        ctx.app.repo, found, plan.known_ids(), check_intake=True, forbidden=ctx.cfg.odd.forbidden_paths, tree=tree
    )
    archived = archived_at(ctx.git, rev, ctx.cfg)
    admission = admit(
        plan, known_units=infos, cfg=ctx.cfg, held=_held(ctx, plan_id, state), state=state, archived=archived
    )
    return _WorktreeAdmission(found, infos, admission, archived)


def _check_worktree(ctx: _Ctx, plan_id: str, rev: str) -> ExitCode:
    """`l4 yolo check PLAN --worktree` (L4-YOLO-034): the admission of the working tree's plan, then `uncovered` and
    `covered_twice` across its plan files. Writes nothing and needs no push."""
    files = plan_files(ctx.app.repo)
    file = next((f for f in files if f.plan_id == plan_id), None)
    if file is None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"check: no plan file {PLANS_DIR}/{plan_id}.json in the working tree")
    if file.plan is None:
        assert file.invalid is not None
        for error in file.invalid.errors:
            ctx.say(error)
        ctx.say(f"{plan_id}: not admitted")
        return ExitCode.USAGE_ERROR
    state = fold_plan(plan_id, ctx.store(plan_id).read().events)
    result = _admit_worktree(ctx, file.plan, plan_id, state, rev)
    known = [u.id for u in collect_units(providers_for(ctx.cfg, ctx.app.repo, ctx.app.environ))]
    coverage = coverage_findings(files, known, ctx.cfg.yolo.hold)
    admission = result.admission
    if not admission.ok or coverage:
        ctx.say(f"{plan_id}: not admitted ({len(admission.findings) + len(coverage)} finding(s))")
        _print_findings(ctx, [*_findings_text(admission, plan_id), *coverage])
        return ExitCode.USAGE_ERROR
    ctx.say(f"{plan_id}: admitted (working tree)")
    ctx.say(f"order: {', '.join(admission.order)}")
    for line in intake_warnings(result.infos, admission.order):
        ctx.say(line)
    paths = [file.path, *dict.fromkeys(i.folder for i in result.infos.values())]
    snap = worktree_snapshot(ctx.git, paths)  # a commit that touches no ref: the budget reads files from a revision
    for line in budget_overruns(ctx.git, ctx.cfg, file.plan, result.infos, snap):
        ctx.say(line)
    return ExitCode.OK


@dataclass(frozen=True)
class _AtTarget:
    """The plan file at the target head and what admission made of it: `plan`, `units` and `admission` are None for a
    file that is not a plan."""

    file: PlanFile
    plan: Plan | None
    units: _Units | None
    admission: Admission | None


def _admission_at(ctx: _Ctx, plan_id: str, rev: str, state: PlanState | None = None) -> _AtTarget:
    """The admission of the plan file at `rev` (the target head), as `check` prints it; `l4 yolo go` reads it too. A
    missing plan file is the exit 2 of `_file`. `state` is the plan's fold (read here when not given): the plan's own
    merged units are done."""
    file = _file(ctx, plan_id, "check")
    if file.plan is None:
        return _AtTarget(file, None, None, None)
    units = _read_units(ctx, rev, file.plan.known_ids(), intake=True)
    if state is None:
        state = fold_plan(plan_id, ctx.store(plan_id).read().events)  # read-only
    admission = admit(
        file.plan,
        known_units=units.infos,
        cfg=ctx.cfg,
        held=_held(ctx, plan_id),
        state=state,
        archived=archived_at(ctx.git, rev, ctx.cfg),
    )
    return _AtTarget(file, file.plan, units, admission)


def run_check(app: AppContext, *, plan: str, worktree: bool = False) -> ExitCode:
    """Admit the plan at the target head; print the findings and the order. Exit 0 admitted, 2 not. No write. With
    `worktree`, the plan files and the units are the working tree's (L4-YOLO-034), before the push."""
    plan_id = _plan_id(plan)
    ctx = _open(app)
    rev = _sync(ctx, who="check")
    if worktree:
        return _check_worktree(ctx, plan_id, rev)
    at = _admission_at(ctx, plan_id, rev)
    if at.plan is None or at.units is None or at.admission is None:
        assert at.file.invalid is not None
        for error in at.file.invalid.errors:
            ctx.say(error)
        ctx.say(f"{plan_id}: not admitted")
        return ExitCode.USAGE_ERROR
    admission = at.admission
    if not admission.ok:
        ctx.say(f"{plan_id}: not admitted ({len(admission.findings)} finding(s))")
        _print_findings(ctx, _findings_text(admission, plan_id))
        return ExitCode.USAGE_ERROR
    ctx.say(f"{plan_id}: admitted at origin/{ctx.target} {rev[:10]}")
    ctx.say(f"order: {', '.join(admission.order)}")
    for line in intake_warnings(at.units.infos, admission.order):
        ctx.say(line)
    for line in budget_overruns(ctx.git, ctx.cfg, at.plan, at.units.infos, rev):  # a warning: the exit code stays 0
        ctx.say(line)
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
    say(f"  2. l4 yolo check {plan_id} --worktree (without the harness: python3 scripts/validate_plan.py),")
    say("     then commit and push the plan file")
    say("     (new specs in the same commit, or after the plan file: one that lands without a plan runs at once)")
    say(f"  3. l4 yolo check {plan_id} (after the push), then l4 yolo review {plan_id}")
    return ExitCode.OK


# --- l4 yolo review ------------------------------------------------------------------------------------------------


def _verdict_json(verdict: Any) -> dict[str, Any]:
    out = {
        "verdict": verdict.verdict,
        "digest": verdict.digest,
        "findings": [dict(f) for f in verdict.findings],
        "assumptions": list(verdict.assumptions),
        "missing": list(verdict.missing),
    }
    if getattr(verdict, "material", None) is not None:  # the key an acceptance is bound to (L4-YOLO-027)
        out["material"] = verdict.material
    if getattr(verdict, "reused_from", None) is not None:
        out["reused_from"] = verdict.reused_from
    return out


def batch_entries(
    plan: Plan, result: ReviewResult, batches: Mapping[str, Any], entry: Any = _verdict_json
) -> dict[str, dict[str, Any]]:
    """The ledger entries of the batches, each with the digests of its units' text as CI records them: `l4 yolo accept`
    counts a batch's rounds by them."""
    members = {b.id: [u.id for u in b.units] for b in plan.batches}
    out: dict[str, dict[str, Any]] = {}
    for bid, verdict in batches.items():
        digests = {
            u: result.units[u].digest for u in members.get(bid, ()) if u in result.units and result.units[u].digest
        }
        out[bid] = {**entry(verdict), **({"digests": digests} if digests else {})}
    return out


def run_review(
    app: AppContext,
    *,
    plan: str,
    local: bool = False,
    no_run: bool = False,
    worktree: bool = False,
    record: bool = False,
    fresh: Sequence[str] = (),
    as_json: bool = False,
) -> ExitCode:
    """Without `--local`: ask CI to review the plan (`start_run`); the review itself is the CI step's. With `--local`:
    admit and review here, recording `plan.admitted` and `plan.reviewed` (or `plan.refused`) as the CI step would.
    With `--worktree`: review the working tree (`review_worktree`); `--record` and `--fresh` need it (exit 2)."""
    if not worktree and (record or fresh or as_json):
        raise L4Exit(ExitCode.USAGE_ERROR, "review: --record, --fresh and --json need --worktree")
    if worktree:
        from l4.yolo.review_worktree import run_review_worktree  # late: that module reads this one

        return run_review_worktree(app, plan=plan, fresh=tuple(fresh), record=record, no_run=no_run, as_json=as_json)
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
    ahead = staleness.divergence(ctx.git, ctx.target_ref, [file.path, *_folders(parsed, units).values()])
    if ahead is not None and ahead.ahead > 0 and ahead.paths:  # D4: the review reads origin, not these commits
        reads = "--local reviews" if local else "CI reviews"
        ctx.say(
            f"warning: {staleness.divergence_text(ahead, ctx.target)}: {reads} origin/{ctx.target}, not your "
            f"commits: {staleness.divergence_verb(ahead)}, then review"
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
        if view.kind == "stale":  # M4: the causes, before the request (the unpushed commits are M6's)
            reasons = _stale_lines(ctx, parsed, file, state, read.events, now, units)
            ctx.say(_stale_header(ctx, f"{plan_id}: the recorded review"))
            for r in reasons:
                if not r.startswith("local: "):
                    ctx.say(f"  {r}")
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
    chosen: dict[str, str] = {}

    def sandbox_for(adapter: str, profile: str) -> Any:
        """The judge's sandbox (design D5): bwrap, or none for a tool-less judge outside CI, said out loud."""
        sandbox, label = judge_sandbox.choose(
            ctx.cfg,
            ctx.app.environ,
            ctx.app.repo,
            adapter=adapter,
            in_ci=ci_like(ctx.app.environ),
            profile=profile,
        )
        chosen.update(sandbox=label, judge=profile)
        if label == "none" and ctx.cfg.sandbox.mode != "none":
            why = judge_sandbox.unsandboxed_reason(ctx.app.environ, ctx.app.repo)
            ctx.say(f"judge unsandboxed ({why}): it has no tools and runs in an empty folder")
        return sandbox

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
            prior=fnd.prior_entries(read.events, PROMPT_VERSION, state.accepted),
            sandbox_for=sandbox_for,
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
            source="local", **chosen, **_revs(ctx, parsed, units),
            units={u: _verdict_json(v) for u, v in result.units.items()},
            batches=batch_entries(parsed, result, batches),
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
    held = accepting.holds(state, events[1].data)  # the acceptances that hold on this review (L4-YOLO-066)
    open_subjects = 0
    for key, name, verdict in [
        *((u, u, v) for u, v in result.units.items()),
        *((f"batch:{b}", f"batch {b}", v) for b, v in batches.items()),
    ]:
        line = f"  {name}: {verdict.verdict}"
        if verdict.verdict == "READY":
            ctx.say(line)
            continue
        line = f"{line}: {_first_line(verdict.findings)}"
        if held.get(key):
            line += f" (accepted by {state.accepted[key].get('by')}: it does not stop the activation)"
        else:
            open_subjects += 1
        ctx.say(line)
    if open_subjects:
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


def _admitted(
    ctx: _Ctx, rev: str, plan: Plan, plan_id: str, state: PlanState, command: str
) -> tuple[_Units, Admission]:
    """The units of the target head and the admission of `plan` on them (the one `activate` and `accept --force` share);
    any finding exits 2 as `<command>: <plan> is not admitted:` with one `  <code>: <text>` line each."""
    units = _read_units(ctx, rev, plan.known_ids(), intake=True)
    admission = admit(
        plan,
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
                [f"{command}: {plan_id} is not admitted:", *(f"  {t}" for t in _findings_text(admission, plan_id))]
            ),
        )
    return units, admission


def _activation_blocker(ctx: _Ctx, plan_id: str, parsed: Plan) -> str | None:
    """What `activate` still refuses after the review is clear (the refusal without its `activate: ` prefix): the target
    is not on origin, or another plan is active, waiting or stopped on it. None when neither holds. `l4 yolo go` asks
    for it before it tells an agent that a person's activation is the next step."""
    if not _branch_on_origin(ctx, parsed.target):
        return f"the target {parsed.target} is not on origin"
    other = active_on(_others(ctx, plan_id), plan_files_at(ctx.git, ctx.target_ref), parsed.target)
    if other is not None:
        return (
            f"plan {other.plan_id} is already active, waiting or stopped on {parsed.target}: "
            f"let it finish, or run l4 yolo cancel {other.plan_id} --reason TEXT first"
        )
    return None


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
    units, admission = _admitted(ctx, rev, parsed, plan_id, state, "activate")
    seen, rejected = _rejected_at(read.events, state), state.stop_unit
    stays = seen is not None and rejected in units.infos and units.phases.get(rejected) == "rejected"
    if stays and _now_digest(ctx, rejected, units.infos[rejected].folder) == seen:  # a restarted unit has no phase
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"activate: {rejected} was rejected, is still rejected and its spec has not changed: fix the spec and "
            f"push it, then l4 yolo review {plan_id} and l4 yolo activate {plan_id} --reason TEXT; or, when the cause "
            f"is the configuration, restart the unit (l4 restart --unit {rejected} --reason TEXT)",
        )
    now = _digests(ctx, parsed, units)
    view = _review_view(parsed, file.text, state, read.events, now)
    voided, force_fix = "", ""
    if (
        state.force_accepted is not None and not view.covered
    ):  # D5: name the subjects the acceptance no longer holds for
        held = accepting.force_holds(state.force_accepted, plan_digest(file.text), now)
        names = [s for s in [*parsed.unit_ids(), *(f"batch:{b.id}" for b in parsed.batches if len(b.units) > 1)]
                 if s in held and not held[s]]  # fmt: skip
        if names:
            voided = (
                f"the force acceptance by {state.force_accepted.get('by')} no longer holds for {', '.join(names)}: "
                "their spec or the plan file changed"
            )
            force_fix = f', or a person runs l4 yolo accept {plan_id} --all --force --reason "..." again'
    tail = f"\n{voided}\nFix: l4 yolo review {plan_id}{force_fix}" if voided else ""
    if not view.covered:
        if view.kind == "none":
            raise L4Exit(
                ExitCode.USAGE_ERROR, f"activate: {plan_id} has not been reviewed: run l4 yolo review {plan_id}{tail}"
            )
        if view.kind == "stale":
            reasons = _stale_lines(ctx, parsed, file, state, read.events, now, units)
            fix = f"l4 yolo review {plan_id}"
            if any(r.startswith("local: ") for r in reasons):
                folders = _folders(parsed, units)
                d = staleness.divergence(ctx.git, ctx.target_ref, [file.path, *folders.values()])
                if d is not None:
                    fix = staleness.divergence_fix(d, ctx.target, fix)
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                "\n".join(
                    [
                        _stale_header(ctx, f"activate: the review of {plan_id}"),
                        *(f"  {r}" for r in reasons),
                        *([voided] if voided else []),
                        f"Fix: {fix}{force_fix}",
                    ]
                ),
            )
    if view.kind == "current" and view.problems:  # a force acceptance does not hide findings it did not override
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            "\n".join(
                [
                    f"activate: the review is not READY for {len(view.problems)} item(s):",
                    *(f"  {p}" for p in view.problems),
                    f"Next: l4 yolo findings {plan_id}",
                ]
            )
            + tail,
        )
    blocker = _activation_blocker(ctx, plan_id, parsed)
    if blocker is not None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"activate: {blocker}")
    base = {u: n for u in parsed.unit_ids() if (n := attempt_refs(ctx.git, u, ctx.fetch_cfg)) is not None}
    # the current unit goes on only when the new order holds it and nothing it now waits for is open (review z1, H2)
    current = state.current
    if current is not None and (current not in admission.order or unit_blocker(parsed, state, current) is not None):
        current = None
    # an acceptance that holds is frozen with the activation; an agent's come first (the person sees them first)
    cleared = sorted(view.cleared, key=lambda a: a["actor"] != "agent")
    accepted = {
        a["subject"]: {"findings": a["findings"], "reason": a["reason"], "by": a["by"], "actor": a["actor"]}
        for a in cleared
    }
    for f in view.forced:  # a subject a holding force acceptance overrode: no findings, the person's reason (D5)
        accepted[f["subject"]] = {
            "findings": [],
            "reason": f["reason"],
            "by": f["by"],
            "actor": "person",
            "force": True,
        }
    extra = {"review": "force_accepted"} if view.forced else {}
    event = _event(
        "plan.activated", plan_digest=plan_digest(file.text), digests=now, limits=parsed.limits.model_dump(mode="json"),
        merge=parsed.merge, by=ctx.who(), reason=reason.strip(), attempt_base=base, current=current,
        accepted=accepted, **extra,
    )  # fmt: skip
    _append(store, [event], read.head)
    for a in cleared:
        mark = " (accepted by an agent)" if a["actor"] == "agent" else ""
        ctx.say(f"accepted: {a['subject']} by {a['by']} ({a['actor']}): {a['reason']}{mark}")
    for f in view.forced:
        ctx.say(accepting.force_line(f["subject"], f["by"], f["reason"]))
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
    if cost is not None and not math.isfinite(cost):  # `nan` and `inf` would make a limit nothing can reach or pass
        raise L4Exit(ExitCode.USAGE_ERROR, "resume: --extend-cost must be a finite number")
    for flag, value in (("cost", cost), ("runs", runs), ("attempts", attempts)):
        if value is not None and value <= 0:
            raise L4Exit(ExitCode.USAGE_ERROR, f"resume: --extend-{flag} must be more than 0")
    when = None
    if deadline is not None:
        when = parse_time(deadline)
        if when is None:
            raise L4Exit(ExitCode.USAGE_ERROR, f"resume: --extend-deadline {deadline!r} is not an ISO 8601 time")
    return Extend(cost, runs, attempts, when)


_EXTEND_OPTIONS = "--extend-cost USD, --extend-runs N, --extend-attempts N or --extend-deadline ISO"


def _extend_words(cost: float | None, runs: int | None, attempts: int | None, deadline: str | None) -> str:
    """The `--extend-…` options as the caller gave them, for the command a person runs."""
    given = (("cost", cost), ("runs", runs), ("attempts", attempts), ("deadline", deadline))
    return " ".join(f"--extend-{name} {value:g}" if isinstance(value, float) else f"--extend-{name} {value}"
                    for name, value in given if value is not None)  # fmt: skip


def _plan_config(ctx: _Ctx, state: PlanState) -> tuple[L4Config | None, str]:
    """`.l4/config.yaml` at `origin/<the plan's recorded target>` and no note, or None and why not: the plan has no
    valid file on the configured base branch, or its target is another branch than that base (review N1: a caller's
    own configuration must not name the branch the key is read from)."""
    plan_id = state.plan_id
    file = next((f for f in plan_files_at(ctx.git, ctx.target_ref) if f.plan_id == plan_id), None)
    plan = file.plan if file else None
    if plan is None:
        return None, f"{plan_id} has no valid plan file on origin/{ctx.target}"
    recorded = (
        state.activated_digest or state.plan_digest or state.review_plan_digest
    )  # a plan file rewritten on a caller's branch is not trusted
    if recorded is None or plan_digest(file.text) != recorded:
        return None, f"the plan file on origin/{ctx.target} differs from the digest the plan recorded"
    if plan.target != ctx.target:
        return None, f"the base branch {ctx.target} of the configuration differs from the plan's target {plan.target}"
    return accepting.target_full_config(ctx.git, f"{_ORIGIN}{plan.target}"), ""


def _review_cfg(ctx: _Ctx, state: PlanState) -> tuple[YoloReviewCfg, str]:
    """`yolo.review` of the plan's own target (defaults, and the reason, when the plan does not name the base)."""
    full, note = _plan_config(ctx, state)
    return (full.yolo.review if full is not None else YoloReviewCfg()), note


_ORIGIN = "refs/remotes/origin/"


def _may_extend(ctx: _Ctx, plan_id: str, words: str) -> bool:
    """L4-YOLO-051: raising a plan's limits is a person's decision. A person may; an agent only when
    `yolo.extend_by_agents` is true in `.l4/config.yaml` on the base branch (read from origin, never the working tree).
    Returns whether the key was what allowed it; raises (exit 2, nothing written) otherwise."""
    kind, marker = accepting.actor(ctx.app.environ, _stdin_tty())
    if kind == "person":
        return False
    note = ""
    if _branch_on_origin(ctx, ctx.target):
        _sync(ctx, who="resume")
        full, note = _plan_config(ctx, fold_plan(plan_id, ctx.store(plan_id).read().events))
        if full is not None and full.yolo.extend_by_agents:
            return True
    why = f"{marker} is set" if marker else "stdin is not a terminal"
    why += f"; {note}" if note else ""
    raise L4Exit(
        ExitCode.USAGE_ERROR,
        f"resume: raising a plan's limits is a person's decision ({why})\n"
        f'Fix: a person runs: l4 yolo resume {plan_id} --reason "..." {words}; or set yolo.extend_by_agents: true in '
        ".l4/config.yaml on the base branch (a pushed change a person can see)",
    )


def _limits_data(state: PlanState, fallback: Mapping[str, Any] | None) -> dict[str, Any]:
    """The limits in force as the events record them: `cost_usd`, `runs`, `attempts` (`max_unit_attempts` plus the
    extension for every unit) and `deadline` (`%Y-%m-%dT%H:%M:%SZ` or None)."""
    limits = effective_limits(state, fallback)
    return {
        "cost_usd": limits.cost_usd, "runs": limits.runs, "attempts": limits.attempts_of(""),
        "deadline": limits.deadline.astimezone(UTC).strftime(_ISO) if limits.deadline else None,
    }  # fmt: skip


_ISO = "%Y-%m-%dT%H:%M:%SZ"


def _extension_refusal(plan_id: str, extend: Extend, before: Mapping[str, Any]) -> str | None:
    """Why an extension of an active plan changes no limit in force, or None (L4-YOLO-050)."""
    if extend.cost is not None and before["cost_usd"] is None:
        return f"{plan_id} has no cost limit: --extend-cost changes nothing"
    if extend.runs is not None and before["runs"] is None:
        return f"{plan_id} has no run limit: --extend-runs changes nothing"
    if extend.deadline is not None:
        if before["deadline"] is None:
            return f"{plan_id} has no deadline: --extend-deadline sets none"
        asked = extend.deadline.astimezone(UTC).strftime(_ISO)
        if asked <= before["deadline"]:
            return f"--extend-deadline {asked} is not later than the deadline in force {before['deadline']}"
    return None


def _changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """`runs 90 -> 110; cost $10.00 -> $15.00`: one `name old -> new` per limit that changed."""

    def show(name: str, value: Any) -> str:
        if name == "cost_usd":
            return _money(value)
        return "none" if value is None and name == "deadline" else "unlimited" if value is None else str(value)

    names = {"cost_usd": "cost", "runs": "runs", "attempts": "attempts", "deadline": "deadline"}
    return "; ".join(
        f"{label} {show(key, before[key])} -> {show(key, after[key])}"
        for key, label in names.items()
        if before[key] != after[key]
    )


def run_resume(
    app: AppContext, *, plan: str, reason: str, extend_cost: float | None = None, extend_runs: int | None = None,
    extend_attempts: int | None = None, extend_deadline: str | None = None, no_run: bool = False,
) -> ExitCode:  # fmt: skip
    """`plan.resumed{by, reason, extend}` from `stopped` or `waiting`, refused while the cause is still there (design
    D10's table), then a run on the target. On an `active` plan only an `--extend-…` goes: it records `plan.extended`
    and nothing else (L4-YOLO-050). Every `--extend-…` is a person's, or an agent's when `yolo.extend_by_agents` is
    true on the base branch (L4-YOLO-051)."""
    if not reason.strip():
        raise L4Exit(ExitCode.USAGE_ERROR, "resume: --reason must say why")
    plan_id = _plan_id(plan)
    extend = _extend(extend_cost, extend_runs, extend_attempts, extend_deadline)
    ctx = _open(app)
    extending = bool(extend.as_data())
    by_key = (
        _may_extend(ctx, plan_id, _extend_words(extend_cost, extend_runs, extend_attempts, extend_deadline))
        if extending
        else False
    )
    who = accepting.actor(ctx.app.environ, _stdin_tty())
    store = ctx.store(plan_id)
    read = store.read()
    state = fold_plan(plan_id, read.events)
    if state.status == "active" and not extending:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"resume: {plan_id} is active: only a stopped or waiting plan resumes; to raise a limit of the active "
            f"plan, pass {_EXTEND_OPTIONS}",
        )
    if state.status not in ("active", "stopped", "waiting"):
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
    if state.status == "active":
        return _extend_active(ctx, store, read, state, parsed, extend, who, by_key, reason.strip())
    live = None
    if on_origin and state.stop_reason and state.stop_reason.startswith("limit_"):
        live = _live_usage(ctx, state, read.events, units, state.stop_unit or state.current)  # what the step checks
    blocker = resume_blocker(
        plan_id, state, read.events, parsed, phases, extend, target_present=on_origin, now=_now(), live=live,
        answered=units.answered, halt_reasons=units.halt_reasons,
    )  # fmt: skip
    if blocker is not None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"resume: {blocker.message}")
    data: dict[str, Any] = {"by": ctx.who(), "reason": reason.strip(), "extend": extend.as_data()}
    if extending:  # who raised the limits, and whether the key let an agent (L4-YOLO-051)
        data.update(actor=who[0], marker=who[1], agent_key=by_key)
    _append(store, [_event("plan.resumed", **data)], read.head)
    ctx.say(f"{plan_id}: resumed")
    if not no_run:
        ctx.say(start_run_line(ctx.app, ctx.cfg))
    return ExitCode.OK


def _extend_active(
    ctx: _Ctx, store: PlanStore, read: PlanRead, state: PlanState, parsed: Plan | None, extend: Extend,
    who: tuple[str, str | None], by_key: bool, reason: str,
) -> ExitCode:  # fmt: skip
    """`plan.extended` on an active plan: the limits change, the plan does not (L4-YOLO-050)."""
    fallback = parsed.limits.model_dump(mode="json") if parsed else None
    before = _limits_data(state, fallback)
    refusal = _extension_refusal(state.plan_id, extend, before)
    if refusal is not None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"resume: {refusal}")
    after_state = state.model_copy(deep=True)
    apply_extend(after_state, extend.as_data())
    after = _limits_data(after_state, fallback)
    event = _event(
        "plan.extended", by=ctx.who(), actor=who[0], marker=who[1], agent_key=by_key, reason=reason,
        extend=extend.as_data(), limits_before=before, limits_after=after,
    )  # fmt: skip
    _append(store, [event], read.head)
    ctx.say(f"{state.plan_id}: limits raised on the active plan (plan.extended): {_changes(before, after)}")
    ctx.say("nothing resumed and no run started: CI advances the plan at its next run")
    return ExitCode.OK


def run_report(app: AppContext, *, plan: str) -> ExitCode:
    """Print `report.md` of the plan ref, or `no report yet`."""
    plan_id = _plan_id(plan)
    ctx = _open(app)
    text = ctx.store(plan_id).read().files.get(REPORT_FILE)
    ctx.say(text.rstrip("\n") if text else "no report yet")
    return ExitCode.OK


# --- l4 yolo status ------------------------------------------------------------------------------------------------


def _next_line(
    plan_id: str, state: PlanState, view: ReviewView | None, blocker: Blocker | None, *,
    unit_phase: str | None = None, answered: bool = False, start: str = "", answer_fix: str = "",
    advance: str | None = None,
) -> str:  # fmt: skip
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
        if view is not None and view.covered and not view.problems:
            return f"l4 yolo activate {plan_id} --reason TEXT"
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
    if status == "waiting" and state.wait_reason == "accepted_finding_open":  # L4-YOLO-031: retry, feedback, waive
        unit = state.current or "<unit>"
        return (
            f"answer the accepted findings the wait names: when the verifier gave no answer, l4 retry --unit {unit} "
            f"--reason TEXT; when the code must change, l4 feedback add --unit {unit} ... (then the git lines it "
            f"prints) and l4 retry --unit {unit} --reason TEXT; when a finding needs no handling, l4 yolo waive "
            f"{plan_id} F-... --reason TEXT (audited); the plan goes on by itself once none is open"
        )
    if status == "waiting" and unit_phase == "awaiting_human" and state.current:  # L4-YOLO-053
        unit = state.current
        if answered:
            return (
                f"nothing: the answers of {unit} are pushed and the next run reads them; the plan then continues by "
                f"itself (to start that run now: l4 yolo resume {plan_id} --reason TEXT, or {start})"
            )
        if answer_fix:  # an answer that is invalid, dismissed or only a draft: the unit's own step comes first
            hint = "" if "--replace" in answer_fix else (
                f' (to change a recorded answer: l4 questions answer Q-NNN --unit {unit} --text "accept ..." --replace)'
            )  # fmt: skip
            return (
                f"{answer_fix}{hint}; the plan continues by itself at the run that reads the answer, "
                "no resume is needed"
            )
        return (
            f"answer the questions of {unit}: l4 questions --unit {unit}, then l4 questions answer Q-NNN --unit {unit} "
            "--text TEXT (it pushes the answer and starts a run); the plan continues by itself at the run that reads "
            "the answer, no resume is needed"
        )
    if status in ("waiting", "stopped"):
        resume = f"l4 yolo resume {plan_id} --reason TEXT"
        if blocker and blocker.fix.startswith(resume.split(" --")[0]):
            return blocker.fix  # a limit: the fix is the resume itself, with the flag
        return f"{blocker.fix}, then {resume}" if blocker else resume
    if status == "active":
        if advance:  # L4-IMP-073: a run that ended without a record, or nothing running, queued or scheduled
            return advance
        return (
            f"nothing: CI advances the plan at each run (l4 yolo resume {plan_id} --reason TEXT --extend-runs N raises "
            f"a limit before it is reached; l4 yolo cancel {plan_id} --reason TEXT stops it)"
        )
    if status == "completed":
        return f"the plan is complete: l4 yolo report {plan_id}; promotion is yours"
    return "none: the plan is cancelled"


def _force_doc(state: PlanState, plan: Plan | None, text: str | None, now: Mapping[str, str]) -> dict[str, Any] | None:
    """The recorded force acceptance as `status --json` and `findings --json` show it (design D6): who, why, when,
    whether it covers the plan and, per subject the event names in plan order, whether it still holds."""
    force = state.force_accepted
    if force is None:
        return None
    named = force.get("subjects") or {}
    wanted = [*plan.unit_ids(), *(f"batch:{b.id}" for b in plan.batches if len(b.units) > 1)] if plan else []
    holding = accepting.force_holds(force, plan_digest(text), now) if text is not None else {}
    order = [s for s in wanted if s in named] + sorted(s for s in named if s not in wanted)
    return {
        "by": force.get("by"), "actor": force.get("actor"), "reason": force.get("reason"), "at": force.get("at"),
        "covered": bool(wanted) and all(holding.get(w, False) for w in wanted),
        "subjects": [
            {
                "subject": s, "holds": holding.get(s, False), "skipped": list(named[s].get("skipped") or []),
                "review_at": named[s].get("review_at"), "verdict": named[s].get("verdict"),
            }
            for s in order
        ],
    }  # fmt: skip


def _force_lines(doc: Mapping[str, Any]) -> list[str]:
    """One `accept.force_line` per subject the acceptance overrode (its `skipped` is not empty)."""
    return [
        accepting.force_line(s["subject"], str(doc["by"]), str(doc["reason"]), holds=s["holds"])
        for s in doc["subjects"]
        if s["skipped"]
    ]


def _describe(
    ctx: _Ctx, rev: str | None, file: PlanFile | None, read: PlanRead, pid: str, units: _Units
) -> dict[str, Any]:
    state = fold_plan(pid, read.events)
    plan = file.plan if file else None
    out: dict[str, Any] = {
        "plan_id": pid, "status": state.status, "target": plan.target if plan else None,
        "merge": plan.merge if plan else state.merge, "activated_by": state.activated_by,
    }  # fmt: skip
    if file is not None and file.plan is not None and state.status not in (*FINAL, "active"):
        out["holds"] = len(holds_of({pid: state}, [file]).held)  # units no run touches until the plan is fixed
    out["activated_force"] = [  # L4-YOLO-062: the subjects the activation froze as force-accepted
        {"subject": s, "by": item.get("by"), "reason": item.get("reason")}
        for s, item in sorted(state.activated_accepted.items())
        if item.get("force")
    ]
    if state.waived:  # L4-YOLO-031
        out["waived"] = [
            {"finding": fid, **{k: w.get(k) for k in ("subject", "by", "actor", "reason")}}
            for fid, w in sorted(state.waived.items())
        ]
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
    extensions = _extensions(read.events)
    if extensions:
        out["extensions"] = extensions
    if (delegate := _delegate_status(ctx, plan, state, units, limits.cost_usd)) is not None:
        out["delegate"] = delegate
    out["usage"] = {
        "cost_usd": used.cost_usd, "cost_limit": limits.cost_usd, "runs": used.runs,
        "idle_runs": used.idle_runs, "runs_limit": limits.runs,
        "attempts": dict(used.attempts), "attempts_limit": limits.attempts,
        "deadline": limits.deadline.strftime("%Y-%m-%dT%H:%M:%SZ") if limits.deadline else None,
    }  # fmt: skip
    view = None
    if plan is not None and file is not None and rev is not None:
        needs_review = state.status in _BEFORE_ACTIVATION or (
            state.status == "stopped" and state.stop_reason in ("inputs_changed", "unit_rejected")
        )  # only there a review under an older prompt means a new review
        now = _digests(ctx, plan, units)
        view = _review_view(plan, file.text, state, read.events, now, prompt_matters=needs_review)
        out["review"] = {
            "state": view.kind,
            "problems": list(view.problems),
            "accepted": [{k: a[k] for k in ("subject", "by", "actor", "reason", "holds")} for a in view.accepted],
            "force_accepted": _force_doc(state, plan, file.text, now),
        }
        if view.prompt_changed:
            out["review"]["prompt_changed"] = True
        if view.kind == "stale":
            out["review"]["stale"] = _stale_lines(
                ctx, plan, file, state, read.events, now, units, prompt_matters=needs_review
            )
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
        blocker = resume_blocker(
            pid, state, read.events, plan, units.phases, Extend(), now=_now(), live=live,
            answered=units.answered, halt_reasons=units.halt_reasons,
        )  # fmt: skip
    current_answered = state.status == "waiting" and state.current in units.answered
    if current_answered and out.get("wait_detail"):  # the detail recorded at the wait is stale once the answer is in
        out["wait_detail"] = ANSWER_RECORDED
    out["last_activity"], out["open_run"] = _activity_of(state, read.events, units)
    if out["open_run"] and out["open_run"].get("ci_url"):  # the ledger holds `<forge>/...`: the real address, once
        out["open_run"]["ci_url"] = _expanded(ctx, out["open_run"]["ci_url"])
    advance = _advance(ctx, state, out, units)  # L4-IMP-073: also marks an open run that ended without a record
    out["delegate_hint"] = _delegate_hint(ctx, state, units)
    out["next"] = _next_line(
        pid, state, view, blocker, unit_phase=units.phases.get(state.current) if state.current else None,
        answered=current_answered, start=how_to_start(ctx.app, ctx.cfg, ctx.target) if current_answered else "",
        answer_fix=units.answer_fixes.get(state.current or "", ""), advance=advance,
    )  # fmt: skip
    return out


def _delegate_hint(ctx: _Ctx, state: PlanState, units: _Units) -> str | None:
    """The `Hint:` line of L4-DLG-021 for the plan's current unit while the delegate is off and it waits."""
    from l4.delegate.hint import HintReader

    current = state.current
    if state.status not in ("active", "waiting") or current is None or not units.open_kinds.get(current):
        return None
    return HintReader(ctx.git, ctx.cfg).hint(current, units.phases.get(current), units.open_kinds[current])


def _delegate_status(
    ctx: _Ctx, plan: Plan | None, state: PlanState, units: _Units, cost_limit: float | None
) -> dict[str, Any] | None:
    """What the delegate did on the plan's current unit and what it cost the plan against its share of the cost limit
    in force (L4-DLG-011); None while no unit of the plan has a delegate record, so the output of a plan that never
    used the delegate does not change."""
    from l4.delegate.limits import PlanCost, delegate_cost
    from l4.delegate.lines import summary
    from l4.delegate.settings import delegate_settings

    if plan is None or not any(u in units.delegate for u in plan.unit_ids()):
        return None
    settings = delegate_settings(ctx.git, ctx.cfg.forge.base_branch).delegate
    spent = sum(delegate_cost(units.delegate.get(u, ()), settings.max_cost_usd_per_answer) for u in plan.unit_ids())
    share = PlanCost(cost_limit, spent).share_usd(settings)
    current = state.current if state.current in units.delegate else None
    out: dict[str, Any] = {"unit": current, "cost_usd": round(spent, 6), "share_usd": share}
    if current is not None:
        out.update(summary(units.delegate[current]))
    return out


def _extensions(events: Sequence[PlanEvent]) -> list[dict[str, Any]]:
    """The `plan.extended` events the fold applied (L4-YOLO-050), oldest first: after the plan's first activation and
    before it became final. A re-activation does not forget them, so neither does this list."""
    found: list[dict[str, Any]] = []
    activated = final = False
    for e in events:
        if e.type == "plan.activated" and not final:
            activated = True
        elif e.type in ("plan.cancelled", "plan.completed"):
            final = True
        elif e.type == "plan.extended" and activated and not final:
            found.append(
                {
                    "at": e.at, "by": e.data.get("by"), "actor": e.data.get("actor"),
                    "agent_key": bool(e.data.get("agent_key")), "reason": e.data.get("reason"),
                    "extend": e.data.get("extend") or {}, "limits_before": e.data.get("limits_before") or {},
                    "limits_after": e.data.get("limits_after") or {},
                }
            )  # fmt: skip
    return found


def _activity_of(
    state: PlanState, events: Sequence[PlanEvent], units: _Units
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """L4-YOLO-030: the newer of the current unit's last activity and the plan ledger's newest event, and the current
    unit's open run; `(None, None)` for a plan that is not active, waiting or stopped."""
    if state.status not in ("active", "waiting", "stopped"):
        return None, None
    unit_activity, unit_run = units.activity.get(state.current, (None, None)) if state.current else (None, None)
    best: dict[str, Any] | None = None
    best_at = None
    newest = max(events, key=lambda e: parse_time(e.at) or datetime.min.replace(tzinfo=UTC), default=None)
    if newest is not None and parse_time(newest.at) is not None:  # a plan event shows as its type
        best, best_at = {"ts": newest.at, "type": newest.type}, parse_time(newest.at)
    when = parse_time(unit_activity.ts) if unit_activity is not None else None
    if unit_activity is not None and when is not None and (best_at is None or when >= best_at):  # a tie: the unit
        best = {"ts": unit_activity.ts, "type": unit_activity.type}
        if unit_activity.task is not None:
            best["task"] = unit_activity.task
        best["run_id"] = unit_activity.run_id
        best["unit"] = state.current
    run: dict[str, Any] | None = None
    if unit_run is not None:
        run = {"run_id": unit_run.run_id, "started": unit_run.started}
        if unit_run.ci_url:
            run["ci_url"] = unit_run.ci_url
        run["unit"] = state.current
        run["ended_without_record"] = False  # `_advance` decides (L4-IMP-073)
    return best, run


# --- L4-IMP-073: a run that ended without a record, and a plan that nothing will advance --------------------------


def cron_period_s(cron: str | None) -> int | None:
    """The period of a schedule in seconds: `*/N * * * *` N minutes, `M * * * *` an hour, `M H * * *` a day; 60 minutes
    for any other form. None for no schedule."""
    if cron is None:
        return None
    fields = cron.split()
    if len(fields) != 5:
        return 3600
    minute, hour, *rest = fields
    if rest == ["*", "*", "*"]:
        if hour == "*":
            step = re.fullmatch(r"\*/(\d+)", minute)
            if step and int(step[1]) > 0:
                return int(step[1]) * 60
            if minute.isdigit():
                return 3600
        elif minute.isdigit() and hour.isdigit():
            return 86400
    return 3600


class _Forge(LazyForge):
    """The forge of a yolo command's context (`make_forge`, looked up when first needed)."""

    def __init__(self, ctx: Any) -> None:
        super().__init__(lambda: make_forge(ctx.cfg, ctx.app.environ, repo=ctx.app.repo))


def _ended_why(ctx: Any, run: OpenRun, forge: _Forge) -> tuple[str | None, bool]:
    """`l4.state.liveness.ended_why`, measured with this module's clock."""
    return ended_why(ctx.cfg, run, forge, _now())


def _default_copy_problem(ctx: Any) -> str | None:
    """GitHub, `action` delivery: why the schedule does not run the base's workflow: the default branch (the local
    `origin/HEAD`) is not the base and its copy of the workflow is missing or pins another harness (L4-IMP-074)."""
    try:
        if (
            effective_delivery(ctx.cfg) != "action"
            or forge_platform(ctx.cfg, ctx.app.environ, origin_url(ctx.app.repo, ctx.app.environ)) != "github"
        ):
            return None
        default = _default_branch(ctx.app.repo, ctx.app.environ)
        if default is None or default == ctx.target:
            return None
        copy_ref = f"refs/remotes/origin/{default}"
        own = _branch_pin(ctx.git, ctx.target_ref, "action")
        if own is None:
            return None
        if ctx.git.run("show", f"{copy_ref}:{WORKFLOW_RELPATH}", check=False).returncode != 0:
            return f"{default} has no {WORKFLOW_RELPATH}"
        theirs = _branch_pin(ctx.git, copy_ref, "action")
        if theirs is not None and theirs != own:
            return f"{default}'s copy of {WORKFLOW_RELPATH} pins {theirs[:7]}, not {own[:7]}"
    except Exception as exc:  # noqa: BLE001 - a hint: when it cannot be read there is nothing to name
        log.info("status: the default branch's copy was not read (%s)", type(exc).__name__)
    return None


def _expanded(ctx: Any, url: str) -> str:
    """`url` with the ledger's `<forge>` placeholder replaced by the forge's web address (as `l4 status` does)."""
    try:
        return app_forge_urls(ctx.app, ctx.cfg).expand(url)
    except AttributeError:  # a context without an application: nothing to expand with
        return url


def _advance(ctx: Any, state: PlanState, out: dict[str, Any], units: _Units) -> str | None:
    """Marks the current unit's open run `ended_without_record` (with its `why`) and, for an `active` plan, the `Next:`
    line that starts a run on the base: when that run ended without a record, or nothing is running or queued on the
    base and the plan is idle for two schedule periods or no schedule can advance it. None keeps today's line."""
    run = out.get("open_run")
    if getattr(ctx, "cfg", None) is None or getattr(ctx, "app", None) is None:
        return None  # no configuration to ask with
    forge = _Forge(ctx)
    unit_run = units.activity.get(state.current, (None, None))[1] if state.current else None
    if unit_run is not None and run is not None and run.get("ci_url"):
        unit_run = replace(unit_run, ci_url=run["ci_url"])  # the expanded address
    why, waits = _ended_why(ctx, unit_run, forge) if run is not None and unit_run is not None else (None, False)
    if why:
        run["ended_without_record"], run["why"] = True, why  # type: ignore[index]
    elif waits:
        run["waiting_for_approval"] = True  # type: ignore[index]
    if state.status != "active":
        return None
    base = ctx.target
    if run is not None:
        if run.get("waiting_for_approval"):
            return f"the CI run {run['ci_url']} of {state.current} waits for approval: open it and approve the run"
        if not run["ended_without_record"]:
            return None  # it may still be running
        return (
            f"the run {run['run_id']} of {state.current} ended without a record ({run['why']}); the unit continues "
            f"from its last pushed step: start a run on {base}: {how_to_start(ctx.app, ctx.cfg, base)}"
        )
    period = cron_period_s(ctx.cfg.ci.schedule)
    no_schedule = "ci.schedule is null" if period is None else _default_copy_problem(ctx)
    last = parse_time(out["last_activity"]["ts"]) if out.get("last_activity") else None
    idle_s = (_now() - last).total_seconds() if last is not None else None
    idle = period is not None and idle_s is not None and idle_s > 2 * period
    if no_schedule is None and not idle:
        return None
    found = forge.get()
    if found is None:
        return None
    try:
        queued = found.base_runs(base)
    except Exception as exc:  # noqa: BLE001 - best effort
        log.info("status: the base's runs were not read (%s)", type(exc).__name__)
        return None
    if queued != 0:
        return None
    start = how_to_start(ctx.app, ctx.cfg, base)
    if no_schedule is not None:
        return (
            f"nothing is running or queued on {base}, and no schedule starts runs there ({no_schedule}): "
            f"start a run on {base}: {start}"
        )
    return (
        f"nothing is running or queued on {base} and the plan has been idle for {ago(idle_s or 0).replace(' ', '')}: "
        f"start a run on {base}: {start}"
    )


def _since(ts: str) -> str:
    when = parse_time(ts)
    return ago((_now() - when).total_seconds()) if when else "?"


def _render(d: dict[str, Any]) -> str:
    head = f"plan {d['plan_id']}: {d['status']}"
    if d.get("target"):
        head += f" (target {d['target']}, merge: {d['merge']})"
    lines = [head, *(f"  {p}" for p in d.get("problems", []))]
    if d.get("holds"):
        lines.append(
            f"  holds {d['holds']} unit{'s' if d['holds'] != 1 else ''}; none of them runs until the plan is fixed, "
            "completed or its file is removed"
        )
    if d.get("activated_by"):
        lines.append(f"  activated by {d['activated_by']}")
    lines += [
        f"  {accepting.force_line(f['subject'], str(f['by']), str(f['reason']))}" for f in d.get("activated_force", [])
    ]
    if "review" in d and d["status"] in (*_BEFORE_ACTIVATION, "stopped"):
        changed = " (the review prompt changed)" if d["review"].get("prompt_changed") else ""
        force = d["review"].get("force_accepted")
        covered = (
            " (force-accepted: no review is needed to activate)"
            if force and force["covered"] and not d["review"]["problems"]
            else ""
        )
        lines.append(f"  review: {d['review']['state']}{changed}{covered}")
        lines += [f"    {r}" for r in d["review"].get("stale", [])]
        lines += [f"    {p}" for p in d["review"]["problems"]]
        lines += [
            f"    {a['subject']}: accepted by {a['by']} ({a['actor']}): {a['reason']}"
            for a in d["review"].get("accepted", [])
            if a["holds"]
        ]
        if force:
            lines += [f"    {line}" for line in _force_lines(force)]
    if d.get("stop"):
        stop = d["stop"]
        unit = f" [{stop['unit']}]" if stop.get("unit") else ""
        lines.append(f"  stopped: {stop['reason']}{unit}" + (f": {stop['detail']}" if stop.get("detail") else ""))
    if d.get("wait"):
        lines.append(f"  waiting: {d['wait']}" + (f": {d['wait_detail']}" if d.get("wait_detail") else ""))
    for x in d.get("extensions", []):
        names = ("cost_usd", "runs", "attempts", "deadline")
        before, after = ({k: v.get(k) for k in names} for v in (x["limits_before"], x["limits_after"]))
        via = ", yolo.extend_by_agents" if x["agent_key"] else ""
        lines.append(f"  extended: {_changes(before, after)} by {x['by']} ({x['actor']}{via}): {x['reason']}")
    lines += [f"  waived: {w['finding']} by {w['by']} ({w['actor']}): {w['reason']}" for w in d.get("waived", [])]
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
        f"runs {use['runs']} of {use['runs_limit'] if use['runs_limit'] is not None else 'unlimited'}"
        + (f" ({use['idle_runs']} idle, not counted)" if use.get("idle_runs") else "")
        + "; "
        f"attempts {attempts} (limit {use['attempts_limit']} each)"
        + (f"; deadline {use['deadline']}" if use["deadline"] else "")
    )
    if d.get("delegate"):  # the current unit's decisions, then the plan's delegate cost against its share
        from l4.delegate.lines import cost_line, summary_line

        g = d["delegate"]
        if g.get("unit"):
            lines.append(f"  {summary_line(g)}")
        lines.append(f"  {cost_line(g['cost_usd'], g.get('share_usd'))}")
    if d.get("last_activity"):
        a = d["last_activity"]
        what = (
            a["type"]
            + (f", task {a['task']}" if a.get("task") else "")
            + (f", unit {a['unit']}" if a.get("unit") else "")
        )
        lines.append(f"  last activity: {_since(a['ts'])} ago ({what})")
    if d.get("open_run"):
        r = d["open_run"]
        link = f": {r['ci_url']}" if r.get("ci_url") else ""
        ended = f": it ended without a record ({r['why']})" if r.get("ended_without_record") else ""
        ended = ": the CI run waits for approval" if r.get("waiting_for_approval") else ended
        lines.append(f"  open run: {r['run_id']} started {_since(r['started'])} ago, no end recorded{ended}{link}")
    lines.append(f"Next: {d['next']}")
    if d.get("delegate_hint"):
        lines.append(d["delegate_hint"])
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
    states = {pid: fold_plan(pid, events) for pid, events in ledgers.items()}
    held = holds_of(states, list(files.values())).held
    for pid in sorted(ledgers):
        state = states[pid]
        if state.status in FINAL:
            continue
        plan = files[pid].plan if pid in files else None
        total = len(plan.unit_ids()) if plan else len(state.order)
        unit = f", unit {state.current} ({phases.get(state.current) or '-'})" if state.current else ""
        cost = effective_limits(state, plan.limits.model_dump(mode="json") if plan else None).cost_usd
        limit = "unlimited" if cost is None else f"${cost:.2f}"
        holding = sum(1 for owner, _ in held.values() if owner == pid)
        holds = (
            f" (holds {holding} unit{'s' if holding != 1 else ''}; none of them runs until the plan is fixed, "
            "completed or its file is removed)"
            if state.status != "active" and holding
            else ""
        )
        lines.append(
            f"plan {pid}: {state.status}{holds}{unit}, {len(state.integrated)}/{total} integrated, "
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


def _latest_review_at(events: Sequence[PlanEvent]) -> str | None:
    """The `at` of the latest `plan.reviewed` (the time the person's accepted judgement was recorded)."""
    return next((e.at for e in reversed(events) if e.type == "plan.reviewed"), None)


def _confirm(ctx: _Ctx | None, plan_id: str, text: str, command: str) -> None:
    """Ask a person to type the plan id (L4-YOLO-064, design D8). A prompt runs only on a terminal, goes to stderr and
    is flushed before stdin is read; a wrong answer exits 2 with nothing recorded. `command` is the message prefix."""
    if not _stdin_tty():
        raise L4Exit(ExitCode.USAGE_ERROR, f"{command}: no terminal to ask the plan id on: pass --yes")
    sys.stdout.flush()
    answer = click.prompt(text, default="", show_default=False, err=True)
    if str(answer).strip() != plan_id:
        raise L4Exit(ExitCode.USAGE_ERROR, f"{command}: the plan id was not typed: nothing was recorded")


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
    """`can_accept(subject)` for `findings.render`: None when `accept.check` lets this caller accept the subject now,
    else its first `Refusal` (the findings show why)."""
    who = accepting.actor(ctx.app.environ, _stdin_tty())
    target, _ = _review_cfg(ctx, state)

    def can_accept(subject: str) -> accepting.Refusal | None:
        entry = _entry_of(review, subject)
        if entry is None:
            return accepting.Refusal(f"{subject} is not in the latest review", "l4 yolo review")
        return accepting.check(state, events, subject, entry, target, who)

    return can_accept


def run_findings(
    app: AppContext, *, plan: str, subject: str | None, show_all: bool, as_json: bool, worktree: bool = False
) -> ExitCode:
    """`l4 yolo findings PLAN [SUBJECT] [--all] [--json] [--worktree]`: the findings of the latest review, each with
    how to resolve it (L4-YOLO-021). Reads the ledger and the plan file; calls no model and writes nothing. With
    `--worktree`, the latest `review --worktree` (dry run) from the local cache instead of the ledger. Exit 2 for an
    unknown plan or subject, else 0 (a plan with no review included)."""
    if worktree:
        from l4.yolo.review_worktree import run_findings_worktree  # late: that module reads this one

        return run_findings_worktree(app, plan=plan, subject=subject, show_all=show_all, as_json=as_json)
    plan_id = _plan_id(plan)
    ctx = _open(app)
    rev = _sync(ctx, who="findings")
    file = next((f for f in plan_files_at(ctx.git, ctx.target_ref) if f.plan_id == plan_id), None)
    read = ctx.store(plan_id).read()
    if file is None and read.head is None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"findings: no plan {plan_id} on origin/{ctx.target}")
    state = fold_plan(plan_id, read.events)
    review = _latest_review(read.events)
    parsed = file.plan if file is not None else None
    units = _read_units(ctx, rev, parsed.known_ids(), intake=False) if parsed is not None else None
    force = (  # L4-YOLO-062: the force acceptance, with its holds from the live digests
        _force_doc(state, parsed, file.text if file is not None else None, _digests(ctx, parsed, units))
        if parsed is not None and units is not None
        else _force_doc(state, None, None, {})
    )
    if review is None:
        if as_json:
            empty = {"schema": fnd.SCHEMA, "plan": plan_id, "base": ctx.target, "plan_digest": None, "subjects": []}
            if force is not None:
                empty["force_accepted"] = force  # type: ignore[assignment]
            ctx.say(json.dumps(empty, indent=2))
        else:
            ctx.say(f"{plan_id}: no review yet (l4 yolo review {plan_id}, or --worktree before the push)")
            if force is not None:
                for line in _force_lines(force):
                    ctx.say(line)
        return ExitCode.OK
    if subject is not None and _entry_of(review, subject) is None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"findings: {subject} is not in the latest review of {plan_id}")
    options: dict[str, Any] = {
        "show_all": show_all,
        "units": _subject_infos(parsed, units),
        "accepted": state.accepted,
        "holds": accepting.holds(state, review),
        "why": accepting.whys(state, review, _latest_review_at(read.events)),
        "can_accept": _acceptor(ctx, state, read.events, review),
        "only": subject,
    }

    def history_of(name: str) -> list[dict[str, Any]]:
        return fnd.history(read.events, name, PROMPT_VERSION)

    if as_json:
        doc = fnd.render_json(plan_id, ctx.target, review, history_of, **options)
        if force is not None:
            doc["force_accepted"] = force
        ctx.say(json.dumps(doc, indent=2))
        return ExitCode.OK
    lines = fnd.render(plan_id, ctx.target, review, history_of, **options)
    if lines:
        for line in lines:
            ctx.say(line)
    else:
        ctx.say(f"{plan_id}: every subject of the latest review is READY (--all lists them)")
    if force is not None:
        for line in _force_lines(force):
            ctx.say(line)
    return ExitCode.OK


MAX_REASON = 1000


def _digests_of(entry: Mapping[str, Any]) -> dict[str, str]:
    """The digests an entry judged: a batch's `digests`, else the unit's own."""
    digests = entry.get("digests")
    if isinstance(digests, Mapping):
        return {str(k): str(v) for k, v in digests.items()}
    return {}


def run_accept(
    app: AppContext,
    *,
    plan: str,
    subject: str | None = None,
    reason: str,
    withdraw: bool,
    yes: bool,
    all_subjects: bool = False,
    force: bool = False,
) -> ExitCode:
    """`l4 yolo accept PLAN SUBJECT --reason TEXT [--withdraw] [--yes]` (`PLAN --all --force` is L4-YOLO-057): record
    that a person (or, when the target's configuration allows it, an agent) accepts the latest verdict of one subject
    as it is (L4-YOLO-027, design D7). Reads as `activate` does and writes one event with the lease. A person sees
    every finding of the subject and types the plan id; `--yes` replaces that only for an agent that
    `yolo.review.accept_by_agents` lets accept. Exit 2 for every refusal, with the cause and the fix; nothing is
    recorded then."""
    text = reason.strip()
    if not text:
        raise L4Exit(ExitCode.USAGE_ERROR, "accept: --reason must say why (what the implementer should do)")
    if len(text) > MAX_REASON:
        raise L4Exit(ExitCode.USAGE_ERROR, f"accept: --reason has {len(text)} characters; at most {MAX_REASON}")
    if force and not all_subjects:
        raise L4Exit(ExitCode.USAGE_ERROR, "accept: --force needs --all: it accepts every subject of the plan")
    if all_subjects and not force:
        raise L4Exit(ExitCode.USAGE_ERROR, "accept: --all needs --force: only a force acceptance takes every subject")
    if all_subjects and subject is not None:
        raise L4Exit(ExitCode.USAGE_ERROR, "accept: --all takes no SUBJECT: it accepts every subject of the plan")
    if not all_subjects and subject is None:
        raise L4Exit(ExitCode.USAGE_ERROR, "accept: name a SUBJECT, or --all --force for every subject of the plan")
    plan_id = _plan_id(plan)
    if force:
        return _run_force_accept(app, plan_id=plan_id, reason=text, withdraw=withdraw, yes=yes)
    assert subject is not None
    ctx = _open(app)
    _sync(ctx, who="accept")
    _valid(ctx, _file(ctx, plan_id, "accept"), "accept")
    store = ctx.store(plan_id)
    read = store.read()
    state = fold_plan(plan_id, read.events)
    who = accepting.actor(ctx.app.environ, _stdin_tty())
    if withdraw:
        if not (
            state.status in _BEFORE_ACTIVATION
            or (state.status == "stopped" and state.stop_reason in ("inputs_changed", "unit_rejected"))
        ):
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                f"accept: {plan_id} is {state.status}: the acceptances were frozen at its activation and the runs "
                "read the frozen ones, so a withdrawal now would change nothing\n"
                f"Fix: cancel the plan (l4 yolo cancel {plan_id}), or change the spec and review again "
                f"(l4 yolo review {plan_id})",
            )
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
    refusal = accepting.check(state, read.events, subject, latest, _review_cfg(ctx, state)[0], who)
    if refusal is not None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"accept: {refusal.message}\nFix: {refusal.fix}")
    if latest.get("material") is None:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"accept: the review of {subject} predates material keys, so an acceptance could not be bound to it\n"
            f"Fix: l4 yolo review {plan_id}",
        )
    if who[0] == "person":
        _show_and_confirm(ctx, plan_id, subject, review, read.events, state, yes=yes)
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
        confirmed="--yes" if yes else "typed", judged_at=latest.get("reused_from") or _latest_review_at(read.events),
    )  # fmt: skip
    _append(store, [event], read.head)
    ctx.say(f"accepted: {subject} by {event.data['by']} ({who[0]}): {text}")
    ctx.say(f"Next: l4 yolo status {plan_id}")
    return ExitCode.OK


def _run_force_accept(app: AppContext, *, plan_id: str, reason: str, withdraw: bool, yes: bool) -> ExitCode:
    """`l4 yolo accept PLAN --all --force --reason TEXT [--withdraw] [--yes]` (L4-YOLO-057 to -062, design D1 to D8)."""
    who = accepting.actor(app.environ, _stdin_tty())
    if not withdraw and who[0] != "person":  # D2: before anything is fetched; accept_by_agents does not apply
        why = f"{who[1]} is set" if who[1] else "stdin is not a terminal"
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"accept: --force is a person's decision, never an agent's ({why}), whatever "
            "yolo.review.accept_by_agents says\n"
            f'Fix: a person runs, in a terminal: l4 yolo accept {plan_id} --all --force --reason "..."',
        )
    ctx = _open(app)
    rev = _sync(ctx, who="accept")
    file = _file(ctx, plan_id, "accept")
    parsed = _valid(ctx, file, "accept")
    store = ctx.store(plan_id)
    read = store.read()
    state = fold_plan(plan_id, read.events)
    if withdraw:  # D7: never refused for who runs it; it only makes the activation stricter
        if accepting.status_refusal(state) is not None:
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                f"accept: {plan_id} is {state.status}: the acceptances were frozen at its activation and the runs "
                "read the frozen ones, so a withdrawal now would change nothing\n"
                f"Fix: cancel the plan (l4 yolo cancel {plan_id}), or change the spec and review again "
                f"(l4 yolo review {plan_id})",
            )
        if state.force_accepted is None:
            raise L4Exit(ExitCode.USAGE_ERROR, f"accept: {plan_id} has no force acceptance: nothing to withdraw")
        event = _event("plan.force_acceptance_withdrawn", reason=reason, by=ctx.who(), actor=who[0], marker=who[1])
        _append(store, [event], read.head)
        ctx.say(f"{plan_id}: the force acceptance is withdrawn")
        ctx.say(f"Next: l4 yolo review {plan_id}")
        return ExitCode.OK
    refusal = accepting.status_refusal(state)
    if refusal is not None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"accept: {refusal.message}\nFix: {refusal.fix}")
    units, admission = _admitted(ctx, rev, parsed, plan_id, state, "accept")
    now = _digests(ctx, parsed, units)
    for unit in parsed.unit_ids():
        if now.get(unit, MISSING) == MISSING:
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                f"accept: {unit} has no folder with files on its branch or on origin/{ctx.target} (unit_missing): "
                f"nothing can be built from it\nFix: push its folder, or remove it from .l4/plans/{plan_id}.json",
            )
    digest = plan_digest(file.text)
    subjects = accepting.force_subjects(parsed, digest, now, read.events, _review_cfg(ctx, state)[0], PROMPT_VERSION)
    ctx.say(
        f"{plan_id}: force-accept {len(subjects)} subject(s) without a readiness review; "
        "no model reviews these specifications before they are built:"
    )
    for name, row in subjects.items():
        words = ", ".join(accepting.SKIPPED_WORDS[c] for c in row["skipped"])
        ctx.say(f"  {name}: {words or 'READY at these inputs: nothing is overridden'}")
    if not yes:
        _confirm(
            ctx,
            plan_id,
            f"Type the plan id ({plan_id}) to accept every subject of {plan_id} without a review",
            "accept",
        )
    order = list(admission.order)
    events = []
    if not (state.status in ("admitted", "reviewed") and state.plan_digest == digest and state.order == order):
        events.append(_event("plan.admitted", plan_digest=digest, order=order, merge=parsed.merge))
    events.append(
        _event(
            "plan.force_accepted", plan_digest=digest, subjects=subjects, reason=reason, by=ctx.who(), actor="person",
            marker=None, confirmed="--yes" if yes else "typed",
        )
    )  # fmt: skip
    _append(store, events, read.head)
    ctx.say(
        f"force-accepted: {len(subjects)} subject(s) of {plan_id} without review by {events[-1].data['by']} (person): "
        f"{reason}"
    )
    ctx.say(f"Next: l4 yolo activate {plan_id} --reason TEXT")
    return ExitCode.OK


_WAIVABLE = ("active", "waiting", "stopped")


def _accepted_findings(state: PlanState) -> dict[str, tuple[str, dict[str, Any], dict[str, Any]]]:
    """finding id -> (subject, the finding, its item) for every finding the activation froze (L4-YOLO-028)."""
    out: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {}
    for subject, item in state.activated_accepted.items():
        for finding in item.get("findings") or ():
            if isinstance(finding, Mapping):
                out[fnd.finding_id(subject, finding)] = (subject, dict(finding), item)
    return out


def run_waive(
    app: AppContext, *, plan: str, finding: str, reason: str, withdraw: bool, yes: bool, no_run: bool = False
) -> ExitCode:
    """`l4 yolo waive PLAN FINDING --reason TEXT [--withdraw] [--yes] [--no-run]`: record that a person (or, when the
    target's configuration lets agents accept, an agent) waives one accepted finding of the activation: the merge gate
    counts it as answered and the harness merges the unit itself (L4-YOLO-031). A person sees the finding and types the
    plan id. Writes one event with the lease, then starts a run. Exit 2 for every refusal, with nothing recorded."""
    text = reason.strip()
    if not text:
        raise L4Exit(ExitCode.USAGE_ERROR, "waive: --reason must say why (why the finding needs no handling)")
    if len(text) > MAX_REASON:
        raise L4Exit(ExitCode.USAGE_ERROR, f"waive: --reason has {len(text)} characters; at most {MAX_REASON}")
    plan_id = _plan_id(plan)
    ctx = _open(app)
    _sync(ctx, who="waive")
    store = ctx.store(plan_id)
    read = store.read()
    state = fold_plan(plan_id, read.events)
    who = accepting.actor(ctx.app.environ, _stdin_tty())
    if state.status not in _WAIVABLE:
        before = state.status in _BEFORE_ACTIVATION
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"waive: {plan_id} is {state.status}: a waiver is of a finding the activation froze"
            + (f"\nFix: before the activation, accept the review instead: l4 yolo accept {plan_id} SUBJECT "
               "--reason TEXT" if before else ""),
        )  # fmt: skip
    if withdraw:
        if finding not in state.waived:
            raise L4Exit(ExitCode.USAGE_ERROR, f"waive: {finding} has no waiver: nothing to withdraw")
        event = _event("plan.waiver_withdrawn", finding=finding, reason=text, by=ctx.who(), actor=who[0])
        _append(store, [event], read.head)
        ctx.say(f"{plan_id}: the waiver of {finding} is withdrawn")
        ctx.say(f"Next: l4 yolo status {plan_id}")
        return ExitCode.OK
    known = _accepted_findings(state)
    if finding not in known:
        ids = ", ".join(sorted(known)) or "none"
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"waive: {finding} is not an accepted finding of {plan_id} (its accepted findings: {ids})\n"
            f"Fix: l4 yolo status {plan_id} names the open ones in its wait",
        )
    review_cfg, note = _review_cfg(ctx, state)
    if who[0] == "agent" and not review_cfg.accept_by_agents:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            "waive: a waiver is a person's decision" + (f" ({note})" if note else "") + "\n"
            f'Fix: a person runs: l4 yolo waive {plan_id} {finding} --reason "..."; or set '
            "yolo.review.accept_by_agents: true in .l4/config.yaml on the base branch (a pushed change a person can "
            "see)",
        )
    subject, found, item = known[finding]
    if who[0] == "person":
        kind = f"{found.get('criterion', '')}/{found.get('severity', '')}"
        ctx.say(f"{finding} [{kind}] of {subject}: {found.get('text', '')}")
        ctx.say(f"  accepted by {item.get('by', '?')} ({item.get('actor', '?')}): {item.get('reason', '')}")
        if not yes:
            _confirm(
                ctx, plan_id, f"Type the plan id ({plan_id}) to waive {finding}: the unit merges without it", "waive"
            )
    elif not yes:
        raise L4Exit(
            ExitCode.USAGE_ERROR, "waive: no terminal to ask the plan id on: an agent that may accept passes --yes"
        )
    event = _event(
        "plan.finding_waived",
        finding=finding,
        subject=subject,
        reason=text,
        by=ctx.who(),
        actor=who[0],
        marker=who[1],
        confirmed="--yes" if yes else "typed",
    )
    _append(store, [event], read.head)
    ctx.say(f"waived: {finding} by {event.data['by']} ({who[0]}): {text}")
    if not no_run:
        ctx.say(start_run_line(ctx.app, ctx.cfg))
    ctx.say(f"Next: l4 yolo status {plan_id}")
    return ExitCode.OK


def _show_and_confirm(
    ctx: _Ctx,
    plan_id: str,
    subject: str,
    review: Mapping[str, Any],
    events: Sequence[PlanEvent],
    state: PlanState,
    *,
    yes: bool = False,
) -> None:
    """Print every finding of the subject, then ask for the plan id unless a person passed `--yes`; any other answer
    exits 2 with nothing recorded."""
    lines = fnd.render(
        plan_id, ctx.target, review, lambda name: fnd.history(events, name, PROMPT_VERSION), show_all=True,
        only=subject, accepted=state.accepted, holds=accepting.holds(state, review),
        why=accepting.whys(state, review, _latest_review_at(events)),
    )  # fmt: skip
    for line in lines:
        ctx.say(line)
    if not yes:
        _confirm(
            ctx, plan_id, f"Type the plan id ({plan_id}) to accept the findings of {subject} as they are", "accept"
        )


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
    "run_waive",
]
