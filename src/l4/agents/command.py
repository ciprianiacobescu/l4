"""Command adapter (SPEC 8.3): any CLI as an agent, from a user-written argv template in the profile.

    options:
      argv: ["mytool", "--model", "{model}", "--in", "{prompt_file}", "--out", "{result_path}"]
      probe_argv: ["mytool", "ping"]          # optional; the `hello` step, passes on exit 0

`{prompt_file}` is a file the adapter writes (the prompt exactly as published), `{result_path}` the file the command
must write its result object to (the prompt contract, which the prompt itself already spells out), `{model}` the
profile's model and `{session_id}` a fresh id. Placeholders are checked when the config is loaded
(`l4.config.schema.command_option_problems`) and substituted by plain text replacement, never `str.format`.
What the command may reach is the user's responsibility: only the allow-listed environment is passed, and the sandbox
still applies. M1: no `resume_argv`, no ACP (agent-factory 5.3).
"""

import os
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import ClassVar

from l4.agents.base import (
    AdapterError,
    AgentCaps,
    ProbeCtx,
    ProbeResult,
    ProbeStep,
    RunRequest,
    RunResult,
    read_result_file,
)
from l4.agents.contract import attach_file_result
from l4.agents.proc import ProcRunner
from l4.availability.probes import _timed, probe_env
from l4.config.schema import PLACEHOLDER, Profile
from l4.safepath import resolve_tool
from l4.sandbox.base import WrappedCommand

PROMPT_FILE = "prompt.md"


def command_argv(template: Sequence[str], **values: str) -> list[str]:
    """Each `{name}` that has a value is replaced (and only those), everything else stays as written."""
    return [PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), part) for part in template]


def _executable(argv0: str, env: Mapping[str, str], forbid: tuple[Path, ...]) -> str | None:
    if "/" in argv0:
        if not Path(argv0).is_absolute():
            raise AdapterError("the command's executable must be a bare name or an absolute path")
        return argv0 if os.access(argv0, os.X_OK) else None
    return resolve_tool(argv0, env, forbid=forbid)


class CommandAdapter:
    name = "command"
    model_unverified: ClassVar[bool] = True

    def __init__(self, runner: ProcRunner | None = None) -> None:
        self._proc = runner or ProcRunner()

    def capabilities(self) -> AgentCaps:
        return AgentCaps("prompt_contract", False, False, False, False, False, False, True)

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        argv = profile.options.get("argv")
        if step == "binary":
            try:
                found = isinstance(argv, list) and _executable(argv[0], ctx.environ, ctx.forbid)
            except AdapterError as exc:
                return ProbeResult(step, False, reason=str(exc))
            return ProbeResult(step, True) if found else ProbeResult(step, False, reason="command executable not found")
        probe_argv = profile.options.get("probe_argv")
        if step != "hello" or not probe_argv:
            return ProbeResult(step, True, skipped=True)
        exe = _executable(probe_argv[0], ctx.environ, ctx.forbid)
        if exe is None:
            return ProbeResult(step, False, reason="probe_argv executable not found")
        done, millis = _timed(ctx, [exe, *command_argv(probe_argv[1:], model=profile.model or "")], probe_env(ctx))
        if done.returncode == 124:
            return ProbeResult(step, False, reason="timeout")
        if done.returncode != 0:
            return ProbeResult(step, False, reason=f"probe command exited with code {done.returncode}")
        return ProbeResult(step, True, {"ms": millis})

    def run(self, req: RunRequest) -> RunResult:
        profile = req.profile
        template = profile.options.get("argv")
        if not isinstance(template, list) or not template:
            raise AdapterError("a command profile needs options.argv")
        if "{model}" in "\0".join(template) and not profile.model:
            raise AdapterError("options.argv uses {model} but the profile has no model")
        exe = _executable(template[0], req.env, (req.cwd,))
        if exe is None:
            raise AdapterError(f"{template[0]} was not found on the agent PATH")
        step_dir = req.result_path.parent
        step_dir.mkdir(parents=True, exist_ok=True)
        req.result_path.unlink(missing_ok=True)  # a leftover from an earlier step must not pass for this one's result
        prompt_file = step_dir / PROMPT_FILE
        prompt_file.write_text(req.prompt, encoding="utf-8")
        argv = [exe, *command_argv(
            template[1:], model=profile.model or "", prompt_file=str(prompt_file), result_path=str(req.result_path),
            session_id=req.preset_session_id or uuid.uuid4().hex,
        )]  # fmt: skip
        cmd = req.wrap(argv, req.env) if req.wrap else WrappedCommand(argv, dict(req.env))
        outcome = self._proc.run(
            cmd.argv, cmd.env, req.cwd, stdout_path=req.raw_events_path,
            stderr_path=req.raw_events_path.with_suffix(".stderr"), stdin=None, timeout_s=req.timeout_s,
            interrupt=req.interrupt, stall_timeout_s=req.stall_timeout_s,
        )  # fmt: skip
        result = RunResult(status="error", raw_events_path=req.raw_events_path, exit_code=outcome.returncode)
        if outcome.timed_out or outcome.stalled:
            result.status = "timeout"
        elif outcome.interrupted:
            result.status = "cancelled"
        elif outcome.returncode != 0:
            result.detail = f"the command exited with code {outcome.returncode}"
        else:
            attach_file_result(result, read_result_file(req.result_path), req.result_schema, "the command")
        return result
