"""`kg.blame.classify`: D6's table, one row per rule, first match wins (L4-KG-007, SCN-KG-14, SCN-KG-15)."""

import pytest

from l4.kg.blame import BLAME_VALUES, classify

ROWS = [
    # security
    ("guard.secret", {}, "security"),
    ("stop", {"code": "secret_in_push"}, "security"),
    # spec
    ("finding", {"source": "deterministic", "spec_gap": True}, "spec"),
    ("finding", {"source": "judge", "spec_gap": True}, "spec"),
    ("question", {"kind": "product"}, "spec"),
    ("question", {"kind": "ambiguous"}, "spec"),
    ("round", {"verdict": "NEEDS_HUMAN", "findings": [{"spec_gap": False}, {"spec_gap": True}]}, "spec"),
    # environment
    ("stop", {"code": "baseline_failed"}, "environment"),
    ("verify.error", {}, "environment"),
    ("gate.hung", {}, "environment"),
    ("ci.preexisting", {}, "environment"),
    ("availability.limit", {}, "environment"),
    # verifier
    ("judge.reply_repaired", {}, "verifier"),
    ("finding", {"source": "human", "spec_gap": False}, "verifier"),
    ("stop", {"code": "verifier_errors"}, "verifier"),
    # agent
    ("guard.violation", {}, "agent"),
    ("guard.test_tamper", {}, "agent"),
    ("task.attempt_failed", {}, "agent"),
    ("feedback.not_addressed", {}, "agent"),
    ("finding", {"source": "deterministic", "spec_gap": False}, "agent"),
    # unknown: a judge finding without a spec gap is shown, never guessed (SCN-KG-15)
    ("finding", {"source": "judge", "spec_gap": False}, "unknown"),
    ("finding", {"source": "feedback", "spec_gap": False}, "unknown"),
    ("question", {"kind": "technical"}, "unknown"),
    ("question", {}, "unknown"),
    ("stop", {"code": "max_task_attempts"}, "unknown"),
    ("round", {"verdict": "NEEDS_HUMAN", "findings": [{"spec_gap": False}]}, "unknown"),
    ("round", {"verdict": "FAIL", "findings": [{"spec_gap": True}]}, "unknown"),
    ("run.started", {}, "unknown"),
]


@pytest.mark.parametrize(("kind", "data", "expected"), ROWS)
def test_each_rule(kind, data, expected):
    assert classify(kind, data) == expected


def test_a_spec_gap_wins_over_a_later_row():
    """SCN-KG-14: the first matching row wins: a human finding that is also a spec gap is `spec`, not `verifier`."""
    assert classify("finding", {"source": "human", "spec_gap": True}) == "spec"


def test_every_value_is_a_known_one_and_no_data_is_needed():
    assert {classify(kind, data) for kind, data, _ in ROWS} <= set(BLAME_VALUES)
    assert classify("guard.secret") == "security"
    assert classify("finding") == "unknown"


def test_it_is_pure():
    data = {"source": "judge", "spec_gap": False}
    assert classify("finding", data) == classify("finding", dict(data))
    assert data == {"source": "judge", "spec_gap": False}
