"""The step timeout of a probe and the named reason when a step does not answer (L4-AVL-012).

`probes.py` re-exports these names; they live here because `quota.py`, which `probes.py` imports, needs them too.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path

from l4.agents.base import AdapterError, ProbeCtx
from l4.doctor.context import CmdResult

_OPENCODE_CAUSE = "an OpenCode v2 daemon or a login prompt can cause this"
_OTHER_CAUSE = "a login prompt or a helper process that keeps the output open can cause this"


class StepTimedOut(AdapterError):
    """A probe step did not answer in time; `reason` is the text the step result carries."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def step_seconds(ctx: ProbeCtx) -> float:
    """The timeout of a `binary`, `auth` or `quota` step: `probe_step_timeout`, never above `probe_timeout`."""
    return min(ctx.step_timeout_s, ctx.timeout_s)


def timeout_reason(cli: str, seconds: float, step: str) -> str:
    cause = _OPENCODE_CAUSE if cli == "opencode" else _OTHER_CAUSE
    return f"{cli} did not answer within {seconds:g} s ({step} step); {cause}: run l4 doctor"


def step_run(
    ctx: ProbeCtx, cli: str, step: str, argv: Sequence[str], env: Mapping[str, str], cwd: Path | None = None
) -> CmdResult:
    """Run one subprocess of a non-hello step with the step timeout; exit 124 (the runner's timeout) raises
    `StepTimedOut` with the named reason."""
    seconds = step_seconds(ctx)
    done = ctx.run(list(argv), cwd or ctx.cwd, dict(env), seconds)
    if done.returncode == 124:
        raise StepTimedOut(timeout_reason(cli, seconds, step))
    return done
