"""Hand-written ledgers (event shapes read from a real run, tests/unit/eval/test_judge_cell_setup.py)."""

from typing import Any

_seq = {"n": 0}


def ev(type_: str, **fields: Any) -> dict[str, Any]:
    _seq["n"] += 1
    return {"ts": f"2026-10-07T00:00:{_seq['n'] % 60:02d}Z", "run_id": "r-1", "seq": _seq["n"], "type": type_, **fields}


def step(phase: str, attempt: int, status: str = "ok", task: str = "1.1") -> list[dict[str, Any]]:
    return [
        ev("step.started", task=task, phase=phase, attempt=attempt, agent="p"),
        ev("step.finished", task=task, phase=phase, attempt=attempt, status=status),
        ev("agent.finished", task=task, phase=phase, status="ok", exit_code=0, detail=None, model=None,
           input_tokens=100, output_tokens=10, permission_denials=0, denied_tools=[]),
    ]  # fmt: skip


def failed(phase: str, attempt: int, reason: str, task: str = "1.1") -> dict[str, Any]:
    return ev("task.attempt_failed", task=task, phase=phase, attempt=attempt, reason=reason, excerpt_lines=0)


def green_ledger(red_failures: int = 0, green_failures: int = 0) -> list[dict[str, Any]]:
    out = [ev("run.started"), ev("task.started", task="1.1", title="t")]
    for n in range(1, red_failures + 1):
        out += [*step("red", n, "failed"), failed("red", n, "the agent's result is invalid: x")]
    out += [*step("red", red_failures + 1), ev("task.red_ok", task="1.1", tests=["a"], frozen=[])]
    for n in range(1, green_failures + 1):
        out += [*step("green", n, "failed"), failed("green", n, "gate test failed")]
    out += [
        *step("green", green_failures + 1),
        ev("task.done", task="1.1", base="b", parents=[], notes="", suppressions=[]),
    ]
    out += [
        ev("phase.changed", **{"from": "implementing", "to": "implemented"}, trigger="all_leaves_done", exit_code=None)
    ]
    out += [ev("run.finished", exit_code=0)]
    return out
