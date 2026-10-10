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
}  # fmt: skip


def test_table_matches_spec_rows():
    assert {(src, e.trigger, e.target, e.exit_code) for e in TRANSITIONS for src in e.sources} == BUILT_ROWS
    assert set(all_edges()) == {(s, t, tg) for s, t, tg, _ in BUILT_ROWS}
    assert len(Phase) == 17 and Phase.WAITING_CAPACITY.value == "waiting_capacity"
    # escalated and halted are left only by `l4 resume`; merged and abandoned are terminal
    sources = {src for e in TRANSITIONS for src in e.sources}
    assert not sources & {P.MERGED, P.ABANDONED}
    assert {e.trigger for e in TRANSITIONS if P.ESCALATED in e.sources} == {T.RESUMED}
    assert P.ARCHIVED not in sources  # leaving `archived` needs the archive revert first (L4-ARC-004): not built
    assert {e.trigger for e in TRANSITIONS if P.HALTED in e.sources} == {T.RESUMED}
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
