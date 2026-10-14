"""The plan state as a fold of the plan ledger alone (design D4, L4-YOLO-006, L4-YOLO-013, L4-YOLO-014).

`fold_plan(plan_id, events)` reads the events in order and returns a `PlanState`. The status rules:

- `refused`, `admitted`, `reviewed` before activation; `active` after `plan.activated`.
- `waiting` on `plan.waiting`, until the next dispatch, merge request, merge or integration, or a resume.
- `stopped` on `plan.stopped`, until `plan.resumed` (back to `active`) or a new `plan.activated` (the re-activation
  after `inputs_changed`: the digests and limits are replaced, the usage is kept).
- `cancelled` and `completed` are final: no later event changes the status.

Usage never goes down. `plan.charged{unit, cost_usd, runs, attempts}` carries the unit's own totals (D11: the cost of
the unit's fold, which survives a restart; 1 + restarts), so each figure is the maximum seen for that unit, and the
plan's cost and runs are the sums over the units. A repeated charge therefore counts once, and a restart that resets the
unit's counters never lowers the plan's. `plan.resumed{extend}` adds to `extended`: `cost_usd` and `runs` numbers, and
`attempts` either a number (every unit, kept under the key `*`) or a `{unit: n}` mapping.

`unit.dispatched` resets the unit's `stale_merges` when its attempts grew since its last `stale` refusal (a new attempt
gets its one `stale` retry, D8). An event type the fold does not know is ignored (forward compatible) and logged at
debug.
"""

import logging
from collections.abc import Iterable
from typing import Any

from l4.yolo.model import PlanEvent, PlanState

log = logging.getLogger("l4.yolo.state")

STALE = "stale"
ALL_UNITS = "*"
_FINAL = ("cancelled", "completed")
_BEFORE_ACTIVATION = ("new", "refused", "admitted", "reviewed")


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _number(value: Any) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def fold_plan(plan_id: str, events: Iterable[PlanEvent]) -> PlanState:
    """The state of the plan `plan_id` after `events`."""
    state = PlanState(plan_id=plan_id)
    cost: dict[str, float] = {}
    runs: dict[str, int] = {}
    stale_at: dict[str, int] = {}  # unit -> its attempts at its latest `stale` refusal

    def wake() -> None:
        if state.status == "waiting":
            state.status = "active"
        state.wait_reason = None

    for event in events:
        data, kind = event.data, event.type
        unit = _text(data.get("unit"))
        if kind == "plan.admitted":
            if state.status in _BEFORE_ACTIVATION:
                state.status = "admitted"
            state.plan_digest = _text(data.get("plan_digest"))
            state.order = [str(u) for u in data.get("order") or []]
            state.findings = []
            if data.get("merge") in ("human", "auto"):
                state.merge = data["merge"]
        elif kind == "plan.refused":
            if state.status in _BEFORE_ACTIVATION:
                state.status = "refused"
            state.findings = [{str(k): str(v) for k, v in f.items()} for f in data.get("findings") or []]
        elif kind == "plan.reviewed":
            if state.status in _BEFORE_ACTIVATION:
                state.status = "reviewed"
            state.review_plan_digest = _text(data.get("plan_digest"))
            state.review, state.review_digests = {}, {}
            for key, entries in (("", data.get("units")), ("batch:", data.get("batches"))):
                for ident, entry in (entries or {}).items():
                    if isinstance(entry, dict) and entry.get("verdict") is not None:
                        state.review[f"{key}{ident}"] = str(entry["verdict"])
                        if entry.get("digest") is not None:
                            state.review_digests[f"{key}{ident}"] = str(entry["digest"])
        elif kind == "plan.activated":
            if state.status not in _FINAL:
                state.status = "active"
            state.plan_digest = _text(data.get("plan_digest")) or state.plan_digest
            state.digests = {str(k): str(v) for k, v in (data.get("digests") or {}).items()}
            state.limits = dict(data.get("limits") or {})
            state.activated_by = _text(data.get("by"))
            state.stop_reason = state.stop_detail = state.stop_unit = state.wait_reason = None
            if data.get("merge") in ("human", "auto"):
                state.merge = data["merge"]
        elif kind == "unit.dispatched" and unit:
            state.current = unit
            if state.used.attempts.get(unit, 0) > stale_at.get(unit, state.used.attempts.get(unit, 0)):
                state.stale_merges.pop(unit, None)
                stale_at.pop(unit, None)
            wake()
        elif kind == "unit.merge_requested":
            wake()
        elif kind == "unit.merged" and unit:
            state.merged[unit] = str(data.get("merge_commit") or data.get("head") or "")
            wake()
        elif kind == "unit.merge_refused" and unit:
            if data.get("reason") == STALE:
                state.stale_merges[unit] = state.stale_merges.get(unit, 0) + 1
                stale_at[unit] = state.used.attempts.get(unit, 0)
        elif kind == "unit.postcheck":
            pass  # a record; the plan step reads the latest one from the ledger
        elif kind == "unit.integrated" and unit:
            state.integrated[unit] = str(data.get("revision") or "")
            if state.current == unit:
                state.current = None
            wake()
        elif kind == "batch.accepted" and data.get("batch"):
            state.accepted_batches[str(data["batch"])] = str(data.get("revision") or "")
            state.failed_batches.pop(str(data["batch"]), None)
        elif kind == "batch.failed" and data.get("batch"):
            state.failed_batches[str(data["batch"])] = str(data.get("detail") or data.get("revision") or "")
            state.accepted_batches.pop(str(data["batch"]), None)
        elif kind == "plan.waiting":
            if state.status in ("active", "waiting"):
                state.status = "waiting"
                state.wait_reason = _text(data.get("reason"))
        elif kind == "plan.stopped":
            if state.status not in _FINAL:
                state.status = "stopped"
                state.stop_reason, state.stop_detail, state.stop_unit = (
                    _text(data.get("reason")),
                    _text(data.get("detail")),
                    unit,
                )
                state.wait_reason = None
        elif kind == "plan.resumed":
            if state.status in ("stopped", "waiting"):
                state.status = "active"
                state.stop_reason = state.stop_detail = state.stop_unit = state.wait_reason = None
                _extend(state, data.get("extend"))
        elif kind == "plan.cancelled":
            if state.status not in _FINAL:
                state.status = "cancelled"
                state.wait_reason = None
        elif kind == "plan.charged" and unit:
            cost[unit] = max(cost.get(unit, 0.0), _number(data.get("cost_usd")))
            runs[unit] = max(runs.get(unit, 0), int(_number(data.get("runs"))))
            state.used.attempts[unit] = max(state.used.attempts.get(unit, 0), int(_number(data.get("attempts"))))
            state.used.cost_usd, state.used.runs = sum(cost.values()), sum(runs.values())
        elif kind == "plan.completed":
            if state.status not in _FINAL:
                state.status = "completed"
                state.completed_revision = _text(data.get("revision"))
                state.current = None
                state.wait_reason = None
        else:
            log.debug("plan %s: ignored event %r", plan_id, kind)
    return state


def _extend(state: PlanState, extend: Any) -> None:
    if not isinstance(extend, dict):
        return
    state.extended.cost_usd += _number(extend.get("cost_usd"))
    state.extended.runs += int(_number(extend.get("runs")))
    attempts = extend.get("attempts")
    if isinstance(attempts, dict):
        for unit, n in attempts.items():
            state.extended.attempts[str(unit)] = state.extended.attempts.get(str(unit), 0) + int(_number(n))
    elif attempts is not None:
        state.extended.attempts[ALL_UNITS] = state.extended.attempts.get(ALL_UNITS, 0) + int(_number(attempts))
