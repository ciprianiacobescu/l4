"""run_task and the escalation hook (escalate-and-note 1.2, 1.3; SCN-IMP-176, 177, 179)."""

from dataclasses import replace

import pytest

from l4.agents.fake import Step
from l4.implementer.loop import EscalationRequest, run_task
from l4.implementer.workbench import Workbench
from l4.specs.base import Task

from .conftest import blocked_step, green_step, red_step, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
TWO = {"roles": {"implementer": ["impl", "impl-b"]}, "profiles": {"impl-b": {"adapter": "fake", "vendor": "otherco"}}}
BAD = Step(structured=result("red"))  # a failed red: "no tests added"
INVALID = Step(structured={"status": "ok"})


class Hook:
    """A fake `escalate`: the second profile's workbench, or a reason; it records every request."""

    def __init__(self, answer: "str | None" = None) -> None:
        self.answer = answer
        self.requests: list[EscalationRequest] = []

    def __call__(self, wb: Workbench, request: EscalationRequest) -> "Workbench | str":
        self.requests.append(request)
        if self.answer is not None:
            return self.answer
        return replace(wb, selected=replace(wb.selected, profile_name="impl-b"))


def agents(bench) -> list[tuple[str, str, int]]:
    return [(e["phase"], e["agent"], e["attempt"]) for e in bench.events("step.started")]


def test_two_failures_then_the_hook_then_attempt_three_on_the_second_workbench(make_bench):
    bench = make_bench([INVALID, BAD, red_step(), green_step()], **TWO)
    hook = Hook()
    outcome = run_task(bench.wb, TASK, escalate=hook)
    assert outcome.status == "done"
    [request] = hook.requests
    assert (request.task, request.phase, request.profile, request.attempt) == ("1.1", "red", "impl", 3)
    assert [p for p, _ in request.failures] == ["impl", "impl"] and all(r for _, r in request.failures)
    [moved] = bench.events("implementer.escalated")
    assert {k: moved[k] for k in ("task", "phase", "from", "to", "failures", "attempt")} == {
        "task": "1.1", "phase": "red", "from": "impl", "to": "impl-b", "failures": 2, "attempt": 3,
    }  # fmt: skip
    # the step keys 1.1/red/1..3 are distinct; the third and the green step run on the second profile
    assert agents(bench) == [
        ("red", "impl", 1), ("red", "impl", 2), ("red", "impl-b", 3), ("green", "impl-b", 1),
    ]  # fmt: skip


def test_a_committed_red_stays_and_retry_stays_across_the_move(make_bench):
    bench = make_bench([INVALID, BAD, red_step(), green_step()], **TWO)
    run_task(bench.wb, TASK, escalate=Hook())
    third = bench.adapter.requests[2].prompt
    assert "Your previous attempt was rejected" in third


@pytest.mark.parametrize(
    "extra",
    [
        {"roles": {"implementer": ["impl"]}},
        TWO | {"implementer": {"escalate_after": 0}},
        TWO | {"implementer": {"max_task_attempts": 2}},
    ],
    ids=["one profile", "escalate_after 0", "max_task_attempts 2"],
)
def test_no_hook_call_when_escalation_is_off_or_cannot_act(make_bench, extra):
    bench = make_bench([BAD, BAD, BAD], **extra)
    hook = Hook()
    outcome = run_task(bench.wb, TASK, escalate=hook)
    assert outcome.status == "halt" and hook.requests == []
    assert not bench.events("implementer.escalated") and not bench.events("implementer.escalation_skipped")
    [tripped] = bench.events("breaker.tripped")
    assert "profiles" not in tripped or len(tripped["profiles"]) == 1
    assert " on " not in outcome.reason.split("; last failure")[0]


def test_no_hook_means_today(make_bench):
    bench = make_bench([BAD, BAD, BAD], **TWO)
    assert run_task(bench.wb, TASK).status == "halt"
    assert len(bench.adapter.requests) == 3


def test_a_returned_reason_is_asked_again_after_the_next_failure(make_bench):
    bench = make_bench([BAD] * 4, implementer={"max_task_attempts": 4}, **TWO)
    hook = Hook("glm is cooling")
    outcome = run_task(bench.wb, TASK, escalate=hook)
    assert outcome.status == "halt"
    assert [r.attempt for r in hook.requests] == [3, 4]  # after failures 2 and 3, not after the 4th (the limit)
    skipped = bench.events("implementer.escalation_skipped")
    assert [(e["task"], e["phase"], e["from"], e["reason"]) for e in skipped] == [
        ("1.1", "red", "impl", "glm is cooling")
    ] * 2
    assert not bench.events("implementer.escalated")


def test_a_blocked_step_never_calls_the_hook(make_bench):
    bench = make_bench([blocked_step()], implementer={"escalate_after": 1}, **TWO)
    hook = Hook()
    assert run_task(bench.wb, TASK, escalate=hook).status == "blocked"
    assert hook.requests == []


def test_a_blocked_step_after_a_failure_calls_the_hook_once_only(make_bench):
    bench = make_bench([BAD, blocked_step()], implementer={"escalate_after": 1}, **TWO)
    hook = Hook("none")
    assert run_task(bench.wb, TASK, escalate=hook).status == "blocked"
    assert len(hook.requests) == 1


def test_green_counts_apart_and_a_move_in_green_keeps_the_committed_red(make_bench):
    bad_green = Step(structured=result("green"))
    bench = make_bench([red_step(), bad_green, bad_green, green_step()], **TWO)
    hook = Hook()
    assert run_task(bench.wb, TASK, escalate=hook).status == "done"
    [request] = hook.requests
    assert (request.phase, request.attempt) == ("green", 3)
    assert agents(bench)[-1] == ("green", "impl-b", 3)


def test_the_last_profile_gets_max_task_attempts_and_the_halt_names_the_profiles(make_bench):
    """SCN-IMP-177 at loop level: 2 failures on the first profile, 3 on the second."""
    bench = make_bench([BAD] * 5, **TWO)

    hook = Hook()
    outcome = run_task(bench.wb, TASK, escalate=hook)
    assert outcome.status == "halt"
    assert len(bench.adapter.requests) == 5
    [tripped] = bench.events("breaker.tripped")
    assert tripped["attempts"] == 5 and tripped["phase"] == "red"
    assert tripped["profiles"] == [{"profile": "impl", "failures": 2}, {"profile": "impl-b", "failures": 3}]
    assert outcome.reason.startswith(
        "task 1.1: max_task_attempts (3) reached in red on impl (2), impl-b (3); last failure: "
    )
    failed = bench.events("task.attempt_failed")
    assert [(e["profile"], e["attempt"]) for e in failed] == [
        ("impl", 1), ("impl", 2), ("impl-b", 3), ("impl-b", 4), ("impl-b", 5),
    ]  # fmt: skip


def test_one_profile_keeps_the_detail_of_today_and_records_its_profile(make_bench):
    bench = make_bench([BAD] * 3)
    outcome = run_task(bench.wb, TASK)
    assert outcome.reason.startswith("task 1.1: max_task_attempts (3) reached in red; last failure: ")
    [tripped] = bench.events("breaker.tripped")
    assert tripped["attempts"] == 3 and tripped["profiles"] == [{"profile": "impl", "failures": 3}]
    assert {e["profile"] for e in bench.events("task.attempt_failed")} == {"impl"}
