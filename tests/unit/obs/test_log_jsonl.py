import json
import logging
from pathlib import Path

import pytest

from l4.context import AppContext
from l4.log import configure_logging, enable_jsonl
from l4.redact import Redactor
from l4.state.ledger import LedgerWriter

RUN_ID = "r-20261004T1200Z-abcd"
SECRET = "hunter2-hunter2-token"


@pytest.fixture(autouse=True)
def clean_logger():
    logger = logging.getLogger("l4")
    before = (list(logger.handlers), logger.level, logger.propagate)
    yield logger
    for handler in list(logger.handlers):
        handler.close()
    logger.handlers[:] = before[0]
    logger.setLevel(before[1])
    logger.propagate = before[2]


def app(repo: Path, *, verbosity: int = 0, log_format: str = "human") -> AppContext:
    return AppContext(
        repo=repo, config_path=None, log_format=log_format, verbosity=verbosity, run_id=RUN_ID, environ={},
        redactor=Redactor({"L4_FORGE_TOKEN": SECRET}),
    )  # fmt: skip


def start(context: AppContext) -> None:
    configure_logging(context)
    enable_jsonl(context)


def lines(repo: Path) -> list[dict]:
    path = repo / ".l4-out" / "logs" / f"{RUN_ID}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_every_event_writes_one_console_and_one_jsonl_line(tmp_path, capsys):
    start(app(tmp_path))
    logging.getLogger("l4.run").info("unit started")
    err = capsys.readouterr().err
    assert err.strip() == "[l4] run: unit started"
    (line,) = lines(tmp_path)
    assert line["stream"] == "log" and line["logger"] == "l4.run" and line["msg"] == "unit started"
    assert line["level"] == "INFO" and line["ts"].endswith("+00:00")


def test_ledger_events_go_to_the_file_only(tmp_path, capsys):
    start(app(tmp_path))
    unit_dir = tmp_path / "unit"
    writer = LedgerWriter.open(unit_dir, "openspec:a", RUN_ID, redactor=Redactor({}))
    writer.append("question.raised", id="Q-001", kind="ambiguous")  # a payload key named `kind` must survive
    writer.finish(0)
    assert capsys.readouterr().err == ""  # the console does not repeat the ledger
    events = [entry["event"] for entry in lines(tmp_path) if entry["stream"] == "event"]
    assert [e["type"] for e in events] == ["run.started", "question.raised", "run.finished"]
    assert events[1]["kind"] == "ambiguous" and events[1]["unit"] == "openspec:a" and events[1]["seq"] == 2
    ledger_on_disk = [json.loads(x) for x in (unit_dir / ".l4/ledger" / f"{RUN_ID}.jsonl").read_text().splitlines()]
    assert events == ledger_on_disk  # the mirror is the ledger line itself


def test_secrets_are_redacted_in_messages_and_events(tmp_path):
    start(app(tmp_path))
    logging.getLogger("l4.run").warning("token is %s", SECRET)
    logging.getLogger("l4.run").error("failed", exc_info=_raise(f"boom {SECRET}"))
    writer = LedgerWriter.open(tmp_path / "u", "openspec:a", RUN_ID, redactor=Redactor({}))
    writer.append("agent.finished", detail=f"leaked {SECRET}")
    text = (tmp_path / ".l4-out" / "logs" / f"{RUN_ID}.jsonl").read_text()
    assert SECRET not in text and "[REDACTED:L4_FORGE_TOKEN]" in text
    assert any("exc" in entry for entry in lines(tmp_path))


def _raise(message: str):
    try:
        raise RuntimeError(message)
    except RuntimeError:
        import sys

        return sys.exc_info()


def test_quiet_silences_the_console_but_not_the_file(tmp_path, capsys):
    start(app(tmp_path, verbosity=-1))
    logging.getLogger("l4.run").info("progress")
    logging.getLogger("l4.run").warning("careful")
    assert capsys.readouterr().err.strip() == "[l4] run: careful"
    assert [entry["msg"] for entry in lines(tmp_path)] == ["progress", "careful"]


def test_debug_goes_to_both_only_when_asked(tmp_path, capsys):
    start(app(tmp_path))
    logging.getLogger("l4.run").debug("detail")
    assert capsys.readouterr().err == "" and not (tmp_path / ".l4-out").exists()
    start(app(tmp_path, verbosity=1))
    logging.getLogger("l4.run").debug("detail")
    assert "detail" in capsys.readouterr().err and lines(tmp_path)[0]["level"] == "DEBUG"


def test_nothing_is_created_until_something_is_logged(tmp_path):
    start(app(tmp_path))
    assert not (tmp_path / ".l4-out").exists()


def test_reconfiguring_does_not_duplicate_handlers(tmp_path, capsys):
    start(app(tmp_path))
    start(app(tmp_path))
    logging.getLogger("l4.run").info("once")
    assert capsys.readouterr().err.count("once") == 1 and len(lines(tmp_path)) == 1


def test_a_symlinked_log_directory_is_not_written_through(tmp_path, capsys):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    repo = tmp_path / "repo"
    (repo / ".l4-out").mkdir(parents=True)
    (repo / ".l4-out" / "logs").symlink_to(elsewhere)
    start(app(repo))
    logging.getLogger("l4.run").warning("first")
    logging.getLogger("l4.run").warning("second")
    err = capsys.readouterr().err
    assert list(elsewhere.iterdir()) == []
    assert err.count("the JSONL log is off") == 1 and "first" in err and "second" in err


def test_json_console_format_is_unchanged(tmp_path, capsys):
    start(app(tmp_path, log_format="json"))
    logging.getLogger("l4.run").info("hello")
    assert json.loads(capsys.readouterr().err)["msg"] == "hello"


def test_commands_that_write_no_outcome_leave_nothing_in_the_repository(tmp_path, capsys):
    configure_logging(app(tmp_path))  # what `init`, `upgrade`, `doctor` and `status` get
    logging.getLogger("l4.init").error("something failed")
    assert "something failed" in capsys.readouterr().err and not (tmp_path / ".l4-out").exists()


def test_enabling_twice_adds_one_handler_and_reconfiguring_drops_it(tmp_path):
    context = app(tmp_path)
    configure_logging(context)
    enable_jsonl(context)
    enable_jsonl(context)
    handlers = [h for h in logging.getLogger("l4").handlers if type(h).__name__ == "JsonlHandler"]
    assert len(handlers) == 1
    configure_logging(context)
    assert not [h for h in logging.getLogger("l4").handlers if type(h).__name__ == "JsonlHandler"]


def test_with_outcome_starts_the_log(tmp_path):
    from l4.exitcodes import ExitCode
    from l4.outcome import CommandResult, with_outcome

    context = app(tmp_path)
    configure_logging(context)

    def call() -> CommandResult:
        logging.getLogger("l4.run").info("working")
        return CommandResult(ExitCode.OK)

    with_outcome(context, call)
    assert [entry["msg"] for entry in lines(tmp_path)] == ["working"]
