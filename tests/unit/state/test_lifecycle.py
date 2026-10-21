from pathlib import Path

import pytest

from l4.exitcodes import ExitCode
from l4.redact import Redactor
from l4.state.fold import fold
from l4.state.ledger import LedgerWriter, read_ledger
from l4.state.lifecycle import (
    TRANSITIONS,
    IllegalTransition,
    Phase,
    Trigger,
    all_edges,
    allowed_edge,
    transition,
)

RUN = "r-20261003T1312Z-7f3a"
P, T = Phase, Trigger

# The rows of SPEC 12.0 built so far, written out independently of the table under test.
# every non-terminal phase but `archived` (which exists only in `on_approval`, not built): the merge request was closed
PR_CLOSED_SOURCES = tuple(p for p in Phase if p not in (Phase.MERGED, Phase.ABANDONED, Phase.ARCHIVED))
SPEC_EDITED_SOURCES = (P.INTAKE, P.READY, P.IMPLEMENTED, P.VERIFYING, P.VERIFIED, P.AWAITING_HUMAN, P.CLARIFYING,
                       P.HALTED, P.ESCALATED)  # fmt: skip
BUILT_ROWS = {
    (P.HALTED, T.RESUMED, None, None),  # M1.4: `l4 resume`
    (P.ESCALATED, T.RESUMED, None, None),  # M1.13 (W-C2): `l4 resume` with an extension, or the label (SPEC 12.0)
    (None, T.UNIT_DISCOVERED_PENDING, P.INTAKE, None),
    (None, T.UNIT_DISCOVERED_DONE, P.IMPLEMENTED, None),
    (P.INTAKE, T.INTAKE_ALL_PASS, P.READY, None),
    (P.READY, T.LEASE_ACQUIRED, P.IMPLEMENTING, None),
    (P.IMPLEMENTING, T.QUESTIONS_BLOCKING, P.AWAITING_HUMAN, ExitCode.AWAITING_HUMAN),
    (P.IMPLEMENTING, T.ALL_LEAVES_DONE, P.IMPLEMENTED, None),
    (P.IMPLEMENTING, T.BREAKER_OR_BUDGET, P.HALTED, ExitCode.HALTED),
    (P.FIXING, T.BREAKER_OR_BUDGET, P.HALTED, ExitCode.HALTED),
    (P.IMPLEMENTED, T.VERIFICATION_STARTED, P.VERIFYING, None),
    (P.VERIFYING, T.VERIFY_PASS, P.VERIFIED, None),
    (P.VERIFYING, T.VERIFY_FAIL_FIX, P.FIXING, ExitCode.CONTINUE),
    (P.VERIFYING, T.VERIFY_NEEDS_HUMAN, P.AWAITING_HUMAN, ExitCode.AWAITING_HUMAN),
    (P.AWAITING_HUMAN, T.VERDICTS_ANSWERED, P.VERIFYING, None),
    (P.FIXING, T.FIX_UNIT_DONE, P.VERIFYING, None),
    (P.VERIFIED, T.MINOR_FINDINGS_FIX, P.FIXING, None),
    (P.VERIFYING, T.VERIFY_FAIL_EXHAUSTED, P.ESCALATED, ExitCode.HALTED),
    (P.VERIFIED, T.HAND_OFF_PUSHED, P.IN_REVIEW, ExitCode.OK),
    (P.WAITING_CAPACITY, T.CAPACITY_RESTORED, None, None),  # SPEC 12.0: back to the remembered phase
    (P.IMPLEMENTING, T.QUESTIONS_TO_CLARIFIER, P.CLARIFYING, None),
    (P.CLARIFYING, T.CLARIFIER_ANSWERED_ALL, P.IMPLEMENTING, None),
    (P.CLARIFYING, T.CLARIFIER_NEEDS_HUMAN, P.AWAITING_HUMAN, ExitCode.AWAITING_HUMAN),
    (P.AWAITING_HUMAN, T.ANSWERS_SUBMITTED, P.IMPLEMENTING, None),
    (P.IN_REVIEW, T.PR_MERGED, P.MERGED, ExitCode.OK),
    (P.IN_REVIEW, T.COMMIT_AFTER_HANDOFF, P.VERIFYING, None),  # M1.9: a commit the harness did not make
    (P.IN_REVIEW, T.SPEC_EDIT_AFTER_HANDOFF, P.IMPLEMENTING, None),  # M1.9: answers or spec edits after H
    (P.IN_REVIEW, T.REPOSITORY_CI_FAILED, P.VERIFYING, None),  # M1.9: the project's own CI is red on H
    *((src, T.REQUIRED_ROLE_UNAVAILABLE, P.WAITING_CAPACITY, ExitCode.WAITING_CAPACITY)
      for src in (P.READY, P.IMPLEMENTING, P.IMPLEMENTED, P.VERIFYING, P.FIXING)),
    # operator-commands (L4-OPS-001, L4-OPS-003, L4-OPS-009)
    (P.HALTED, T.SPEC_EDIT_SINCE_STOP, P.IMPLEMENTING, None),  # a person edited the unit folder after the stop
    (P.ESCALATED, T.SPEC_EDIT_SINCE_STOP, P.IMPLEMENTING, None),
    (P.IN_REVIEW, T.RETRY_REQUESTED, P.VERIFYING, None),  # `l4 retry` on a unit in review
    (P.VERIFYING, T.BREAKER_OR_BUDGET, P.HALTED, ExitCode.HALTED),  # a secret in the push halts in any phase
    (P.VERIFIED, T.BREAKER_OR_BUDGET, P.HALTED, ExitCode.HALTED),
    (P.ABANDONED, T.PR_REOPENED, None, None),  # back to the phase the merge request was closed in
    *((src, T.PR_CLOSED, P.ABANDONED, None) for src in PR_CLOSED_SOURCES),
    *((src, T.SPEC_EDITED, P.IMPLEMENTING, None) for src in SPEC_EDITED_SOURCES),  # L4-OPS-014: a spec push
}  # fmt: skip


def test_table_matches_spec_rows():
    assert {(src, e.trigger, e.target, e.exit_code) for e in TRANSITIONS for src in e.sources} == BUILT_ROWS
    assert set(all_edges()) == {(s, t, tg) for s, t, tg, _ in BUILT_ROWS}
    assert len(Phase) == 17 and Phase.WAITING_CAPACITY.value == "waiting_capacity"
    # escalated and halted are left only by `l4 resume`; merged and abandoned are terminal
    sources = {src for e in TRANSITIONS for src in e.sources}
    assert not sources & {P.MERGED}  # merged is terminal; abandoned leaves only when the merge request is reopened
    assert {e.trigger for e in TRANSITIONS if P.ABANDONED in e.sources} == {T.PR_REOPENED}
    assert {e.trigger for e in TRANSITIONS if P.ESCALATED in e.sources} == {
        T.RESUMED,
        T.SPEC_EDIT_SINCE_STOP,
        T.SPEC_EDITED,
        T.PR_CLOSED,
    }
    assert P.ARCHIVED not in sources  # leaving `archived` needs the archive revert first (L4-ARC-004): not built
    assert {e.trigger for e in TRANSITIONS if P.HALTED in e.sources} == {
        T.RESUMED,
        T.SPEC_EDIT_SINCE_STOP,
        T.SPEC_EDITED,
        T.PR_CLOSED,
    }
    assert not any(Phase.CLARIFYING in e.sources for e in TRANSITIONS if e.trigger is T.REQUIRED_ROLE_UNAVAILABLE)
    assert allowed_edge(P.IMPLEMENTING, T.BREAKER_OR_BUDGET).exit_code is ExitCode.HALTED  # type: ignore[union-attr]
    assert allowed_edge(P.READY, T.VERIFY_PASS) is None


def writer_and_state(tmp_path: Path):
    writer = LedgerWriter.open(tmp_path, "openspec:x", RUN, redactor=Redactor({}))
    return writer, (lambda: fold(read_ledger(tmp_path).events, "openspec:x"))


def test_transition_appends_exactly_one_phase_changed_and_returns_the_edge(tmp_path: Path):
    writer, state = writer_and_state(tmp_path)
    edge = transition(writer, state(), T.UNIT_DISCOVERED_PENDING)
    assert edge.target is P.INTAKE and edge.exit_code is None
    transition(writer, state(), T.INTAKE_ALL_PASS)
    transition(writer, state(), T.LEASE_ACQUIRED, branch="l4/openspec/x")
    halted = transition(writer, state(), T.BREAKER_OR_BUDGET, reason="attempts")
    assert halted.exit_code is ExitCode.HALTED
    events = [e for e in read_ledger(tmp_path).events if e.type == "phase.changed"]
    assert [(e.data["from"], e.data["to"], e.data["trigger"], e.data["exit_code"]) for e in events] == [
        (None, "intake", "unit_discovered_pending", None),
        ("intake", "ready", "intake_all_pass", None),
        ("ready", "implementing", "lease_acquired", None),
        ("implementing", "halted", "breaker_or_budget", 13),
    ]
    assert events[2].data["branch"] == "l4/openspec/x" and events[3].data["reason"] == "attempts"
    assert state().phase == "halted" and state().previous_phase == "implementing"


def test_illegal_edge_writes_nothing(tmp_path: Path):
    writer, state = writer_and_state(tmp_path)
    transition(writer, state(), T.UNIT_DISCOVERED_PENDING)
    before = read_ledger(tmp_path).events
    for trigger in (T.VERIFY_PASS, T.HAND_OFF_PUSHED, T.LEASE_ACQUIRED, T.UNIT_DISCOVERED_PENDING):
        with pytest.raises(IllegalTransition, match=trigger.value):
            transition(writer, state(), trigger)
    assert read_ledger(tmp_path).events == before


def test_a_phase_the_table_does_not_know_is_an_illegal_transition(tmp_path: Path):
    writer, _ = writer_and_state(tmp_path)
    state = fold([], "openspec:x").model_copy(update={"phase": "not_a_phase"})
    with pytest.raises(IllegalTransition, match="not_a_phase"):
        transition(writer, state, T.INTAKE_ALL_PASS)


@pytest.mark.parametrize("parked_from", [P.READY, P.IMPLEMENTING, P.IMPLEMENTED, P.VERIFYING])
def test_a_unit_parked_for_capacity_returns_to_the_phase_it_left(tmp_path: Path, parked_from: Phase):
    writer, state = writer_and_state(tmp_path)
    path = {
        P.READY: [T.UNIT_DISCOVERED_PENDING, T.INTAKE_ALL_PASS],
        P.IMPLEMENTING: [T.UNIT_DISCOVERED_PENDING, T.INTAKE_ALL_PASS, T.LEASE_ACQUIRED],
        P.IMPLEMENTED: [T.UNIT_DISCOVERED_DONE],
        P.VERIFYING: [T.UNIT_DISCOVERED_DONE, T.VERIFICATION_STARTED],
    }[parked_from]
    for trigger in path:
        transition(writer, state(), trigger)
    assert transition(writer, state(), T.REQUIRED_ROLE_UNAVAILABLE).exit_code is ExitCode.WAITING_CAPACITY
    assert state().phase == "waiting_capacity" and state().previous_phase == parked_from.value
    back = transition(writer, state(), T.CAPACITY_RESTORED)
    assert back.target is parked_from and back.exit_code is None
    assert state().phase == parked_from.value and state().previous_phase is None


def test_capacity_restored_without_a_remembered_phase_is_illegal(tmp_path: Path):
    writer, _ = writer_and_state(tmp_path)
    state = fold([], "openspec:x").model_copy(update={"phase": "waiting_capacity", "previous_phase": None})
    with pytest.raises(IllegalTransition, match="remembered"):
        transition(writer, state, T.CAPACITY_RESTORED)
    assert [e for e in read_ledger(tmp_path).events if e.type == "phase.changed"] == []


def test_the_clarifier_round_trip_and_the_answers_edge(tmp_path: Path):
    writer, state = writer_and_state(tmp_path)
    for trigger in (T.UNIT_DISCOVERED_PENDING, T.INTAKE_ALL_PASS, T.LEASE_ACQUIRED, T.QUESTIONS_TO_CLARIFIER):
        assert transition(writer, state(), trigger).exit_code is None
    assert state().phase == "clarifying"
    assert transition(writer, state(), T.CLARIFIER_NEEDS_HUMAN).exit_code is ExitCode.AWAITING_HUMAN
    assert state().phase == "awaiting_human"
    transition(writer, state(), T.ANSWERS_SUBMITTED)
    assert state().phase == "implementing"
    transition(writer, state(), T.QUESTIONS_TO_CLARIFIER)
    transition(writer, state(), T.CLARIFIER_ANSWERED_ALL)
    assert state().phase == "implementing"


def test_only_a_unit_in_review_can_merge(tmp_path: Path):
    writer, state = writer_and_state(tmp_path)
    for trigger in (T.UNIT_DISCOVERED_DONE, T.VERIFICATION_STARTED, T.VERIFY_PASS, T.HAND_OFF_PUSHED):
        transition(writer, state(), trigger)
    assert transition(writer, state(), T.PR_MERGED).exit_code is ExitCode.OK
    assert state().phase == "merged"
    with pytest.raises(IllegalTransition):
        transition(writer, state(), T.PR_MERGED)


def test_a_rerun_is_no_longer_a_trigger():
    assert "rerun_requested" not in {t.value for t in Trigger}


@pytest.mark.parametrize("closed_in", PR_CLOSED_SOURCES)
def test_a_closed_merge_request_abandons_the_unit_and_a_reopened_one_returns_it(tmp_path: Path, closed_in: Phase):
    """L4-OPS-009: `pr_closed` is legal from every phase that has a source row, and `pr_reopened` returns to it."""
    writer, _ = writer_and_state(tmp_path)
    at = fold([], "openspec:x").model_copy(update={"phase": closed_in.value})
    assert transition(writer, at, T.PR_CLOSED).target is P.ABANDONED
    events = [e for e in read_ledger(tmp_path).events if e.type == "phase.changed"]
    state = fold(read_ledger(tmp_path).events, "openspec:x")
    assert (state.phase, state.previous_phase) == ("abandoned", closed_in.value)
    assert events[-1].data["trigger"] == "pr_closed"
    back = transition(writer, state, T.PR_REOPENED)
    assert back.target is closed_in and back.exit_code is None
    assert fold(read_ledger(tmp_path).events, "openspec:x").phase == closed_in.value


@pytest.mark.parametrize("stopped_in", [P.HALTED, P.ESCALATED])
def test_a_spec_edit_since_the_stop_returns_to_implementing_not_to_previous_phase(tmp_path: Path, stopped_in: Phase):
    writer, _ = writer_and_state(tmp_path)
    at = fold([], "openspec:x").model_copy(update={"phase": stopped_in.value, "previous_phase": "verifying"})
    assert transition(writer, at, T.SPEC_EDIT_SINCE_STOP).target is P.IMPLEMENTING


def test_a_spec_edit_goes_to_implementing_from_the_phases_that_are_not_finished(tmp_path: Path):
    """L4-OPS-014: `in_review` keeps `spec_edit_after_handoff`; `fixing` defers (no edge); `implementing` needs none."""
    from l4.state.lifecycle import SPEC_EDIT_PHASES

    assert frozenset(SPEC_EDITED_SOURCES) == SPEC_EDIT_PHASES
    for phase in (P.IN_REVIEW, P.FIXING, P.IMPLEMENTING, P.WAITING_CAPACITY, P.MERGED, P.ABANDONED, P.REJECTED, None):
        assert allowed_edge(phase, T.SPEC_EDITED) is None
    writer, _ = writer_and_state(tmp_path)
    at = fold([], "openspec:x").model_copy(update={"phase": P.HALTED.value, "previous_phase": "verifying"})
    assert transition(writer, at, T.SPEC_EDITED).target is P.IMPLEMENTING


def test_an_archived_unit_and_a_merged_one_are_not_abandoned_by_a_closed_merge_request(tmp_path: Path):
    for phase in (P.MERGED, P.ABANDONED, P.ARCHIVED):
        assert allowed_edge(phase, T.PR_CLOSED) is None


def test_transition_carries_the_detail_of_a_stop_in_the_event_and_the_fold(tmp_path: Path):
    """L4-OPS-005: `detail` is the person's text, `reason` the code; the fold keeps both."""
    writer, state = writer_and_state(tmp_path)
    for trigger in (T.UNIT_DISCOVERED_PENDING, T.INTAKE_ALL_PASS, T.LEASE_ACQUIRED):
        transition(writer, state(), trigger)
    transition(writer, state(), T.BREAKER_OR_BUDGET, reason="max_task_attempts", detail="task 1.1 failed 3 times")
    [event] = [e for e in read_ledger(tmp_path).events if e.type == "phase.changed" and e.data["to"] == "halted"]
    assert event.data["reason"] == "max_task_attempts" and event.data["detail"] == "task 1.1 failed 3 times"
    assert (state().halt_reason, state().halt_detail) == ("max_task_attempts", "task 1.1 failed 3 times")
    transition(writer, state(), T.RESUMED)
    assert (state().halt_reason, state().halt_detail) == (None, None)
