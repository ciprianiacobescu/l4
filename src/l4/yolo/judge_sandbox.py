"""The sandbox of a readiness judge outside CI (review-resolution design D5, section 8). A judge whose adapter
enforces "no tool" in its own argv and that runs in an empty folder may run without bwrap on a person's machine; CI
and a judge with a shell never do."""

from collections.abc import Mapping
from pathlib import Path

from l4.agents.opencode import FREE_PREFIX
from l4.config.schema import L4Config
from l4.proc import run_process
from l4.safepath import resolve_tool
from l4.sandbox.base import Sandbox, SandboxUnavailable
from l4.sandbox.bwrap import BwrapSandbox
from l4.sandbox.none import NoSandbox
from l4.sandbox.select import BWRAP_HINT, select_sandbox

TOOL_LESS_ADAPTERS = ("claude-code", "opencode", "fake")


def _bwrap(environ: Mapping[str, str], repo: Path) -> tuple[Sandbox | None, str]:
    """(a usable bwrap sandbox, or None and why not)."""
    exe = resolve_tool("bwrap", environ, forbid=(repo,))
    if exe is None:
        return None, "bwrap was not found on PATH"
    sandbox = BwrapSandbox(exe, run_process)
    verdict = sandbox.available()
    return (sandbox, "") if verdict.ok else (None, verdict.reason)


def unsandboxed_reason(environ: Mapping[str, str], repo: Path) -> str:
    """Why bwrap is not usable (`bwrap was not found on PATH` or bwrap's own reason); empty when it is usable."""
    return _bwrap(environ, repo)[1]


def choose(
    cfg: L4Config, environ: Mapping[str, str], repo: Path, *, adapter: str, in_ci: bool, profile: str | None = None
) -> tuple[Sandbox, str]:
    """The sandbox and its label (`bwrap` or `none`); raises `SandboxUnavailable` for a refusal. `profile` names the
    judge's profile: an opencode one on a free `opencode/` model is not tool-less (its tools stay at `ask`)."""
    mode = cfg.sandbox.mode
    if mode == "none":
        return NoSandbox(allow_none=cfg.sandbox.allow_none), "none"
    if mode in ("user", "container"):
        return select_sandbox(cfg.sandbox, environ, repo=repo), mode  # not implemented: raises
    sandbox, why = _bwrap(environ, repo)
    if sandbox is not None:
        return sandbox, "bwrap"
    if in_ci:
        raise SandboxUnavailable(f"{why}; {BWRAP_HINT}")
    model = cfg.profiles[profile].model if profile in cfg.profiles else None
    asks = adapter == "opencode" and bool(model) and str(model).startswith(FREE_PREFIX)
    if asks:
        raise SandboxUnavailable(
            f"the opencode judge on the free model {model} leaves its tools at ask, so it is not tool-less; without "
            "bwrap use a claude-code or an api-key opencode judge profile, or let CI review"
        )
    if adapter in TOOL_LESS_ADAPTERS:
        return NoSandbox(allow_none=True), "none"
    raise SandboxUnavailable(
        f"the {adapter} judge keeps a read-only shell; without bwrap use a claude-code or opencode judge profile, "
        "or let CI review"
    )
