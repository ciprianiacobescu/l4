"""`l4 status` shows the cause and the next step (L4-OPS-006, SCN-OPS-11, design D6)."""

import json

from .test_status_branch import IMPLEMENTING, run_cli

DETAIL = "task 1.1: max_task_attempts (3) reached in red; the last test failure was a timeout in test_reorder"
HALTED = [
    *IMPLEMENTING,
    ("phase.changed", {"from": "implementing", "to": "halted", "reason": "max_task_attempts", "detail": DETAIL}),
]


def table_rows(out: str) -> tuple[list[str], list[str]]:
    header, row = out.splitlines()[:2]
    return header.split(), row.split()


def test_the_table_has_a_reason_column_after_phase(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *HALTED), trailers)
    code, out, _ = run_cli(unit_repo, capsys, "status")
    assert code == 0
    header, row = table_rows(out)
    assert header[:3] == ["UNIT", "PHASE", "REASON"]
    reason = out.splitlines()[1].split("halted", 1)[1].split("  ")[1].strip()
    assert reason == " ".join(DETAIL.split())[:59] + "…" and len(reason) == 60  # cut at 60 with an ellipsis
    assert reason.startswith("task 1.1: max_task_attempts (3) reached in red; ")  # SCN-OPS-11


def test_a_short_reason_is_not_cut(unit_repo, trailers, capsys):
    short = [*IMPLEMENTING, ("phase.changed", {"from": "implementing", "to": "escalated", "reason": "same_failure",
                                               "detail": "round 2 failed the same way as round 1"})]  # fmt: skip
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *short), trailers)
    _, out, _ = run_cli(unit_repo, capsys, "status")
    assert "round 2 failed the same way as round 1" in out and "…" not in out


def test_other_phases_show_a_dash(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    _, out, _ = run_cli(unit_repo, capsys, "status")
    assert out.splitlines()[1].split()[1:3] == ["implementing", "-"]


def test_waiting_capacity_shows_until(unit_repo, trailers, capsys):
    parked = [*IMPLEMENTING, ("phase.changed", {"from": "implementing", "to": "waiting_capacity",
                                                "retry_after": "2026-10-14T10:00:00+00:00"})]  # fmt: skip
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *parked), trailers)
    _, out, _ = run_cli(unit_repo, capsys, "status")
    assert "until 2026-10-14T10:00:00+00:00" in out


def test_unit_prints_the_block_after_the_row(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *HALTED), trailers)
    code, out, _ = run_cli(unit_repo, capsys, "status", "--unit", "openspec:add-x")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith("UNIT") and "halted" in lines[1]
    assert lines[-1] == "Next: l4 retry --unit openspec:add-x --reason TEXT"  # SCN-OPS-11
    assert "Phase: halted" in lines
    assert f"Cause: {DETAIL}" in lines  # whole, not cut
    assert "Stopped in run: r-20261003T1312Z-7f3a" in lines
    assert "Or: add the label l4:retry" in lines


def test_unit_block_for_a_unit_with_nothing_to_say(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    _, out, _ = run_cli(unit_repo, capsys, "status", "--unit", "openspec:add-x")
    lines = out.splitlines()
    assert "Phase: implementing" in lines and lines[-1] == "Next: nothing: the harness continues at the next run"
    assert not any(line.startswith(("Cause:", "Stopped in run:", "Or:")) for line in lines)


def test_json_carries_reason_and_next_beside_the_old_fields(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *HALTED), trailers)
    _, out, _ = run_cli(unit_repo, capsys, "status", "--json")
    (unit,) = json.loads(out)["units"]
    assert unit["reason"] == DETAIL and unit["next"] == "l4 retry --unit openspec:add-x --reason TEXT"
    assert unit["phase"] == "halted" and unit["halt_reason"] == "max_task_attempts" and "spec_tasks" in unit


def test_json_reason_is_null_when_there_is_none(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    _, out, _ = run_cli(unit_repo, capsys, "status", "--json")
    (unit,) = json.loads(out)["units"]
    assert unit["reason"] is None and unit["next"].startswith("nothing")


def test_plan_shows_the_recorded_detail(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *HALTED), trailers)
    _, out, _ = run_cli(unit_repo, capsys, "plan", "--json")
    (unit,) = json.loads(out)["units"]
    assert unit["reason"] == f"halted: {DETAIL}"


def halted_on(task: str, *, reason: str = "max_task_attempts", fix_unit: str | None = None):
    tripped = {"reason": "max_task_attempts", "task": task, **({"fix_unit": fix_unit} if fix_unit else {})}
    return [
        *IMPLEMENTING,
        ("breaker.tripped", tripped),
        ("phase.changed", {"from": "implementing", "to": "halted", "reason": reason, "detail": DETAIL}),
    ]


def test_unit_shows_the_retry_note_line_before_next(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *halted_on("1.1")), trailers)
    _, out, _ = run_cli(unit_repo, capsys, "status", "--unit", "openspec:add-x")
    lines = out.splitlines()
    assert lines[-2] == "Retry note: the --reason of l4 retry goes to the implementer of task 1.1"
    assert lines[-1].startswith("Next: ")


def test_unit_names_the_fix_unit_of_the_note(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(
        lambda repo: unit_repo.write_ledger(repo, *halted_on("1.1", fix_unit="add-x-fix-1")), trailers
    )
    _, out, _ = run_cli(unit_repo, capsys, "status", "--unit", "openspec:add-x")
    assert "Retry note: the --reason of l4 retry goes to the implementer of task 1.1 of add-x-fix-1" in out


def test_no_retry_note_line_for_a_stop_that_names_no_task(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *HALTED), trailers)
    _, out, _ = run_cli(unit_repo, capsys, "status", "--unit", "openspec:add-x")
    assert "Retry note" not in out


def test_json_carries_halt_task_and_halt_fix_unit(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(
        lambda repo: unit_repo.write_ledger(repo, *halted_on("1.1", fix_unit="add-x-fix-1")), trailers
    )
    _, out, _ = run_cli(unit_repo, capsys, "status", "--json")
    [unit] = json.loads(out)["units"]
    assert (unit["halt_task"], unit["halt_fix_unit"]) == ("1.1", "add-x-fix-1")
