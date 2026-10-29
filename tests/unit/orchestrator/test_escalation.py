"""escalate-and-note 2.3 to 2.5 (L4-IMP-017, L4-OPS-018): the orchestrator's hook moves a task's phase to the next
profile of the chain, keeps the move inside the task, and `resume` can carry the note's task."""

from datetime import UTC, datetime

import pytest

from l4.agents.base import LimitSignal
from l4.agents.fake import Step
from l4.availability.cooldown import AvailabilityStore, cooldown_key
from l4.cli import main
from l4.config.schema import Profile
from l4.state import resume as resume_module

from ..implementer.conftest import green_step, red_step, result
from .conftest import BRANCH, UNIT
from .test_fallback import RESETS, TWO

FAIL = Step(structured=result("red"))  # "no tests added": a failed red attempt
INVALID = Step()  # no result object: a failed attempt too


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


def test_a_limit_on_the_moved_profile_cools_that_profile_and_the_task_goes_back(run_l4, fake_clock):  # SCN-IMP-182
    limit = LimitSignal("fake", None, "usage_limit", RESETS, "test", "You have hit your usage limit")
    run = run_l4([FAIL, FAIL, Step(status="quota", limit=limit), red_step(), green_step()], **TWO)
    assert run.code == 0
    (cooled,) = run.events("availability.cooldown")
    assert cooled["profile"] == "impl-b"
    assert vendors(run)[3:] == [vendors(run)[0]] * 2  # fresh counts, back on the run's profile
    assert run.events("task.attempt_failed")[-1]["attempt"] == 2  # a limit is not an attempt
    assert run.outcome["units"][0]["profiles"].get("implementer") == "impl"


THREE = TWO | {
    "roles": {"implementer": ["impl", "impl-b", "impl-c"]},
    "profiles": TWO["profiles"] | {"impl-c": {"adapter": "fake", "vendor": "thirdco"}},
}


def test_a_silent_escalated_profile_cools_and_the_task_goes_on_on_the_next_one(run_l4, fake_clock):  # SCN-IMP-430
    silent = Step(idle_s=600, status="timeout")
    run = run_l4([FAIL, FAIL, silent, red_step(), green_step()], **THREE)
    assert run.code == 0, run.triggers()
    [cooled] = run.events("availability.cooldown")
    assert (cooled["profile"], cooled["kind"]) == ("impl-b", "silent")
    assert [(e["from"], e["to"]) for e in run.events("implementer.escalated")] == [
        ("impl", "impl-b"),
        ("impl", "impl-c"),
    ]
    assert vendors(run) == [vendors(run)[0]] * 2 + ["otherco", "thirdco", "thirdco"]
    assert len(run.events("task.attempt_failed")) == 2  # the silent stop is not an attempt
    assert run.outcome["units"][0]["profiles"].get("implementer") == "impl"  # the run's profile is the first, still


@pytest.fixture
def halted(run_l4):
    run = run_l4([FAIL], implementer={"max_task_attempts": 1})
    assert run.code == 13
    return run


def resume_with(tdd_repo, monkeypatch, **note) -> list[dict]:
    real = resume_module.run_unit_in_worktree
    # the command binds a note itself; the test overrides it
    monkeypatch.setattr(resume_module, "run_unit_in_worktree", lambda *a, **k: real(*a, **{**k, **note}))
    code = main(["resume", "--unit", UNIT, "--reason", "again", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ)
    assert code == 0
    return code


def test_a_resume_with_a_note_task_records_it(halted, tdd_repo, monkeypatch):  # 2.5
    resume_with(tdd_repo, monkeypatch, note_task="1.1", note_fix_unit="fx-1")
    (event,) = halted.local_events("unit.resumed")
    assert (event["note_task"], event["note_fix_unit"]) == ("1.1", "fx-1")


def test_a_resume_without_records_neither_key(halted, tdd_repo, monkeypatch):  # 2.5
    resume_with(tdd_repo, monkeypatch, note_task=None, note_fix_unit=None)  # `l4 resume` itself now binds
    (event,) = halted.local_events("unit.resumed")
    assert "note_task" not in event and "note_fix_unit" not in event


# --- 4.1: both halves on one run (L4-IMP-017, L4-OPS-018) ---------------------------------------------------------


NOTE = "add the keyword to the signature with a default; never call a keyword the function does not have"


def test_a_halt_a_retry_with_a_note_and_the_next_run_carry_the_note_then_the_escalation(run_l4, tdd_repo, capsys):
    first = run_l4([FAIL] * 5, **TWO)  # SCN-IMP-177: two failures on impl, three on impl-b, then the halt
    assert first.code == 13
    assert "A person's note" not in "".join(r.prompt for r in first.adapter.requests)
    capsys.readouterr()
    argv = ["retry", "--unit", UNIT, "--reason", NOTE, "--no-run", "--repo", str(tdd_repo.repo)]
    assert main(argv, environ=tdd_repo.environ) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "note: the reason goes to the next steps of task 1.1"
    (retried,) = first.events("unit.retried")
    assert (retried["reason"], retried["note_task"]) == (NOTE, "1.1")

    second = run_l4([FAIL, FAIL, red_step(), green_step()], **TWO)  # SCN-OPS-28 with the escalation after two failures
    assert second.code == 0
    prompts = [r.prompt for r in second.adapter.requests]
    assert vendors(second)[0] == vendors(first)[0] and vendors(second)[2] != vendors(second)[0]
    block = f"# A person's note\n<l4:data source=\"retry note\">\nA person's note on this retry: {NOTE}\n</l4:data>"
    assert all(block in p for p in prompts)  # red and green, every attempt, both profiles
    assert all(p.count('source="retry note"') == 1 for p in prompts)
    assert not any('reason="escalation"' in p for p in prompts[:2])  # the first profile: the note only
    assert all('reason="escalation"' in p for p in prompts[2:3])  # the second profile: the note and the escalation
    assert prompts[2].index('reason="escalation"') < prompts[2].index("A person's note")  # the note is the last block
    rendered = [e for e in second.events("prompt.rendered") if e.get("retry_note")]
    assert len(rendered) == len(prompts)
    assert rendered[0]["retry_note"]["event"] == "unit.retried" and rendered[0]["retry_note"]["ts"] == retried["ts"]
