"""HB-9, L4-VER-010: three consecutive internal verifier errors on a unit in `verifying` escalate it, counted from
the committed ledger, and no fourth verifier call is made."""

from types import SimpleNamespace

from l4.state.breaker import consecutive_verifier_errors

from ..implementer.conftest import green_step, red_step
from .conftest import UNIT


def ev(type_: str, **kw) -> SimpleNamespace:
    return SimpleNamespace(type=type_, data=kw)


def test_the_count_is_the_trailing_errors_since_a_verdict_or_a_phase_change():
    errors = [ev("verify.error")] * 2
    assert consecutive_verifier_errors(errors) == 2
    assert consecutive_verifier_errors([ev("verify.error"), ev("verify.verdict"), ev("verify.error")]) == 1
    assert consecutive_verifier_errors([*errors, ev("phase.changed", to="verifying")]) == 0
    assert consecutive_verifier_errors([ev("run.started"), *errors, ev("run.finished")]) == 2
    assert consecutive_verifier_errors([]) == 0


def test_three_errors_in_a_row_escalate_and_the_fourth_run_calls_no_verifier(run_l4, install_hooks):
    calls: list[int] = []

    def verify(ctx):
        calls.append(1)
        raise RuntimeError("the verifier crashed")

    install_hooks(verify=verify)
    first = run_l4([red_step(), green_step()])
    assert first.code == 1 and len(calls) == 1
    second = run_l4([])
    assert second.code == 1 and len(calls) == 2
    third = run_l4([])
    assert third.code == 13 and len(calls) == 3  # the third error is the last one: the unit is escalated
    assert third.triggers()[-1] == "verify_fail_exhausted"
    assert third.outcome["units"][0]["phase_after"] == "escalated"
    assert "3 consecutive internal verifier errors" in third.outcome["units"][0]["exit_reason"]
    fourth = run_l4([])
    assert fourth.code == 13 and len(calls) == 3  # no fourth call
    assert [e["type"] for e in third.ledger()].count("verify.error") == 3
    assert UNIT in third.outcome["units"][0]["unit"]


def test_a_verdict_between_errors_resets_the_count(run_l4, install_hooks):
    from l4.state.lifecycle import Trigger

    outcomes = iter(["raise", "raise", Trigger.VERIFY_NEEDS_HUMAN])
    seen: list[str] = []

    def verify(ctx):
        seen.append("call")
        what = next(outcomes)
        if what == "raise":
            raise RuntimeError("flaky")
        return what

    install_hooks(verify=verify)
    run_l4([red_step(), green_step()])
    run_l4([])
    third = run_l4([])
    assert third.code == 11 and third.outcome["units"][0]["phase_after"] == "awaiting_human"
    assert len(seen) == 3
