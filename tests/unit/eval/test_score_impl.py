from l4.eval.score import score_implementer

from ._ledgers import ev, failed, green_ledger, step

EXPECTED = {"implementer": {"outcome": "pass"}, "judge": {"verdict": "PASS"}}


def test_red_and_green_ok_on_the_first_attempt_is_a_pass() -> None:
    score = score_implementer(green_ledger(), EXPECTED)
    assert score["outcome"] == "pass"
    assert score["attempts"] == {"red": 1, "green": 1}
    assert score["halted_at"] is None and score["blocked"] is False and score["breaker"] is None


def test_attempts_count_failures_plus_the_one_that_ended_the_phase() -> None:
    score = score_implementer(green_ledger(red_failures=2, green_failures=1), EXPECTED)
    assert score["outcome"] == "pass"
    assert score["attempts"] == {"red": 3, "green": 2}


def test_the_breaker_in_red_is_a_fail_with_the_phase_and_reason() -> None:
    events = [ev("task.started", task="1.1", title="t")]
    for n in (1, 2, 3):
        events += [*step("red", n, "failed"), failed("red", n, "x")]
    events.append(
        ev("breaker.tripped", reason="max_task_attempts", task="1.1", phase="red", attempts=3, last_failure="x")
    )
    score = score_implementer(events, EXPECTED)
    assert score["outcome"] == "fail"
    assert score["halted_at"] == "red" and score["breaker"] == "max_task_attempts"
    assert score["attempts"] == {"red": 3, "green": 0}


def test_the_breaker_in_green_keeps_the_red_that_passed() -> None:
    events = [
        ev("task.started", task="1.1", title="t"),
        *step("red", 1),
        ev("task.red_ok", task="1.1", tests=[], frozen=[]),
    ]
    for n in (1, 2, 3):
        events += [*step("green", n, "failed"), failed("green", n, "x")]
    events.append(
        ev("breaker.tripped", reason="max_task_attempts", task="1.1", phase="green", attempts=3, last_failure="x")
    )
    score = score_implementer(events, EXPECTED)
    assert score["outcome"] == "fail" and score["halted_at"] == "green"
    assert score["attempts"] == {"red": 1, "green": 3}


def test_a_blocked_result_is_a_fail_with_blocked_true() -> None:
    events = [
        ev("task.started", task="1.1", title="t"), *step("red", 1, "blocked"),
        ev("question.raised", id="Q-1", task="1.1", kind="ambiguous", title="which?"),
    ]  # fmt: skip
    score = score_implementer(events, EXPECTED)
    assert score["outcome"] == "fail" and score["blocked"] is True and score["halted_at"] is None


def test_a_verdict_other_than_pass_makes_the_cell_a_fail() -> None:
    events = [
        *green_ledger(),
        ev("verify.verdict", round=1, verdict="NEEDS_HUMAN", findings=2, criteria_passed=1, criteria_total=2),
    ]
    score = score_implementer(events, EXPECTED)
    assert score["outcome"] == "fail" and score["verdict"] == "NEEDS_HUMAN" and score["halted_at"] == "verify"
    ok = score_implementer(
        [
            *green_ledger(),
            ev("verify.verdict", round=1, verdict="PASS", findings=0, criteria_passed=2, criteria_total=2),
        ],
        EXPECTED,
    )
    assert ok["outcome"] == "pass" and ok["verdict"] == "PASS"


def test_no_events_is_a_fail_not_a_crash() -> None:
    score = score_implementer([], EXPECTED)
    assert score["outcome"] == "fail" and score["attempts"] == {"red": 0, "green": 0}


def test_an_already_satisfied_task_is_done_without_a_green() -> None:
    events = [
        ev("task.started", task="1.1", title="t"),
        *step("red", 1),
        ev("task.done", task="1.1", base="b", parents=[], notes="", suppressions=[]),
    ]
    score = score_implementer(events, EXPECTED)
    assert score["outcome"] == "pass" and score["attempts"] == {"red": 1, "green": 0}
