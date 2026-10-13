"""`l4 plan` (SPEC 2.1, simulation-harness D6): the next action of every unit, from its folded phase and task counts.

Next action is one of implement, clarify, verify, hand_off, follow_up, none. The question facts come from the unit's
snapshot (`questions.md` of the unit branch, read beside tasks and ledger): an `awaiting_human` unit is actionable
only when committed answers free a task. The path of the files is never probed here. No resume/sweep duties. `--probe`
adds what `l4.sim.availability` finds out about the agents the next actions need; without it the plan is the same
bytes. `facts_of` over `l4.state.status.load_snapshot` plays the part of simulation-harness' `LiveUnitSource`.
`--sweep` first runs the minimal sweeper (`l4.ci.sweeper`: merged units and their archive merge requests, and the
project's own CI on the hand-off commit of a unit in review, printed as `ci: H <sha10> ...` on stderr), then plans.
`--detailed-exitcode` exits 10 when something is actionable; the CI outputs (`.l4-out/l4.env`, `$GITHUB_OUTPUT`) are
written by `with_outcome` from the `actionable` ids. M1: `StaticUnitSource`.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import click

from l4.ci.sweeper import sweep as run_sweep
from l4.config.redaction import load_app_config
from l4.context import AppContext
from l4.exitcodes import plan_exit_code
from l4.forge.urls import ForgeUrls, app_forge_urls
from l4.implementer.tasks import answers_unblock, open_blocking_questions, questions_hold
from l4.outcome import CommandResult, TaskCounts, UnitOutcome
from l4.sim.availability import ProbingAvailability, availability_json, roles_needed
from l4.specs.questions import blocked_tasks
from l4.state.lifecycle import SPEC_EDIT_PHASES, TERMINAL, Phase
from l4.state.status import UnitSnapshot, snapshots
from l4.vcs.git import Git
from l4.verifier.verdicts import legacy_round, verdict_status

PLAN_SCHEMA = "l4/plan@1"
_TERMINAL_VALUES = {p.value for p in TERMINAL}
_SPEC_EDIT_VALUES = {p.value for p in SPEC_EDIT_PHASES}
_IMPLEMENT = {Phase.INTAKE.value, Phase.READY.value, Phase.IMPLEMENTING.value}
_VERIFY = {Phase.IMPLEMENTED.value, Phase.VERIFYING.value}
_FIXING = {Phase.FIXING.value}  # parked in the fix loop: a run takes the unit back into it (L4-OPS-009)
_NOT_ACTIONABLE = {
    Phase.AWAITING_HUMAN.value: "awaiting_human: no new answers",
    Phase.FIXING.value: "fixing: fix units are not implemented in M0",
    Phase.WAITING_CAPACITY.value: "waiting_capacity: run l4 retry to try the agents now",
    Phase.HALTED.value: "halted: run l4 retry (or the label l4:retry)",
    Phase.ESCALATED.value: "escalated: run l4 retry (or the label l4:retry)",
    Phase.REJECTED.value: "rejected: inputs unchanged",
    Phase.IN_REVIEW.value: "in_review: waiting for merge",
    Phase.ARCHIVED.value: "archived: waiting for merge",
    Phase.MERGED.value: "merged",
    Phase.ABANDONED.value: "abandoned",
}


@dataclass(frozen=True)
class UnitFacts:
    unit: str
    framework: str
    phase: str | None
    tasks_done: int
    tasks_total: int
    corrupt: str | None = None  # where the ledger is unreadable, if it is
    open_blocking_questions: tuple[str, ...] = ()  # unanswered questions that hold a pending task
    answers_unblock: tuple[str, ...] = ()  # answered questions that free a pending task, when one is eligible
    retry_after: str | None = None  # waiting_capacity: when the earliest cool-down ends
    previous_phase: str | None = None  # waiting_capacity: the phase the unit was parked from
    halt_detail: str | None = None  # halted or escalated: the person's text of the stop (L4-OPS-005, L4-OPS-006)
    drafts: tuple[str, ...] = ()  # an answer is written but Status is still `open`: never consumed (SCN-QMD-03)
    unreadable: tuple[str, ...] = ()  # questions whose section or Blocking tasks line could not be read
    verdicts_open: tuple[str, ...] = ()  # verdict questions the verifier asked and nobody answered
    verdicts_ready: tuple[str, ...] = ()  # answered with `accept` or `reject`, not yet consumed
    verdicts_invalid: tuple[str, ...] = ()  # answered, but not starting with `accept` or `reject`
    verdicts_dismissed: tuple[str, ...] = ()  # Status `dismissed`: read as open (L4-OPS-009)
    fix_unit_of: str | None = None  # this unit is a fix unit of that parent: never planned on its own (G5)
    open_fix_unit: str | None = None  # the last fix unit spawned and not done
    fix_progress: tuple[int, int] | None = None  # (done, total) tasks of the open fix unit
    fix_questions_open: tuple[str, ...] = ()  # its unanswered questions, when every pending task is held by one
    legacy_round: int | None = None  # awaiting_human on a NEEDS_HUMAN round that has no verdict question (L4-VER-013)
    handoff_sha: str | None = None  # in_review: H, the hand-off commit (M1.9)
    after_handoff: tuple[str, ...] = ()  # in_review: shas of the commits after H that the harness did not make
    spec_edit_after_handoff: bool = False  # in_review: those commits changed the unit folder (answers, spec edits)
    handoff_lost: bool = False  # in_review: no H on the branch (history rewritten)
    spec_edited: tuple[
        str, ...
    ] = ()  # a person's commits after the harness's last one changed the unit folder (OPS-014)
    ci_failed_jobs: tuple[str, ...] = ()  # in_review: the project's CI is red on H, which is the branch head
    follow_up_items: tuple[str, ...] = ()  # merged: the feedback items (ids) a follow-up should take (L4-FBK-010)
    follow_up_open: str | None = None  # merged: the follow-up that is open, so newer items wait


@dataclass(frozen=True)
class PlanEntry:
    unit: str
    framework: str
    phase: str | None
    next_action: str  # implement | clarify | verify | hand_off | follow_up | none
    actionable: bool
    reason: str
    tasks_done: int
    tasks_total: int


def _after_capacity(facts: UnitFacts, now: datetime) -> tuple[str, str] | None:
    """The `waiting_capacity` row (forge-and-ci 2.32, reduced): the previous phase's action once `retry_after` has
    passed, `none` before that. A park from `fixing` is continued by a run too (`implement`: the run drives the fix
    unit). A park without a readable `retry_after`, or from another phase, stays as it was (the park always records
    one now, L4-OPS-009)."""
    try:
        due = datetime.fromisoformat(facts.retry_after or "")
    except ValueError:
        return None
    if due.tzinfo is None:
        return None
    if due > now:
        return "none", f"waiting_capacity until {facts.retry_after}"
    previous = facts.previous_phase
    action = "implement" if previous in _IMPLEMENT | _FIXING else "verify" if previous in _VERIFY else None
    return (action, f"capacity: retry_after {facts.retry_after} passed") if action else None


def _in_review(facts: UnitFacts) -> tuple[str, str] | None:
    """The review re-entry rows (SPEC 12.0, M1 form: `in_review` only). A commit after H the harness did not make comes
    first (G1), then the project's own CI red on H (G2); the harness's own commits after H wait like H does."""
    h = (facts.handoff_sha or "")[:10]
    if facts.after_handoff and facts.spec_edit_after_handoff:
        return "implement", f"in_review: answers or spec edits after the hand-off ({h})"
    if facts.after_handoff:
        shas = ", ".join(sha[:10] for sha in facts.after_handoff)
        return "verify", f"in_review: commit(s) after the hand-off not made by the harness: {shas}"
    if facts.handoff_lost:
        return "verify", "in_review: the hand-off commit is not on the branch (history rewritten)"
    if facts.ci_failed_jobs:
        return "verify", f"in_review: repository CI failed on {h}: {', '.join(facts.ci_failed_jobs)}"
    return None


def next_action(facts: UnitFacts, now: datetime | None = None) -> tuple[str, str]:
    """(action, reason), a pure function of the phase and the task counts (SPEC 12.0); `now` only matters for a unit
    waiting for capacity."""
    phase = facts.phase
    if facts.corrupt:
        return "none", f"ledger corrupt: {facts.corrupt}"
    if facts.fix_unit_of:
        return "none", f"fix unit of {facts.fix_unit_of}: run the parent"
    if facts.spec_edited and phase in _SPEC_EDIT_VALUES:  # a person's push re-enters the unit by itself (L4-OPS-014)
        return "implement", f"spec edited after {phase}: {facts.spec_edited[-1][:10]}"
    pending = facts.tasks_done < facts.tasks_total
    if phase is None:
        if facts.tasks_total == 0:
            return "none", "no tasks"
        return ("implement", "pending tasks") if pending else ("verify", "all tasks done, no verification record")
    if phase in _IMPLEMENT:
        return "implement", f"{phase}: pending tasks" if pending else f"{phase}: continue"
    if phase in _VERIFY:
        return "verify", f"{phase}: verification outstanding"
    if phase == Phase.FIXING.value and facts.open_fix_unit:
        if facts.fix_questions_open:
            return "none", f"fixing: fix unit questions open: {', '.join(facts.fix_questions_open)}"
        done = f": {facts.fix_progress[0]}/{facts.fix_progress[1]} tasks" if facts.fix_progress else ""
        return "implement", f"fix unit {facts.open_fix_unit}{done}"
    if phase == Phase.VERIFIED.value:
        if facts.open_fix_unit:
            return "implement", f"fix unit {facts.open_fix_unit} spawned for minor findings"
        return "hand_off", "verified: ready for hand-off"
    if phase == Phase.CLARIFYING.value:
        return "clarify", "clarifying: open questions go to the clarifier"
    if phase == Phase.AWAITING_HUMAN.value:
        if facts.verdicts_invalid:
            return "none", (
                f"awaiting_human: verdict answer must start with accept or reject: {', '.join(facts.verdicts_invalid)}"
            )
        if facts.verdicts_dismissed:
            ids = "; ".join(
                f"{qid}: a verdict question cannot be dismissed: start the answer with accept or reject"
                for qid in facts.verdicts_dismissed
            )
            return "none", f"awaiting_human: {ids}"
        if facts.verdicts_ready and not facts.verdicts_open:
            return "verify", f"verdicts answered: {', '.join(facts.verdicts_ready)}"
        if facts.answers_unblock:
            return "implement", f"answers submitted: {', '.join(facts.answers_unblock)}"
        if facts.legacy_round is not None:
            return "verify", (
                f"legacy round {facts.legacy_round}: NEEDS_HUMAN without verdict questions, the run raises them"
            )
        waiting = f" (open: {', '.join(facts.open_blocking_questions)})" if facts.open_blocking_questions else ""
        if facts.verdicts_open:
            waiting += f" (verdicts open: {', '.join(facts.verdicts_open)})"
        if facts.drafts:
            waiting += f" (answer written but Status is still open: {', '.join(facts.drafts)})"
        if facts.unreadable:
            waiting += f" (unreadable in questions.md, all tasks held: {', '.join(facts.unreadable)})"
        return "none", f"{_NOT_ACTIONABLE[phase]}{waiting}"
    if phase == Phase.WAITING_CAPACITY.value and (row := _after_capacity(facts, now or datetime.now(UTC))):
        return row
    if phase == Phase.IN_REVIEW.value and (row := _in_review(facts)):
        return row
    if phase == Phase.MERGED.value and facts.follow_up_items:
        ids = ", ".join(facts.follow_up_items)
        if facts.follow_up_open:
            return "none", f"merged: feedback {ids} waits for the open follow-up {facts.follow_up_open}"
        return "follow_up", f"merged: feedback {ids} becomes a follow-up unit"
    if phase in (Phase.HALTED.value, Phase.ESCALATED.value) and facts.halt_detail:
        return "none", f"{phase}: {facts.halt_detail}"  # the recorded cause, not the fixed text (L4-OPS-006)
    if phase in _NOT_ACTIONABLE:
        return "none", _NOT_ACTIONABLE[phase]
    return "none", f"unknown phase {phase}"


def compute_plan(units: Sequence[UnitFacts]) -> list[PlanEntry]:
    entries = []
    for facts in sorted(units, key=lambda f: f.unit):
        action, reason = next_action(facts)
        entries.append(
            PlanEntry(
                facts.unit, facts.framework, facts.phase, action, action != "none", reason, facts.tasks_done,
                facts.tasks_total,
            )
        )  # fmt: skip
    return entries


def _issue_ids(snapshot: UnitSnapshot, *kinds: str) -> tuple[str, ...]:
    issues = snapshot.questions.issues if snapshot.questions else ()
    return tuple(dict.fromkeys(i.question_id for i in issues if i.kind in kinds))


def _fix_facts(snapshot: UnitSnapshot) -> tuple[tuple[int, int] | None, tuple[str, ...]]:
    """(done, total) tasks of the open fix unit, and its unanswered questions when each pending task is held by one."""
    name = snapshot.state.open_fix_unit
    child = next((c for c in snapshot.children if c.name == name), None) if name else None
    if child is None:
        return None, ()
    pending = [t.key for t in child.tasks if not t.done]
    file = child.questions
    blocked = blocked_tasks(file.questions, pending, file.unreadable_ids) if file else frozenset()
    held = questions_hold(child.tasks, blocked)
    return (child.tasks_done, len(child.tasks)), tuple(open_blocking_questions(file, child.tasks)) if held else ()


def _review_facts(snapshot: UnitSnapshot) -> dict[str, Any]:
    review, failure = snapshot.review, snapshot.state.ci_failure
    if review is None:
        return {}
    facts: dict[str, Any] = {
        "handoff_sha": review.handoff, "after_handoff": tuple(c.sha for c in review.foreign),
        "spec_edit_after_handoff": review.spec_edit, "handoff_lost": review.lost,
    }  # fmt: skip
    if failure is not None and review.at_handoff and failure.head == review.handoff:
        facts["ci_failed_jobs"] = tuple(str(job.get("name", "")) for job in failure.jobs)
    return facts


def _spec_edit_facts(snapshot: UnitSnapshot) -> dict[str, Any]:
    edit, pending = snapshot.spec_edit, snapshot.state.pending_spec_edit
    if edit is not None:
        return {"spec_edited": edit.shas}
    return {"spec_edited": tuple(pending.commits)} if pending is not None else {}  # seen while fixing (L4-OPS-014)


def _follow_up_facts(snapshot: UnitSnapshot) -> dict[str, Any]:
    offer = snapshot.follow_up
    if offer is None or not offer.items:
        return {}
    return {"follow_up_items": tuple(i.id for i in offer.items), "follow_up_open": offer.open}


def facts_of(snapshot: UnitSnapshot) -> UnitFacts:
    verdicts = verdict_status(snapshot.questions, snapshot.state.verdicts_consumed)
    progress, fix_open = _fix_facts(snapshot)
    return UnitFacts(
        unit=snapshot.ref.id,
        framework=snapshot.ref.framework.value,
        phase=snapshot.state.phase,
        tasks_done=snapshot.tasks_done,
        tasks_total=snapshot.tasks_total,
        corrupt=snapshot.corrupt,
        open_blocking_questions=tuple(open_blocking_questions(snapshot.questions, snapshot.tasks)),
        answers_unblock=tuple(answers_unblock(snapshot.questions, snapshot.tasks)),
        retry_after=snapshot.state.retry_after,
        previous_phase=snapshot.state.previous_phase,
        halt_detail=snapshot.state.halt_detail,
        drafts=_issue_ids(snapshot, "unsubmitted_answer"),
        unreadable=_issue_ids(snapshot, "unreadable_section", "unreadable_blocking"),
        verdicts_open=verdicts.open,
        verdicts_ready=verdicts.ready,
        verdicts_invalid=verdicts.invalid,
        verdicts_dismissed=verdicts.dismissed,
        fix_unit_of=snapshot.fix_of,
        open_fix_unit=snapshot.state.open_fix_unit,
        fix_progress=progress,
        fix_questions_open=fix_open,
        legacy_round=legacy_round(snapshot.state, snapshot.questions),
        **_review_facts(snapshot),
        **_spec_edit_facts(snapshot),
        **_follow_up_facts(snapshot),
    )


def render_json(entries: Sequence[PlanEntry], availability: Mapping[str, Any] | None = None) -> str:
    """Sorted keys and no timestamps or run ids in the body: two runs over the same state are byte-identical.
    `availability` (from `--probe`) is a top-level key that is absent otherwise."""
    units = [
        {
            "unit": e.unit, "framework": e.framework, "phase": e.phase, "next_action": e.next_action,
            "actionable": e.actionable, "reason": e.reason, "tasks": {"done": e.tasks_done, "total": e.tasks_total},
        }
        for e in entries
    ]  # fmt: skip
    document: dict[str, Any] = {"schema": PLAN_SCHEMA, "units": units}
    if availability is not None:
        document["availability"] = availability
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False)


def render_table(entries: Sequence[PlanEntry], availability: Sequence[str] = ()) -> str:
    if not entries:
        return "no units"
    header = ("UNIT", "PHASE", "TASKS", "NEXT", "REASON")
    rows = [(e.unit, e.phase or "-", f"{e.tasks_done}/{e.tasks_total}", e.next_action, e.reason) for e in entries]
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    table = "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in [header, *rows])
    return "\n".join([table, "", "availability:", *(f"  {line}" for line in availability)]) if availability else table


def _outcome(snapshot: UnitSnapshot, urls: ForgeUrls | None = None) -> UnitOutcome:
    state = snapshot.state
    phase = state.phase or "none"
    return UnitOutcome(
        unit=snapshot.ref.id, phase_before=phase, phase_after=phase,  # plan changes nothing
        tasks=TaskCounts(done=snapshot.tasks_done, total=snapshot.tasks_total),
        open_questions=list(state.questions.open),
        verdict=state.last_verdict.verdict if state.last_verdict else None,
        cost_usd=state.cost_usd, iteration=state.iteration,
        pr_url=urls.expand(state.pr) if urls is not None and state.pr else state.pr,
    )  # fmt: skip


def run_plan(
    app: AppContext, *, units: tuple[str, ...], as_json: bool, probe: bool, sweep: bool, detailed_exitcode: bool
) -> CommandResult:
    app, cfg = load_app_config(app)  # schema errors: exit 2, nothing else runs
    rows = snapshots(app, cfg, units)
    if sweep and (done := run_sweep(app, cfg, Git(app.repo, environ=app.environ), rows, ci=True)):
        for action in done:
            if action.what.startswith("ci_"):  # stderr: stdout is the plan, and `--json` must stay JSON
                click.echo(app.redactor.redact_text(f"{action.unit}: ci: {action.detail}"), err=True)
        rows = snapshots(app, cfg, units)  # the sweep wrote pending events: fold them
    entries = compute_plan([facts_of(s) for s in rows])
    found: dict[str, Any] | None = None
    lines: list[str] = []
    if probe:
        view = ProbingAvailability(cfg, app.environ, app.repo)
        roles = roles_needed({e.next_action for e in entries if e.actionable})  # the heads the next actions need
        found = availability_json(view, roles)
        lines = [view.head(role).line() for role in roles]
    click.echo(app.redactor.redact_text(render_json(entries, found) if as_json else render_table(entries, lines)))
    live = [s for s in rows if (s.state.phase or "") not in _TERMINAL_VALUES]
    actionable = tuple(e.unit for e in entries if e.actionable)
    urls = app_forge_urls(app, cfg)
    return CommandResult(plan_exit_code(actionable, detailed_exitcode), [_outcome(s, urls) for s in live], actionable)
