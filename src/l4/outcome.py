"""`.l4-out/outcome.json` (L4-CLI-002) and the wrappers that guarantee it exists."""

import json
import logging
import os
import random
import re
import secrets
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from l4 import __version__
from l4.buildinfo import harness_commit
from l4.cancel import RunCancelled
from l4.context import AppContext
from l4.exitcodes import ExitCode, classify_exception
from l4.fsutil import seal_out_dir
from l4.log import enable_jsonl
from l4.redact import Redactor

OUTCOME_COMMANDS = ("run", "verify", "archive", "plan")
OUTCOME_FILENAME = "outcome.json"
SCHEMA_ID = "l4/outcome@1"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TaskCounts(_Model):
    done: int = 0
    total: int = 0


class UnitOutcome(_Model):
    unit: str
    phase_before: str
    phase_after: str
    tasks: TaskCounts = Field(default_factory=TaskCounts)
    open_questions: list[str] = Field(default_factory=list)
    verdict: str | None = None
    profiles: dict[str, str] = Field(default_factory=dict)
    cost_usd: float | None = None
    iteration: int = 0
    pr_url: str | None = None
    retry_after: str | None = None  # ISO time, set for waiting_capacity
    continuation: Literal["not_needed", "dispatched", "failed"] = "not_needed"
    exit_reason: str | None = None  # one line for the unit's exit when the code alone says too little (`ci map-exit`)


class Outcome(_Model):
    schema_id: Literal["l4/outcome@1"] = Field(SCHEMA_ID, alias="schema")
    run_id: str
    harness_version: str
    harness_commit: str | None = None  # set when running a vendored copy (`l4 init --vendor`)
    exit_code: ExitCode
    units: list[UnitOutcome] = Field(default_factory=list)
    # github-parity D4: what the forge answered to the continuation request of a run that left units at the soft
    # deadline. Not part of the model dump (the key is absent otherwise): `write_outcome` adds it when set.
    continuation: Literal["dispatched", "already_queued", "unsupported"] | None = Field(None, exclude=True)


@dataclass(frozen=True)
class CommandResult:
    """What a handler may return instead of a bare ExitCode, so `outcome.json` can list the units."""

    code: ExitCode | int  # a plain int only from `ci map-exit`, which passes a foreign code through
    units: Sequence[UnitOutcome] = ()
    actionable: Sequence[str] = ()  # unit ids with a next action (`plan`, `run --dry-run`); `L4_UNITS_ACTIONABLE`
    continuation: Literal["dispatched", "already_queued", "unsupported"] | None = None  # `run` only (L4-GHP-004)
    # `run` only: unit id -> why its run exited 14, for the plan that dispatched it (L4-YOLO-013)
    rejected: Mapping[str, str] = field(default_factory=dict)
    # `run` only: unit id -> (exit code, why) for a unit whose run ended before it started (no `run.started`), and the
    # units whose run did start: a plan records the first and clears it with the second (L4-YOLO-013)
    not_started: Mapping[str, tuple[int, str]] = field(default_factory=dict)
    began: Sequence[str] = ()


def new_run_id(now: datetime | None = None, rng: random.Random | None = None) -> str:
    """`r-YYYYMMDDTHHMMZ-xxxx`."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%MZ")
    suffix = f"{rng.getrandbits(16):04x}" if rng else secrets.token_hex(2)
    return f"r-{stamp}-{suffix}"


def write_outcome(outcome: Outcome, out_dir: Path, redactor: Redactor) -> Path:
    """Atomic (temp file + rename in the same directory) and redacted. Refuses a symlinked output directory."""
    if out_dir.is_symlink():
        raise OSError(f"{out_dir} is a symlink; refusing to write the outcome through it")
    seal_out_dir(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = redactor.redact_obj(outcome.model_dump(mode="json", by_alias=True))
    if outcome.continuation is not None:
        payload["continuation"] = outcome.continuation
    target = out_dir / OUTCOME_FILENAME
    fd, tmp_name = tempfile.mkstemp(dir=out_dir, prefix=".outcome-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return target


CI_ENV_FILENAME = "l4.env"
_UNSAFE = re.compile(r"[\x00-\x1f\x7f]")


def write_ci_outputs(result: CommandResult, out_dir: Path, environ: Mapping[str, str]) -> None:
    """Mirror the headline fields of the outcome for CI (L4-CLI-002): `.l4-out/l4.env` (a GitLab dotenv artifact) with
    `L4_EXIT`, `L4_UNITS_ACTIONABLE`, `L4_PHASES`, and, when `$GITHUB_OUTPUT` names a file, `exit_code`, `units`
    (a JSON list of the actionable unit ids), `phases` (a JSON object, unit to phase after the run) and
    `units_actionable` (their count) appended to it. `L4_PHASES` of the dotenv file is `unit=phase,...`.
    Control characters are stripped: a value must not be able to start another line in a CI output file."""
    compact = (",", ":")
    values = {
        "exit_code": str(int(result.code)),
        "units": json.dumps(list(result.actionable), separators=compact),
        "phases": json.dumps({u.unit: u.phase_after for u in result.units}, separators=compact),
        "units_actionable": str(len(result.actionable)),
    }
    clean = {key: _UNSAFE.sub("", value) for key, value in values.items()}
    phases = _UNSAFE.sub("", ",".join(f"{u.unit}={u.phase_after}" for u in result.units))
    dotenv = (f"L4_EXIT={clean['exit_code']}", f"L4_UNITS_ACTIONABLE={clean['units_actionable']}",
              f"L4_PHASES={phases}")  # fmt: skip
    seal_out_dir(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(out_dir / CI_ENV_FILENAME, "\n".join(dotenv) + "\n")
    target = environ.get("GITHUB_OUTPUT")
    if target:
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write("".join(f"{key}={value}\n" for key, value in clean.items()))


def _write_text_atomic(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".l4env-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def run_guarded(call: Callable[[], CommandResult]) -> CommandResult:
    """Run a handler call; any exception becomes its exit code and a redacted console message."""
    try:
        return call()
    except RunCancelled as cancelled:  # W-D2: the run was stopped; cleanup has already run
        logging.getLogger("l4.cli").error("run cancelled (signal %d); nothing more was pushed", cancelled.signum)
        return CommandResult(ExitCode.CANCELLED)
    except Exception as exc:
        code, message = classify_exception(exc)
        log = logging.getLogger("l4.cli")
        log.error(message)
        log.debug("traceback", exc_info=exc)
        return CommandResult(code)


def with_outcome(app: AppContext, call: Callable[[], CommandResult]) -> CommandResult:
    """`run_guarded` plus `.l4-out/outcome.json`, written even when the command ends in an error."""
    result = CommandResult(ExitCode.INTERNAL_ERROR)
    seal_out_dir(app.out_dir)  # before the JSONL log or any report is written there
    enable_jsonl(app)
    try:
        result = run_guarded(call)
    finally:
        outcome = Outcome(
            run_id=app.run_id,
            harness_version=__version__,
            harness_commit=harness_commit(),
            exit_code=result.code,
            units=list(result.units),
            continuation=result.continuation,
        )
        write_outcome(outcome, app.out_dir, app.redactor)
        try:
            write_ci_outputs(result, app.out_dir, app.environ)
        except OSError as exc:  # a CI output file that cannot be written must not hide the command's own result
            logging.getLogger("l4.cli").warning("cannot write the CI outputs: %s", type(exc).__name__)
    return result
