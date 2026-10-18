import json
import random
from datetime import UTC, datetime, timedelta

from l4.state.fold import HANDLERS, UnitState, dump_state, fold, recorded_ready
from l4.state.ledger import LedgerEvent

T0 = datetime(2026, 10, 3, 13, 0, 0, tzinfo=UTC)


def ev(n: int, run: str, seq: int, type_: str, **data) -> LedgerEvent:
    return LedgerEvent(T0 + timedelta(seconds=n), run, "openspec:x", seq, type_, data)


RUN1, RUN2 = "r-20261003T1300Z-aaaa", "r-20261003T1400Z-bbbb"
EVENTS = [
    ev(0, RUN1, 1, "run.started"),
    ev(1, RUN1, 2, "phase.changed", **{"from": None, "to": "intake", "trigger": "unit_discovered_pending"}),
    ev(2, RUN1, 3, "phase.changed", **{"from": "intake", "to": "ready", "trigger": "intake_all_pass"}),
    ev(3, RUN1, 4, "phase.changed", **{"from": "ready", "to": "implementing", "trigger": "lease_acquired"}),
    ev(4, RUN1, 5, "availability.selected", role="implementer", profile="codex"),
    ev(5, RUN1, 6, "agent.session", profile="codex", session_id="sess-1"),
    ev(6, RUN1, 7, "task.started", task="1.1"),
    ev(7, RUN1, 8, "budget.cost", usd=0.25),
    ev(8, RUN1, 9, "task.done", task="1.1"),
    ev(9, RUN1, 10, "question.raised", id="Q-001"),
    ev(
        10,
        RUN1,
        11,
        "phase.changed",
        **{"from": "implementing", "to": "awaiting_human", "trigger": "questions_blocking"},
    ),
    ev(11, RUN1, 12, "run.finished", exit_code=11),
    ev(100, RUN2, 1, "run.started"),
    ev(101, RUN2, 2, "question.answered", id="Q-001"),
    ev(102, RUN2, 3, "availability.selected", role="implementer", profile="codex"),
    ev(103, RUN2, 4, "budget.cost", usd=0.5),
    ev(104, RUN2, 5, "pr.updated", url="https://forge.invalid/mr/1"),
    ev(105, RUN2, 6, "verify.verdict", round=1, verdict="PASS", findings=0),
    ev(106, RUN2, 7, "some.future_event", whatever=1),
]


def test_fold_is_pure_and_order_independent_of_file_order():
    forward = fold(EVENTS, "openspec:x")
    shuffled = list(EVENTS)
    random.Random(7).shuffle(shuffled)
    assert fold(shuffled, "openspec:x") == forward
    assert fold(reversed(EVENTS), "openspec:x") == forward
    assert forward.model_dump() == fold(EVENTS, "openspec:x").model_dump()
    assert forward.iteration == 2 and forward.phase == "awaiting_human" and forward.previous_phase is None
    assert forward.tasks.done == ["1.1"] and forward.tasks.in_progress is None
    assert forward.questions.open == [] and forward.questions.answered == ["Q-001"]
    assert forward.profiles_used == {"implementer": ["codex"]} and forward.sessions == {"codex": "sess-1"}
    assert forward.cost_usd == 0.75 and forward.pr == "https://forge.invalid/mr/1"
    assert forward.last_verdict is not None and forward.last_verdict.verdict == "PASS"
    assert forward.updated_at == "2026-10-03T13:01:46.000000Z"  # the last event's ts: no clock is read
    assert "some.future_event" not in HANDLERS  # unknown event types are ignored, not errors


def test_empty_ledger_is_a_unit_without_a_phase():
    state = fold([], "openspec:x")
    assert state.phase is None and state.iteration == 0 and state.updated_at is None


def test_previous_phase_is_remembered_only_for_the_four_parking_phases():
    def run(*moves: tuple[str | None, str]) -> UnitState:
        events = [ev(0, RUN1, 1, "run.started")]
        events += [
            ev(i + 1, RUN1, i + 2, "phase.changed", **{"from": a, "to": b, "trigger": "t"})
            for i, (a, b) in enumerate(moves)
        ]
        return fold(events, "openspec:x")

    assert run(("ready", "implementing"), ("implementing", "waiting_capacity")).previous_phase == "implementing"
    assert run(("implementing", "halted")).previous_phase == "implementing"
    assert run(("verifying", "escalated")).previous_phase == "verifying"
    assert run(("implementing", "halted"), ("halted", "implementing")).previous_phase is None
    assert run(("ready", "implementing")).previous_phase is None


def test_malformed_payloads_are_ignored_not_fatal():
    events = [
        ev(0, RUN1, 1, "run.started"),
        ev(1, RUN1, 2, "task.done", task=5),
        ev(2, RUN1, 3, "budget.cost", usd="lots"),
        ev(3, RUN1, 4, "phase.changed", to=None),
        ev(4, RUN1, 5, "question.raised"),
    ]
    state = fold(events, "openspec:x")
    assert state.tasks.done == [] and state.cost_usd == 0 and state.phase is None and state.questions.open == []


def test_dump_state_is_canonical_bytes():
    state = fold(EVENTS, "openspec:x")
    dumped = dump_state(state)
    assert dumped.endswith(b"\n") and not dumped.endswith(b"\n\n")
    body = json.loads(dumped)
    assert list(body)[:3] == ["schema", "unit", "phase"] and body["schema"] == "l4/state@1"
    assert dumped == dump_state(fold(reversed(EVENTS), "openspec:x"))
    assert dumped == json.dumps(body, indent=2, ensure_ascii=False).encode() + b"\n"


def test_rebuild_is_byte_identical_and_ledger_wins(tmp_path):
    """M0 form of SCN-STA-01/02: there is no state.json or --rebuild yet (M1: state-vcs-locks 1.19), so the claim
    is that the fold of the ledger is byte-identical on every read and that a hand-edited state file cannot matter."""
    from l4.redact import Redactor
    from l4.state.ledger import LedgerWriter, read_ledger

    writer = LedgerWriter.open(tmp_path, "openspec:x", RUN1, redactor=Redactor({}))
    writer.append("phase.changed", **{"from": None, "to": "intake", "trigger": "unit_discovered_pending"})
    writer.append("task.done", task="1.1")
    writer.finish(0)
    (tmp_path / ".l4" / "state.json").write_text('{"schema": "l4/state@1", "phase": "verified"}')
    first = dump_state(fold(read_ledger(tmp_path).events, "openspec:x"))
    assert first == dump_state(fold(read_ledger(tmp_path).events, "openspec:x"))
    assert json.loads(first)["phase"] == "intake"


def test_availability_selected_uses_the_spec_field_name():
    state = fold([ev(0, RUN1, 1, "availability.selected", role="implementer", selected="codex-sol")], "openspec:x")
    assert state.profiles_used == {"implementer": ["codex-sol"]}


def test_ci_results_are_folded_per_head():
    """`ci.failed` and `ci.preexisting` (the sweep's record of the project's own CI on H) are keyed by head."""
    jobs = [{"name": "test", "stage": "test", "url": "https://x/j/1", "tail": "boom"}]
    events = [
        ev(0, RUN1, 1, "run.started"),
        ev(1, RUN1, 2, "ci.failed", head="a" * 40, pipeline=7, jobs=jobs, preexisting=["lint"]),
        ev(2, RUN1, 3, "ci.preexisting", head="b" * 40, pipeline=8, jobs=["lint"]),
        ev(3, RUN1, 4, "ci.failed", head=5, jobs="nope"),  # malformed: ignored
    ]
    state = fold(events, "openspec:x")
    assert state.ci_heads == {"a" * 40: "failed", "b" * 40: "preexisting"}
    failure = state.ci_failure
    assert failure is not None and failure.head == "a" * 40 and failure.pipeline == 7
    assert failure.jobs == jobs and failure.preexisting == ["lint"]
    # a preexisting record is not a failure; the last failure wins
    later = [*events, ev(4, RUN1, 5, "ci.failed", head="c" * 40, pipeline=9, jobs=[], preexisting=[])]
    assert fold(later, "openspec:x").ci_failure.head == "c" * 40  # type: ignore[union-attr]
    assert fold(events[:1], "openspec:x").ci_heads == {} and fold(events[:1], "openspec:x").ci_failure is None


def test_recorded_ready_reads_the_latest_pr_ready_of_the_pending_events():
    """L4-ARC-008: H is the latest `pr.ready{head}` in fold order among the pending events; one without a string head
    changes nothing. `fold` itself never sets it (a `pr.ready` in the branch tree is anyone's text)."""
    assert recorded_ready([]) == (None, None)
    assert recorded_ready([ev(0, RUN1, 1, "pr.ready", url="u", number=1)]) == (None, None)
    first = ev(1, RUN1, 2, "pr.ready", url="u", number=1, head="a" * 40)
    second = ev(2, RUN2, 1, "pr.ready", url="u", number=1, head="b" * 40)
    assert recorded_ready([second, first]) == ("b" * 40, second.ts)
    for bad in (None, 7, "", ["c"]):
        junk = ev(3, RUN2, 2, "pr.ready", url="u", number=1, head=bad)
        assert recorded_ready([first, second, junk]) == ("b" * 40, second.ts)
    assert fold([first, second], "openspec:x").ready_head is None
    assert "pr.ready" not in HANDLERS
