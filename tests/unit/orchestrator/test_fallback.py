"""M1.2 Stage C on fakes: a limit in the middle of a task moves it to the next profile of the chain (agent-factory
1.25, implementer-tdd-loop 2.25), `L4-Fallback-From` marks the commits that follow, and an empty chain parks the unit
with a `retry_after` that `l4 plan` and a later `l4 run` honour (forge-and-ci 2.32)."""

import json
from datetime import UTC, datetime, timedelta

from l4.agents.base import LimitSignal
from l4.agents.fake import Step
from l4.cli import main
from l4.exitcodes import ExitCode

from ..implementer.conftest import green_step, red_step, result
from .conftest import BRANCH, UNIT

RESETS = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
TWO = {"roles": {"implementer": ["impl", "impl-b"]}, "profiles": {"impl-b": {"adapter": "fake", "vendor": "otherco"}}}


def limited(**over: object) -> Step:
    limit = LimitSignal("fake", None, "usage_limit", RESETS, "test", "You have hit your usage limit")
    return Step(status="quota", limit=limit, **over)


def test_a_limit_in_green_continues_the_task_on_the_next_profile(run_l4, fake_clock):
    run = run_l4([red_step(), limited(writes={"leftover.txt": "half done"}), green_step()], **TWO)
    assert run.code == 0
    assert len(run.adapter.requests) == 3
    assert run.events("availability.cooldown")[0]["profile"] == "impl"
    assert run.events("availability.cooldown")[0]["until"] == "2026-01-01T06:00:00Z"
    fallback = run.events("availability.fallback")
    assert [(e["from"], e["to"], e["reason"]) for e in fallback] == [("impl", "impl-b", "usage_limit")]
    selected = run.events("availability.selected")
    assert [(e["selected"], e.get("fallback_from")) for e in selected] == [("impl", None), ("impl-b", "impl")]
    # the red commit is kept, not redone; the half-done work of the limited step is gone
    assert [s.split("(")[0] for s in run.subjects() if not s.startswith("chore")] == ["test", "feat"]
    assert "leftover.txt" not in run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", BRANCH)
    fmt = "%s|%(trailers:key=L4-Agent,key=L4-Fallback-From,valueonly,separator=;)"
    log = run.raw(run.tdd.origin, "log", "--reverse", f"--format={fmt}", f"main..{BRANCH}")
    red, green = [line for line in log.splitlines() if line.startswith(("test(", "feat("))]
    assert red.endswith("|impl") and green.endswith("|impl-b;impl")
    assert run.outcome["units"][0]["profiles"] == {"implementer": "impl-b", "fallback_from": "impl"}


def test_the_next_profile_is_told_what_happened_without_a_transcript(run_l4, fake_clock):
    run = run_l4([red_step(), limited(printed="SECRET TRANSCRIPT LINE"), green_step()], **TWO)
    assert run.code == 0
    first, _limited, after = (r.prompt for r in run.adapter.requests)
    assert "previous-attempt" not in first
    assert 'kind="previous-attempt"' in after
    block = after.split('kind="previous-attempt"', 1)[1].split("</l4:data>", 1)[0]
    assert "impl" in block and "usage_limit" in block and "SECRET TRANSCRIPT LINE" not in after


def test_a_limit_in_red_restarts_the_task_on_the_next_profile(run_l4, fake_clock):
    run = run_l4([limited(writes={"leftover.txt": "x"}), red_step(), green_step()], **TWO)
    assert run.code == 0
    assert [s.split("(")[0] for s in run.subjects() if not s.startswith("chore")] == ["test", "feat"]
    assert "leftover.txt" not in run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", BRANCH)


def test_a_kiro_throttle_in_red_moves_the_task_on_and_consumes_no_attempt(run_l4, fake_clock):
    """Kiro e2e H2 (KF2): a FREE-tier throttle is a rate limit end to end: the profile cools for 2 minutes, the next
    profile takes the task, and with a single attempt allowed the unit still finishes, because none was used."""
    from l4.agents.kiro_cli import throttle_signal

    limit = throttle_signal("Internal error (code -32603): The request was throttled by the service", fake_clock.now())
    throttled = Step(status="rate_limited", limit=limit, writes={"leftover.txt": "x"})
    run = run_l4([throttled, red_step(), green_step()], **TWO | {"implementer": {"max_task_attempts": 1}})
    assert run.code == 0
    assert run.events("task.attempt_failed") == [] and run.events("breaker.tripped") == []
    (cooldown,) = run.events("availability.cooldown")
    assert (cooldown["profile"], cooldown["kind"], cooldown["until"]) == ("impl", "rate_limit", "2026-01-01T00:02:00Z")
    fallback = run.events("availability.fallback")
    assert [(e["from"], e["to"], e["reason"]) for e in fallback] == [("impl", "impl-b", "rate_limit")]
    assert "leftover.txt" not in run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", BRANCH)


def silent(**over: object) -> Step:
    """A step the idle watchdog stopped before any tool call (L4-IMP-087)."""
    return Step(idle_s=600, status="timeout", **over)


def test_a_silent_step_moves_the_task_and_the_run_without_counting(run_l4, tdd_repo, raw, fake_clock):
    """SCN-IMP-426 end to end: events, the step again on the second profile, and the next task on it too."""
    from .conftest import UNIT_DIR, new_origin_main

    tasks = "## 1. Discount codes\n\n- [ ] 1.1 Add `apply_discount`\n- [ ] 1.2 Document it\n"
    new_origin_main(tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": tasks})
    # task 1.2's red fails (a red step that adds no test) and, with one attempt allowed, halts: 1.1 got through only
    # because the silent stop used none
    no_test = Step(structured=result("red"))
    run = run_l4(
        [silent(writes={"leftover.txt": "half done"}), red_step(), green_step(), no_test],
        **TWO | {"implementer": {"max_task_attempts": 1}},
    )  # fmt: skip
    assert run.code == 13, run.triggers()
    assert [(e["task"], e["profile"]) for e in run.events("task.attempt_failed")] == [("1.2", "impl-b")]
    [limit] = run.events("availability.limit")
    assert (limit["kind"], limit["source"], limit["excerpt"]) == ("silent", "run.idle", "no output for 10m")
    [cooldown] = run.events("availability.cooldown")
    assert (cooldown["profile"], cooldown["kind"], cooldown["until"]) == ("impl", "silent", "2026-01-01T00:30:00Z")
    [fallback] = run.events("availability.fallback")
    assert (fallback["from"], fallback["to"], fallback["reason"]) == ("impl", "impl-b", "silent")
    [idle] = run.events("agent.idle")
    assert idle["silent"] is True
    requests = run.adapter.requests
    assert [r.profile.vendor for r in requests] == [requests[0].profile.vendor] + [requests[1].profile.vendor] * 3
    assert requests[1].profile.vendor != requests[0].profile.vendor  # the step again, and the next task, on impl-b
    assert "leftover.txt" not in run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", BRANCH)
    assert run.outcome["units"][0]["profiles"] == {"implementer": "impl-b", "fallback_from": "impl"}


def test_the_next_profile_is_told_that_the_profile_went_silent(run_l4, fake_clock):
    run = run_l4([silent(printed="SECRET TRANSCRIPT LINE"), red_step(), green_step()], **TWO)
    assert run.code == 0
    after = run.adapter.requests[1].prompt
    block = after.split('kind="previous-attempt"', 1)[1].split("</l4:data>", 1)[0]
    assert 'limit="silent"' in block and "went silent: no output for 10m" in block
    assert "usage limit" not in block and "SECRET TRANSCRIPT LINE" not in after


def test_nothing_left_parks_the_unit_with_the_earliest_reset_and_a_later_run_re_enters(run_l4, fake_clock, capsys):
    run = run_l4([red_step(), limited()], **TWO | {"roles": {"implementer": ["impl"]}})
    assert run.code == ExitCode.WAITING_CAPACITY
    (unit,) = run.outcome["units"]
    assert unit["phase_after"] == "waiting_capacity" and unit["retry_after"] == "2026-01-01T06:00:00Z"
    parked = [e for e in run.events("phase.changed") if e["to"] == "waiting_capacity"]
    assert parked[0]["retry_after"] == "2026-01-01T06:00:00Z" and parked[0]["from"] == "implementing"
    assert "retry_after 2026-01-01T06:00:00Z" in capsys.readouterr().err
    still = run_l4([green_step()], **TWO | {"roles": {"implementer": ["impl"]}})  # the clock has not moved
    assert still.code == ExitCode.WAITING_CAPACITY and still.adapter.requests == []
    fake_clock.advance(timedelta(hours=7))
    again = run_l4([green_step()], **TWO | {"roles": {"implementer": ["impl"]}})
    assert again.code == 0 and "capacity_restored" in again.triggers()
    assert again.outcome["units"][0]["phase_after"] == "implemented"
    assert again.outcome["units"][0].get("retry_after") is None


def test_plan_says_implement_only_once_retry_after_has_passed(run_l4, fake_clock, capsys):
    cfg = TWO | {"roles": {"implementer": ["impl"]}}
    run = run_l4([red_step(), limited()], **cfg)
    assert run.code == ExitCode.WAITING_CAPACITY
    capsys.readouterr()
    # RESETS is in the past of the machine's clock, so the planner (which has no injected clock) already sees it passed
    assert main(["plan", "--json", "--repo", str(run.tdd.repo)], environ=run.tdd.environ) == 0
    (entry,) = json.loads(capsys.readouterr().out)["units"]
    assert entry["unit"] == UNIT and entry["next_action"] == "implement"
    assert entry["reason"] == "capacity: retry_after 2026-01-01T06:00:00Z passed"


def test_plan_says_none_while_retry_after_is_in_the_future(run_l4, fake_clock, capsys):
    soon = datetime.now(UTC) + timedelta(hours=1)  # the planner reads the machine clock, so this must be real time
    limit = LimitSignal("fake", None, "usage_limit", soon, "test", "You have hit your usage limit")
    run = run_l4([red_step(), Step(status="quota", limit=limit)], **TWO | {"roles": {"implementer": ["impl"]}})
    assert run.code == ExitCode.WAITING_CAPACITY
    capsys.readouterr()
    assert main(["plan", "--json", "--repo", str(run.tdd.repo)], environ=run.tdd.environ) == 0
    (entry,) = json.loads(capsys.readouterr().out)["units"]
    assert entry["unit"] == UNIT and entry["next_action"] == "none"


def test_a_hook_that_sees_a_limit_moves_the_implementer_through_the_shared_fall_back(run_l4, install_hooks):
    moved: list = []

    class Forge:
        push_config: tuple = ()

        def __init__(self, ctx) -> None:
            self.ctx = ctx

        def after_push(self, phase) -> None:
            if not moved:  # a bare limit: an audit writer's reply carries no RunResult
                limit = LimitSignal("fake", None, "usage_limit", RESETS + timedelta(days=400), "audit-writer", "limit")
                moved.append(self.ctx.shared["fall_back"](limit))

    install_hooks(forge=Forge)
    run = run_l4([red_step(), green_step()], **TWO)
    assert run.code == 0 and [m.profile_name for m in moved] == ["impl-b"]
    assert moved[0].fallback_from == "impl"
    # the switch is the orchestrator's: the outcome names the profile that took over
    assert run.outcome["units"][0]["profiles"] == {"implementer": "impl-b", "fallback_from": "impl"}
