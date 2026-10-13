"""A cell's raw run becomes its result (plan D5): the score, the error classes and, when the cell says nothing about
the model under test, the `invalid` reason that keeps it out of every rate."""

from collections.abc import Mapping, Sequence
from typing import Any

from l4.eval.cellrun import Cell, CellRaw
from l4.eval.errors import DETAIL_MAX, CellError, classify, invalidating
from l4.eval.score import cost_of, score_implementer, score_judge
from l4.eval.scorecard import cell_result
from l4.redact import Redactor

# l4's own: internal error, usage, environment not ready. The model was not measured: the cell is `invalid`
# (`harness_error`), never a failure of the profile, unless a known cause (a cold cache, a login) names it better.
_CRASH_CODES = (1, 2, 3)
HARNESS_ERROR = "harness_error"
_IMPL_KEYS = ("attempts", "halted_at", "breaker", "blocked", "verdict")
# the ledger events that show the implementer took a step: before any of them, a breaker stopped an environment, a
# seed or the harness, never the model
_MODEL_STEP = frozenset({"step.started", "agent.finished", "task.attempt_failed", "task.red_ok", "task.done"})
_JUDGE_KEYS = ("verdict", "expected_verdict", "agreement", "findings", "worst_severity", "missed_defect")


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip() and "] artefacts:" not in line]
    return lines[-1] if lines else ""


def _not_measured(cell: Cell, events: Sequence[Mapping[str, Any]]) -> str | None:
    """The `invalid` reason of a cell that ran but never reached the model under test: an implementer cell whose run
    halted before its first agent step (`baseline_failed`: the base project's tests could not run in the cell, or
    `halted_before_agent`), a judge cell whose judge was never called (`judge_not_reached`: the reference replay or
    the run stopped before verification). Such a cell is not a failure of the profile."""
    types = {str(e.get("type")) for e in events}
    if cell.role == "judge":
        return None if "verify.judge" in types else "judge_not_reached"
    breaker = next((e for e in events if e.get("type") == "breaker.tripped"), None)
    if breaker is None or types & _MODEL_STEP:
        return None
    return "baseline_failed" if breaker.get("reason") == "baseline_failed" else "halted_before_agent"


REFERENCE_UNAVAILABLE = "reference_unavailable"
_MEASURED_ROLE = {"implementer": "implementer", "judge": "judges"}  # the `role` of `availability.unavailable`


def _capacity_error(cell: Cell, events: Sequence[Mapping[str, Any]]) -> tuple[CellError, bool]:
    """The error of an exit 12 that no limit event explains, and whether it is the reference's: the newest
    `availability.unavailable` names the role nobody could serve. The other role of the cell (the fixed judge of an
    implementer cell, the replay of a judge cell) is the reference: its absence says nothing about the profile under
    test. A measured profile skipped only at its auth step is a missing login."""
    gone = [e for e in events if e.get("type") == "availability.unavailable"]
    if not gone:
        return CellError("unavailable", "waiting_capacity (exit 12): no profile of a required role answered"), False
    role = str(gone[-1].get("role") or "")
    skipped = [s for s in gone[-1].get("skipped") or [] if isinstance(s, Mapping)]
    named = "; ".join(f"{s.get('profile')} {s.get('step')}: {s.get('reason')}" for s in skipped) or "no profile"
    if role != _MEASURED_ROLE[cell.role]:
        return CellError("unavailable", f"the reference {role} profile is unavailable: {named}"), True
    if skipped and all(s.get("step") == "auth" for s in skipped):
        return CellError("login", f"{role}: {named}"), False
    return CellError("unavailable", f"waiting_capacity (exit 12): {role}: {named}"), False


def finish_cell(
    cell: Cell, raw: CellRaw, expected: Mapping[str, Any], *, free: bool, redactor: Redactor
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "role": cell.role, "profile": cell.profile, "unit": cell.unit, "k": cell.k, "wall_s": raw.wall_s,
        "returncode": raw.returncode,
    }  # fmt: skip
    if raw.invalid and raw.invalid != "cell_timeout":  # a pre-check: nothing ran
        return cell_result({**base, "status": "invalid", "invalid_reason": raw.invalid})
    errors = classify(
        raw.ledger_events, raw.log_text, redactor, cell_timeout=raw.invalid == "cell_timeout", setup_tail=raw.setup_tail
    )
    kinds = {e.kind for e in errors}
    reference = False
    if raw.returncode == 12 and not kinds & {"rate_limit", "unavailable", "login", "setup_cold"}:
        error, reference = _capacity_error(cell, raw.ledger_events)
        errors.append(CellError(error.kind, error.detail[:DETAIL_MAX]))
    elif raw.returncode in _CRASH_CODES:
        # a failed setup gate names its own cause; the workspace (and its log) is gone after the cell
        cause = f"setup: {_last_line(raw.setup_tail)}" if raw.setup_tail.strip() else _last_line(raw.log_text)
        detail = f"l4 run exit {raw.returncode}: {redactor.redact_text(cause)}"
        errors.append(CellError("other", " ".join(detail.split())[:DETAIL_MAX]))
    invalid = (
        raw.invalid or (REFERENCE_UNAVAILABLE if reference else None) or invalidating(errors)
        or (HARNESS_ERROR if raw.returncode in _CRASH_CODES else None) or _not_measured(cell, raw.ledger_events)
    )  # fmt: skip
    fields: dict[str, Any] = {
        **base, **cost_of(raw.ledger_events, free=free),
        "errors": [{"kind": e.kind, "detail": e.detail} for e in errors],
    }  # fmt: skip
    if invalid:
        return cell_result({**fields, "status": "invalid", "invalid_reason": invalid})
    if cell.role == "implementer":
        score = score_implementer(raw.ledger_events, expected)
        return cell_result({**fields, "status": score["outcome"], **{k: score[k] for k in _IMPL_KEYS}})
    score = score_judge(raw.ledger_events, expected, raw.report_text)
    schema_errors = [{"kind": "schema", "detail": "the judge reply broke its schema"} for _ in score["errors"]]
    if schema_errors and not any(e["kind"] == "schema" for e in fields["errors"]):
        fields["errors"] = [*fields["errors"], *schema_errors]
    return cell_result({**fields, "status": score["outcome"], **{k: score[k] for k in _JUDGE_KEYS}})
