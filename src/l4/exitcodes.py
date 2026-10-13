"""Process exit codes (SPEC L4-CLI-001): one definition, one severity order."""

import json
from collections.abc import Iterable, Sequence
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from l4.context import AppContext
    from l4.outcome import CommandResult  # noqa: F401  (annotation only: outcome imports this module)


class ExitCode(IntEnum):
    OK = 0
    INTERNAL_ERROR = 1
    USAGE_ERROR = 2
    DOCTOR_FAILED = 3
    CONTINUE = 10
    AWAITING_HUMAN = 11
    WAITING_CAPACITY = 12
    HALTED = 13
    REJECTED = 14
    REGRESSION = 15  # `l4 eval --compare`: a measured profile got worse (M1.14); never a designed stop
    CANCELLED = 16  # a signal or a finished CI job stopped the run (W-D2); nothing was pushed


# 14 (rejected: an invalid spec on the base) outranks 13 (halted): the CI include allows 13 to fail (a halt is unit
# state the forge mirrors), never 14, so a run with one of each stays red
SEVERITY_ORDER: tuple[int, ...] = (1, 16, 2, 3, 14, 15, 13, 11, 12, 10, 0)


# The codes of a designed stop (SPEC 2.2): the run did what it was built to do and is waiting for a person, for
# capacity, for another run, or on a halt that the forge already mirrors. CI shows none of them as a red job: the GitLab
# include's `allow_failure: exit_codes` is checked against this tuple, and `map_exit` turns each into exit 0 on GitHub.
# 1, 2, 3, 14 and 15 are not in it: a harness or environment fault, a rejected unit, or a regression found by
# `l4 eval --compare`, stays a failure.
CI_ALLOWED: tuple[int, ...] = (10, 11, 12, 13)


def most_severe(codes: Iterable[int]) -> ExitCode:
    """The most severe code of several units; ValueError for a code outside the table."""
    seen = set(codes)
    unknown = seen - set(SEVERITY_ORDER)
    if unknown:
        raise ValueError(f"unknown exit code(s): {sorted(unknown)}")
    for code in SEVERITY_ORDER:
        if code in seen:
            return ExitCode(code)
    return ExitCode.OK


def plan_exit_code(actionable: Sequence[str], detailed: bool) -> ExitCode:
    """`l4 plan` exits 0 whether or not there is work (L4-CLI-001); `--detailed-exitcode` exits 10 when something is
    actionable, so a CI script can branch on it."""
    return ExitCode.CONTINUE if detailed and actionable else ExitCode.OK


class L4Exit(Exception):
    """Raised by handlers to end the process with a specific code and an optional message."""

    def __init__(self, code: ExitCode, message: str = "") -> None:
        super().__init__(message)
        self.code = code


def classify_exception(exc: Exception) -> tuple[ExitCode, str]:
    """Map an exception escaping a handler to its exit code and a one-line message (unredacted)."""
    if isinstance(exc, L4Exit):
        return exc.code, str(exc) or exc.code.name.lower()
    return ExitCode.INTERNAL_ERROR, f"internal error: {type(exc).__name__}: {exc}"


_MEANING = {
    ExitCode.INTERNAL_ERROR: "harness bug or infrastructure failure",
    ExitCode.USAGE_ERROR: "bad arguments or invalid config",
    ExitCode.DOCTOR_FAILED: "environment not ready",
    ExitCode.CONTINUE: "progress made, a continuation was dispatched or is needed",
    ExitCode.AWAITING_HUMAN: "blocked on questions or a human gate",
    ExitCode.WAITING_CAPACITY: "every profile in a required chain is unavailable",
    ExitCode.HALTED: "circuit breaker tripped, budget exhausted or verification escalated",
    ExitCode.REJECTED: "unit out of scope, spec invalid or no spec framework",
    ExitCode.REGRESSION: "eval scorecard regressed against the baseline",
    ExitCode.CANCELLED: "the run was cancelled by a signal or its CI job ended; nothing was pushed",
}
_GITHUB_LEVEL = {
    ExitCode.CONTINUE: "notice",
    ExitCode.HALTED: "warning",
    ExitCode.AWAITING_HUMAN: "warning",
    ExitCode.WAITING_CAPACITY: "warning",
}


class MappedExit(NamedTuple):
    annotation: str | None
    exit_code: int


def map_exit(code: int, platform: str, reason: str | None = None) -> MappedExit:
    """CI rendering of an exit code (SPEC 2.2). GitHub: 10/11/12/13 become annotations and exit 0, every other
    non-zero code exits 1. GitLab: the annotation, and the original code so `allow_failure: exit_codes` applies.
    `reason` replaces the generic meaning of a known code (the run's own words for what happened; the code is the same).
    A code outside the table (137 after an OOM kill, 127 for a missing binary) is a failure of `l4` itself, never
    a usage error: it is reported as it came, and GitLab keeps it (1 when it cannot be a process exit status)."""
    if platform not in ("github", "gitlab"):
        raise ValueError(f"unknown CI platform: {platform!r}")
    if code == 0:
        return MappedExit(None, 0)
    known = ExitCode(code) if code in SEVERITY_ORDER else None
    if known is None:
        text = f"l4 exited with unexpected code {code}"
        if platform == "gitlab":
            return MappedExit(text, code if 1 <= code <= 255 else 1)
        return MappedExit(f"::error::{text}", 1)
    text = f"l4 exit {int(known)} ({known.name.lower()}): {reason or _MEANING[known]}"
    if platform == "gitlab":
        # GitLab still prints its own `ERROR: Job failed: exit status N` for an allowed failure and shows the job as
        # `failed (allowed)`: the line above it says what that is
        return MappedExit(f"designed stop, not a failure: {text}" if code in CI_ALLOWED else text, int(known))
    level = _GITHUB_LEVEL.get(known)
    if level is None:
        return MappedExit(f"::error::{text}", 1)
    return MappedExit(f"::{level}::{text}", 0)


def _run_reason(out_dir: Path, code: int) -> str | None:
    """The `exit_reason` of the units in `outcome.json`, when that file is the outcome of a run that ended with `code`
    (a stale or unreadable file gives none: the generic text stands)."""
    try:
        doc = json.loads((out_dir / "outcome.json").read_text(encoding="utf-8"))
        if doc.get("exit_code") != code:
            return None
        reasons = dict.fromkeys(str(u["exit_reason"]) for u in doc.get("units", []) if u.get("exit_reason"))
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    return "; ".join(reasons)[:300] or None


def run_map_exit(app: "AppContext", *, code: int) -> "CommandResult":
    """`l4 ci map-exit CODE`. Platform comes from the CI environment; anything but GitHub preserves the code."""
    platform = "github" if app.environ.get("GITHUB_ACTIONS") == "true" else "gitlab"
    from l4.outcome import CommandResult

    mapped = map_exit(code, platform, _run_reason(app.out_dir, code))
    if mapped.annotation:
        print(mapped.annotation)
    return CommandResult(mapped.exit_code)
