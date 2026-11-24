"""implementer-stall-limit through a real `l4 run` of the fixture unit (L4-IMP-112, L4-IMP-113, L4-AVL-014): an idle
stop after tool calls and a time-limit stop are limits of their profile, the work tree goes back to HEAD, and the next
profile is told. The step's own rules are in tests/unit/implementer/test_stall_limit.py."""

import subprocess
from datetime import UTC, datetime

from l4 import orchestrator
from l4.agents.fake import Step
from l4.availability.cooldown import AvailabilityStore, cooldown_key
from l4.config.loader import load_config
from l4.exitcodes import ExitCode

from ..implementer.conftest import IMPL, green_step, red_step, result
from .conftest import BRANCH
from .test_escalate_spent_profiles import CHAIN, earlier_run, failed
from .test_fallback import LINT_IMPL, TWO
from .test_step_deadline import advance, budget, new_events


def idle(tool_calls: int = 14, **over: object) -> Step:
    """FAKE: an agent that made `tool_calls` calls and then printed nothing for the idle limit."""
    return Step(idle_s=600, status="timeout", tool_calls=tool_calls, **over)


def timed_out(**over: object) -> Step:
    """FAKE: an agent that reached the step's wall-clock limit."""
    return Step(status="timeout", **over)


def tree_of(request) -> str:
    """The porcelain status of the worktree a step starts in, without the harness's own directories."""
    out = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=request.cwd, capture_output=True, text=True
    ).stdout
    return "\n".join(line for line in out.splitlines() if not any(h in line for h in (".l4", ".venv", ".agent")))


def previous_block(prompt: str) -> str:
    return prompt.split('kind="previous-attempt"', 1)[1].split("</l4:data>", 1)[0]


def test_an_idle_stall_is_a_limit_and_the_task_moves_on(run_l4, fake_clock):
    """SCN-IMP-602 end to end."""
    run = run_l4([red_step(), idle(14, writes={"leftover.txt": "half done"}), green_step()], **TWO)
    assert run.code == 0, run.triggers()
    [record] = run.events("agent.idle")
    assert (record["kind"], record["as_limit"], record["silent"], record["tool_calls"]) == ("idle", True, False, 14)
    [limit] = run.events("availability.limit")
    assert (limit["kind"], limit["source"], limit["excerpt"]) == (
        "idle",
        "run.idle",
        "no output for 10m after 14 tool calls",
    )
    [cooldown] = run.events("availability.cooldown")
    assert (cooldown["profile"], cooldown["kind"], cooldown["until"]) == ("impl", "idle", "2026-01-01T00:30:00Z")
    [fallback] = run.events("availability.fallback")
    assert (fallback["from"], fallback["to"], fallback["reason"]) == ("impl", "impl-b", "idle")
    assert run.events("task.attempt_failed") == [] and run.events("implementer.escalated") == []
    block = previous_block(run.adapter.requests[2].prompt)
    assert 'limit="idle"' in block
    assert "went idle: no output for 10m after 14 tool calls, so L4 stopped it, while working on this task" in block
    assert "leftover.txt" not in run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", BRANCH)
    assert run.outcome["units"][0]["profiles"] == {"implementer": "impl-b", "fallback_from": "impl"}


def test_a_time_limit_stall_is_a_limit_and_the_task_moves_on(run_l4, fake_clock):
    """SCN-IMP-603 end to end."""
    run = run_l4([red_step(), timed_out(writes={"leftover.txt": "half done"}), green_step()], **TWO)
    assert run.code == 0, run.triggers()
    [record] = run.events("agent.time_limit")
    assert (record["as_limit"], record["limit_s"], record["phase"]) == (True, 1800, "green")
    assert run.events("agent.idle") == []
    [limit] = run.events("availability.limit")
    assert (limit["kind"], limit["source"], limit["excerpt"]) == (
        "time",
        "run.timeout",
        "the agent step reached its time limit (30m)",
    )
    [cooldown] = run.events("availability.cooldown")
    assert (cooldown["profile"], cooldown["kind"], cooldown["until"]) == ("impl", "time", "2026-01-01T00:30:00Z")
    [fallback] = run.events("availability.fallback")
    assert (fallback["from"], fallback["to"], fallback["reason"]) == ("impl", "impl-b", "time")
    assert run.events("task.attempt_failed") == []
    block = previous_block(run.adapter.requests[2].prompt)
    assert 'limit="time"' in block
    assert (
        "ran out of time: the agent step reached its time limit (30m), so L4 stopped it, while working on this task"
        in block
    )


def test_the_next_profile_starts_from_head_and_the_discarded_work_is_recorded(run_l4, fake_clock):
    """SCN-IMP-604 end to end: a green step edits the frozen red test, two source files and `AGENTS.md`, and stalls."""
    seen: list[str] = []
    stalled = idle(
        3,
        writes={
            "tests/test_discount.py": "# edited by the stalled step\n",
            "src/pytdd/extra_a.py": "A = 1\n",
            "src/pytdd/extra_b.py": "B = 2\n",
            "AGENTS.md": "# not for the agent to write\n",
        },
    )  # fmt: skip
    run = run_l4([red_step(), stalled, green_step(on_start=lambda request: seen.append(tree_of(request)))], **TWO)
    assert run.code == 0, run.triggers()
    assert seen == [""]  # the work tree of the next profile's step holds no change
    assert [e for e in run.events("guard.violation") if e.get("path") == "AGENTS.md"]
    [record] = run.events("agent.idle")
    assert record["discarded_files"] == 3
    assert record["discarded_paths"] == ["src/pytdd/extra_a.py", "src/pytdd/extra_b.py", "tests/test_discount.py"]
    tests = run.raw(run.tdd.origin, "show", f"{BRANCH}:tests/test_discount.py")
    assert "edited by the stalled step" not in tests
    assert "src/pytdd/extra_a.py" not in run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", BRANCH)


def test_a_near_pass_is_handed_on_and_the_stalled_edits_are_not(run_l4, fake_clock):
    """SCN-IMP-605: attempt 1 passed every test and failed only lint; attempt 2 started from it and stalled after
    editing other files; the next profile starts from attempt 1's changes alone."""
    seen: list[tuple[str, str]] = []

    def watch(request) -> None:
        seen.append(((request.cwd / "src/pytdd/pricing.py").read_text(), tree_of(request)))

    near = Step(writes={"src/pytdd/pricing.py": IMPL + "\n# LINTBAD\n"}, structured=result("green"))
    stalled = idle(5, writes={"src/pytdd/pricing.py": IMPL + "\n# STALLED EDIT\n", "src/pytdd/extra.py": "X = 1\n"})
    after = Step(writes={"src/pytdd/pricing.py": IMPL}, structured=result("green"), on_start=watch)
    run = run_l4([red_step(), near, stalled, after], lint=[LINT_IMPL], **TWO)
    assert run.code == 0, run.outcome
    [(pricing, status)] = seen
    assert "LINTBAD" in pricing and "STALLED EDIT" not in pricing
    assert "extra.py" not in status
    assert [(e["attempt"], e["from_attempt"], e["from_profile"]) for e in run.events("task.near_pass_applied")][-1] == (
        2, 1, "impl",
    )  # fmt: skip
    prompt = run.adapter.requests[3].prompt
    assert 'kind="near-pass"' in prompt and 'limit="idle"' in prompt


def test_a_stalled_red_step_leaves_nothing_for_the_next_red(run_l4, fake_clock):
    """SCN-IMP-606: the tree of the second profile's red step holds none of the stalled step's test files."""
    seen: list[str] = []
    stalled = timed_out(
        writes={"tests/test_one.py": "def test_one():\n    assert True\n", "tests/test_two.py": "x = 1\n"}
    )
    run = run_l4([stalled, red_step(on_start=lambda request: seen.append(tree_of(request))), green_step()], **TWO)
    assert run.code == 0, run.triggers()
    assert seen == [""]
    assert [e["phase"] for e in run.events("agent.time_limit")] == ["red"]
    committed = run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", BRANCH)
    assert "tests/test_one.py" not in committed and "tests/test_two.py" not in committed
    assert run.events("task.red_committed")


def test_a_stall_limit_adds_no_failed_attempt_so_a_single_attempt_still_finishes(run_l4, fake_clock):
    run = run_l4([timed_out(), red_step(), green_step()], **TWO | {"implementer": {"max_task_attempts": 1}})
    assert run.code == 0 and run.events("breaker.tripped") == []


# --- L4-IMP-115, L4-AVL-015: a stall that cannot move, and a fallback that never takes a spent profile ----------


def cool_profile(tdd_repo, config: dict, name: str) -> None:
    """Cool `name` of `config` in the runner's cache, under the key its profile has."""
    tdd_repo.write_config(**config)
    profile = load_config(tdd_repo.repo).profiles[name]
    AvailabilityStore(tdd_repo.cache).cooldowns.record(
        name, cooldown_key(name, profile), datetime(2026, 1, 2, tzinfo=UTC), "usage_limit", "test"
    )


def spent_rows(profile: str) -> list[tuple[str, dict]]:
    """Three failed red attempts of task 1.1 on `profile`, as an earlier run left them: `max_task_attempts` of them."""
    return [failed(n, profile) for n in (1, 2, 3)]


ONE_OTHER = CHAIN | {"roles": {"implementer": ["impl", "impl-b"]}}


def test_a_stall_never_hands_the_step_to_a_spent_profile(run_l4, tdd_repo, raw, fake_clock):
    """SCN-IMP-622: impl-b used all its red attempts in an earlier run and no move of this run set a veto; the stall on
    impl goes to impl-c, and impl-b's step is never started."""
    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, spent_rows("impl-b"))
    run = run_l4([idle(3), red_step(), green_step()], **CHAIN)
    assert run.code == 0, run.triggers()
    [fallback] = new_events(run, old, "availability.fallback")
    assert (fallback["from"], fallback["to"], fallback["reason"]) == ("impl", "impl-c", "idle")
    assert [r.profile.vendor for r in run.adapter.requests][1:] == ["thirdco", "thirdco"]  # impl-b never ran
    assert new_events(run, old, "breaker.tripped") == []


def test_a_silent_stop_never_hands_the_step_to_a_spent_profile_either(run_l4, tdd_repo, raw, fake_clock):
    """SCN-IMP-622, the silent kind: the protection that 0.4.60 lacks."""
    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, spent_rows("impl-b"))
    run = run_l4([Step(idle_s=600, status="timeout"), red_step(), green_step()], **CHAIN)
    assert run.code == 0, run.triggers()
    [fallback] = new_events(run, old, "availability.fallback")
    assert (fallback["from"], fallback["to"], fallback["reason"]) == ("impl", "impl-c", "silent")
    assert "otherco" not in [r.profile.vendor for r in run.adapter.requests]


def test_the_stall_veto_does_not_stay_on_the_runs_selection(run_l4, tdd_repo, raw, fake_clock, monkeypatch):
    """The spent veto of the task that stalled is asked of that fallback only: the run's selection holds none of it, so
    a later task's fallback is not refused profiles that are spent for another task."""
    seen: list = []
    real = orchestrator.Orchestrator.switch_profile

    def spy(self, limit, task=None):
        chosen = real(self, limit, task)
        request = self._select().request
        seen.append(() if request is None else request.constraints)
        return chosen

    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, spent_rows("impl-b"))
    monkeypatch.setattr(orchestrator.Orchestrator, "switch_profile", spy)
    run = run_l4([idle(3), red_step(), green_step()], **CHAIN)
    assert run.code == 0 and new_events(run, old, "availability.fallback")
    [constraints] = seen
    spent = [c for c in constraints if (c("impl-b", None) or "").startswith("spent")]
    assert spent == []


def test_a_silent_stop_whose_only_other_profile_is_spent_parks_the_unit(run_l4, tdd_repo, raw, fake_clock):
    """The owner's delegate accepted this: the spent veto refuses the only other profile, so the unit waits for
    capacity (exit 12, `retry_after` the end of the stalled profile's cool-down) and no task halts on
    `max_task_attempts` with attempts left on the profile before it."""
    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, spent_rows("impl-b"))
    run = run_l4([Step(idle_s=600, status="timeout")], **ONE_OTHER)
    assert run.code == ExitCode.WAITING_CAPACITY, run.triggers()
    [unit] = run.outcome["units"]
    assert unit["phase_after"] == "waiting_capacity" and unit["retry_after"] == "2026-01-01T00:30:00Z"
    [cooldown] = new_events(run, old, "availability.cooldown")
    assert (cooldown["profile"], cooldown["kind"]) == ("impl", "silent")
    assert new_events(run, old, "breaker.tripped") == []


def test_a_time_stall_whose_only_other_profile_is_spent_is_a_failed_attempt(run_l4, tdd_repo, raw, fake_clock):
    """SCN-AVL-41 end to end: no replacement, so the stall fails the attempt and nothing cools or parks."""
    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, spent_rows("impl-b"))
    run = run_l4([timed_out(), red_step(), green_step()], **ONE_OTHER)
    assert run.code == 0, run.triggers()
    [record] = new_events(run, old, "agent.time_limit")
    assert (record["as_limit"], record["reason"]) == (False, "time: no other profile can take the step")
    [failure] = new_events(run, old, "task.attempt_failed")
    assert failure["reason"] == "the agent step reached its time limit (30m)"
    assert new_events(run, old, "availability.cooldown") == [] and new_events(run, old, "availability.fallback") == []


def test_a_stall_with_every_other_profile_cooling_or_spent_is_a_failed_attempt(run_l4, tdd_repo, raw, fake_clock):
    """SCN-IMP-611 end to end: impl cools, so the run starts on impl-b; impl-c is spent for red, so impl-b's stall has
    no profile to move to: a failed attempt, no cool-down, and the unit does not park."""
    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, spent_rows("impl-c"))
    cool_profile(tdd_repo, CHAIN, "impl")
    run = run_l4([timed_out(), red_step(), green_step()], **CHAIN)
    assert run.code == 0, run.triggers()
    [record] = new_events(run, old, "agent.time_limit")
    assert (record["profile"], record["as_limit"], record["reason"]) == (
        "impl-b", False, "time: no other profile can take the step",
    )  # fmt: skip
    assert new_events(run, old, "availability.fallback") == []
    assert [e["profile"] for e in new_events(run, old, "availability.cooldown")] == []


def test_a_time_limit_stall_that_leaves_no_time_hands_back_and_keeps_the_stall(run_l4, tdd_repo, fake_clock):
    """SCN-IMP-613, second half: the green step reaches its limit on impl and leaves 300 s; the next profile's step
    does not fit, so it is not started and the unit is handed back (exit 10), the stall limit staying in the ledger."""
    budget(tdd_repo, fake_clock, left_at_start=1000 + 1800 + 300)
    run = run_l4([red_step(on_start=advance(fake_clock, 1000)), timed_out(on_start=advance(fake_clock, 1800))], **TWO)
    assert run.code == 10, run.triggers()
    assert len(run.adapter.requests) == 2  # the next profile's green is never requested
    [reached] = run.events("deadline.reached")
    assert reached["when"] == "before" and reached["phase"] == "green"
    [record] = run.events("agent.time_limit")
    assert record["as_limit"] is True
    assert run.events("task.attempt_failed") == []


# --- a stall moves forward only (L4-IMP-115, L4-AVL-015) --------------------------------------------------------------

LATER = 1860  # seconds: a step that "works" this long outlasts the 30-minute cool-down of the stall before it


def test_a_stall_on_a_middle_profile_moves_to_a_later_one_not_to_an_earlier_usable_one(run_l4, fake_clock):
    """SCN-IMP-623: impl stalled in red and cooled; impl-b took the task and its cool-down passed while it worked; its
    green step then stalls, impl is usable again and comes first in the chain, and the step goes to impl-c anyway."""
    script = [idle(3), red_step(on_start=advance(fake_clock, LATER)), timed_out(), green_step()]
    run = run_l4(script, **CHAIN)
    assert run.code == 0, run.triggers()
    moves = [(e["from"], e["to"], e["reason"]) for e in run.events("availability.fallback")]
    assert moves == [("impl", "impl-b", "idle"), ("impl-b", "impl-c", "time")]
    assert [r.profile.vendor for r in run.adapter.requests] == ["fakeco", "otherco", "otherco", "thirdco"]
    assert run.events("task.attempt_failed") == []


def test_a_stall_on_the_last_profile_is_a_failed_attempt_though_an_earlier_one_is_usable(run_l4, fake_clock):
    """SCN-IMP-624: the same, with no profile after impl-b. impl is usable again but earlier, so the stall fails the
    attempt, nothing is cooled for it, and the task goes on on impl-b."""
    script = [idle(3), red_step(on_start=advance(fake_clock, LATER)), timed_out(), green_step()]
    run = run_l4(script, **ONE_OTHER)
    assert run.code == 0, run.triggers()
    assert [(e["from"], e["to"]) for e in run.events("availability.fallback")] == [("impl", "impl-b")]
    [record] = run.events("agent.time_limit")
    assert (record["profile"], record["as_limit"], record["reason"]) == (
        "impl-b", False, "time: no other profile can take the step",
    )  # fmt: skip
    assert [e["profile"] for e in run.events("availability.cooldown")] == ["impl"]
    [failure] = run.events("task.attempt_failed")
    assert (failure["profile"], failure["reason"]) == ("impl-b", "the agent step reached its time limit (30m)")
    assert [r.profile.vendor for r in run.adapter.requests] == ["fakeco", "otherco", "otherco", "otherco"]


def test_a_silent_stop_still_goes_back_to_an_earlier_profile(run_l4, fake_clock):
    """SCN-IMP-625: the silent kind keeps its 0.4.60 selection, which starts from the chain's first usable profile."""
    script = [idle(3), red_step(on_start=advance(fake_clock, LATER)), Step(idle_s=600, status="timeout"), green_step()]
    run = run_l4(script, **ONE_OTHER)
    assert run.code == 0, run.triggers()
    moves = [(e["from"], e["to"], e["reason"]) for e in run.events("availability.fallback")]
    assert moves == [("impl", "impl-b", "idle"), ("impl-b", "impl", "silent")]


def cool_until(tdd_repo, config: dict, name: str, until: datetime) -> None:
    tdd_repo.write_config(**config)
    profile = load_config(tdd_repo.repo).profiles[name]
    AvailabilityStore(tdd_repo.cache).cooldowns.record(name, cooldown_key(name, profile), until, "usage_limit", "test")


def test_the_wait_in_the_run_keeps_the_spent_veto_of_the_stall(run_l4, tdd_repo, raw, fake_clock):
    """O4: impl-b is spent for red, impl-c cools for 20 minutes. The silent stop of impl finds nothing usable, the run
    waits out impl-c's cool-down and selects again, and that selection refuses impl-b as the first one did."""
    from datetime import timedelta

    old = earlier_run(run_l4, tdd_repo, raw, fake_clock, spent_rows("impl-b"))
    config = CHAIN | {"availability": {"wait_in_run": "30m", "wait_in_run_max_total": "1h"}}
    cool_until(tdd_repo, config, "impl-c", fake_clock.now() + timedelta(minutes=20))
    run = run_l4([Step(idle_s=600, status="timeout"), red_step(), green_step()], **config)
    assert run.code == 0, run.triggers()
    assert new_events(run, old, "availability.wait_in_run")
    assert [r.profile.vendor for r in run.adapter.requests][1:] == ["thirdco", "thirdco"]  # impl-b never ran
    assert run.outcome["units"][0]["profiles"]["implementer"] == "impl-c"
    assert new_events(run, old, "breaker.tripped") == []
