"""The unit lifecycle (SPEC 12.0): the phases, and `transition()` as the only code that changes one.

`TRANSITIONS` is the table of SPEC 12.0 as far as the built lines need it; an edge that is not in it is refused.
M1: state-vcs-locks 1.20 is complete for the rows of M1.1 stage A: clarifying, `awaiting_human -> implementing` on
`answers_submitted`, and `in_review -> merged`; M1.4 adds `halted -> previous phase` on `resumed`. M1.3 added the
verdict row of `awaiting_human`, the fix rows (`verifying -> fixing`, `fixing -> verifying`, `verified -> fixing`,
`verifying -> escalated`) and `fixing` as a source of `required_role_unavailable` and `breaker_or_budget`. M1.13 adds
`escalated -> previous phase` on `resumed`. Still absent: `abandoned`, archive, `rejected` re-entry, and `clarifying` as
a source of `required_role_unavailable` (the clarifier never raises exit 12, clarification-loop 1.13).
Four rows are not on the 1.27 list because built lines need them: `None -> implemented` (a unit whose tasks are all
done enters at implemented, SPEC 12.0 row 2, so `l4 plan` may say `verify`), `verified -> in_review` (the hand-off of
forge-and-ci 1.39), `waiting_capacity -> previous phase` (SPEC 12.0 row 12b: without it a unit parked by a failed
probe could never run again) and `in_review -> merged`.
M1.9 builds the review re-entry rows of SPEC 12.0, with `in_review` as the only source (`archived` exists only in
`on_approval`, which is not built, and leaving it needs the archive revert of L4-ARC-004 first): `commit_after_handoff`
-> `verifying` (a commit after H that the harness did not make), `spec_edit_after_handoff` -> `implementing` (answers or
spec edits after H) and `repository_ci_failed` -> `verifying` (the project's own CI is red on H). None has an exit
code: the run goes on.
operator-commands (L4-OPS-001, -003, -009) adds the rows an operator's verb or a closed merge request needs:
`halted | escalated -> implementing` on `spec_edit_since_stop` (a person changed the unit folder after the stop),
`in_review -> verifying` on `retry_requested`, `verifying | verified -> halted` on `breaker_or_budget` (a secret in
the push halts in any phase), every non-terminal phase `-> abandoned` on `pr_closed` (not `archived`, which exists only
in `on_approval`), and `abandoned -> previous phase` on `pr_reopened`.
"""

from enum import StrEnum
from typing import NamedTuple

from l4.exitcodes import ExitCode
from l4.state.fold import UnitState
from l4.state.ledger import LedgerWriter


class Phase(StrEnum):
    INTAKE = "intake"
    REJECTED = "rejected"
    READY = "ready"
    IMPLEMENTING = "implementing"
    CLARIFYING = "clarifying"
    AWAITING_HUMAN = "awaiting_human"
    WAITING_CAPACITY = "waiting_capacity"
    IMPLEMENTED = "implemented"
    VERIFYING = "verifying"
    FIXING = "fixing"
    VERIFIED = "verified"
    IN_REVIEW = "in_review"
    ARCHIVED = "archived"
    MERGED = "merged"
    ABANDONED = "abandoned"
    HALTED = "halted"
    ESCALATED = "escalated"


TERMINAL = frozenset({Phase.MERGED, Phase.ABANDONED})


class Trigger(StrEnum):
    UNIT_DISCOVERED_PENDING = "unit_discovered_pending"
    UNIT_DISCOVERED_DONE = "unit_discovered_done"
    INTAKE_ALL_PASS = "intake_all_pass"
    LEASE_ACQUIRED = "lease_acquired"
    REQUIRED_ROLE_UNAVAILABLE = "required_role_unavailable"
    QUESTIONS_BLOCKING = "questions_blocking"
    ALL_LEAVES_DONE = "all_leaves_done"
    BREAKER_OR_BUDGET = "breaker_or_budget"
    VERIFICATION_STARTED = "verification_started"
    VERIFY_PASS = "verify_pass"
    VERIFY_FAIL_FIX = "verify_fail_fix"
    VERIFY_NEEDS_HUMAN = "verify_needs_human"
    VERDICTS_ANSWERED = "verdicts_answered"
    FIX_UNIT_DONE = "fix_unit_done"
    MINOR_FINDINGS_FIX = "minor_findings_fix"
    VERIFY_FAIL_EXHAUSTED = "verify_fail_exhausted"
    HAND_OFF_PUSHED = "hand_off_pushed"
    CAPACITY_RESTORED = "capacity_restored"
    QUESTIONS_TO_CLARIFIER = "questions_to_clarifier"
    CLARIFIER_ANSWERED_ALL = "clarifier_answered_all"
    CLARIFIER_NEEDS_HUMAN = "clarifier_needs_human"
    ANSWERS_SUBMITTED = "answers_submitted"
    PR_MERGED = "pr_merged"
    COMMIT_AFTER_HANDOFF = "commit_after_handoff"
    SPEC_EDIT_AFTER_HANDOFF = "spec_edit_after_handoff"
    REPOSITORY_CI_FAILED = "repository_ci_failed"
    RESUMED = "resumed"
    SPEC_EDIT_SINCE_STOP = "spec_edit_since_stop"
    RETRY_REQUESTED = "retry_requested"
    PR_CLOSED = "pr_closed"
    PR_REOPENED = "pr_reopened"


class Edge(NamedTuple):
    sources: frozenset[Phase | None]  # None: the unit has no phase yet
    trigger: Trigger
    target: Phase | None  # None: the phase remembered in `UnitState.previous_phase`
    exit_code: ExitCode | None  # the run's exit code on this edge, None when the run goes on


class IllegalTransition(Exception):
    pass


def _edge(
    sources: set[Phase | None], trigger: Trigger, target: Phase | None, exit_code: ExitCode | None = None
) -> Edge:
    return Edge(frozenset(sources), trigger, target, exit_code)


TRANSITIONS: tuple[Edge, ...] = (
    _edge({None}, Trigger.UNIT_DISCOVERED_PENDING, Phase.INTAKE),
    _edge({None}, Trigger.UNIT_DISCOVERED_DONE, Phase.IMPLEMENTED),
    _edge({Phase.INTAKE}, Trigger.INTAKE_ALL_PASS, Phase.READY),
    _edge({Phase.READY}, Trigger.LEASE_ACQUIRED, Phase.IMPLEMENTING),
    _edge(
        {Phase.READY, Phase.IMPLEMENTING, Phase.IMPLEMENTED, Phase.VERIFYING, Phase.FIXING},
        Trigger.REQUIRED_ROLE_UNAVAILABLE,
        Phase.WAITING_CAPACITY,
        ExitCode.WAITING_CAPACITY,
    ),
    _edge({Phase.IMPLEMENTING}, Trigger.QUESTIONS_BLOCKING, Phase.AWAITING_HUMAN, ExitCode.AWAITING_HUMAN),
    _edge({Phase.IMPLEMENTING}, Trigger.QUESTIONS_TO_CLARIFIER, Phase.CLARIFYING),
    _edge({Phase.CLARIFYING}, Trigger.CLARIFIER_ANSWERED_ALL, Phase.IMPLEMENTING),
    _edge({Phase.CLARIFYING}, Trigger.CLARIFIER_NEEDS_HUMAN, Phase.AWAITING_HUMAN, ExitCode.AWAITING_HUMAN),
    _edge({Phase.IMPLEMENTING}, Trigger.ALL_LEAVES_DONE, Phase.IMPLEMENTED),
    _edge(
        {Phase.IMPLEMENTING, Phase.FIXING, Phase.VERIFYING, Phase.VERIFIED},
        Trigger.BREAKER_OR_BUDGET,
        Phase.HALTED,
        ExitCode.HALTED,
    ),
    _edge({Phase.IMPLEMENTED}, Trigger.VERIFICATION_STARTED, Phase.VERIFYING),
    _edge({Phase.VERIFYING}, Trigger.VERIFY_PASS, Phase.VERIFIED),
    _edge({Phase.VERIFYING}, Trigger.VERIFY_FAIL_FIX, Phase.FIXING, ExitCode.CONTINUE),
    _edge({Phase.VERIFYING}, Trigger.VERIFY_NEEDS_HUMAN, Phase.AWAITING_HUMAN, ExitCode.AWAITING_HUMAN),
    _edge({Phase.AWAITING_HUMAN}, Trigger.VERDICTS_ANSWERED, Phase.VERIFYING),
    _edge({Phase.FIXING}, Trigger.FIX_UNIT_DONE, Phase.VERIFYING),
    _edge({Phase.VERIFIED}, Trigger.MINOR_FINDINGS_FIX, Phase.FIXING),
    _edge({Phase.VERIFYING}, Trigger.VERIFY_FAIL_EXHAUSTED, Phase.ESCALATED, ExitCode.HALTED),
    _edge({Phase.VERIFIED}, Trigger.HAND_OFF_PUSHED, Phase.IN_REVIEW, ExitCode.OK),
    _edge({Phase.WAITING_CAPACITY}, Trigger.CAPACITY_RESTORED, None),
    _edge({Phase.AWAITING_HUMAN}, Trigger.ANSWERS_SUBMITTED, Phase.IMPLEMENTING),
    _edge({Phase.IN_REVIEW}, Trigger.PR_MERGED, Phase.MERGED, ExitCode.OK),
    _edge({Phase.IN_REVIEW}, Trigger.COMMIT_AFTER_HANDOFF, Phase.VERIFYING),
    _edge({Phase.IN_REVIEW}, Trigger.SPEC_EDIT_AFTER_HANDOFF, Phase.IMPLEMENTING),
    _edge({Phase.IN_REVIEW}, Trigger.REPOSITORY_CI_FAILED, Phase.VERIFYING),
    # `l4 resume` or a member's label; from `escalated` it needs a fix-round extension when the rounds are used up
    # (L4-IMP-013, checked by `state.resume`, not by the table)
    _edge({Phase.HALTED, Phase.ESCALATED}, Trigger.RESUMED, None),
    # operator-commands: a person changed the unit folder since the stop, so the unit implements again (L4-OPS-003)
    _edge({Phase.HALTED, Phase.ESCALATED}, Trigger.SPEC_EDIT_SINCE_STOP, Phase.IMPLEMENTING),
    _edge({Phase.IN_REVIEW}, Trigger.RETRY_REQUESTED, Phase.VERIFYING),  # `l4 retry` / `l4:retry` (L4-OPS-001)
    # the merge request was closed without a merge, or reopened before any restart (L4-OPS-009)
    _edge(set(Phase) - {Phase.MERGED, Phase.ABANDONED, Phase.ARCHIVED}, Trigger.PR_CLOSED, Phase.ABANDONED),
    _edge({Phase.ABANDONED}, Trigger.PR_REOPENED, None),
)


def allowed_edge(phase: Phase | None, trigger: Trigger) -> Edge | None:
    return next((e for e in TRANSITIONS if e.trigger is trigger and phase in e.sources), None)


def all_edges() -> list[tuple[Phase | None, Trigger, Phase | None]]:
    """Every (source, trigger, target); the simulation suite asserts each one is exercised (SPEC 12.0)."""
    return [(src, e.trigger, e.target) for e in TRANSITIONS for src in e.sources]


def transition(
    writer: LedgerWriter, state: UnitState, trigger: Trigger, *, detail: str | None = None, **context: object
) -> Edge:
    """Append exactly one `phase.changed` and return the edge (its `exit_code` is the run's exit code, if any).
    An undeclared edge raises `IllegalTransition` and writes nothing. `detail` (L4-OPS-005): the person's text for a
    stop, next to `reason`, its code; written only when given, so an old caller's event is unchanged."""
    try:
        current = Phase(state.phase) if state.phase is not None else None
    except ValueError:
        raise IllegalTransition(f"unknown phase {state.phase!r}: cannot apply {trigger.value}") from None
    edge = allowed_edge(current, trigger)
    if edge is None:
        raise IllegalTransition(f"no edge from {current.value if current else 'no phase'} on {trigger.value}")
    target = edge.target
    if target is None:
        try:
            target = Phase(state.previous_phase)
        except ValueError:
            raise IllegalTransition(f"{trigger.value}: no remembered phase to return to") from None
        edge = edge._replace(target=target)
    code = int(edge.exit_code) if edge.exit_code is not None else None
    if detail is not None:
        context["detail"] = detail
    writer.append(
        "phase.changed", **{"from": current.value if current else None}, to=target.value,
        trigger=trigger.value, exit_code=code, **context,
    )  # fmt: skip
    return edge
