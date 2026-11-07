"""A move never takes a spent profile, moves on from a used one, and a later run continues it (L4-IMP-094;
SCN-IMP-500, 502, 503, 504), through the real selection step: a real `l4 run` of the fixture unit with three fake
profiles of three vendors, the earlier run's records seeded after a first run that leaves the branch and the ledger."""

from datetime import UTC, datetime

from l4.agents.fake import Step
from l4.availability.cooldown import AvailabilityStore, cooldown_key
from l4.config.schema import Profile

from ..implementer.conftest import red_step, result
from .test_escalation import THREE
from .test_step_deadline import budget, fire, new_events, no_budget, run_ids, seed_events

FAIL = Step(structured=result("red"))  # "no tests added": a failed red attempt
CHAIN = THREE | {"verifier": {"independence": "none"}}
SPENT = "spent: 3 failed attempts of red of task 1.1 (implementer.max_task_attempts 3)"


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
