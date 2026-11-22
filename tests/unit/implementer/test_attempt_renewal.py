"""L4-IMP-104 (SCN-IMP-566..570): an answer that unfreezes a file for a task's green gives it a new window, once per
question. The grants are the real `unfreeze_for` ones in the first test; the others stand a FAKE `unfreeze_for` in
(`grants`) so that each rule is read on its own."""

import pytest

from l4 import deadline
from l4.agents.fake import Step
from l4.implementer import loop
from l4.implementer.loop import MAX_RENEWALS, run_task, seed_attempts
from l4.implementer.tdd import run_red
from l4.implementer.unfreeze import Grant, Unfreeze

from .conftest import red_step, result
from .test_escalation import TWO, Hook, agents
from .test_loop import TASK, fail

LAZY = Step(structured=result("green"))  # green that changes nothing: `red tests still failing`
TEST = "tests/test_discount.py"


def grant(question: str = "Q-001", reason: str = "human_answer", *paths: str, by: str = "human") -> Grant:
    return Grant(question, "d" * 64, paths or (TEST,), reason=reason, by=by)


def stand_in(monkeypatch, *grants: Grant) -> None:
    """FAKE `unfreeze_for`: the grants an answered question would give the task's green."""
    monkeypatch.setattr(loop, "unfreeze_for", lambda wb, task, manifest: Unfreeze(tuple(grants)))


def at_green(make_bench, script, **kw):
    """A bench whose red step is committed and whose run is resumed at green."""
    bench = make_bench([red_step(), *script], **kw)
    assert run_red(bench.wb, TASK, attempt=1).status == "ok"
    return bench


def renewed(bench) -> list[dict]:
    return bench.events("task.attempts_renewed")


def greens(bench) -> list[int]:
    return [a for phase, _, a in agents(bench) if phase == "green"]


# --- SCN-IMP-566, 567: one renewal per answer --------------------------------------------------------------------


@pytest.mark.parametrize("who", ["human_answer", "delegate_answer"])
def test_scn_imp_566_an_answer_gives_green_a_full_window(make_bench, monkeypatch, who):
    bench = at_green(make_bench, [LAZY, LAZY, LAZY, LAZY])
    fail(bench, "green", 1)
    fail(bench, "green", 2)
    stand_in(monkeypatch, grant("Q-001", who, by="delegate" if who == "delegate_answer" else "human"))
    outcome = run_task(bench.wb, TASK)
    [event] = renewed(bench)
    assert (event["task"], event["phase"], event["questions"], event["failed"]) == ("1.1", "green", ["Q-001"], 2)
    assert greens(bench) == [3, 4, 5]  # attempt numbers go on; three fresh failures are needed to halt
    assert outcome.status == "halt" and bench.events("breaker.tripped")[0]["reason"] == "max_task_attempts"
    types = [e["type"] for e in map(__import__("json").loads, (bench.wb.ledger.path).read_text().splitlines())]
    assert types.index("task.attempts_renewed") < types.index("step.started", types.index("task.red_ok"))


def test_an_agents_answer_renews_like_a_persons(make_bench, monkeypatch):
    bench = at_green(make_bench, [LAZY] * 3)
    fail(bench, "green", 1)
    stand_in(monkeypatch, grant("Q-001", "human_answer", by="agent"))
    run_task(bench.wb, TASK)
    assert renewed(bench)[0]["failed"] == 1


def test_scn_imp_567_the_same_answer_renews_once(make_bench, monkeypatch):
    bench = at_green(make_bench, [LAZY, LAZY, LAZY, LAZY])
    fail(bench, "green", 1)
    fail(bench, "green", 2)
    stand_in(monkeypatch, grant())
    assert run_task(bench.wb, TASK).status == "halt"
    assert len(renewed(bench)) == 1 and greens(bench) == [3, 4, 5]
    # a later run resumes the task at green with the same answer: no second renewal, and the failures count
    bench.adapter._script.extend([LAZY, LAZY])
    assert run_task(bench.wb, TASK).status == "halt"
    assert len(renewed(bench)) == 1
    assert greens(bench) == [3, 4, 5]  # the window is full: no attempt is left


def test_scn_imp_567_one_attempt_is_left_after_two_failures_of_the_renewed_window(make_bench, monkeypatch):
    bench = at_green(make_bench, [LAZY, LAZY, LAZY])
    fail(bench, "green", 1)
    fail(bench, "green", 2)
    stand_in(monkeypatch, grant())
    bench.writer.append("task.attempts_renewed", task="1.1", phase="green", questions=["Q-001"], failed=2)
    fail(bench, "green", 3)
    fail(bench, "green", 4)
    run_task(bench.wb, TASK)
    assert len(renewed(bench)) == 1 and greens(bench) == [5]  # no second renewal, and one attempt left


def test_a_question_an_earlier_answer_unfrozen_names_is_credited_even_in_a_list(make_bench, monkeypatch):
    bench = at_green(make_bench, [LAZY] * 2)
    fail(bench, "green", 1)
    bench.writer.append("task.unfrozen", task="1.1", paths=[TEST], reason="human_answer", question="Q-001, Q-002")
    stand_in(monkeypatch, grant("Q-001"), grant("Q-002", by="agent"))
    run_task(bench.wb, TASK)
    assert renewed(bench) == []  # an answer that 0.4.59 already used renews nothing


@pytest.mark.parametrize("reason", [{"reason": "delegate_answer"}, {}])
def test_an_old_or_delegate_unfrozen_event_credits_its_question(make_bench, monkeypatch, reason):
    bench = at_green(make_bench, [LAZY] * 2)
    fail(bench, "green", 1)
    bench.writer.append("task.unfrozen", task="1.1", paths=[TEST], question="Q-001", **reason)
    stand_in(monkeypatch, grant("Q-001"))
    run_task(bench.wb, TASK)
    assert renewed(bench) == []


def test_a_named_by_task_event_credits_nothing(make_bench, monkeypatch):
    bench = at_green(make_bench, [LAZY] * 3)
    fail(bench, "green", 1)
    bench.writer.append("task.unfrozen", task="1.1", paths=[TEST], reason="named_by_task", question="Q-001")
    stand_in(monkeypatch, grant("Q-001"))
    run_task(bench.wb, TASK)
    assert len(renewed(bench)) == 1


def test_an_event_of_another_task_or_fix_unit_credits_nothing(make_bench, monkeypatch):
    bench = at_green(make_bench, [LAZY] * 3)
    fail(bench, "green", 1)
    bench.writer.append("task.unfrozen", task="1.2", paths=[TEST], reason="human_answer", question="Q-001")
    bench.writer.append(
        "task.attempts_renewed", task="1.1", phase="green", questions=["Q-001"], failed=1, fix_unit="f-1"
    )
    stand_in(monkeypatch, grant("Q-001"))
    run_task(bench.wb, TASK)
    assert len(renewed(bench)) == 2  # the earlier one of the other fix unit is the other, and this one is new


def test_a_red_commit_of_the_run_is_followed_by_the_renewal_check(make_bench, monkeypatch):
    """No resumed red: the red step commits in this run, and the answer that opens a frozen file is credited then."""
    bench = make_bench([red_step(), LAZY, LAZY, LAZY])
    stand_in(monkeypatch, grant("Q-001"))
    run_task(bench.wb, TASK)
    [event] = renewed(bench)
    assert (event["questions"], event["failed"]) == (["Q-001"], 0)
    types = [e["type"] for e in map(__import__("json").loads, bench.wb.ledger.path.read_text().splitlines())]
    assert (
        types.index("task.red_ok")
        < types.index("task.attempts_renewed")
        < types.index("step.started", types.index("task.red_ok"))
    )
    assert greens(bench) == [1, 2, 3]  # a window of its own: the attempt numbers start at 1


# --- SCN-IMP-568: what renews nothing ----------------------------------------------------------------------------


def test_scn_imp_568_a_grant_with_no_path_and_the_tasks_own_text_renew_nothing(make_bench, monkeypatch):
    bench = at_green(make_bench, [LAZY, LAZY, LAZY, LAZY])
    fail(bench, "green", 1)
    fail(bench, "green", 2)
    named = Grant(None, None, (TEST,), reason="named_by_task", source="plan:p@d")
    empty = Grant("Q-001", "d" * 64, (), reason="human_answer")
    stand_in(monkeypatch, named, empty)
    assert run_task(bench.wb, TASK).status == "halt"
    assert renewed(bench) == [] and greens(bench) == [3]  # the failures count as before: one more halts


def test_scn_imp_568_no_grant_no_renewal(make_bench, monkeypatch):
    bench = at_green(make_bench, [LAZY] * 2)
    fail(bench, "green", 1)
    stand_in(monkeypatch)
    run_task(bench.wb, TASK)
    assert renewed(bench) == []


def test_scn_imp_568_a_delegate_answer_with_the_switch_off_unfreezes_nothing_so_renews_nothing(
    make_bench, raw, monkeypatch
):
    """The real `unfreeze_for`: the delegate's accept with `delegate.unfreeze: false` gives no grant."""
    from .test_unfreeze_delegate import base_says, record_delegate

    base_says(monkeypatch, unfreeze=False)
    bench = at_green(make_bench, [LAZY, LAZY, LAZY, LAZY])
    fail(bench, "green", 1)
    fail(bench, "green", 2)
    record_delegate(bench, raw, unfreeze=False)
    run_task(bench.wb, TASK)
    assert renewed(bench) == []


def test_scn_imp_566_the_real_delegate_accept_renews_the_window(make_bench, raw, monkeypatch):
    from .test_unfreeze_delegate import base_says, record_delegate

    base_says(monkeypatch, unfreeze=True)
    bench = at_green(make_bench, [LAZY, LAZY, LAZY, LAZY])
    fail(bench, "green", 1)
    fail(bench, "green", 2)
    record_delegate(bench, raw, unfreeze=True)
    run_task(bench.wb, TASK)
    [event] = renewed(bench)
    assert (event["questions"], event["failed"]) == (["Q-001"], 2) and greens(bench) == [3, 4, 5]


# --- SCN-IMP-569: the bound ---------------------------------------------------------------------------------------


def two_renewals(bench) -> None:
    for n, question in enumerate(("Q-001", "Q-002"), start=1):
        fail(bench, "green", 2 * n - 1)
        fail(bench, "green", 2 * n)
        bench.writer.append("task.attempts_renewed", task="1.1", phase="green", questions=[question], failed=2)


def test_scn_imp_569_a_third_renewal_that_clears_a_failure_is_refused(make_bench, monkeypatch, caplog):
    bench = at_green(make_bench, [LAZY])
    two_renewals(bench)
    fail(bench, "green", 5)
    fail(bench, "green", 6)
    stand_in(monkeypatch, grant("Q-003"))
    with caplog.at_level("WARNING", logger="l4.implementer"):
        outcome = run_task(bench.wb, TASK)
    assert MAX_RENEWALS == 2 and len(renewed(bench)) == 2  # nothing recorded
    assert "no attempt renewal for Q-003: 2 renewals since the last retry, resume or restart" in caplog.text
    assert greens(bench) == [7] and outcome.status == "halt"  # the breaker trips as before


@pytest.mark.parametrize("reset", ["unit.retried", "unit.resumed", "unit.restarted"])
def test_scn_imp_569_a_reset_starts_the_count_again(make_bench, monkeypatch, reset):
    bench = at_green(make_bench, [LAZY, LAZY, LAZY, LAZY])
    two_renewals(bench)
    bench.writer.append(reset, reason="a person")
    fail(bench, "green", 5)
    stand_in(monkeypatch, grant("Q-003"))
    run_task(bench.wb, TASK)
    assert [e["questions"] for e in renewed(bench)] == [["Q-001"], ["Q-002"], ["Q-003"]]


def test_a_renewal_that_clears_no_failure_is_recorded_even_at_the_cap(make_bench, monkeypatch):
    bench = at_green(make_bench, [LAZY] * 3)
    two_renewals(bench)  # the cap is reached, but the window holds no failure
    stand_in(monkeypatch, grant("Q-003"))
    run_task(bench.wb, TASK)
    assert [e["failed"] for e in renewed(bench)] == [2, 2, 0]  # recorded, so that the answer cannot renew later


def test_a_renewal_with_no_failure_does_not_count_toward_the_cap(make_bench, monkeypatch):
    bench = at_green(make_bench, [LAZY] * 3)
    fail(bench, "green", 1)
    bench.writer.append("task.attempts_renewed", task="1.1", phase="green", questions=["Q-001"], failed=1)
    bench.writer.append("task.attempts_renewed", task="1.1", phase="green", questions=["Q-002"], failed=0)
    fail(bench, "green", 2)
    stand_in(monkeypatch, grant("Q-003"))
    run_task(bench.wb, TASK)
    assert [e["questions"] for e in renewed(bench)] == [["Q-001"], ["Q-002"], ["Q-003"]]  # two counted at most


def test_two_questions_answered_together_renew_once_with_both_ids(make_bench, monkeypatch):
    bench = at_green(make_bench, [LAZY] * 3)
    fail(bench, "green", 1)
    stand_in(monkeypatch, grant("Q-002", by="agent"), grant("Q-001"))
    run_task(bench.wb, TASK)
    [event] = renewed(bench)
    assert event["questions"] == ["Q-001", "Q-002"] and event["failed"] == 1


# --- seed_attempts ------------------------------------------------------------------------------------------------


def test_seed_attempts_clears_the_green_counts_and_the_move_at_a_renewal_and_keeps_the_attempt_number(make_bench):
    bench = make_bench([], **TWO)
    w = bench.writer
    fail(bench, "red", 1, reason="red stays")
    fail(bench, "green", 1, reason="g1")
    fail(bench, "green", 2, profile="impl-b", reason="g2")
    w.append(
        "implementer.escalated", task="1.1", phase="green", **{"from": "impl", "to": "impl-b"}, failures=1, attempt=2
    )
    w.append("task.attempts_renewed", task="1.1", phase="green", questions=["Q-001"], failed=2)
    fail(bench, "green", 3, reason="g3")
    seeded = seed_attempts(bench.wb, TASK)
    assert seeded.failures["green"] == {"impl": 1} and seeded.reasons["green"] == [("impl", "g3")]
    assert seeded.failures["red"] == {"impl": 1}  # red is not touched
    assert seeded.attempts == {"red": 1, "green": 3} and seeded.escalated_from == {}


def test_seed_attempts_keeps_the_attempt_number_when_the_renewal_is_the_last_event(make_bench):
    bench = make_bench([])
    fail(bench, "green", 1)
    fail(bench, "green", 2)
    bench.writer.append("task.attempts_renewed", task="1.1", phase="green", questions=["Q-001"], failed=2)
    seeded = seed_attempts(bench.wb, TASK)
    assert seeded.failures["green"] == {} and seeded.attempts["green"] == 2


def test_a_renewal_of_another_task_or_phase_or_fix_unit_clears_nothing(make_bench):
    bench = make_bench([])
    fail(bench, "green", 1)
    w = bench.writer
    w.append("task.attempts_renewed", task="1.2", phase="green", questions=["Q-009"], failed=1)
    w.append("task.attempts_renewed", task="1.1", phase="red", questions=["Q-009"], failed=1)
    w.append("task.attempts_renewed", task="1.1", phase="green", questions=["Q-009"], failed=1, fix_unit="f-1")
    assert seed_attempts(bench.wb, TASK).failures["green"] == {"impl": 1}


def test_a_ledger_without_the_event_seeds_as_before(make_bench):
    bench = make_bench([])
    fail(bench, "green", 1, reason="g1")
    fail(bench, "green", 2, reason="g2")
    seeded = seed_attempts(bench.wb, TASK)
    assert seeded.failures["green"] == {"impl": 2} and seeded.attempts["green"] == 2


def test_the_deadlines_stop_count_ignores_a_renewal(make_bench):
    bench = make_bench([])
    w = bench.writer
    w.append("deadline.reached", when="during", phase="green", task="1.1", attempt=1, first=True)
    before = (
        len(deadline.stops(loop._ledger_events(bench.wb), "1.1", "green")),
        deadline.last_is_stop(loop._ledger_events(bench.wb), "1.1", "green"),
    )
    w.append("task.attempts_renewed", task="1.1", phase="green", questions=["Q-001"], failed=0)
    events = loop._ledger_events(bench.wb)
    assert (len(deadline.stops(events, "1.1", "green")), deadline.last_is_stop(events, "1.1", "green")) == before


# --- 0.4.59 ledgers (SCN-IMP-570) --------------------------------------------------------------------------------


def test_scn_imp_570_an_answer_no_green_used_renews_on_the_next_run_and_one_a_green_used_does_not(
    make_bench, monkeypatch
):
    unused = at_green(make_bench, [LAZY, LAZY, LAZY, LAZY])
    fail(unused, "green", 1)
    fail(unused, "green", 2)
    stand_in(monkeypatch, grant("Q-001"))
    run_task(unused.wb, TASK)
    assert len(renewed(unused)) == 1


def test_scn_imp_570_an_answer_a_0_4_59_green_used_renews_nothing(make_bench, monkeypatch):
    used = at_green(make_bench, [LAZY, LAZY, LAZY])
    fail(used, "green", 1)
    used.writer.append("task.unfrozen", task="1.1", paths=[TEST], reason="human_answer", question="Q-001")
    fail(used, "green", 2)
    stand_in(monkeypatch, grant("Q-001"))
    assert run_task(used.wb, TASK).status == "halt"
    assert renewed(used) == [] and greens(used) == [3]  # one attempt left, as before


# --- profiles -----------------------------------------------------------------------------------------------------


def test_a_renewal_clears_both_profiles_counts_and_the_move_and_the_phase_starts_on_the_selected_profile(
    make_bench, monkeypatch
):
    bench = at_green(make_bench, [LAZY] * 5, implementer={"escalate_after": 2}, **TWO)
    fail(bench, "green", 1, profile="impl")
    fail(bench, "green", 2, profile="impl")
    bench.writer.append(
        "implementer.escalated", task="1.1", phase="green", **{"from": "impl", "to": "impl-b"}, failures=2, attempt=3
    )
    fail(bench, "green", 3, profile="impl-b")
    stand_in(monkeypatch, grant("Q-001"))
    hook = Hook()
    run_task(bench.wb, TASK, escalate=hook)
    [event] = renewed(bench)
    assert event["failed"] == 3
    # the cleared move is not asked again from the profile that failed: the first attempt is on the selected profile
    assert [a for a in agents(bench) if a[0] == "green"][0] == ("green", "impl", 4)
    assert hook.requests and hook.requests[0].profile == "impl" and hook.requests[0].attempt == 6
