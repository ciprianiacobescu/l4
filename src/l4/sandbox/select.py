"""Pick the sandbox, failing closed (SPEC L4-SEC-005). `auto` never degrades to `none`."""

import logging
from collections.abc import Mapping
from pathlib import Path

from l4.agents.base import EventSink
from l4.config.schema import SandboxCfg
from l4.exitcodes import ExitCode, L4Exit
from l4.proc import Runner, run_process
from l4.safepath import resolve_tool
from l4.sandbox.base import Sandbox, SandboxUnavailable
from l4.sandbox.bwrap import BwrapSandbox
from l4.sandbox.none import DISABLED_WARNING, NoSandbox

log = logging.getLogger("l4.sandbox")

BWRAP_HINT = "install bubblewrap (apt install bubblewrap) and allow unprivileged user namespaces for the runner user"


def select_sandbox(
    cfg: SandboxCfg,
    environ: Mapping[str, str],
    *,
    repo: Path,
    events: EventSink | None = None,
    runner: Runner = run_process,
) -> Sandbox:
    """`events` is where `sandbox.disabled` goes when `mode: none` is accepted; `l4 run` passes its ledger writer."""
    if cfg.mode == "none":
        sandbox = NoSandbox(allow_none=cfg.allow_none)
        log.warning(DISABLED_WARNING)
        if events is not None:
            events.append("sandbox.disabled", mode="none", by="config")
        return sandbox
    if cfg.mode in ("user", "container"):
        raise L4Exit(ExitCode.USAGE_ERROR, f"sandbox.mode: {cfg.mode} not yet implemented (M2: sandbox-security)")
    exe = resolve_tool("bwrap", environ, forbid=(repo,))
    if exe is None:
        raise SandboxUnavailable(f"bwrap was not found on PATH; {BWRAP_HINT}")
    sandbox = BwrapSandbox(exe, runner)
    verdict = sandbox.available()
    if not verdict.ok:
        raise SandboxUnavailable(f"{verdict.reason}; {BWRAP_HINT}")
    return sandbox
