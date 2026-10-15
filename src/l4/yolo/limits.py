"""The plan limits, evaluated in one place (design D11, R3, R12; L4-YOLO-017..).

`effective_limits(state)` is what is in force: the limits frozen at activation (`PlanState.limits`; the model's
defaults for a figure the plan did not give) plus what `l4 yolo resume` extended (`PlanState.extended`, and the latest
`extended_deadline`). `reached(state, *, now)` says which limit the usage has reached, if any. The plan step and
`l4 yolo resume` both use these functions, so a plan that the step stops for a limit is refused by `resume` for the
very same reason until the limit is raised (`resume_allows`).

The comparisons are fixed (R3). The cost and the runs are reached when the used figure is `>=` the limit. The attempts
of a unit are exceeded when they are `>` `max_unit_attempts` plus its extensions (`*` for every unit, and the unit's
own). The deadline is reached when `now >=` it. A unit that is integrated is not checked for attempts. The codes are
`limit_cost`, `limit_runs`, `limit_attempts` and `limit_deadline`, checked in that order.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.vcs.push import ATTEMPT_REF_PREFIX
from l4.yolo.model import PlanEvent, PlanState
from l4.yolo.state import ALL_UNITS, apply_extend, is_unit_key, parse_time

log = logging.getLogger("l4.yolo.limits")

LIMIT_COST = "limit_cost"
LIMIT_RUNS = "limit_runs"
LIMIT_ATTEMPTS = "limit_attempts"
LIMIT_DEADLINE = "limit_deadline"
LIMIT_CODES = (LIMIT_COST, LIMIT_RUNS, LIMIT_ATTEMPTS, LIMIT_DEADLINE)
DEFAULT_MAX_UNIT_ATTEMPTS = 2


@dataclass(frozen=True)
class EffectiveLimits:
    """The limits in force. `None` means no limit (cost, runs, deadline)."""

    cost_usd: float | None
    runs: int | None
    attempts: int  # `max_unit_attempts`, before the extensions
    deadline: datetime | None  # aware
    extra_attempts: Mapping[str, int] = field(default_factory=dict)  # unit or `*` -> attempts added by resume

    def attempts_of(self, unit: str) -> int:
        """The attempts `unit` may use: `max_unit_attempts` plus the extensions for every unit and for this one."""
        return self.attempts + self.extra_attempts.get(ALL_UNITS, 0) + self.extra_attempts.get(unit, 0)


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def effective_limits(state: PlanState, fallback: Mapping[str, Any] | None = None) -> EffectiveLimits:
    """The limits in force for `state`. `fallback` (a `PlanLimits` dict) stands in for the limits frozen at activation
    before there are any (a plan that is not activated yet); the frozen ones win. The deadline is the later of the
    frozen one and `state.extended_deadline`."""
    frozen = state.limits or fallback or {}
    cost, runs = _float(frozen.get("max_cost_usd")), _int(frozen.get("max_runs"))
    attempts = _int(frozen.get("max_unit_attempts"))
    deadline = (
        parse_time(frozen.get("deadline")) if not isinstance(frozen.get("deadline"), datetime) else frozen["deadline"]
    )
    if isinstance(deadline, datetime) and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if state.extended_deadline is not None and (deadline is None or state.extended_deadline > deadline):
        deadline = state.extended_deadline
    return EffectiveLimits(
        None if cost is None else cost + state.extended.cost_usd,
        None if runs is None else runs + state.extended.runs,
        DEFAULT_MAX_UNIT_ATTEMPTS if attempts is None else attempts,
        deadline,
        dict(state.extended.attempts),
    )


def reached_at(
    state: PlanState, *, now: datetime, fallback: Mapping[str, Any] | None = None
) -> tuple[str, str, str | None] | None:
    """`(code, detail, unit)` of the first limit reached, or None. `unit` is set for `limit_attempts` only."""
    limits = effective_limits(state, fallback)
    used = state.used
    if limits.cost_usd is not None and used.cost_usd >= limits.cost_usd:
        return LIMIT_COST, f"${used.cost_usd:.2f} spent of ${limits.cost_usd:.2f}", None
    if limits.runs is not None and used.runs >= limits.runs:
        return LIMIT_RUNS, f"{used.runs} run(s) used of {limits.runs}", None
    for unit, attempts in used.attempts.items():
        if not is_unit_key(unit) or unit in state.integrated:
            continue
        allowed = limits.attempts_of(unit)
        if attempts > allowed:
            return LIMIT_ATTEMPTS, f"{unit} is on attempt {attempts} of {allowed}", unit
    if limits.deadline is not None:
        stamp = now if now.tzinfo else now.replace(tzinfo=UTC)
        if stamp >= limits.deadline:
            return LIMIT_DEADLINE, f"the deadline {limits.deadline.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ} has passed", None
    return None


def reached(state: PlanState, *, now: datetime, fallback: Mapping[str, Any] | None = None) -> tuple[str, str] | None:
    """`(code, detail)` of the first limit the plan has reached (cost, runs, attempts, deadline), or None (R3)."""
    hit = reached_at(state, now=now, fallback=fallback)
    return None if hit is None else (hit[0], hit[1])


def resume_allows(
    state: PlanState, extend: Mapping[str, Any] | None, *, now: datetime, fallback: Mapping[str, Any] | None = None
) -> tuple[str, str] | None:
    """What still blocks `l4 yolo resume` once `extend` (the `extend` of `plan.resumed`: `cost_usd`, `runs`, `attempts`
    as a number or a `{unit: n}` mapping, `deadline`) is applied: `(code, detail)` of the first limit that would be
    reached again, or None when the resume may go on. `state` is not changed."""
    after = state.model_copy(deep=True)
    apply_extend(after, dict(extend) if extend else None)
    return reached(after, now=now, fallback=fallback)


# --- the live figures of a unit (R1, R3, R13): one place for the plan step and `l4 yolo resume` -----------------


def attempt_refs(git: Git, unit: str, config: Sequence[tuple[str, str]] = ()) -> int | None:
    """How many `refs/l4/attempts/<fw>/<name>/<n>` refs `unit` has on origin (`l4 restart` keeps each old head there),
    or None when origin cannot be asked."""
    pattern = f"{ATTEMPT_REF_PREFIX}{unit.replace(':', '/', 1)}/*"
    try:
        listing = git.run("ls-remote", "origin", pattern, config=config).stdout
    except GitError as exc:
        log.warning("%s: its attempt refs could not be listed: %s", unit, str(exc).splitlines()[0][:200])
        return None
    refs = [line.split("\t")[-1].strip() for line in listing.splitlines() if "\t" in line]
    return sum(1 for ref in refs if ref.rsplit("/", 1)[-1].isdigit())


def live_attempt(state: PlanState, unit: str, refs: int | None) -> int:
    """The attempt `unit` is on in this plan: 1 + its attempt refs on origin, minus the refs it had when the plan was
    activated (`attempt_base`, R13: a restart before the plan is not an attempt of the plan). When origin cannot be
    asked (`refs` None), and always as a floor, the highest attempt already charged stands: an attempt number never
    goes down. This is the one function the plan step and `l4 yolo resume` count attempts with."""
    counted = 1 if refs is None else 1 + max(0, refs - state.attempt_base.get(unit, 0))
    return max(counted, state.used.attempts.get(unit, 1))


def charged_of(events: Sequence[PlanEvent], unit: str, attempt: int) -> tuple[float, int]:
    """The cost and the runs `plan.charged` already holds for one attempt of a unit (the fold's maximum)."""
    cost, runs = 0.0, 0
    for event in events:
        same = event.type == "plan.charged" and event.data.get("unit") == unit
        if same and int(event.data.get("attempt", 1) or 0) == attempt:
            cost = max(cost, float(event.data.get("cost_usd") or 0))
            runs = max(runs, int(event.data.get("runs") or 0))
    return cost, runs


def live_state(
    state: PlanState, events: Sequence[PlanEvent], unit: str | None, attempt: int, unit_cost: float
) -> PlanState:
    """The folded state with what `unit` has used and the ledger does not hold yet: the cost its ledger shows now
    (`unit_cost`) and the attempt it is on (`attempt`). Only that unit runs (the plan is serial). The plan step checks
    its limits on this state, and `l4 yolo resume` and `l4 yolo status` read the same figures."""
    if unit is None or unit in state.integrated or not is_unit_key(unit):
        return state
    charged_cost, _ = charged_of(events, unit, attempt)
    used = state.used.model_copy(deep=True)
    used.cost_usd += max(0.0, unit_cost - charged_cost)
    used.attempts[unit] = max(used.attempts.get(unit, 0), attempt)
    return state.model_copy(update={"used": used})
