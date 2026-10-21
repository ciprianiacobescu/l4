"""`l4 status` shows the last activity and the open run of a unit (L4-OPS-020, SCN-OPS-34 to SCN-OPS-36)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from l4.cli import redactor_for
from l4.context import AppContext
from l4.redact import Redactor
from l4.state.ledger import LedgerWriter
from l4.state.status import run_status

from .conftest import UNIT_REL

NOW = datetime(2026, 10, 16, 11, 22, tzinfo=UTC)
UNIT = "openspec:add-x"
OLD_RUN, OPEN_RUN = "r-20261016T0953Z-0474", "r-20261016T1101Z-1a2b"
LINK = "<forge>/owner/repo/actions/runs/123"


def started_at(base: Path, run_id: str, minutes: int, events=(), *, finish=False, **started) -> None:
    """`run.started` `minutes` ago (the writer's clock is set before `open`), then the events."""
    now = [NOW - timedelta(minutes=minutes)]
    writer = LedgerWriter.open(
        base / UNIT_REL, UNIT, run_id, redactor=Redactor({}), clock=lambda: now[0], **started
    )  # fmt: skip
    for ago_minutes, event_type, data in events:
        now[0] = NOW - timedelta(minutes=ago_minutes)
        writer.append(event_type, **data)
    if finish:
        writer.finish(0)


def status(unit_repo, capsys, *argv: str, github: bool = True) -> str:
    environ = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "cache")}
    if github:
        environ["GITHUB_SERVER_URL"] = "https://github.com"
    app = AppContext(
        repo=unit_repo.repo, config_path=None, log_format="human", verbosity=0, run_id="r-20261016T1122Z-0000",
        environ=environ, redactor=redactor_for(environ),
    )  # fmt: skip
    unit = argv[argv.index("--unit") + 1] if "--unit" in argv else None
    code = run_status(app, unit=unit, as_json="--json" in argv, rebuild=False, clock=lambda: NOW)
    assert code == 0
    return capsys.readouterr().out


def ledger_with_open_run(base: Path, **started) -> None:
    started_at(base, OLD_RUN, 90, [(80, "task.done", {"task": "1.1"})], finish=True)
    started_at(base, OPEN_RUN, 21, [(6, "task.red_ok", {"task": "2.1"})], command="run", **started)


def test_the_last_activity_and_the_open_run_with_its_link(unit_repo, trailers, capsys):  # SCN-OPS-34
    unit_repo.push_unit_branch(lambda repo: ledger_with_open_run(repo, ci_url=LINK), trailers)
    out = status(unit_repo, capsys)
    header, row = out.splitlines()[:2]
    assert header.split()[-3:] == ["VERDICT", "LAST", "SOURCE"] and "6m ago" in row
    block = status(unit_repo, capsys, "--unit", UNIT).splitlines()
    assert f"Last activity: 6m ago (task.red_ok, task 2.1, run {OPEN_RUN})" in block
    link = "https://github.com/owner/repo/actions/runs/123"
    assert f"Open run: {OPEN_RUN} started 21m ago, no end recorded: {link}" in block


def test_the_two_lines_follow_stopped_in_run(unit_repo, trailers, capsys):
    def halted(repo: Path) -> None:
        started_at(repo, OPEN_RUN, 21, [(6, "phase.changed", {"from": "implementing", "to": "halted"})], command="run")

    unit_repo.push_unit_branch(halted, trailers)
    lines = status(unit_repo, capsys, "--unit", UNIT).splitlines()
    at = lines.index(f"Stopped in run: {OPEN_RUN}")
    assert lines[at + 1].startswith("Last activity: 6m ago (phase.changed, run ") and lines[at + 2].startswith(
        "Open run:"
    )


def test_no_open_run_when_the_newest_run_ended(unit_repo, trailers, capsys):  # SCN-OPS-35
    def ended(repo: Path) -> None:
        started_at(repo, OPEN_RUN, 21, [(6, "task.red_ok", {"task": "2.1"})], finish=True, command="run")

    unit_repo.push_unit_branch(ended, trailers)
    block = status(unit_repo, capsys, "--unit", UNIT).splitlines()
    assert any(line.startswith("Last activity: ") for line in block) and not any(
        x.startswith("Open run:") for x in block
    )


def test_no_link_without_a_recorded_one(unit_repo, trailers, capsys):  # SCN-OPS-35
    unit_repo.push_unit_branch(lambda repo: ledger_with_open_run(repo), trailers)
    assert (
        f"Open run: {OPEN_RUN} started 21m ago, no end recorded"
        in status(unit_repo, capsys, "--unit", UNIT).splitlines()
    )


def test_a_sweep_run_with_no_end_is_not_an_open_run(unit_repo, capsys):  # SCN-OPS-35
    started_at(unit_repo.repo, OPEN_RUN, 21, [(6, "task.red_ok", {"task": "2.1"})], command="plan --sweep")
    block = status(unit_repo, capsys, "--unit", UNIT).splitlines()
    assert any(line.startswith("Last activity: ") for line in block) and not any(
        x.startswith("Open run:") for x in block
    )


def test_a_unit_with_no_ledger_has_a_dash_and_neither_line(unit_repo, capsys):  # SCN-OPS-35
    out = status(unit_repo, capsys, "--unit", UNIT)
    assert out.splitlines()[1].split()[-2] == "-"
    assert "Last activity:" not in out and "Open run:" not in out
    payload = json.loads(status(unit_repo, capsys, "--json"))
    (unit,) = payload["units"]
    assert unit["last_activity"] is None and unit["open_run"] is None


def test_json_has_both_keys_with_the_expanded_link(unit_repo, trailers, capsys):  # SCN-OPS-36 (--json)
    unit_repo.push_unit_branch(lambda repo: ledger_with_open_run(repo, ci_url=LINK), trailers)
    (unit,) = json.loads(status(unit_repo, capsys, "--json"))["units"]
    assert unit["last_activity"] == {
        "ts": "2026-10-16T11:16:00.000000Z",
        "type": "task.red_ok",
        "task": "2.1",
        "run_id": OPEN_RUN,
    }
    assert unit["open_run"] == {
        "run_id": OPEN_RUN, "started": "2026-10-16T11:01:00.000000Z",
        "ci_url": "https://github.com/owner/repo/actions/runs/123",
    }  # fmt: skip


def test_json_open_run_without_a_link_has_no_ci_url(unit_repo, trailers, capsys):  # SCN-OPS-36 (--json)
    unit_repo.push_unit_branch(lambda repo: ledger_with_open_run(repo), trailers)
    (unit,) = json.loads(status(unit_repo, capsys, "--json"))["units"]
    assert "ci_url" not in unit["open_run"] and unit["open_run"]["run_id"] == OPEN_RUN


def test_open_run_reads_job_timeout_s():  # run-continuation 7.2 (L4-IMP-073)
    from l4.state.ledger import LedgerEvent
    from l4.state.status import _activity

    def started(run_id: str, **data) -> LedgerEvent:
        return LedgerEvent(NOW, run_id, UNIT, 1, "run.started", {"command": "run", **data})

    _, run = _activity([started(OPEN_RUN, ci_url=LINK, job_timeout_s=10800)])
    assert run is not None and run.job_timeout_s == 10800
    _, run = _activity([started(OPEN_RUN, ci_url=LINK)])
    assert run is not None and run.job_timeout_s is None
    _, run = _activity([started(OPEN_RUN, job_timeout_s="soon")])  # a value that is no number is no timeout
    assert run is not None and run.job_timeout_s is None
    _, run = _activity([started(OPEN_RUN, job_timeout_s=True)])
    assert run is not None and run.job_timeout_s is None
