"""Which units the delegate may answer for (delegate-answers 9.1; L4-DLG-001, design D1).

`in_scope` is pure over what the run already read: the plan files with the folded state of their ledgers, the target
branch and the `yolo.hold` patterns. With `delegate.scope: yolo` a unit is in scope when it is the current unit of a
plan that is `active` or `waiting` on the target, or the fix unit of that unit. `scope: all` adds the units that no
plan file lists while no plan is `active` on the target (L4-YOLO-010 gives such a unit no agent work while one is, and
the delegate is agent work). A unit that `yolo.hold` matches (and no plan plans), a unit of a stopped, cancelled or not
yet activated plan, and a finished unit are never in scope."""

from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase

from l4.config.schema import DelegateCfg
from l4.yolo.model import PlanState
from l4.yolo.plans import PlanFile, holds_of

FINISHED = ("merged", "archived", "abandoned")
LIVE = ("active", "waiting")  # the plans whose current unit is worked on or waited for


@dataclass(frozen=True)
class PlansView:
    """The plans of the target as the run read them: `files` (every plan file), `states` (plan id -> the folded
    ledger, absent for a plan with none), `target` (the base branch) and `hold` (the `yolo.hold` patterns)."""

    files: tuple[PlanFile, ...] = ()
    states: Mapping[str, PlanState] = None  # type: ignore[assignment]
    target: str = "main"
    hold: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.states is None:
            object.__setattr__(self, "states", {})


def in_scope(
    unit: str, plans: PlansView, cfg: DelegateCfg, *, phase: str | None = None, fix_of: str | None = None
) -> bool:
    """`unit` is the unit id; `fix_of` the parent's id when it is a fix unit (it follows its parent); `phase` its folded
    phase (None: unknown, not finished)."""
    if not cfg.enabled or (phase or "") in FINISHED:
        return False
    subject = fix_of or unit
    held = holds_of(plans.states, plans.files).held.get(subject)
    if held is not None:
        plan_id, status = held
        current = plans.states[plan_id].current if plan_id in plans.states else None
        return status in LIVE and current == subject
    if any(fnmatchcase(subject, pattern) for pattern in plans.hold):
        return False
    if cfg.scope != "all":
        return False
    return not any(
        f.plan is not None
        and f.plan.target == plans.target
        and (state := plans.states.get(f.plan_id)) is not None
        and state.status == "active"
        for f in plans.files
    )
