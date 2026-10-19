"""No sandbox: agents and gates run as the harness's OS user and can read its secrets. Only reachable through an
explicit, recorded risk acceptance (`sandbox.mode: none` plus `sandbox.allow_none: true`)."""

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path

from l4.sandbox.base import Availability, SandboxSpec, SandboxUnavailable, WrappedCommand

DISABLED_WARNING = (
    "SANDBOX DISABLED (accepted risk): agents and gates run as the harness OS user and can read its secrets"
)
READ_ONLY_WARNING = "the worktree of a read-only step stays writable: there is no sandbox to mount it read-only"

log = logging.getLogger("l4.sandbox")


class NoSandbox:
    name = "none"

    def __init__(self, *, allow_none: bool) -> None:
        if not allow_none:
            raise SandboxUnavailable("sandbox.mode: none is refused unless sandbox.allow_none is true")
        self._warned_read_only = False

    def available(self) -> Availability:
        return Availability(True)

    def wrap(
        self, argv: Sequence[str], spec: SandboxSpec, env: Mapping[str, str], cwd: Path | None = None
    ) -> WrappedCommand:  # the caller starts the process in `cwd`
        if spec.worktree_read_only and not self._warned_read_only:
            self._warned_read_only = True
            log.warning(READ_ONLY_WARNING)
        return WrappedCommand(list(argv), dict(env))


class AbsentSandbox:
    """What a command that runs no agent and no gate gets instead of a sandbox (`l4 resume`, SPEC section 2.1): any
    use is a bug, so it fails closed with `SandboxUnavailable` rather than running unwrapped."""

    name = "absent"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def available(self) -> Availability:
        raise SandboxUnavailable(self.reason)

    def wrap(
        self, argv: Sequence[str], spec: SandboxSpec, env: Mapping[str, str], cwd: Path | None = None
    ) -> WrappedCommand:
        raise SandboxUnavailable(self.reason)
