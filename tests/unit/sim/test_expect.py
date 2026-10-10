from l4.sim.expect import Mismatch, Observed, compare_expect, format_mismatches, normalize_events
from l4.sim.scenarios import Expect

EVENTS = [
    {"type": "run.started", "seq": 1},
    {"type": "phase.changed", "to": "implementing", "trigger": "start"},
    {"type": "task.started", "task": "1.1"},
    {"type": "phase.changed", "to": "in_review", "trigger": "pr"},
]


def observed(**over) -> Observed:
    base = dict(exit_code=0, final_phase="in_review", events=EVENTS, trailers={"L4-Unit": ["openspec:a", "openspec:a"]})
    return Observed(**{**base, **over})


def test_a_matching_run_has_no_mismatch():
    expect = Expect(
        exit_code=0,
        final_phase="in_review",
        events_include=[{"type": "phase.changed", "to": "implementing"}, {"type": "task.started", "task": "1.1"}],
        trailers_include={"L4-Unit": "openspec:a"},
    )
    assert compare_expect(expect, observed()) == []
    assert compare_expect(Expect(), observed(exit_code=3, events=[])) == []  # nothing expected, nothing compared


def test_phase_mismatch_prints_diff_and_first_diverging_event():
    expect = Expect(
        exit_code=0,
        final_phase="verified",
        events_include=[{"type": "task.started", "task": "1.1"}, {"type": "task.started", "task": "1.2"}],
    )
    found = compare_expect(expect, observed())
    assert [m.field for m in found] == ["final_phase", "events_include[1]"]
    assert found[0] == Mismatch("final_phase", "verified", "in_review")
    text = format_mismatches(found, EVENTS)
    assert "final_phase: expected 'verified', actual 'in_review'" in text
    assert "events_include[1]: expected {'type': 'task.started', 'task': '1.2'}" in text
    assert "closest event of that type: {'type': 'task.started', 'task': '1.1'}" in text


def test_events_are_expected_in_order():
    expect = Expect(events_include=[{"type": "task.started"}, {"type": "phase.changed", "to": "implementing"}])
    (mismatch,) = compare_expect(expect, observed())
    assert mismatch.field == "events_include[1]" and "after event 2" in mismatch.actual


def test_exit_code_and_trailer_mismatches():
    expect = Expect(exit_code=11, trailers_include={"L4-Unit": "kiro:b", "L4-Fallback-From": "codex"})
    found = compare_expect(expect, observed())
    assert [(m.field, m.expected, m.actual) for m in found] == [
        ("exit_code", 11, 0),
        ("trailers_include.L4-Unit", "kiro:b", ["openspec:a", "openspec:a"]),
        ("trailers_include.L4-Fallback-From", "codex", "absent"),
    ]


def test_format_with_no_events_or_no_event_of_the_type():
    wanted = Mismatch("events_include[0]", {"type": "fix.done"}, "no matching event anywhere")
    assert "recorded no events" in format_mismatches([wanted], [])
    assert "no 'fix.done' event at all; the last event was" in format_mismatches([wanted], EVENTS)


SHA = "a" * 40
DIGEST = "b" * 64


def test_normalize_drops_what_differs_between_runs(tmp_path):
    root = str(tmp_path / "l4-sim-x")
    events = [
        {"ts": "2026-01-01T00:00:00Z", "run_id": "r-20261004T1200Z-abcd", "seq": 1, "type": "run.started"},
        {"ts": "t", "run_id": "r", "seq": 2, "type": "sandbox.disabled", "reason": "no bwrap"},
        {
            "ts": "t", "run_id": "r", "seq": 3, "type": "task.done", "sha": SHA, "prompt_sha256": DIGEST,
            "worktree": f"{root}/clone/wt", "nested": {"commit": f"fix {SHA[:40]}", "run": "r-20261004T1200Z-abcd"},
            "list": [SHA, 3],
        },
    ]  # fmt: skip
    assert normalize_events(events, [root]) == [
        {"type": "run.started"},
        {
            "type": "task.done", "sha": "<sha>", "prompt_sha256": "<sha256>", "worktree": "<tmp>/clone/wt",
            "nested": {"commit": "fix <sha>", "run": "<run>"}, "list": ["<sha>", 3],
        },
    ]  # fmt: skip
    assert events[0]["ts"]  # the input is not modified


def test_normalize_drops_lock_holder_and_nonce():
    events = [{"type": "lock.acquired", "unit": "u", "holder": "host:42", "nonce": "ab12", "seq": 1}]
    assert normalize_events(events) == [{"type": "lock.acquired", "unit": "u"}]
