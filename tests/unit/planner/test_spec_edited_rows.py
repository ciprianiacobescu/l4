"""L4-OPS-014: a person's spec edit since the harness's last commit makes a stopped or waiting unit actionable."""

from pathlib import Path

import pytest

from l4.orchestrator import ACTIONABLE
from l4.planner import UnitFacts, facts_of, next_action
from l4.specs.base import Framework, UnitRef
from l4.state.fold import UnitState
from l4.state.lifecycle import SPEC_EDIT_PHASES
from l4.state.review import SpecEdit
from l4.state.status import UnitSnapshot

SHA = "c" * 40
OTHER = "d" * 40


def facts(phase: str, **over) -> UnitFacts:
    base = {"unit": "openspec:x", "framework": "openspec", "phase": phase, "tasks_done": 2, "tasks_total": 2}
    return UnitFacts(**{**base, **over})


@pytest.mark.parametrize("phase", sorted(p.value for p in SPEC_EDIT_PHASES))
def test_a_spec_edit_plans_implement_in_every_phase_that_takes_the_edge(phase):
    action, reason = next_action(facts(phase, spec_edited=(OTHER, SHA)))
    assert action == "implement" and action in ACTIONABLE
    assert reason == f"spec edited after {phase}: {SHA[:10]}"


@pytest.mark.parametrize("phase", ["halted", "escalated", "awaiting_human", "verified", "verifying"])
def test_without_the_fact_the_phase_keeps_its_row(phase):
    assert next_action(facts(phase))[1] != next_action(facts(phase, spec_edited=(SHA,)))[1]


@pytest.mark.parametrize("phase", ["in_review", "fixing", "implementing", "waiting_capacity", "merged"])
def test_the_other_phases_ignore_the_fact(phase):
    assert next_action(facts(phase, spec_edited=(SHA,))) == next_action(facts(phase))


def test_the_fact_comes_from_the_snapshot():
    state = UnitState(unit="openspec:x", phase="escalated")
    ref = UnitRef(Framework.OPENSPEC, "x", Path("/nonexistent/openspec/changes/x"))
    snap = UnitSnapshot(ref, state, [], "branch", spec_edit=SpecEdit((OTHER, SHA), "e" * 40, SHA))
    assert facts_of(snap).spec_edited == (OTHER, SHA)
    assert facts_of(UnitSnapshot(ref, state, [], "branch")).spec_edited == ()
