"""The capacity parks of a unit that only a fix can end (L4-YOLO-035), read from its ledger.

A park is the `phase.changed` into `waiting_capacity`; the `availability.unavailable{role, required, skipped,
retry_after}` that precedes it names the profiles that could not serve. A park is fix-only when no profile of the chain
was cooling: every skip a missing binary, a failed login, a `hello` that was refused or answered wrongly, a constraint
or `serves` (nothing but a fix ends it, L4-AVL-007), and `retry_after` is not in the future. A cool-down (a limit or
credit with a reset), a busy profile or a usage window is not fix-only: the wait ends by itself. A transient failure (a
step or `hello` that timed out) is not fix-only either: its park has a `retry_after` in the future (L4-AVL-013)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from l4.state.ledger import LedgerEvent

PROGRESS = frozenset({"task.done", "task.red_ok", "task.green_committed"})
SELF_ENDING_STEPS = frozenset({"cooling", "quota", "concurrency"})  # skips that end without a fix
_SLACK_S = 2.0  # `retry_after` is the park's own time when nothing cools (second precision)


@dataclass(frozen=True)
class FixPark:
    """One fix-only park: when it happened, the role that nobody served, and each unusable profile with the probe
    step it failed and why."""

    ts: datetime
    role: str
    profiles: tuple[tuple[str, str, str], ...]  # (profile, step, reason)

    @property
    def names(self) -> frozenset[str]:
        return frozenset(p for p, _, _ in self.profiles)


def _parse(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fix_only(event: LedgerEvent) -> FixPark | None:
    skipped = event.data.get("skipped")
    if not isinstance(skipped, list) or not skipped:
        return None
    profiles: list[tuple[str, str, str]] = []
    for entry in skipped:
        if not isinstance(entry, dict) or entry.get("step") in SELF_ENDING_STEPS or entry.get("resets_at"):
            return None
        profiles.append((str(entry.get("profile", "")), str(entry.get("step", "")), str(entry.get("reason", ""))))
    retry = _parse(event.data.get("retry_after"))
    if retry is not None and (retry - event.ts).total_seconds() > _SLACK_S:
        return None  # a cool-down ends the wait at `retry_after`
    return FixPark(event.ts, str(event.data.get("role", "")), tuple(profiles))


def fix_parks(events: Sequence[LedgerEvent]) -> tuple[FixPark, ...]:
    """The trailing run of fix-only parks with no work of the unit between them, oldest first. A park with a cooling
    profile (or none recorded) and any task progress end the run."""
    run: list[FixPark] = []
    pending: LedgerEvent | None = None
    for event in events:
        if event.type == "availability.unavailable" and event.data.get("required"):
            pending = event
        elif event.type == "phase.changed":
            if event.data.get("to") == "waiting_capacity":
                park = _fix_only(pending) if pending is not None else None
                if park is None:
                    run.clear()
                else:
                    run.append(park)
            pending = None
        elif event.type in PROGRESS or (event.type == "step.finished" and event.data.get("status") == "ok"):
            run.clear()
            pending = None
    return tuple(run)
