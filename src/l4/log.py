"""Logging (L4-OBS-001/002): stdlib logging on stderr, plus a JSONL file of the same records and of every ledger event,
every line passed through the Redactor.

The file is `<out_dir>/logs/<run-id>.jsonl` (`.l4-out/logs`, the SPEC default). `enable_jsonl` starts it for the
commands that already write `.l4-out/outcome.json` (`with_outcome`): `init`, `upgrade`, `doctor` and `status` leave
nothing in the repository. It runs before any config is read, so a non-default `observability.log_dir` is not
honoured yet (M1: bootstrap-core 1.8, the full `EventLog`). The ledger writer logs each event on `l4.ledger` with the
event in `record.l4_event`: the console ignores those records, the file keeps them as
`{"stream": "event", "event": {...}}` next to the `{"stream": "log", ...}` lines.
"""

import json
import logging
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from l4.context import AppContext
from l4.redact import Redactor

LOG_DIRNAME = "logs"


class RedactingFormatter(logging.Formatter):
    """Formats `[l4] <role>: message` (or a JSON line) and redacts message and traceback alike."""

    def __init__(self, redactor: Redactor, *, as_json: bool) -> None:
        super().__init__()
        self._redactor = redactor
        self._json = as_json

    def format(self, record: logging.LogRecord) -> str:
        message = self._redactor.redact_text(record.getMessage())
        trace = self._redactor.redact_text(self.formatException(record.exc_info)) if record.exc_info else None
        if self._json:
            payload = {
                "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "logger": record.name,
                "msg": message,
            }
            if trace:
                payload["exc"] = trace
            return json.dumps(payload)
        role = record.name.removeprefix("l4.")
        line = f"[l4] {message}" if role == "l4" else f"[l4] {role}: {message}"
        return f"{line}\n{trace}" if trace else line


class JsonlHandler(logging.Handler):
    """One redacted JSON line per record. The file is created at the first record, so a command that logs nothing
    leaves nothing behind, and a symlinked output directory is never written through."""

    def __init__(self, path: Path, redactor: Redactor) -> None:
        super().__init__()
        self._path = path
        self._redactor = redactor
        self._stream: Any = None
        self._failed = False

    def _open(self) -> Any:
        directory = self._path.parent
        if self._path.parent.parent.is_symlink() or directory.is_symlink():
            raise OSError(f"{directory} is a symlink")
        directory.mkdir(parents=True, exist_ok=True)
        return self._path.open("a", encoding="utf-8", buffering=1)

    def emit(self, record: logging.LogRecord) -> None:
        if self._failed:
            return
        event = getattr(record, "l4_event", None)
        if event is not None:
            payload: dict[str, Any] = {"stream": "event", "event": event}
        else:
            payload = {
                "stream": "log",
                "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info:
                payload["exc"] = "".join(traceback.format_exception(*record.exc_info))
        try:
            if self._stream is None:
                self._stream = self._open()
            self._stream.write(json.dumps(self._redactor.redact_obj(payload), ensure_ascii=False) + "\n")
        except OSError as exc:
            self._failed = True  # say so once; a log file must never stop a run
            print(f"[l4] cannot write {self._path}: {type(exc).__name__}; the JSONL log is off", file=sys.stderr)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        super().close()


def level_for(verbosity: int) -> int:
    if verbosity >= 1:
        return logging.DEBUG
    return {0: logging.INFO, -1: logging.WARNING}.get(verbosity, logging.ERROR)


def configure_logging(app: AppContext) -> None:
    """(Re)configure the `l4` logger tree for this invocation; stream is stderr, stdout stays for data."""
    logger = logging.getLogger("l4")
    for old in list(logger.handlers):
        logger.removeHandler(old)
        old.close()  # the JSONL handler holds a file
    level = level_for(app.verbosity)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(RedactingFormatter(app.redactor, as_json=app.log_format == "json"))
    console.setLevel(level)
    console.addFilter(lambda record: not hasattr(record, "l4_event"))  # events belong in the file, not on the console
    logger.addHandler(console)
    logger.setLevel(min(level, logging.INFO))  # `-q` quiets the console, not the file `enable_jsonl` may start
    logger.propagate = False


def enable_jsonl(app: AppContext) -> None:
    """Also write every record, and every ledger event, to this run's JSONL file (once per `configure_logging`)."""
    logger = logging.getLogger("l4")
    if any(isinstance(handler, JsonlHandler) for handler in logger.handlers):
        return
    handler = JsonlHandler(app.out_dir / LOG_DIRNAME / f"{app.run_id}.jsonl", app.redactor)
    handler.setLevel(min(level_for(app.verbosity), logging.INFO))
    logger.addHandler(handler)
