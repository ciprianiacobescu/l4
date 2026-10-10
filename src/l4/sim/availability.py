"""What `l4 plan --probe` and `l4 run --dry-run` know about the agents a next action needs (simulation-harness D7).

`AvailabilityView` answers for the head of a role's chain. `NullAvailability` knows nothing (`unknown`) and never
starts a process: it is what a plan or a dry run uses unless `--probe` is given. `ProbingAvailability` walks the
probe ladder (binary, auth, hello) of the head in a scratch directory outside any checkout, once per role.
M1: reading `$L4_CACHE/availability.json` through M1.2's `CooldownRegistry`, so that a cached result answers without a
probe and `cooling`/`exhausted` show; merged with M1.2 (parallel-ownership C14).
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from l4.agents.base import ProbeCtx
from l4.agents.factory import Factory
from l4.config.schema import L4Config
from l4.doctor.checks_agents import scratch_dir
from l4.exitcodes import L4Exit
from l4.proc import run_process

ROLES_OF_ACTION: Mapping[str, tuple[str, ...]] = {
    "implement": ("implementer",),
    "clarify": ("clarifier",),
    "verify": ("judges",),
    "hand_off": (),
}
Status = Literal["unknown", "usable", "unavailable"]


@dataclass(frozen=True)
class RoleStatus:
    role: str
    profile: str | None  # the head of the role's chain, None when the role has no chain
    status: Status
    reason: str = ""

    def as_json(self) -> dict[str, str | None]:
        body: dict[str, str | None] = {"profile": self.profile, "status": self.status}
        if self.reason:
            body["reason"] = self.reason
        return body

    def line(self) -> str:
        text = f"{self.role}: {self.profile or '-'} {self.status}"
        return f"{text} ({self.reason})" if self.reason else text


class AvailabilityView(Protocol):
    def head(self, role: str) -> RoleStatus: ...


def roles_needed(actions: Collection[str]) -> tuple[str, ...]:
    """The roles the given next actions use, once each, in a stable order."""
    wanted = {role for action in actions for role in ROLES_OF_ACTION.get(action, ())}
    return tuple(role for role in ("implementer", "clarifier", "judges") if role in wanted)


def _head(cfg: L4Config, role: str) -> str | None:
    chain: list[str] = getattr(cfg.roles, role)
    return chain[0] if chain else None


class NullAvailability:
    def __init__(self, cfg: L4Config) -> None:
        self._cfg = cfg

    def head(self, role: str) -> RoleStatus:
        return RoleStatus(role, _head(self._cfg, role), "unknown")


class ProbingAvailability:
    """Probes the head through `Factory.for_role`, the same ladder a run uses. Each role is probed once."""

    def __init__(self, cfg: L4Config, environ: Mapping[str, str], repo: Path) -> None:
        self._cfg, self._environ, self._repo = cfg, environ, repo
        self._seen: dict[str, RoleStatus] = {}

    def head(self, role: str) -> RoleStatus:
        if role not in self._seen:
            self._seen[role] = self._probe(role)
        return self._seen[role]

    def _probe(self, role: str) -> RoleStatus:
        name = _head(self._cfg, role)
        if name is None:
            return RoleStatus(role, None, "unknown", "no profile in the chain")
        with scratch_dir(self._repo) as scratch:
            ctx = ProbeCtx(environ=self._environ, cwd=Path(scratch), run=run_process, forbid=(self._repo,))
            try:
                Factory(self._cfg, ctx).for_role(role, "plan")
            except L4Exit as exc:  # RoleUnavailable (exit 12), or a profile that cannot be built
                return RoleStatus(role, name, "unavailable", str(exc).split(": ", 1)[-1][:200])
        return RoleStatus(role, name, "usable")


def availability_json(view: AvailabilityView, roles: Collection[str]) -> dict[str, Any]:
    return {role: view.head(role).as_json() for role in roles}
