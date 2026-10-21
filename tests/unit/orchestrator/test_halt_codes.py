"""L4-OPS-005: every halt records a code (`reason`) and the person's text (`detail`) on its `phase.changed`, and the
fold keeps both (`halt_reason`, `halt_detail`). The log line is `halted: <detail>`."""

from l4 import orchestrator
from l4.implementer.tdd import BaselineFailed
from l4.state.fold import fold

from ..implementer.conftest import green_step, red_step
from .conftest import UNIT, UNIT_DIR, new_origin_main


def halt_event(run) -> dict:
    return [e for e in run.local_events("phase.changed") if e["to"] == "halted"][-1]


def test_the_task_attempt_limit_halts_with_its_code_and_its_text(run_l4, capsys):
    run = run_l4([red_step(), red_step()], implementer={"max_task_attempts": 1})
    assert run.code == 13
    event = halt_event(run)
    assert event["reason"] == "max_task_attempts"
    assert event["detail"].startswith("task 1.1: max_task_attempts (1) reached")
    assert f"{UNIT} halted: {event['detail']}" in capsys.readouterr().err
    assert run.outcome["units"][0]["exit_reason"] == f"halted: {event['detail']}"[:300]


def test_a_checkbox_the_harness_cannot_write_halts_as_unselectable_task(run_l4, tdd_repo, raw):
    new_origin_main(tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": "## 1. Pricing\n\n- [-] 1.1 Add `apply_discount`\n"})
    run = run_l4([red_step()])
    assert run.code == 13
    event = halt_event(run)
    assert event["reason"] == "unselectable_task" and "1.1" in event["detail"]
    assert run.local_events("breaker.tripped")[-1]["reason"] == "unselectable_task"


def test_a_baseline_that_fails_halts_as_baseline_failed(run_l4, monkeypatch):
    def failing(wb, task, *, escalate=None):  # the orchestrator passes its escalation hook (L4-IMP-017)
        raise BaselineFailed("the test gate cannot run at the base: report missing")

    monkeypatch.setattr(orchestrator, "run_task", failing)
    run = run_l4([red_step()])
    assert run.code == 13
    event = halt_event(run)
    assert (event["reason"], event["detail"]) == (
        "baseline_failed",
        "the test gate cannot run at the base: report missing",
    )


def test_a_planted_link_halts_the_unit_at_once_with_the_evidence(run_l4, tmp_path):
    """L4-SEC-021 (owner decision 1): like a secret in a push, a link a gate planted is not a failed attempt to retry"""
    from ..implementer.test_planted_links import nothing_in, swap_cmd

    outside = tmp_path / "host-dir"
    outside.mkdir()
    cond = "grep -q apply_discount src/pytdd/pricing.py && ! grep -q NotImplementedError src/pytdd/pricing.py"
    run = run_l4([red_step(), red_step(), red_step()], test={"command": swap_cmd(outside, cond)})
    assert run.code == 13
    event = halt_event(run)
    assert event["reason"] == "planted_link"
    assert event["detail"].startswith("task 1.1: a gate run put a symbolic link at src/pytdd")
    breaker = run.local_events("breaker.tripped")[-1]
    assert breaker["reason"] == "planted_link" and breaker["task"] == "1.1"
    assert breaker["links"][0]["path"] == "src/pytdd" and breaker["links"][0]["points_to"] == str(outside)
    assert len(run.adapter.requests) == 1  # no second attempt
    assert nothing_in(outside)
    assert run.outcome["units"][0]["exit_reason"].startswith("halted: task 1.1: a gate run put a symbolic link")


def test_the_fold_of_a_halted_unit_keeps_code_and_detail(run_l4):
    from l4.state.ledger import read_ledger

    run = run_l4([red_step(), red_step()], implementer={"max_task_attempts": 1})
    from l4.vcs.names import UnitNames

    names = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=run.tdd.cache, repo_key=run.tdd.key)
    state = fold(read_ledger(names.worktree / UNIT_DIR).events, UNIT)
    assert (state.phase, state.halt_reason) == ("halted", "max_task_attempts")
    assert state.halt_detail is not None and state.halt_detail.startswith("task 1.1: max_task_attempts")


def test_a_ci_not_fixed_escalation_keeps_the_failing_test_in_the_ledger_the_exit_reason_and_status(
    run_l4, install_hooks, tdd_repo, capsys
):
    """review M1: the verify hook's escalation goes through `_verify` and `_go`; nothing cuts the test id at 300."""
    from l4.ci.unfixed import CiHistory
    from l4.cli import main
    from l4.state.lifecycle import Trigger
    from l4.verifier.fixloop import ci_not_fixed_detail

    job = "ci.yml / lint, types and the whole of the tests on the supported platforms"
    history = CiHistory(
        job=job, head="a" * 40, again_head="b" * 40, again_changed=0, unfixed=True, put_back=(), notes=None,
        failed_step="Run the tests",
        failing="FAILED tests/test_cli.py::test_help - AssertionError | 1 failed, 9 passed",
    )  # fmt: skip
    why = ci_not_fixed_detail([history])
    assert len(why) > 300 and len(why) <= 600

    def verify(ctx):
        ctx.shared["escalation"] = ("ci_not_fixed", why)
        return Trigger.VERIFY_FAIL_EXHAUSTED

    install_hooks(verify=verify)
    run = run_l4([red_step(), green_step()])
    assert run.code == 13
    event = [e for e in run.local_events("phase.changed") if e["to"] == "escalated"][-1]
    assert event["reason"] == "ci_not_fixed" and event["detail"] == why
    assert "FAILED tests/test_cli.py::test_help" in run.outcome["units"][0]["exit_reason"]
    capsys.readouterr()
    again = run_l4([])  # the refusal of the next run names it too
    assert "FAILED tests/test_cli.py::test_help" in again.outcome["units"][0]["exit_reason"]
    capsys.readouterr()
    main(["status", "--unit", UNIT, "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ)
    out = capsys.readouterr().out
    assert "FAILED tests/test_cli.py::test_help" in out
