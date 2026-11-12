"""A move never takes a spent profile, moves on from a used one, and a later run continues it (L4-IMP-094;
SCN-IMP-500..507), at loop level: the profiles `impl`, `impl-b` and `impl-c` stand for the chain's three tiers."""

import json
from dataclasses import replace

import pytest

from l4.implementer.loop import EscalationRequest, run_task, seed_attempts, spent_constraint, used_constraint
from l4.implementer.workbench import Workbench

from .conftest import RUN_ID
from .test_escalation import BAD, TWO, Hook, agents
from .test_loop import TASK, THREE, fail

CHAIN = ["impl", "impl-b", "impl-c"]
SPENT = "spent: 3 failed attempts of red of task 1.1 (implementer.max_task_attempts 3)"
USED = "used its share: 2 failed attempts of red of task 1.1 (implementer.escalate_after 2)"
LIMIT = 3
SHARE = 2


class SelectingHook:
    """A fake `escalate` that behaves like `Orchestrator._escalation_profile`: it walks after `request.profile` in two
    passes. Pass 1 skips a cooling profile and one that `used_constraint` refuses (a profile that failed the phase
    `escalate_after` times or more); pass 2, only when pass 1 takes nothing and such a profile is in the way, skips a
    cooling profile and one that `spent_constraint` refuses. It answers the next profile's workbench, or a reason that
    names every profile it skipped. It records every request and every pass (`ChainHook` moves blindly: do not reuse
    it)."""

    def __init__(self, chain: list[str] = CHAIN, cooling: tuple[str, ...] = ()) -> None:
        self.chain, self.cooling = chain, cooling
        self.requests: list[EscalationRequest] = []
        self.passes: list[int] = []

    def walk(self, request: EscalationRequest, veto) -> "tuple[str | None, list[str]]":
        skipped: list[str] = []
        for name in self.chain[self.chain.index(request.profile) + 1 :]:
            if name in self.cooling:
                skipped.append(f"profile {name} is cooling until tomorrow")
            elif (why := veto(name, None)) is not None:
                skipped.append(f"profile {name}: {why}")
            else:
                return name, skipped
        return None, skipped

    def __call__(self, wb: Workbench, request: EscalationRequest) -> "Workbench | str":
        self.requests.append(request)
        self.passes.append(1)
        name, skipped = self.walk(request, used_constraint(request, SHARE, LIMIT))
        later_used = {p for p, _ in request.used} & set(self.chain[self.chain.index(request.profile) + 1 :])
        if name is None and later_used:
            self.passes.append(2)
            name, skipped = self.walk(request, spent_constraint(request, LIMIT))
        if name is None:
            return "no usable profile after " + request.profile + ": " + "; ".join(skipped)
        return replace(wb, selected=replace(wb.selected, profile_name=name))


def move(bench, phase: str = "red", **more: object) -> None:
    """An earlier run's move, as the ledger holds it."""
    bench.writer.append(
        "implementer.escalated", task="1.1", phase=phase, **{"from": "impl-b"}, to="impl-c", failures=2, attempt=3,
        **more,
    )  # fmt: skip


def seed_run_b(bench) -> None:
    """The window of SCN-IMP-500: impl-b failed red twice and the step moved to impl-c."""
    fail(bench, "red", 1, profile="impl-b", reason="tests pass before any implementation")
    fail(bench, "red", 2, profile="impl-b", reason="timeout")
    move(bench)


def reds(n: int) -> list:
    return [BAD] * n


def moves(bench) -> list[tuple[str, str]]:
    return [(e["from"], e["to"]) for e in bench.events("implementer.escalated")]


def order(bench, first: str, then: str, *, last: bool = False) -> bool:
    """Does the (last, if `last`) record of type `first` come before the first record of type `then`?"""
    lines = (bench.wb.ref.path / ".l4" / "ledger" / f"{RUN_ID}.jsonl").read_text().splitlines()
    types = [json.loads(line)["type"] for line in lines]
    at = len(types) - 1 - types[::-1].index(first) if last else types.index(first)
    return at < types.index(then)


# ---- seed_attempts: the newest move of each phase in the window


def test_seed_attempts_reads_the_newest_move_of_each_phase_in_the_window(make_bench):
    bench = make_bench([], **THREE)
    w = bench.writer
    w.append("implementer.escalated", task="1.1", phase="red", **{"from": "impl"}, to="impl-b", failures=2, attempt=3)
    w.append("implementer.escalated", task="1.1", phase="red", **{"from": "impl-b"}, to="impl-c", failures=2, attempt=5)
    w.append("implementer.escalated", task="1.2", phase="red", **{"from": "impl-c"}, to="x", failures=2, attempt=3)
    w.append("implementer.escalated", task="1.1", phase="green", **{"from": "impl"}, to="impl-b", fix_unit="fix-1")
    w.append("implementer.escalated", task="1.1", phase="green", **{"from": ""}, to="impl-b", failures=2, attempt=3)
    seeded = seed_attempts(bench.wb, TASK)
    assert seeded.escalated_from == {"red": "impl-b"}  # another task, another fix unit, an empty `from`: not read


def test_seed_attempts_does_not_read_a_move_before_a_reset(make_bench):
    bench = make_bench([], **THREE)
    seed_run_b(bench)
    bench.writer.append("unit.retried", reason="again")
    assert seed_attempts(bench.wb, TASK).escalated_from == {}
    move(bench, phase="single")
    assert seed_attempts(bench.wb, TASK).escalated_from == {"single": "impl-b"}


# ---- SCN-IMP-500: a later run continues the move of an earlier one


def test_a_later_run_continues_the_move_of_an_earlier_one(make_bench):
    """SCN-IMP-500: the run-B replay."""
    bench = make_bench(reds(3), **THREE)
    seed_run_b(bench)
    hook = SelectingHook()
    outcome = run_task(bench.wb, TASK, escalate=hook)
    [first] = hook.requests
    assert (first.profile, first.attempt) == ("impl-b", 3)
    [moved] = bench.events("implementer.escalated")[-1:]
    assert {k: moved[k] for k in ("task", "phase", "from", "to", "failures", "attempt")} == {
        "task": "1.1", "phase": "red", "from": "impl-b", "to": "impl-c", "failures": 2, "attempt": 3,
    }  # fmt: skip
    assert len(bench.events("implementer.escalated")) == 2  # the earlier run's and this run's
    assert agents(bench) == [("red", "impl-c", 3), ("red", "impl-c", 4), ("red", "impl-c", 5)]
    assert outcome.status == "halt"
    assert outcome.reason.startswith(
        "task 1.1: max_task_attempts (3) reached in red on impl-b (2), impl-c (3); last failure: "
    )
    [tripped] = bench.events("breaker.tripped")
    assert tripped["profiles"] == [{"profile": "impl-b", "failures": 2}, {"profile": "impl-c", "failures": 3}]
    assert order(bench, "implementer.escalated", "step.started", last=True)


def test_the_move_is_asked_from_the_profile_the_earlier_run_moved_from(make_bench):
    bench = make_bench(reds(3), **THREE)
    seed_run_b(bench)
    seen: list[str] = []

    class Peek(SelectingHook):
        def __call__(self, wb, request):
            answer = super().__call__(wb, request)
            seen.append(request.profile)
            return answer

    run_task(bench.wb, TASK, escalate=Peek())
    assert seen == ["impl-b"]


# ---- SCN-IMP-501: a move skips a profile that used its share while a later one is usable


def test_a_move_skips_a_used_profile_when_a_later_one_is_usable(make_bench):
    """SCN-IMP-501: impl-b failed twice and its move was refused; impl fails 3 and 4; one move, to impl-c."""
    bench = make_bench(reds(5), **THREE)
    fail(bench, "red", 1, profile="impl-b")
    fail(bench, "red", 2, profile="impl-b")
    bench.writer.append(
        "implementer.escalation_skipped", task="1.1", phase="red", **{"from": "impl-b"}, failures=2, reason="cooling"
    )
    hook = SelectingHook()
    run_task(bench.wb, TASK, escalate=hook)
    assert [(r.profile, r.attempt) for r in hook.requests] == [("impl", 5)]
    assert hook.requests[0].used == (("impl-b", 2), ("impl", 2)) and hook.passes == [1]
    [moved] = bench.events("implementer.escalated")
    assert (moved["from"], moved["to"], moved["failures"], moved["attempt"]) == ("impl", "impl-c", 2, 5)
    assert agents(bench)[:3] == [("red", "impl", 3), ("red", "impl", 4), ("red", "impl-c", 5)]


def test_a_used_profile_still_takes_the_step_when_nothing_after_it_can(make_bench):
    """Chain [impl, impl-b, impl-c], impl-c cooling, impl-b at `escalate_after`: pass 2 gives impl-b its last attempt
    (D1: a profile is held to `escalate_after` only when a later profile can take over)."""
    bench = make_bench(reds(5), **THREE)
    fail(bench, "red", 1, profile="impl-b")
    fail(bench, "red", 2, profile="impl-b")
    hook = SelectingHook(cooling=("impl-c",))
    outcome = run_task(bench.wb, TASK, escalate=hook)
    assert [(r.profile, r.attempt) for r in hook.requests] == [("impl", 5), ("impl-b", 5)]
    assert hook.passes == [1, 2, 1]  # impl: pass 1 gave nothing, pass 2 gave impl-b; impl-b: nothing is used after it
    assert moves(bench) == [("impl", "impl-b")]
    assert [e["from"] for e in bench.events("implementer.escalation_skipped")] == ["impl-b"]
    assert agents(bench)[2] == ("red", "impl-b", 5)
    assert "reached in red on impl-b (3), impl (2); no later profile can take it (" in outcome.reason


def test_the_used_text_names_the_phase_the_task_and_the_key(make_bench):
    request = EscalationRequest("4.1", "green", "impl", (), 7, (("impl-b", 5),), (("impl-b", 5), ("impl-c", 3)))
    check = used_constraint(request, 3, 5)
    assert check("impl-c", None) == (  # type: ignore[arg-type]
        "used its share: 3 failed attempts of green of task 4.1 (implementer.escalate_after 3)"
    )
    assert check("impl-b", None) == (  # type: ignore[arg-type]
        "spent: 5 failed attempts of green of task 4.1 (implementer.max_task_attempts 5)"
    )  # a spent profile gets the spent text
    assert check("impl-d", None) is None  # type: ignore[arg-type]


# ---- SCN-IMP-502: a spent profile is not taken


def test_a_spent_profile_is_refused_by_the_selection(make_bench):
    """SCN-IMP-502: impl-b failed three times in the window (an earlier configuration allowed it)."""
    bench = make_bench(reds(5), **THREE)
    for n in (1, 2, 3):
        fail(bench, "red", n, profile="impl-b")
    hook = SelectingHook()
    run_task(bench.wb, TASK, escalate=hook)
    [request] = hook.requests
    assert request.profile == "impl" and request.spent == (("impl-b", 3),)
    assert spent_constraint(request, LIMIT)("impl-b", None) == SPENT  # type: ignore[arg-type]
    assert spent_constraint(request, LIMIT)("impl-c", None) is None  # type: ignore[arg-type]
    assert moves(bench) == [("impl", "impl-c")]


def test_the_spent_text_names_the_phase_and_the_task():
    request = EscalationRequest("4.1", "green", "impl", (), 7, (("impl-b", 5),))
    assert spent_constraint(request, 5)("impl-b", None) == (  # type: ignore[arg-type]
        "spent: 5 failed attempts of green of task 4.1 (implementer.max_task_attempts 5)"
    )


# ---- SCN-IMP-503: every later profile spent


def test_every_later_profile_spent_gives_one_refusal_and_a_halt_that_says_why(make_bench):
    """SCN-IMP-503."""
    bench = make_bench(reds(3), **THREE)
    for n in (1, 2, 3):
        fail(bench, "red", n, profile="impl-b")
    for n in (4, 5, 6):
        fail(bench, "red", n, profile="impl-c")
    hook = SelectingHook()
    outcome = run_task(bench.wb, TASK, escalate=hook)
    assert [(r.profile, r.attempt) for r in hook.requests] == [("impl", 9)]
    [skipped] = bench.events("implementer.escalation_skipped")
    assert skipped["from"] == "impl" and skipped["failures"] == 2 and "on" not in skipped
    assert "impl-b" in skipped["reason"] and "impl-c" in skipped["reason"] and SPENT in skipped["reason"]
    assert bench.events("implementer.escalated") == []
    assert outcome.status == "halt" and outcome.reason.startswith(
        "task 1.1: max_task_attempts (3) reached in red on impl-b (3), impl-c (3), impl (3); "
        "no later profile can take it ("
    )
    assert outcome.reason.index("no later profile can take it") < outcome.reason.index("; last failure: ")


def test_the_nearest_attempt_comes_before_a_refused_move_in_the_halt(make_bench):
    """L4-IMP-100 D6: `_halt` cuts the reason at 300 characters and a refused move's reasons can be long, so the
    nearest attempt comes right after the phase. The near pass is seeded on this run's ledger: only the order is
    tested."""
    bench = make_bench(reds(3), **THREE)
    for n in (1, 2, 3):
        fail(bench, "red", n, profile="impl-b", **({"near_pass": True} if n == 2 else {}))
    for n in (4, 5, 6):
        fail(bench, "red", n, profile="impl-c")
    outcome = run_task(bench.wb, TASK, escalate=SelectingHook())
    assert outcome.status == "halt" and outcome.reason.startswith(
        "task 1.1: max_task_attempts (3) reached in red on impl-b (3), impl-c (3), impl (3); nearest: attempt 2 "
        "(impl-b) passed every test and failed only its lint or type gates; no later profile can take it ("
    )
    assert outcome.reason.index("; no later profile") < outcome.reason.index("; last failure: ")


# ---- SCN-IMP-504: a cooling target is skipped, and the run starts on its own profile


def test_a_cooling_target_gives_way_and_the_step_starts_on_the_runs_profile(make_bench):
    """SCN-IMP-504."""
    bench = make_bench(reds(5), **THREE)
    seed_run_b(bench)
    hook = SelectingHook(cooling=("impl-c",))
    outcome = run_task(bench.wb, TASK, escalate=hook)
    skipped = bench.events("implementer.escalation_skipped")[0]
    assert (skipped["from"], skipped["on"], skipped["failures"]) == ("impl-b", "impl", 2)
    assert order(bench, "implementer.escalation_skipped", "step.started")
    assert agents(bench) == [
        ("red", "impl", 3), ("red", "impl", 4), ("red", "impl-b", 5),
    ]  # fmt: skip
    assert moves(bench)[-1:] == [("impl", "impl-b")]
    refusals = bench.events("implementer.escalation_skipped")
    assert len(refusals) == 2 and "on" not in refusals[1] and refusals[1]["from"] == "impl-b"
    assert outcome.status == "halt" and "reached in red on impl-b (3), impl (2); no later profile can take it (" in (
        outcome.reason
    )
    assert "; last failure: " in outcome.reason


# ---- the bound


def test_every_profile_seeded_with_two_failures_asks_at_most_the_chains_length(make_bench):
    bench = make_bench(reds(6), **THREE)
    for n, profile in enumerate(CHAIN * 2, 1):
        fail(bench, "red", n, profile=profile)
    hook = SelectingHook()
    run_task(bench.wb, TASK, escalate=hook)
    assert [r.profile for r in hook.requests] == ["impl", "impl-b"]
    assert agents(bench) == [("red", "impl-c", 7)]


def test_a_hook_that_answers_the_same_profile_ends_the_loop_after_one_request(make_bench):
    bench = make_bench(reds(6), **THREE)
    for n, profile in enumerate(["impl", "impl"], 1):
        fail(bench, "red", n, profile=profile)

    class Same:
        requests: list = []

        def __call__(self, wb, request):
            self.requests.append(request)
            return wb

    hook = Same()
    hook.requests = []
    run_task(bench.wb, TASK, escalate=hook)
    assert len(hook.requests) == 1 and agents(bench) == [("red", "impl", 3)]


# ---- SCN-IMP-505: one run, nothing in the window


def test_one_run_with_an_empty_window_is_unchanged(make_bench):
    """SCN-IMP-505: reds fail 2, 2 and 3 times."""
    bench = make_bench(reds(7), **THREE)
    hook = SelectingHook()
    outcome = run_task(bench.wb, TASK, escalate=hook)
    assert [(r.profile, r.attempt) for r in hook.requests] == [("impl", 3), ("impl-b", 5)]
    assert outcome.reason.startswith(
        "task 1.1: max_task_attempts (3) reached in red on impl (2), impl-b (2), impl-c (3); last failure: "
    )
    assert "no later profile" not in outcome.reason


# ---- SCN-IMP-506: a retry starts the task on the run's profile


def test_a_retry_starts_the_task_on_the_runs_profile(make_bench):
    """SCN-IMP-506."""
    bench = make_bench(reds(7), **THREE)
    seed_run_b(bench)
    bench.writer.append("unit.retried", reason="again")
    hook = SelectingHook()
    run_task(bench.wb, TASK, escalate=hook)
    assert hook.requests == [] or hook.requests[0].attempt > 1
    assert agents(bench)[0] == ("red", "impl", 1)


# ---- no continuation


def test_no_continuation_when_the_move_started_from_the_runs_profile(make_bench):
    bench = make_bench(reds(6), **THREE)
    fail(bench, "red", 1, profile="impl")
    fail(bench, "red", 2, profile="impl")
    bench.writer.append("implementer.escalated", task="1.1", phase="red", **{"from": "impl"}, to="impl-b", failures=2)
    hook = SelectingHook()
    run_task(bench.wb, TASK, escalate=hook)
    assert [r.profile for r in hook.requests] == ["impl", "impl-b"]  # the seeded failures of impl: as before


def test_no_continuation_when_the_move_started_before_the_runs_profile(make_bench):
    """The run is on impl-b and the move was from impl: nothing is asked before the first attempt."""
    bench = make_bench(reds(6), **THREE)
    bench.wb.selected = _on(bench.wb, "impl-b")
    bench.writer.append("implementer.escalated", task="1.1", phase="red", **{"from": "impl"}, to="impl-b", failures=2)
    hook = SelectingHook()
    run_task(bench.wb, TASK, escalate=hook)
    assert hook.requests == [] or hook.requests[0].attempt > 1
    assert agents(bench)[0] == ("red", "impl-b", 1)


def _on(wb, profile: str):
    return replace(wb.selected, profile_name=profile)


def test_no_continuation_when_the_origin_is_not_in_the_chain(make_bench):
    bench = make_bench(reds(9), **THREE)
    fail(bench, "red", 1, profile="gone")
    fail(bench, "red", 2, profile="gone")
    bench.writer.append("implementer.escalated", task="1.1", phase="red", **{"from": "gone"}, to="impl-b", failures=2)
    hook = SelectingHook()
    run_task(bench.wb, TASK, escalate=hook)
    assert hook.requests == [] or hook.requests[0].attempt > 1


def test_no_continuation_without_escalation(make_bench):
    bench = make_bench(reds(6), **{**THREE, "implementer": {"escalate_after": 0, "max_task_attempts": 3}})
    seed_run_b(bench)
    hook = SelectingHook()
    run_task(bench.wb, TASK, escalate=hook)
    assert hook.requests == [] and agents(bench)[0] == ("red", "impl", 3)


# ---- SCN-IMP-507: the halt names why no later profile took the step


def test_the_halt_names_why_no_later_profile_took_the_step(make_bench):
    """SCN-IMP-507."""
    bench = make_bench(reds(3), **TWO)
    hook = Hook("impl-b is cooling")
    outcome = run_task(bench.wb, TASK, escalate=hook)
    assert outcome.status == "halt"
    assert outcome.reason.startswith(
        "task 1.1: max_task_attempts (3) reached in red; no later profile can take it (impl-b is cooling); "
        "last failure: "
    )
    assert len(hook.requests) == 1  # asked after attempt 2 only


def test_the_halt_clause_takes_the_newest_refusal(make_bench):
    bench = make_bench(reds(5), **{**TWO, "implementer": {"escalate_after": 2, "max_task_attempts": 5}})
    answers = iter(["first reason", "second reason", "third reason"])

    class Changing:
        def __call__(self, wb, request):
            return next(answers)

    outcome = run_task(bench.wb, TASK, escalate=Changing())
    assert "(third reason); last failure: " in outcome.reason and "first reason" not in outcome.reason


@pytest.mark.parametrize(
    "extra",
    [{"implementer": {"escalate_after": 0, "max_task_attempts": 3}}, {"roles": {"implementer": ["impl"]}}],
    ids=["escalation off", "one profile"],
)
def test_the_halt_keeps_todays_reason_without_a_move_to_refuse(make_bench, extra):
    bench = make_bench(reds(3), **{**TWO, **extra})
    outcome = run_task(bench.wb, TASK, escalate=Hook("nope"))
    assert "no later profile" not in outcome.reason
    assert outcome.reason.startswith("task 1.1: max_task_attempts (3) reached in red; last failure: ")


def test_no_hook_keeps_todays_reason(make_bench):
    bench = make_bench(reds(3), **TWO)
    outcome = run_task(bench.wb, TASK)
    assert outcome.reason.startswith("task 1.1: max_task_attempts (3) reached in red; last failure: ")
