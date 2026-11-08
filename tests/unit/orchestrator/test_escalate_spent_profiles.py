"""A move never takes a spent profile, moves on from a used one, and a later run continues it (L4-IMP-094;
SCN-IMP-500, 502, 503, 504), through the real selection step: a real `l4 run` of the fixture unit with three fake
profiles of three vendors, the earlier run's records seeded after a first run that leaves the branch and the ledger."""

from datetime import UTC, datetime

from l4.agents.base import LimitSignal
from l4.agents.fake import Step
from l4.availability.cooldown import AvailabilityStore, cooldown_key
from l4.config.schema import Profile
from l4.state.fold import fold
from l4.state.ledger import LedgerEvent

from ..implementer.conftest import red_step, result
from .test_escalation import THREE
from .test_step_deadline import budget, fire, new_events, no_budget, run_ids, seed_events

FAIL = Step(structured=result("red"))  # "no tests added": a failed red attempt
CHAIN = THREE | {"verifier": {"independence": "none"}}
SPENT = "spent: 3 failed attempts of red of task 1.1 (implementer.max_task_attempts 3)"
USED = "used its share: 2 failed attempts of red of task 1.1 (implementer.escalate_after 2)"
ENVELOPE = ("ts", "run_id", "unit", "seq", "type")


def failed(attempt: int, profile: str) -> tuple[str, dict]:
    return "task.attempt_failed", {"task": "1.1", "phase": "red", "attempt": attempt, "profile": profile, "reason": "r"}


def moved(origin: str, target: str, failures: int = 2, attempt: int = 3) -> tuple[str, dict]:
    return "implementer.escalated", {
        "task": "1.1", "phase": "red", "from": origin, "to": target, "failures": failures, "attempt": attempt,
    }  # fmt: skip


def earlier_run(run_l4, tdd_repo, raw, fake_clock, rows: list[tuple[str, dict]]) -> set[str]:
    """A first run that stops at the deadline (the branch and ledger exist), then the records of the runs between."""
    budget(tdd_repo, fake_clock, left_at_start=100000)
    first = run_l4([red_step(on_start=fire)], **CHAIN)
    assert first.code == 10
    no_budget(tdd_repo)
    seed_events(tdd_repo, raw, fake_clock, rows)
    return {*run_ids(first), "r-20260101T0001Z-5eed"}


def profiles_used(run) -> list[str]:
    """What the fold says the unit's implementer profiles are: the judges' independence reads this list."""
    events = [
        LedgerEvent(
            datetime.fromisoformat(e["ts"].replace("Z", "+00:00")), e["run_id"], e["unit"], e["seq"], e["type"],
            {k: v for k, v in e.items() if k not in ENVELOPE},
        )
        for e in run.ledger()
    ]  # fmt: skip
    return fold(events, events[0].unit).profiles_used["implementer"]


def cool(tdd_repo, profile: str) -> None:
    until = datetime(2026, 1, 2, tzinfo=UTC)
    AvailabilityStore(tdd_repo.cache).cooldowns.record(
        profile, cooldown_key(profile, Profile(adapter="fake")), until, "usage_limit", "test"
    )


def test_a_later_run_continues_the_move_of_an_earlier_one(run_l4, tdd_repo, raw, fake_clock):
    """SCN-IMP-500: the run-B replay, through `_escalation_profile`."""
    rows = [failed(1, "impl-b"), failed(2, "impl-b"), moved("impl-b", "impl-c")]
    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, rows)
    run = run_l4([FAIL, FAIL, FAIL], **CHAIN)
    assert run.code == 13
    [escalated] = new_events(run, old, "implementer.escalated")
    assert (escalated["from"], escalated["to"], escalated["failures"], escalated["attempt"]) == (
        "impl-b",
        "impl-c",
        2,
        3,
    )
    selected = new_events(run, old, "availability.selected")
    assert [(e["selected"], e.get("escalated_from")) for e in selected] == [("impl", None), ("impl-c", "impl-b")]
    assert [(e["phase"], e["attempt"]) for e in new_events(run, old, "step.started")] == [
        ("red", 3), ("red", 4), ("red", 5),
    ]  # fmt: skip
    assert [r.profile.vendor for r in run.adapter.requests] == ["thirdco"] * 3  # impl ran none
    halted = [e for e in new_events(run, old, "phase.changed") if e["to"] == "halted"][-1]
    assert halted["detail"].startswith(
        "task 1.1: max_task_attempts (3) reached in red on impl-b (2), impl-c (3); last failure: "
    )
    assert run.outcome["units"][0]["profiles"].get("implementer") == "impl"  # the run's profile did not change


def test_a_spent_profile_is_refused_before_it_is_probed(run_l4, tdd_repo, raw, fake_clock):
    """SCN-IMP-502: impl-b failed red three times in the window; the move from impl skips it as a constraint."""
    rows = [failed(n, "impl-b") for n in (1, 2, 3)]
    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, rows)
    run = run_l4([FAIL, FAIL, FAIL, FAIL], **CHAIN)
    [escalated] = new_events(run, old, "implementer.escalated")
    assert (escalated["from"], escalated["to"]) == ("impl", "impl-c")
    [_, chosen] = new_events(run, old, "availability.selected")
    assert chosen["selected"] == "impl-c" and chosen["escalated_from"] == "impl"
    [skipped] = chosen["skipped"]
    assert (skipped["profile"], skipped["step"], skipped["reason"]) == ("impl-b", "constraint", SPENT)
    assert "impl-b" not in chosen["probes"]  # the veto comes before the probe


def test_a_cooling_target_gives_way_without_parking(run_l4, tdd_repo, raw, fake_clock):
    """SCN-IMP-504 end to end: impl-c is cooling; the continuation is refused with `on`, nothing parks."""
    rows = [failed(1, "impl-b"), failed(2, "impl-b"), moved("impl-b", "impl-c")]
    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, rows)
    cool(tdd_repo, "impl-c")
    run = run_l4([FAIL, FAIL, FAIL], **CHAIN)
    assert run.code == 13
    first, second = new_events(run, old, "implementer.escalation_skipped")
    assert (first["from"], first["on"], first["failures"]) == ("impl-b", "impl", 2)
    assert second["from"] == "impl-b" and "on" not in second
    assert new_events(run, old, "availability.unavailable") == []
    assert "waiting_capacity" not in [e["to"] for e in new_events(run, old, "phase.changed")]
    assert [(e["from"], e["to"]) for e in new_events(run, old, "implementer.escalated")] == [("impl", "impl-b")]
    own = run.adapter.requests[0].profile.vendor  # the run's own profile ran 3 and 4, impl-b the last attempt
    assert [r.profile.vendor for r in run.adapter.requests] == [own, own, "otherco"]
    assert [(e["phase"], e["attempt"]) for e in new_events(run, old, "step.started")] == [
        ("red", 3), ("red", 4), ("red", 5),
    ]  # fmt: skip
    halted = [e for e in new_events(run, old, "phase.changed") if e["to"] == "halted"][-1]
    assert "reached in red on impl-b (3), impl (2); no later profile can take it (" in halted["detail"]


def test_every_later_profile_spent_halts_with_the_reason(run_l4, tdd_repo, raw, fake_clock):
    """SCN-IMP-503: one refusal that names both profiles, no move, and the halt detail says why."""
    rows = [failed(n, "impl-b") for n in (1, 2, 3)] + [failed(n, "impl-c") for n in (4, 5, 6)]
    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, rows)
    run = run_l4([FAIL, FAIL, FAIL], **CHAIN)
    assert run.code == 13
    [skipped] = new_events(run, old, "implementer.escalation_skipped")
    assert skipped["from"] == "impl" and "impl-b" in skipped["reason"] and "impl-c" in skipped["reason"]
    assert new_events(run, old, "implementer.escalated") == []
    halted = [e for e in new_events(run, old, "phase.changed") if e["to"] == "halted"][-1]
    assert halted["detail"].startswith(
        "task 1.1: max_task_attempts (3) reached in red on impl-b (3), impl-c (3), impl (3); "
        "no later profile can take it ("
    )


def test_a_move_skips_a_used_profile_without_selecting_it(run_l4, tdd_repo, raw, fake_clock):
    """SCN-IMP-501 through `_escalation_profile`: impl-b failed twice, so the move from impl goes to impl-c in one
    pass 1; impl-b is listed as skipped, is never probed, and is not one of the unit's implementer profiles."""
    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, [failed(1, "impl-b"), failed(2, "impl-b")])
    run = run_l4([FAIL, FAIL, FAIL, FAIL, FAIL], **CHAIN)
    [escalated] = new_events(run, old, "implementer.escalated")
    got = (escalated["from"], escalated["to"], escalated["failures"], escalated["attempt"])
    assert got == ("impl", "impl-c", 2, 5)
    moves = [e for e in new_events(run, old, "availability.selected") if e.get("escalated_from")]
    [chosen] = moves  # one record for the move
    assert chosen["selected"] == "impl-c"
    [skipped] = chosen["skipped"]
    assert (skipped["profile"], skipped["step"], skipped["reason"]) == ("impl-b", "constraint", USED)
    assert "impl-b" not in chosen["probes"]
    assert [(e["phase"], e["attempt"]) for e in new_events(run, old, "step.started")][:3] == [
        ("red", 3), ("red", 4), ("red", 5),
    ]  # fmt: skip
    assert "impl-b" not in profiles_used(run)  # a profile that never ran does not narrow the judges


def test_a_used_profile_takes_the_step_when_nothing_after_it_can(run_l4, tdd_repo, raw, fake_clock):
    """Pass 2: impl-c is cooling and impl-b is at `escalate_after`, so impl-b keeps its last attempt (D1). The move
    has one `availability.selected`, and impl-b is not listed in its `skipped`: pass 2 took it."""
    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, [failed(1, "impl-b"), failed(2, "impl-b")])
    cool(tdd_repo, "impl-c")
    run = run_l4([FAIL, FAIL, FAIL], **CHAIN)
    assert run.code == 13
    [escalated] = new_events(run, old, "implementer.escalated")
    assert (escalated["from"], escalated["to"], escalated["attempt"]) == ("impl", "impl-b", 5)
    [chosen] = [e for e in new_events(run, old, "availability.selected") if e.get("escalated_from")]
    assert chosen["selected"] == "impl-b" and chosen["skipped"] == []  # the walk took impl-b before it met impl-c
    [refused] = new_events(run, old, "implementer.escalation_skipped")  # impl-b: nothing after it can take the step
    assert refused["from"] == "impl-b" and "on" not in refused
    assert [(e["phase"], e["attempt"]) for e in new_events(run, old, "step.started")] == [
        ("red", 3), ("red", 4), ("red", 5),
    ]  # fmt: skip
    assert profiles_used(run) == ["impl", "impl-b"]
    halted = [e for e in new_events(run, old, "phase.changed") if e["to"] == "halted"][-1]
    assert "reached in red on impl-b (3), impl (2); no later profile can take it (" in halted["detail"]


def test_a_limit_on_the_moved_profile_never_hands_the_step_back_to_a_spent_one(run_l4, tdd_repo, raw, fake_clock):
    """SCN-IMP-502's limit: the fallback (`Factory.on_limit`) selects from the chain's start with the veto of pass 2:
    impl-b used its max_task_attempts in the window, the move from impl goes to impl-c, impl cools while impl-c runs
    the moved step and impl-c limits, so the unit waits for capacity and impl-b runs no fourth attempt."""
    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, [failed(n, "impl-b") for n in (1, 2, 3)])
    limit = LimitSignal("fake", None, "usage_limit", datetime(2026, 1, 1, 6, 0, tzinfo=UTC), "test", "usage limit")
    limited = Step(status="quota", limit=limit, on_start=lambda _req: cool(tdd_repo, "impl"))
    run = run_l4([FAIL, FAIL, limited, FAIL], **CHAIN)
    assert run.code == 12
    assert [(e["from"], e["to"]) for e in new_events(run, old, "implementer.escalated")] == [("impl", "impl-c")]
    own = run.adapter.requests[0].profile.vendor
    assert [r.profile.vendor for r in run.adapter.requests] == [own, own, "thirdco"]  # impl-b ran nothing
    assert "waiting_capacity" in [e["to"] for e in new_events(run, old, "phase.changed")]


def test_a_second_limit_in_the_task_never_hands_the_step_to_a_spent_profile(run_l4, tdd_repo, raw, fake_clock):
    """The veto holds for every fallback of the task (D1): impl-b is spent, the move goes from impl to impl-c, impl-c
    limits and the step falls back to impl, the next move is refused (impl-c cooling), and impl limits too. The second
    fallback refuses impl-b as the first did, so the unit waits for capacity and impl-b runs nothing."""
    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, [failed(n, "impl-b") for n in (1, 2, 3)])
    limit = LimitSignal("fake", None, "usage_limit", datetime(2026, 1, 1, 6, 0, tzinfo=UTC), "test", "usage limit")
    quota = Step(status="quota", limit=limit)
    run = run_l4([FAIL, FAIL, quota, quota, FAIL], **CHAIN)
    assert run.code == 12
    assert [(e["from"], e["to"]) for e in new_events(run, old, "implementer.escalated")] == [("impl", "impl-c")]
    own = run.adapter.requests[0].profile.vendor
    assert [r.profile.vendor for r in run.adapter.requests] == [own, own, "thirdco", own]  # impl-b ran nothing
    fallbacks = [(e["from"], e["to"]) for e in new_events(run, old, "availability.fallback")]
    assert fallbacks == [("impl-c", "impl")]
    assert "waiting_capacity" in [e["to"] for e in new_events(run, old, "phase.changed")]
