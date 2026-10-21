"""The plan state as a fold of the plan ledger alone (design D4, L4-YOLO-006, L4-YOLO-013, L4-YOLO-014).

`fold_plan(plan_id, events)` reads the events in order and returns a `PlanState`. The status rules:

- `refused`, `admitted`, `reviewed` before activation; `active` after `plan.activated`.
- `waiting` on `plan.waiting`, until the next dispatch, merge request, merge or integration, or a resume.
- `stopped` on `plan.stopped`, until `plan.resumed` (back to `active`) or a new `plan.activated` (the re-activation
  after `inputs_changed`: the digests, limits and `activated_digest` are replaced, the usage is kept).
- `cancelled` and `completed` are final: no later event changes the status.

The activated plan is frozen (R2, D4, D10). `plan.activated` freezes the plan digest as `activated_digest`. While the
plan is activated (active, waiting, stopped) `plan.admitted`, `plan.refused` and `plan.reviewed` change only the review
fields (`findings`, `review`, `review_digests`, `review_plan_digest`): never `activated_digest`, `plan_digest`, `order`,
`merge` or the status. The latest admission is remembered, and a re-activation of that very plan digest adopts its
order and merge mode. `plan.stopped` and `plan.resumed` before any activation are ignored, so a plan that was never
activated cannot become `active` without digests or limits.

Usage never goes down (R1, D11). A restart starts a new unit ledger, so the unit's own totals cover one attempt.
`plan.charged{unit, attempt, cost_usd, runs}` carries the totals of one attempt of one unit. The fold keeps the maximum
per (unit, attempt) and sums them: a repeated charge counts once, and a restart that zeroes the unit's counters never
lowers the plan's. The attempts used by a unit are the highest attempt charged. A charge without `attempt` (an older
ledger) counts as attempt 1. Keys that start with `plan:` (the judge's cost, `plan:review`, attempt 0) count in the
plan's cost and runs but are not units: they have no entry in `used.attempts`.

`plan.run_idle{unit, attempt, run}` (L4-YOLO-014) names a run of one attempt that did nothing (no agent, no gate, no
phase change but a wait): the fold subtracts the distinct idle runs of each (unit, attempt) from its charged runs,
never below zero, and keeps their number as `used.idle_runs`. A record is of one run, so a repeated record counts once.
An older harness ignores the event and counts the runs as before.

`plan.resumed{extend}` adds to `extended`: `cost_usd` and `runs` numbers, and `attempts` either a number (every unit,
kept under the key `*`) or a `{unit: n}` mapping. An `extend.deadline` raises `extended_deadline` (the latest wins; a
time without a zone is read as UTC).

`plan.force_accepted` (L4-YOLO-057) keeps its data plus `at` as `force_accepted` in any status but final; a later one
replaces it as a whole and `plan.force_acceptance_withdrawn` clears it.

`plan.extended{extend}` (L4-YOLO-050) raises the limits of an activated plan that is not final, in any status, and
changes nothing else: no status, no wait or stop reason, no `stale_merges`. Before the activation it is ignored.

`plan.activated{current: <unit or null>}` says which unit the plan goes on with: the activation keeps the current unit
only when the new order holds it and every prerequisite of it is integrated, else it is null. An event without the key
(an older ledger) keeps the current unit unless the new order drops it.

`plan.activated{attempt_base: {unit: n}}` records how many attempt refs each unit had on origin at the activation (R13):
the unit's attempts in the plan are counted from there, and a re-activation keeps the first base of a unit. A
`plan.resumed` that a person recorded resets `stale_merges` (the harness's own wake-up does not): the next step tries
the merge once more.

`unit.dispatched` resets the unit's `stale_merges` when its attempts grew since its last `stale` refusal (a new attempt
gets its one `stale` retry, D8). An event type the fold does not know is ignored (forward compatible) and logged at
debug.
"""

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from l4.yolo.model import PlanEvent, PlanState

log = logging.getLogger("l4.yolo.state")

STALE = "stale"
PLAN_KEY_PREFIX = "plan:"  # a `plan.charged` key that is not a unit (R1)
ALL_UNITS = "*"
_FINAL = ("cancelled", "completed")
_BEFORE_ACTIVATION = ("new", "refused", "admitted", "reviewed")
MERGE = ("human", "auto")


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _number(value: Any) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def is_unit_key(key: str) -> bool:
    """False for the keys of `plan.charged` that are not units (`plan:review`, R1)."""
    return not key.startswith(PLAN_KEY_PREFIX)


def parse_time(value: Any) -> datetime | None:
    """An ISO-8601 time as an aware datetime (a naive one is read as UTC); None when it is not one."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def fold_plan(plan_id: str, events: Iterable[PlanEvent]) -> PlanState:
    """The state of the plan `plan_id` after `events`."""
    state = PlanState(plan_id=plan_id)
    cost: dict[tuple[str, int], float] = {}
    runs: dict[tuple[str, int], int] = {}
    idle: dict[tuple[str, int], set[str]] = {}  # (unit, attempt) -> runs of `plan.run_idle` records
    activated = False
    admitted: tuple[str | None, list[str], str | None] = (None, [], None)  # latest admission: digest, order, merge
    stale_at: dict[str, int] = {}  # unit -> its attempts at its latest `stale` refusal

    def wake() -> None:
        if state.status == "waiting":
            state.status = "active"
        state.wait_reason = None

    for event in events:
        data, kind = event.data, event.type
        unit = _text(data.get("unit"))
        if kind == "plan.admitted":
            order = [str(u) for u in data.get("order") or []]
            admitted = (_text(data.get("plan_digest")), order, data["merge"] if data.get("merge") in MERGE else None)
            state.findings = []
            if not activated and state.status in _BEFORE_ACTIVATION:
                state.status = "admitted"
                state.plan_digest, state.order = admitted[0], order
                if admitted[2]:
                    state.merge = admitted[2]  # type: ignore[assignment]
        elif kind == "plan.refused":
            if not activated and state.status in _BEFORE_ACTIVATION:
                state.status = "refused"
            state.findings = [{str(k): str(v) for k, v in f.items()} for f in data.get("findings") or []]
        elif kind == "plan.reviewed":
            if not activated and state.status in _BEFORE_ACTIVATION:
                state.status = "reviewed"
            state.review_plan_digest = _text(data.get("plan_digest"))
            version = data.get("prompt_version")
            state.review_prompt_version = version if isinstance(version, int) and not isinstance(version, bool) else 1
            state.review, state.review_digests = {}, {}
            for key, entries in (("", data.get("units")), ("batch:", data.get("batches"))):
                for ident, entry in (entries or {}).items():
                    if isinstance(entry, dict) and entry.get("verdict") is not None:
                        state.review[f"{key}{ident}"] = str(entry["verdict"])
                        if entry.get("digest") is not None:
                            state.review_digests[f"{key}{ident}"] = str(entry["digest"])
        elif kind == "plan.activated" and state.status not in _FINAL:
            activated = True
            state.status = "active"
            state.plan_digest = _text(data.get("plan_digest")) or state.plan_digest
            state.activated_digest = state.plan_digest
            if admitted[0] is not None and admitted[0] == state.plan_digest:
                state.order = list(admitted[1])
                if admitted[2]:
                    state.merge = admitted[2]  # type: ignore[assignment]
            state.digests = {str(k): str(v) for k, v in (data.get("digests") or {}).items()}
            state.limits = dict(data.get("limits") or {})
            for base_unit, refs in (data.get("attempt_base") or {}).items():  # R13: the first record of a unit stands
                state.attempt_base.setdefault(str(base_unit), int(_number(refs)))
            state.activated_by = _text(data.get("by"))
            state.activated_accepted = {  # frozen for the unit run (D7, D8); a re-activation replaces
                str(k): dict(v) for k, v in (data.get("accepted") or {}).items() if isinstance(v, dict)
            }
            state.waived = {}  # a waiver is of a finding of the activation it was given in (L4-YOLO-031)
            state.stop_reason = state.stop_detail = state.stop_unit = state.wait_reason = None
            if data.get("merge") in MERGE:
                state.merge = data["merge"]
            if (
                "current" in data
            ):  # the activation says which unit goes on: none when it has a new blocker (review z1, H2)
                state.current = _text(data["current"])
            elif state.current is not None and state.order and state.current not in state.order:
                state.current = None  # a unit the activated order does not hold is no longer the plan's (review #1)
        elif kind == "plan.accepted":
            subject = _text(data.get("subject"))
            if subject and state.status not in _FINAL:
                state.accepted[subject] = dict(data)
        elif kind == "plan.acceptance_withdrawn":
            state.accepted.pop(_text(data.get("subject")) or "", None)
        elif kind == "plan.force_accepted":
            if state.status not in _FINAL and data.get("actor") == "person":  # the command writes no other
                state.force_accepted = {**data, "at": event.at}
        elif kind == "plan.force_acceptance_withdrawn":
            state.force_accepted = None
        elif kind == "plan.finding_waived":
            finding = _text(data.get("finding"))
            if finding and state.status not in _FINAL:
                state.waived[finding] = dict(data)
        elif kind == "plan.waiver_withdrawn":
            state.waived.pop(_text(data.get("finding")) or "", None)
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
            if activated and state.status not in _FINAL:
                state.status = "stopped"
                state.stop_reason, state.stop_detail, state.stop_unit = (
                    _text(data.get("reason")),
                    _text(data.get("detail")),
                    unit,
                )
                state.wait_reason = None
        elif kind == "plan.resumed":
            if activated and state.status in ("stopped", "waiting"):
                state.status = "active"
                state.stop_reason = state.stop_detail = state.stop_unit = state.wait_reason = None
                apply_extend(state, data.get("extend"))
                if data.get("by") != "harness":  # a person's resume: the next step tries the merge once more (R7)
                    state.stale_merges.clear()
                    stale_at.clear()
        elif kind == "plan.extended":
            if activated and state.status not in _FINAL:
                apply_extend(state, data.get("extend"))
        elif kind == "plan.cancelled":
            if state.status not in _FINAL:
                state.status = "cancelled"
                state.wait_reason = None
        elif kind == "plan.charged" and unit:
            attempt = int(_number(data["attempt"])) if "attempt" in data else 1
            key = (unit, attempt)
            cost[key] = max(cost.get(key, 0.0), _number(data.get("cost_usd")))
            runs[key] = max(runs.get(key, 0), int(_number(data.get("runs"))))
            if is_unit_key(unit):
                state.used.attempts[unit] = max(state.used.attempts.get(unit, 0), attempt)
            state.used.cost_usd = sum(cost.values())
            state.used.runs, state.used.idle_runs = _runs_used(runs, idle)
        elif kind == "plan.run_idle" and unit:
            attempt = int(_number(data["attempt"])) if "attempt" in data else 1
            known = idle.setdefault((unit, attempt), set())
            known.add(_text(data.get("run")) or f"#{len(known)}")
            state.used.runs, state.used.idle_runs = _runs_used(runs, idle)
        elif kind == "plan.completed":
            if state.status not in _FINAL:
                state.status = "completed"
                state.completed_revision = _text(data.get("revision"))
                state.current = None
                state.wait_reason = None
        else:
            log.debug("plan %s: ignored event %r", plan_id, kind)
    return state


def _runs_used(runs: dict[tuple[str, int], int], idle: dict[tuple[str, int], set[str]]) -> tuple[int, int]:
    """The runs that count against `max_runs` and the idle runs left out of them: per (unit, attempt) the charged
    maximum less the runs recorded idle, never below zero (L4-YOLO-014)."""
    used = sum(max(0, n - len(idle.get(key, ()))) for key, n in runs.items())
    return used, sum(min(n, len(idle.get(key, ()))) for key, n in runs.items())


def apply_extend(state: PlanState, extend: Any) -> None:
    """Add what `plan.resumed{extend}` carries to `state.extended` (the fold and `limits.resume_allows` share it)."""
    if not isinstance(extend, dict):
        return
    state.extended.cost_usd += _number(extend.get("cost_usd"))
    state.extended.runs += int(_number(extend.get("runs")))
    later = parse_time(extend.get("deadline"))
    if later is not None and (state.extended_deadline is None or later > state.extended_deadline):
        state.extended_deadline = later.astimezone(UTC)
    attempts = extend.get("attempts")
    if isinstance(attempts, dict):
        for unit, n in attempts.items():
            state.extended.attempts[str(unit)] = state.extended.attempts.get(str(unit), 0) + int(_number(n))
    elif attempts is not None:
        state.extended.attempts[ALL_UNITS] = state.extended.attempts.get(ALL_UNITS, 0) + int(_number(attempts))
