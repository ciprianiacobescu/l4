"""The ways a role can have nothing to run on (exit 12), kept apart from `l4.agents.factory` so the selector can
raise them without importing the factory. `l4.agents.factory` re-exports all three names."""

from dataclasses import dataclass
from datetime import datetime

from l4.exitcodes import ExitCode, L4Exit

REQUIRED_ROLES = ("implementer", "verifier_agent", "judges")  # the others are optional and degrade (L4-AVL-010)


@dataclass(frozen=True)
class Unready:
    """A profile of a chain that is not usable for a reason that is not a cool-down: its binary or login is missing, a
    constraint or `serves` refused it, a probe failed, or its login stayed busy. Nothing cools it, so it is probed
    again on the next run (L4-AVL-007)."""

    profile: str
    adapter: str | None
    auth: str | None
    step: str
    reason: str


class RoleUnavailable(L4Exit):
    """No usable profile for a role: exit 12."""

    def __init__(self, role: str, reason: str, steps: tuple[str, ...] = ()) -> None:
        super().__init__(ExitCode.WAITING_CAPACITY, f"role {role} is unavailable: {reason}")
        self.steps = steps  # why each profile of the chain was out (`serves`, `constraint`, a probe step, `cooling`...)


class WaitingCapacity(RoleUnavailable):
    """A required chain with nothing usable. A subclass, so every `except RoleUnavailable` keeps working; the unit
    parks in `waiting_capacity` until `retry_after`: the earliest end of a cool-down, else now (every failure was
    binary, auth, hello, a constraint or `serves`, and `unready` lists them)."""

    def __init__(self, role: str, reason: str, retry_after: datetime, unready: tuple[Unready, ...] = ()) -> None:
        super().__init__(role, reason)
        self.retry_after = retry_after
        self.unready = unready
