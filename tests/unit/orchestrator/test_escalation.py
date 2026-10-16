"""escalate-and-note 2.3 to 2.5 (L4-IMP-017, L4-OPS-018): the orchestrator's hook moves a task's phase to the next
profile of the chain, keeps the move inside the task, and `resume` can carry the note's task."""

from datetime import UTC, datetime

import pytest

from l4.agents.fake import Step
from l4.availability.cooldown import AvailabilityStore, cooldown_key
from l4.config.schema import Profile

from ..implementer.conftest import green_step, red_step, result
from .conftest import BRANCH, UNIT
from .test_fallback import TWO

FAIL = Step(structured=result("red"))  # "no tests added": a failed red attempt
INVALID = Step(structured={"status": "ok"})  # no `summary`: a failed attempt too


def vendors(run) -> list[str | None]:
    """Which profile ran each step (the two fake profiles differ by their vendor)."""
    return [r.profile.vendor for r in run.adapter.requests]


def test_two_failed_reds_move_the_phase_to_the_next_profile_without_a_cooldown(run_l4):  # SCN-IMP-176
    run = run_l4([FAIL, INVALID, red_step(), green_step()], **TWO)
    assert run.code == 0
    (moved,) = run.events("implementer.escalated")
    assert (moved["task"], moved["phase"], moved["from"], moved["to"], moved["failures"], moved["attempt"]) == (
        "1.1", "red", "impl", "impl-b", 2, 3,
    )  # fmt: skip
    selected = run.events("availability.selected")
    assert [(e["selected"], e.get("escalated_from"), e.get("fallback_from")) for e in selected] == [
        ("impl", None, None), ("impl-b", "impl", None),
    ]  # fmt: skip
    assert run.events("availability.cooldown") == [] and run.events("availability.fallback") == []
    assert vendors(run)[:2] != vendors(run)[2:3] * 2 and len(run.adapter.requests) == 4
    third = run.adapter.requests[2].prompt
    assert 'kind="previous-attempt"' in third and 'reason="escalation"' in third
    assert "Your previous attempt was rejected" in third
    assert 'kind="previous-attempt"' not in run.adapter.requests[0].prompt


def test_the_last_profile_gets_max_task_attempts_then_the_unit_halts_naming_both(run_l4):  # SCN-IMP-177
    run = run_l4([FAIL, FAIL, FAIL, FAIL, FAIL], **TWO)
    assert run.code == 13
    assert len(run.adapter.requests) == 5 and len(run.events("implementer.escalated")) == 1
    (tripped,) = run.events("breaker.tripped")
    assert tripped["attempts"] == 5
    assert tripped["profiles"] == [{"profile": "impl", "failures": 2}, {"profile": "impl-b", "failures": 3}]
    halted = [e for e in run.events("phase.changed") if e["to"] == "halted"][-1]
    assert halted["detail"].startswith("task 1.1: max_task_attempts (3) reached in red on impl (2), impl-b (3); last")


def test_the_task_keeps_the_profile_and_commits_name_it_without_a_fallback_mark(run_l4):  # SCN-IMP-178
    run = run_l4([FAIL, FAIL, red_step(), green_step()], **TWO)
    assert run.code == 0
    green = run.adapter.requests[3]
    assert green.profile.vendor == run.adapter.requests[2].profile.vendor
    assert 'kind="previous-attempt"' not in green.prompt
    fmt = "%s|%(trailers:key=L4-Agent,valueonly,separator=;)|%(trailers:key=L4-Fallback-From,valueonly,separator=;)"
    log = run.raw(run.tdd.origin, "log", "--reverse", f"--format={fmt}", f"main..{BRANCH}")
    red, feat = [line.split("|") for line in log.splitlines() if line.startswith(("test(", "feat("))]
    assert red[1].startswith("impl-b") and feat[1].startswith("impl-b") and red[2] == feat[2] == ""
    assert run.outcome["units"][0]["profiles"].get("fallback_from") is None


def test_the_next_task_starts_on_the_first_profile_again(run_l4, tdd_repo, raw):  # SCN-IMP-178
    from .conftest import UNIT_DIR, new_origin_main

    tasks = "## 1. Discount codes\n\n- [ ] 1.1 Add `apply_discount`\n- [ ] 1.2 Document it\n"
    new_origin_main(tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": tasks})
    run = run_l4([FAIL, FAIL, red_step(), green_step(), FAIL], **TWO)  # 1.2's red fails; the script then runs out
    first_vendor = run.adapter.requests[0].profile.vendor
    assert run.adapter.requests[2].profile.vendor != first_vendor
    assert run.adapter.requests[4].profile.vendor == first_vendor
    assert [e["task"] for e in run.events("implementer.escalated")] == ["1.1"]


def test_a_cooling_next_profile_skips_the_move_and_parks_nothing(run_l4, tdd_repo, fake_clock):  # SCN-IMP-180
    until = datetime(2026, 1, 2, tzinfo=UTC)
    AvailabilityStore(tdd_repo.cache).cooldowns.record(
        "impl-b", cooldown_key("impl-b", Profile(adapter="fake")), until, "usage_limit", "test"
    )
    run = run_l4([FAIL, FAIL, FAIL], **TWO)
    assert run.code == 13
    skipped = run.events("implementer.escalation_skipped")
    assert [(e["task"], e["phase"], e["from"]) for e in skipped] == [("1.1", "red", "impl")]  # after attempt 2 only
    assert run.events("implementer.escalated") == [] and run.events("availability.unavailable") == []
    assert "waiting_capacity" not in [e["to"] for e in run.events("phase.changed")]
    assert len(run.adapter.requests) == 3


def test_a_blocked_step_raises_the_question_and_does_not_escalate(run_l4):  # SCN-IMP-182
    from ..implementer.conftest import blocked_step

    run = run_l4([FAIL, blocked_step()], **TWO)
    assert run.events("implementer.escalated") == [] and run.events("implementer.escalation_skipped") == []
    assert len(run.adapter.requests) == 2
