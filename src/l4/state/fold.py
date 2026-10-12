"""`UnitState` as a pure fold over the ledger (SPEC 12.1, L4-STA-002): the ledger is the truth, state.json a cache.

M0 folds the events the M0 path emits; unknown types are ignored so a newer ledger still folds.
M1: state-vcs-locks 1.19 (`rebuild_state`, `state_drift`, state.json), and the fields of l4/state@1 that no M0
event sets (`fix_round`, `children`, `parent`, `cooldowns`, `branch`, retry/halt reasons, breakers).
"""

import json
from collections.abc import Callable, Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from l4.state.ledger import TS_FORMAT, LedgerEvent

# Phases the unit is parked in: the phase it came from is remembered so `resume` can return there (SPEC 12.0).
PARKING_PHASES = frozenset({"waiting_capacity", "halted", "escalated", "abandoned"})


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TaskProgress(_Model):
    done: list[str] = Field(default_factory=list)  # task keys, sorted
    in_progress: str | None = None


class QuestionState(_Model):
    open: list[str] = Field(default_factory=list)
    answered: list[str] = Field(default_factory=list)


class LastVerdict(_Model):
    round: int
    verdict: str
    findings: int


class CiFailure(_Model):
    """The last `ci.failed` of the sweep: the project's own CI was red on H (M1.9, SPEC 12.0)."""

    head: str
    pipeline: int | str | None = None
    jobs: list[dict[str, Any]] = Field(default_factory=list)  # {name, stage, url, tail}
    preexisting: list[str] = Field(default_factory=list)  # red on H and on the base: not this unit's


class FeedbackState(_Model):
    """One item of `feedback.md` as the ledger records it (L4-FBK-004, L4-FBK-007; design D7). `sha256` is the hash of
    the item's human content at the LAST TAKE (`feedback.taken`): an item whose current content hashes differently is
    takeable again. `changed_sha256` is the hash a `feedback.changed` saw after that take, until the next take."""

    status: Literal["taken", "addressed", "not_addressed", "withdrawn", "invalid", "waiting"]
    kind: str | None = None
    sha256: str | None = None  # of the last take; None for an item that was never taken
    changed_sha256: str | None = None
    round: int | None = None  # the round of the last take, addressed or not_addressed
    fix_unit: str | None = None  # the fix unit of the last take
    sha: str | None = None  # `feedback.addressed{sha}`: the commit that addressed it
    evidence: str | None = None  # the judge's evidence for addressed or not_addressed
    problem: str | None = None  # `feedback.invalid{problem}`
    reason: str | None = None  # `feedback.waiting{reason}`, e.g. fix_unit_full


class UnitState(_Model):
    schema_id: Literal["l4/state@1"] = Field("l4/state@1", alias="schema")
    unit: str
    phase: str | None = None
    previous_phase: str | None = None
    iteration: int = 0
    tasks: TaskProgress = Field(default_factory=TaskProgress)
    questions: QuestionState = Field(default_factory=QuestionState)
    profiles_used: dict[str, list[str]] = Field(default_factory=dict)
    sessions: dict[str, str] = Field(default_factory=dict)
    retry_after: str | None = None  # ISO time; set while the unit is in waiting_capacity
    fallback_from: dict[str, str] = Field(default_factory=dict)  # role -> the preferred profile it fell back from
    cost_usd: float = 0.0
    last_verdict: LastVerdict | None = None
    fix_round: int = 0
    children: list[str] = Field(default_factory=list)  # fix unit names, in the order they were spawned
    open_fix_unit: str | None = None  # the last fix unit spawned and not yet done
    verdicts_consumed: list[str] = Field(default_factory=list)  # verdict question ids a `human.verdict` recorded
    verdict_asked_round: int | None = None  # the latest round that a `question.raised{kind: verdict}` names
    pr: str | None = None
    ci_heads: dict[str, str] = Field(
        default_factory=dict
    )  # head sha -> failed | preexisting: the sweep acts once per H
    ci_failure: CiFailure | None = None
    breaker_trips: int = 0  # `breaker.tripped` events since the last `unit.resumed` (L4-IMP-013)
    fix_rounds_extra: int = 0  # the sum of `budget.extended{fix_rounds}`, added to `verifier.max_fix_rounds`
    feedback_rounds_extra: int = 0  # the sum of `budget.extended{feedback_rounds}`, added to `feedback.max_rounds`
    fix_rounds_counted: int = 0  # the fix units that are not feedback-only: what `verifier.max_fix_rounds` limits
    feedback_rounds_used: int = 0  # `fix.spawned{feedback_only: true}` events: feedback fix units (absent = false)
    feedback: dict[str, FeedbackState] = Field(default_factory=dict)  # item id -> state, from the `feedback.*` events
    resumed_signals: list[str] = Field(default_factory=list)  # `unit.resumed{signal}`: label events acted on (one each)
    refused_signals: dict[str, str] = Field(default_factory=dict)  # `resume.refused{signal, why}`: said once each
    halt_reason: str | None = None  # the `reason` of the edge into `halted` or `escalated`; None in any other phase
    hinted_heads: list[str] = Field(default_factory=list)  # `resume.hint{head}`: branch heads a halt pointer was for
    updated_at: str | None = None


def _text(event: LedgerEvent, key: str) -> str | None:
    value = event.data.get(key)
    return value if isinstance(value, str) and value else None


def _run_started(state: UnitState, event: LedgerEvent) -> None:
    state.iteration += 1


def _phase_changed(state: UnitState, event: LedgerEvent) -> None:
    target, source = _text(event, "to"), _text(event, "from")
    if target is None:
        return
    if target in PARKING_PHASES:
        state.previous_phase = source
    elif source in PARKING_PHASES:
        state.previous_phase = None
    state.retry_after = _text(event, "retry_after") if target == "waiting_capacity" else None
    state.halt_reason = _text(event, "reason") if target in ("halted", "escalated") else None
    state.phase = target


def _fix_unit(event: LedgerEvent) -> str | None:
    """The fix unit an event belongs to (`event_context` of its workbench): its tasks and questions are numbered from 1
    like the parent's, so they are not the parent's own."""
    return _text(event, "fix_unit")


def _task_started(state: UnitState, event: LedgerEvent) -> None:
    if _fix_unit(event):
        return
    if task := _text(event, "task"):
        state.tasks.in_progress = task


def _task_done(state: UnitState, event: LedgerEvent) -> None:
    if _fix_unit(event):
        return
    if task := _text(event, "task"):
        state.tasks.done = sorted({*state.tasks.done, task})
        if state.tasks.in_progress == task:
            state.tasks.in_progress = None


def _question_id(event: LedgerEvent) -> str | None:
    """`Q-001` for the parent's questions, `<fix unit>/Q-001` for a fix unit's: the files number them separately."""
    qid = _text(event, "id")
    fix = _fix_unit(event)
    return f"{fix}/{qid}" if qid and fix else qid


def _question_raised(state: UnitState, event: LedgerEvent) -> None:
    qid = _question_id(event)
    if qid and qid not in state.questions.open and qid not in state.questions.answered:
        state.questions.open.append(qid)
    round_ = event.data.get("round")
    if event.data.get("kind") == "verdict" and isinstance(round_, int) and not isinstance(round_, bool):
        state.verdict_asked_round = max(state.verdict_asked_round or 0, round_)


def _question_answered(state: UnitState, event: LedgerEvent) -> None:
    if qid := _question_id(event):
        state.questions.open = [q for q in state.questions.open if q != qid]
        if qid not in state.questions.answered:
            state.questions.answered.append(qid)


def _availability_selected(state: UnitState, event: LedgerEvent) -> None:
    role, profile = _text(event, "role"), _text(event, "selected") or _text(event, "profile")  # SPEC 8.4: `selected`
    if role and profile:
        used = state.profiles_used.setdefault(role, [])
        if profile not in used:
            used.append(profile)
        if origin := _text(event, "fallback_from"):
            state.fallback_from[role] = origin
        else:
            state.fallback_from.pop(role, None)


def _agent_session(state: UnitState, event: LedgerEvent) -> None:
    profile, session = _text(event, "profile"), _text(event, "session_id")
    if profile and session:
        state.sessions[profile] = session


def _budget_cost(state: UnitState, event: LedgerEvent) -> None:
    usd = event.data.get("usd")
    if isinstance(usd, int | float) and not isinstance(usd, bool):
        state.cost_usd = round(state.cost_usd + usd, 6)


def _verify_verdict(state: UnitState, event: LedgerEvent) -> None:
    verdict, round_, findings = _text(event, "verdict"), event.data.get("round"), event.data.get("findings")
    if verdict and isinstance(round_, int) and isinstance(findings, int):
        state.last_verdict = LastVerdict(round=round_, verdict=verdict, findings=findings)


def _fix_spawned(state: UnitState, event: LedgerEvent) -> None:
    name, round_ = _text(event, "fix_unit"), event.data.get("round")
    if name is None:
        return
    if name not in state.children:
        state.children.append(name)
        if event.data.get("feedback_only") is True:
            state.feedback_rounds_used += 1  # D8: counted apart from `verifier.max_fix_rounds`
        else:
            state.fix_rounds_counted += 1
    if isinstance(round_, int) and not isinstance(round_, bool):
        state.fix_round = max(state.fix_round, round_)
    state.open_fix_unit = name


def _fix_done(state: UnitState, event: LedgerEvent) -> None:
    if _text(event, "fix_unit") == state.open_fix_unit:
        state.open_fix_unit = None


def _human_verdict(state: UnitState, event: LedgerEvent) -> None:
    if (qid := _text(event, "question")) and qid not in state.verdicts_consumed:
        state.verdicts_consumed.append(qid)


def _pr_updated(state: UnitState, event: LedgerEvent) -> None:
    if url := _text(event, "url"):
        state.pr = url


def _ci_failed(state: UnitState, event: LedgerEvent) -> None:
    head, jobs, preexisting = _text(event, "head"), event.data.get("jobs"), event.data.get("preexisting", [])
    if head is None or not isinstance(jobs, list) or not all(isinstance(j, dict) for j in jobs):
        return
    if not isinstance(preexisting, list) or not all(isinstance(n, str) for n in preexisting):
        return
    pipeline = event.data.get("pipeline")
    state.ci_heads[head] = "failed"
    state.ci_failure = CiFailure(
        head=head, jobs=jobs, preexisting=preexisting,
        pipeline=pipeline if isinstance(pipeline, int | str) and not isinstance(pipeline, bool) else None,
    )  # fmt: skip


def _ci_preexisting(state: UnitState, event: LedgerEvent) -> None:
    if head := _text(event, "head"):
        state.ci_heads.setdefault(head, "preexisting")


def _breaker_tripped(state: UnitState, event: LedgerEvent) -> None:
    state.breaker_trips += 1


def _unit_resumed(state: UnitState, event: LedgerEvent) -> None:
    state.breaker_trips = 0  # M1: the other breaker counters (no_progress, same_error, oscillation) reset here too
    if (signal := _text(event, "signal")) and signal not in state.resumed_signals:
        state.resumed_signals.append(signal)


def _budget_extended(state: UnitState, event: LedgerEvent) -> None:
    """`l4 resume --extend-fix-rounds N` / `--extend-feedback-rounds N` and a member's `l4:resume` label on an escalated
    unit (L4-IMP-013, L4-FBK-006). Other
    budgets are not folded here (their extension is refused until the iteration and cost limits read them)."""
    rounds = event.data.get("fix_rounds")
    if isinstance(rounds, int) and not isinstance(rounds, bool) and rounds > 0:
        state.fix_rounds_extra += rounds
    feedback = event.data.get("feedback_rounds")  # `l4 resume --extend-feedback-rounds N`, the label (L4-FBK-006)
    if isinstance(feedback, int) and not isinstance(feedback, bool) and feedback > 0:
        state.feedback_rounds_extra += feedback


def _feedback_item(state: UnitState, event: LedgerEvent) -> tuple[str, FeedbackState | None] | None:
    """The item id of a `feedback.*` event and its current state; None when the event names no item."""
    if (item := _text(event, "id")) is None:
        return None
    return item, state.feedback.get(item)


def _feedback_taken(state: UnitState, event: LedgerEvent) -> None:
    """`feedback.taken{id, kind, sha256, round, fix_unit}`: the item's content at this take is the one D7 compares."""
    if (found := _feedback_item(state, event)) is None:
        return
    round_ = event.data.get("round")
    state.feedback[found[0]] = FeedbackState(
        status="taken", kind=_text(event, "kind"), sha256=_text(event, "sha256"),
        round=round_ if isinstance(round_, int) and not isinstance(round_, bool) else None,
        fix_unit=_text(event, "fix_unit"),
    )  # fmt: skip


def _feedback_judged(status: Literal["addressed", "not_addressed"]) -> Callable[[UnitState, LedgerEvent], None]:
    def handler(state: UnitState, event: LedgerEvent) -> None:
        """`feedback.addressed{id, round, sha, evidence}` and `feedback.not_addressed{id, round, evidence}`."""
        if (found := _feedback_item(state, event)) is None:
            return
        item = found[1] or FeedbackState(status=status)
        round_ = event.data.get("round")
        state.feedback[found[0]] = item.model_copy(update={
            "status": status, "sha": _text(event, "sha"), "evidence": _text(event, "evidence"),
            "round": round_ if isinstance(round_, int) and not isinstance(round_, bool) else item.round,
        })  # fmt: skip

    return handler


def _feedback_changed(state: UnitState, event: LedgerEvent) -> None:
    """`feedback.changed{id, previous_sha256, sha256}`: edited after a take. The last-take hash stays as it was."""
    if (found := _feedback_item(state, event)) is None:
        return
    item = found[1] or FeedbackState(status="taken", sha256=_text(event, "previous_sha256"))
    state.feedback[found[0]] = item.model_copy(update={"changed_sha256": _text(event, "sha256")})


def _feedback_withdrawn(state: UnitState, event: LedgerEvent) -> None:
    if (found := _feedback_item(state, event)) is not None:
        state.feedback[found[0]] = (found[1] or FeedbackState(status="withdrawn")).model_copy(
            update={"status": "withdrawn"}
        )


def _feedback_invalid(state: UnitState, event: LedgerEvent) -> None:
    if (found := _feedback_item(state, event)) is not None:
        state.feedback[found[0]] = (found[1] or FeedbackState(status="invalid")).model_copy(
            update={"status": "invalid", "problem": _text(event, "problem")}
        )


def _feedback_waiting(state: UnitState, event: LedgerEvent) -> None:
    """`feedback.waiting{ids, reason}`: items that could not be taken yet (reason: `fix_unit_full`, `handoff`, ...)."""
    ids = event.data.get("ids")
    for item in ids if isinstance(ids, list) else []:
        if isinstance(item, str) and item:
            current = state.feedback.get(item) or FeedbackState(status="waiting")
            state.feedback[item] = current.model_copy(update={"status": "waiting", "reason": _text(event, "reason")})


def _resume_hint(state: UnitState, event: LedgerEvent) -> None:
    if (head := _text(event, "head")) and head not in state.hinted_heads:
        state.hinted_heads.append(head)


def _resume_refused(state: UnitState, event: LedgerEvent) -> None:
    if signal := _text(event, "signal"):
        state.refused_signals.setdefault(signal, _text(event, "why") or "")


HANDLERS: dict[str, Callable[[UnitState, LedgerEvent], None]] = {
    "run.started": _run_started,
    "phase.changed": _phase_changed,
    "task.started": _task_started,
    "task.done": _task_done,
    "question.raised": _question_raised,
    "question.answered": _question_answered,
    "availability.selected": _availability_selected,
    "agent.session": _agent_session,
    "budget.cost": _budget_cost,
    "verify.verdict": _verify_verdict,
    "fix.spawned": _fix_spawned,
    "fix.done": _fix_done,
    "human.verdict": _human_verdict,
    "pr.updated": _pr_updated,
    "ci.failed": _ci_failed,
    "ci.preexisting": _ci_preexisting,
    "breaker.tripped": _breaker_tripped,
    "unit.resumed": _unit_resumed,
    "budget.extended": _budget_extended,
    "feedback.taken": _feedback_taken,
    "feedback.addressed": _feedback_judged("addressed"),
    "feedback.not_addressed": _feedback_judged("not_addressed"),
    "feedback.changed": _feedback_changed,
    "feedback.withdrawn": _feedback_withdrawn,
    "feedback.invalid": _feedback_invalid,
    "feedback.waiting": _feedback_waiting,
    "resume.refused": _resume_refused,
    "resume.hint": _resume_hint,
}


def fold(events: Iterable[LedgerEvent], unit: str) -> UnitState:
    """Pure: no clock, no I/O. Events are ordered by (ts, run_id, seq) here, so the order they arrive in is
    irrelevant."""
    state = UnitState(unit=unit)
    last = None
    for event in sorted(events, key=lambda e: (e.ts, e.run_id, e.seq)):
        handler = HANDLERS.get(event.type)
        if handler:
            handler(state, event)
        last = event
    if last:
        state.updated_at = last.ts.strftime(TS_FORMAT)
    return state


def dump_state(state: UnitState) -> bytes:
    """Canonical JSON: model field order, two-space indent, trailing newline."""
    body: dict[str, Any] = state.model_dump(mode="json", by_alias=True)
    return (json.dumps(body, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
