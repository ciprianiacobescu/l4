"""`l4 status --unit U --events` and `--verification`: the read-only commands behind `l4_unit_events` and
`l4_verification` (L4-MCP-003, SCN-MCP-06)."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from l4.cli import redactor_for
from l4.context import AppContext
from l4.exitcodes import L4Exit
from l4.redact import Redactor
from l4.state.ledger import LedgerWriter
from l4.state.status import run_status

from .conftest import UNIT_REL

NOW = datetime(2026, 10, 16, 11, 22, tzinfo=UTC)
UNIT = "openspec:add-x"
RUN = "r-20261016T1101Z-1a2b"


def ledger(base) -> None:
    clock = [NOW - timedelta(minutes=30)]
    writer = LedgerWriter.open(base / UNIT_REL, UNIT, RUN, redactor=redactor_for({}), clock=lambda: clock[0])
    for minutes, kind, data in (
        (25, "task.attempt_failed", {"task": "1.1", "reason": "tests red", "attempt": 1}),
        (20, "phase.changed", {"from": "implementing", "to": "halted"}),
        (10, "task.attempt_failed", {"task": "1.2", "reason": "gate: ruff", "attempt": 2}),
    ):
        clock[0] = NOW - timedelta(minutes=minutes)
        writer.append(kind, **data)
    writer.finish(0)


def run(unit_repo, capsys, **kw) -> str:
    environ = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "cache")}
    app = AppContext(
        repo=unit_repo.repo, config_path=None, log_format="human", verbosity=0, run_id="r-20261016T1122Z-0000",
        environ=environ, redactor=redactor_for(environ),
    )  # fmt: skip
    args = {"unit": UNIT, "as_json": False, "rebuild": False, "clock": lambda: NOW} | kw
    assert run_status(app, **args) == 0
    return capsys.readouterr().out


def pushed(unit_repo, trailers, extra=lambda repo: None):
    def change(repo):
        ledger(repo)
        extra(repo)

    unit_repo.push_unit_branch(change, trailers)


def test_events_json_lists_the_ledger_events_in_order(unit_repo, trailers, capsys):  # SCN-MCP-06
    pushed(unit_repo, trailers)
    payload = json.loads(run(unit_repo, capsys, events=True, as_json=True))
    assert payload["schema"] == "l4/events@1" and payload["unit"] == UNIT
    types = [e["type"] for e in payload["events"]]
    assert types == ["run.started", "task.attempt_failed", "phase.changed", "task.attempt_failed", "run.finished"]
    failed = payload["events"][1]
    assert failed["reason"] == "tests red" and failed["task"] == "1.1" and failed["run_id"] == RUN
    assert failed["seq"] == 2 and failed["ts"].startswith("2026-10-16T10:57")
    assert payload["total"] == 5 and payload["shown"] == 5


def test_type_filters_and_last_keeps_the_newest(unit_repo, trailers, capsys):  # SCN-MCP-06
    pushed(unit_repo, trailers)
    only = json.loads(run(unit_repo, capsys, events=True, as_json=True, event_type="task.attempt_failed"))
    assert [e["task"] for e in only["events"]] == ["1.1", "1.2"]
    last = json.loads(run(unit_repo, capsys, events=True, as_json=True, event_type="task.attempt_failed", last=1))
    assert [e["task"] for e in last["events"]] == ["1.2"]
    assert last["total"] == 2 and last["shown"] == 1


def test_events_text_is_one_line_per_event(unit_repo, trailers, capsys):
    pushed(unit_repo, trailers)
    out = run(unit_repo, capsys, events=True, event_type="task.attempt_failed")
    lines = out.strip().splitlines()
    assert len(lines) == 2 and "task.attempt_failed" in lines[0] and "tests red" in lines[0]


def test_events_come_from_the_working_tree_when_the_unit_has_no_branch(unit_repo, capsys):
    ledger(unit_repo.repo)
    payload = json.loads(run(unit_repo, capsys, events=True, as_json=True, last=2))
    assert [e["type"] for e in payload["events"]] == ["task.attempt_failed", "run.finished"]


def test_events_and_verification_need_a_unit_and_a_sane_count(unit_repo, capsys):
    for kw in ({"events": True}, {"verification": True}):
        with pytest.raises(L4Exit, match="--unit"):
            run(unit_repo, capsys, unit=None, **kw)
    with pytest.raises(L4Exit, match="--events"):
        run(unit_repo, capsys, event_type="x")
    with pytest.raises(L4Exit, match="--last"):
        run(unit_repo, capsys, events=True, last=0)
    with pytest.raises(L4Exit, match="one of"):
        run(unit_repo, capsys, events=True, verification=True)


def test_events_are_redacted(unit_repo, trailers, capsys):
    secret = "glpat-abcdefghijklmnopqrstuvwxyz0123456789"

    def leaky(repo):
        writer = LedgerWriter.open(repo / UNIT_REL, UNIT, RUN, redactor=Redactor({}))  # the writer saw no secret
        writer.append("task.attempt_failed", task="1.1", reason=f"token {secret} leaked")
        writer.finish(0)

    unit_repo.push_unit_branch(leaky, trailers)
    environ = {**unit_repo.environ, "GITLAB_TOKEN": secret}
    app = AppContext(
        repo=unit_repo.repo, config_path=None, log_format="human", verbosity=0, run_id="r-20261016T1122Z-0000",
        environ=environ, redactor=redactor_for(environ),
    )  # fmt: skip
    assert run_status(app, unit=UNIT, as_json=True, rebuild=False, events=True, clock=lambda: NOW) == 0
    out = capsys.readouterr().out
    assert "leaked" in out and secret not in out


def test_verification_prints_the_file_from_the_unit_branch(unit_repo, trailers, capsys):
    pushed(
        unit_repo,
        trailers,
        lambda repo: (repo / UNIT_REL / "verification.md").write_text("# Verification\n\nFAIL: x\n"),
    )
    assert run(unit_repo, capsys, verification=True) == "# Verification\n\nFAIL: x\n"


def test_verification_without_a_file_says_so(unit_repo, trailers, capsys):
    pushed(unit_repo, trailers)
    assert "no verification.md" in run(unit_repo, capsys, verification=True)


def test_verification_from_the_working_tree(unit_repo, capsys):
    (unit_repo.unit_dir / "verification.md").write_text("local evidence\n")
    assert run(unit_repo, capsys, verification=True) == "local evidence\n"
