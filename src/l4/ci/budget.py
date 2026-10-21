"""One reading of the CI job's budget (L4-IMP-076 to L4-IMP-079): the budget and where it came from, the job's own
timeout, the two texts about a set `ci.time_budget`, and the fix of a budget's source.

Doctor, `l4 run`, `l4 upgrade` and the deadline texts share it. It imports no orchestrator, doctor or init module
(doctor `--ci` has the L4-NFR-001 time bound), and `l4.deadline` stays a leaf."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..config.schema import duration_seconds
from ..deadline import FLOOR_S
from ..fsutil import UnsafeFile, read_regular_file, reject_symlinks
from .github import WORKFLOW_RELPATH

BudgetSource = Literal["ci.time_budget", "CI_JOB_TIMEOUT", "L4_JOB_TIMEOUT_MINUTES"]
WORKFLOW_SOURCE = f"{WORKFLOW_RELPATH} timeout-minutes"
_WORKFLOW_LIMIT = 1024 * 1024
_TIMEOUT_LINE = re.compile(r"^\s*timeout-minutes:\s*([0-9]+)\s*$", re.MULTILINE)


_ASCII_DIGITS = re.compile(r"[0-9]+")


def _ascii_int(value: str) -> int | None:
    """The integer of an all-ASCII-digit text; None otherwise (`'²'.isdigit()` is True and `int('²')` raises)."""
    return int(value) if _ASCII_DIGITS.fullmatch(value) else None


@dataclass(frozen=True)
class Budget:
    seconds: int
    source: BudgetSource


def job_budget(cfg: Any, environ: Mapping[str, str]) -> Budget | None:
    """The budget before the margin: a set `ci.time_budget`, else (for `auto`) GitLab's `CI_JOB_TIMEOUT` (seconds),
    else GitHub's `L4_JOB_TIMEOUT_MINUTES`; None when unknown."""
    configured = cfg.ci.time_budget
    if configured != "auto":
        return Budget(duration_seconds(configured), "ci.time_budget")
    raw = environ.get("CI_JOB_TIMEOUT", "")
    minutes = environ.get("L4_JOB_TIMEOUT_MINUTES", "")
    if (seconds := _ascii_int(raw)) is not None:
        return Budget(seconds, "CI_JOB_TIMEOUT")
    if (count := _ascii_int(minutes)) is not None:
        return Budget(count * 60, "L4_JOB_TIMEOUT_MINUTES")
    return None


def workflow_timeout_s(text: str) -> int | None:
    """The first `timeout-minutes: <integer>` line of a workflow text, in seconds."""
    match = _TIMEOUT_LINE.search(text)
    return int(match.group(1)) * 60 if match else None


def read_workflow(repo: Path) -> str | None:
    """The checked-out `.github/workflows/l4.yml`; None for no file, a link, a file over 1 MiB or any read error."""
    try:
        reject_symlinks(repo, *Path(WORKFLOW_RELPATH).parts)
        return read_regular_file(repo / WORKFLOW_RELPATH, limit=_WORKFLOW_LIMIT).decode("utf-8")
    except (UnsafeFile, OSError, UnicodeDecodeError):
        return None


def job_timeout(environ: Mapping[str, str], workflow_text: str | None) -> tuple[int, str] | None:
    """The job's own timeout and its source label: `CI_JOB_TIMEOUT`, else `L4_JOB_TIMEOUT_MINUTES`, else the workflow
    text's `timeout-minutes`; None when unknown."""
    raw = environ.get("CI_JOB_TIMEOUT", "")
    if (seconds := _ascii_int(raw)) is not None:
        return seconds, "CI_JOB_TIMEOUT"
    minutes = environ.get("L4_JOB_TIMEOUT_MINUTES", "")
    if (count := _ascii_int(minutes)) is not None:
        return count * 60, "L4_JOB_TIMEOUT_MINUTES"
    if workflow_text is not None and (from_text := workflow_timeout_s(workflow_text)) is not None:
        return from_text, WORKFLOW_SOURCE
    return None


def too_short(cfg: Any) -> str | None:
    """L4-IMP-076: the text when a set `ci.time_budget` minus the margin leaves less than one step; else None."""
    configured = cfg.ci.time_budget
    if configured == "auto":
        return None
    margin = cfg.ci.soft_deadline_margin
    usable = duration_seconds(configured) - duration_seconds(margin)
    if usable >= FLOOR_S:
        return None
    left = "leaves no time" if usable <= 0 else f"leaves {usable // 60} min"
    return (
        f"ci.time_budget {configured} minus soft_deadline_margin {margin} {left}, less than one step "
        f"({FLOOR_S // 60} min): set ci.time_budget: auto (the job timeout) or raise it"
    )


def shortens_job(cfg: Any, timeout: tuple[int, str] | None) -> str | None:
    """L4-IMP-077: the text when a set `ci.time_budget` is shorter than the job's timeout by more than the margin."""
    configured = cfg.ci.time_budget
    if configured == "auto" or timeout is None:
        return None
    seconds, source = timeout
    budget_s = duration_seconds(configured)
    margin_s = duration_seconds(cfg.ci.soft_deadline_margin)
    if seconds - budget_s <= margin_s:
        return None
    return (
        f"ci.time_budget {configured} is shorter than the job's timeout ({seconds // 60} min, {source}) by more "
        f"than soft_deadline_margin {cfg.ci.soft_deadline_margin}: the soft deadline comes at minute "
        f"{max(0, budget_s - margin_s) // 60}, not at minute {(seconds - margin_s) // 60}; "
        "set ci.time_budget: auto (the job timeout) unless the job must stop early"
    )


def raise_fix(source: BudgetSource | None) -> str:
    """L4-IMP-078: the fix of the budget's real source."""
    if source == "ci.time_budget":
        return "raise ci.time_budget (or set it to auto)"
    if source == "CI_JOB_TIMEOUT":
        return "raise the job's timeout (CI_JOB_TIMEOUT)"
    return "raise timeout-minutes and L4_JOB_TIMEOUT_MINUTES"


def upgrade_notes(cfg: Any, workflow_text: str | None) -> tuple[str, ...]:
    """L4-IMP-079: the `error:` and `warning:` lines of `l4 upgrade`. The job's timeout is the workflow's only."""
    notes: list[str] = []
    if (error := too_short(cfg)) is not None:
        notes.append(f"error: {error}; until it is fixed, l4 run exits 2 and doctor CFG-012 fails")
    if (warning := shortens_job(cfg, job_timeout({}, workflow_text))) is not None:
        notes.append(f"warning: {warning}")
    return tuple(notes)
