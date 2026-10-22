"""SPIKE, NOT REGISTERED: a GitHub Copilot CLI adapter prototype (`@github/copilot` 1.0.102), for
`docs/plan/proposal-copilot-cli.md`. Nothing imports this module: it is not in `l4.agents.factory.ADAPTERS`,
`l4.config.roles`, the pin catalog or the credential table, and no role can select it. It exists so the proposal's
command lines and parser are code checked against streams recorded on 1.0.102 (in BYOK mode against a local model,
`tests/fixtures/recorded/copilot-cli/1.0.102-byok`), not prose. The GitHub-routed path (a Copilot token) was not run.

Every run reads its prompt from stdin (piped stdin is a non-interactive prompt, no `-p` needed [V 1.0.102]) and runs
from a private `COPILOT_HOME` in the step's private directory that holds only `settings.json` (`HOME_SETTINGS`):

    copilot --output-format json --no-ask-user --no-auto-update --no-custom-instructions --disable-builtin-mcps
        --disable-client-telemetry --disallow-temp-dir --session-id <uuid>
        --usage-output-file <step>/copilot-usage.json [--model M]
        <mode flags>

mode flags: a judge `--available-tools=l4_no_tools` (an unknown name in the allow-list leaves the model no tool at
all [V]; an EMPTY `--available-tools` is ignored and leaves every tool [V], so it is never used); the delegate's
read-only run `--available-tools=view,grep,glob` (reads inside the cwd are approved without a prompt [V]); an
implementer `--allow-tool=write`, `--allow-tool=shell(<gate binary>:*)` and `--add-dir <step dir>` (`write`
approved `create` in the cwd, and `--add-dir` admitted the result file outside it, which was denied without it
[V]). The shell rule matches on the command's first word only (`shell(./.venv/bin/python:*)` ran
`./.venv/bin/python -m pytest` [V]; `shell(./.venv/bin/python -m pytest:*)` matched nothing [V]), so it is coarser
than claude's `Bash(prefix:*)`. Shell commands it deems read-only (`ls`, `echo`) run with no rule matching them
[V]. In prompt mode a request outside the policy is denied, never asked (`error.code == "denied"` [V]). The CLI's
own path check is not a boundary (a script in the cwd read a file outside it [V]): the sandbox is.

The JSONL stream gives the served model (`assistant.message.model`), the reply (`assistant.message.content`), the
tool calls (`tool.execution_start` / `tool.execution_complete`), a fatal error (`session.error` with `errorType` and
`statusCode`) and a final `result` with `sessionId` and `exitCode` [V, BYOK]. Token usage and AI credits come from
the `--usage-output-file` document. An unauthenticated run prints no stream: exit 1 and `Error: No authentication
information found.` on standard error [V, GitHub path].
"""

import json
import re
import shutil
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from l4.agents.base import (
    TRANSIENT_STATUSES,
    AdapterError,
    AgentCaps,
    LimitSignal,
    ProbeCtx,
    ProbeResult,
    ProbeStep,
    RunRequest,
    RunResult,
    Usage,
    judge_workdir,
    read_result_file,
    wrap_command,
)
from l4.agents.contract import attach_file_result, attach_judge_reply, attach_read_only_reply
from l4.agents.credentials import credential_loader
from l4.agents.proc import ProcRunner
from l4.availability.probes import _binary
from l4.config.schema import Profile
from l4.safepath import resolve_tool

NAME = "copilot"
CREDENTIAL_VARIABLE = "COPILOT_GITHUB_TOKEN"  # highest precedence; GH_TOKEN / GITHUB_TOKEN are forge tokens in L4
HOME_DIR = "copilot-home"
USAGE_FILE = "copilot-usage.json"
NO_TOOLS = "l4_no_tools"  # an unknown tool name: the allow-list then admits nothing [V 1.0.102]
READ_TOOLS = ("view", "grep", "glob")  # on gpt models the CLI serves `grep` as `rg` [V]; both names count as reads
READ_TOOL_NAMES = frozenset({*READ_TOOLS, "rg"})
HOME_SETTINGS = {
    "autoUpdate": False,
    "disableAllHooks": True,
    "memory": False,
    "includeCoAuthoredBy": False,  # default true: the agent would be told to add a Co-authored-by trailer
}  # read from `$COPILOT_HOME/settings.json` [V: `copilot config --list` shows each]
_NO_AUTH = re.compile(r"No authentication information found", re.I)
_TOKEN_REJECTED = re.compile(r"authenticat|unauthori[sz]ed|\b40[13]\b|token", re.I)


def write_home(home: Path) -> Path:
    """A fresh `COPILOT_HOME` at `home` holding only `settings.json`; returns `home`. The CLI writes its session
    state (the whole prompt and system message), logs and session store there, inside the step's private dir."""
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    (home / "settings.json").write_text(json.dumps(HOME_SETTINGS, indent=2), encoding="utf-8")
    return home


def gate_rule(gate_prefix: str | None) -> list[str]:
    """`--allow-tool=shell(<first word>:*)` for the gate command, or nothing: the rule language matches the command's
    first word (with `:*` for any arguments), so the whole prefix cannot be pinned."""
    words = (gate_prefix or "").split()
    return [f"--allow-tool=shell({words[0]}:*)"] if words else []


def build_command(req: RunRequest, *, exe: str, session_id: str, usage_path: Path) -> list[str]:
    mode = req.permission_policy.mode
    argv = [
        exe, "--output-format", "json", "--no-ask-user", "--no-auto-update", "--no-custom-instructions",
        "--disable-builtin-mcps", "--disable-client-telemetry", "--disallow-temp-dir", "--session-id", session_id,
        "--usage-output-file", str(usage_path),
    ]  # fmt: skip
    if req.profile.model:
        argv += ["--model", req.profile.model]
    if mode == "judge":
        return [*argv, f"--available-tools={NO_TOOLS}"]
    if mode == "read_only":
        return [*argv, f"--available-tools={','.join(READ_TOOLS)}"]
    argv += ["--allow-tool=write", *gate_rule(req.permission_policy.gate_prefix)]
    return [*argv, "--add-dir", str(req.result_path.parent)]


def events(text: str) -> list[dict[str, Any]]:
    """The JSON objects with a string `type` of a `--output-format json` stream; other lines are skipped."""
    found = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and isinstance(event.get("type"), str):
            found.append(event)
    return found


def stream_facts(stream: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """`session_id` and `exit_code` (the final `result`), `final_text` (the last non-empty assistant content),
    `last_message` (the content of the last assistant message after the last tool call), `model` (the served model
    of the last assistant message), `tools` (every tool started, in order), `denials` (`{tool_name}` per denied
    call), `error` (the last `session.error`) and `retry_reasons` (every `assistant.turn_retry` reason)."""
    facts: dict[str, Any] = {"tools": [], "denials": [], "retry_reasons": []}
    started: dict[str, str] = {}
    last_message: str | None = None
    for event in stream:
        kind, data = event["type"], event.get("data") if isinstance(event.get("data"), dict) else {}
        if kind == "assistant.message":
            content = data.get("content") if isinstance(data.get("content"), str) else ""
            if isinstance(data.get("model"), str) and data["model"]:
                facts["model"] = data["model"]
            if content.strip():
                facts["final_text"] = content
                last_message = content
        elif kind == "tool.execution_start":
            name = data.get("toolName") if isinstance(data.get("toolName"), str) else "unknown"
            facts["tools"].append(name)
            started[str(data.get("toolCallId"))] = name
            last_message = None  # only text after the last tool call is the last message
        elif kind == "tool.execution_complete":
            error = data.get("error") if isinstance(data.get("error"), dict) else {}
            if error.get("code") == "denied":
                facts["denials"].append({"tool_name": started.get(str(data.get("toolCallId")), "unknown")})
        elif kind == "session.error":
            facts["error"] = data
        elif kind == "assistant.turn_retry" and isinstance(data.get("reason"), str):
            facts["retry_reasons"].append(data["reason"])
        elif kind == "result":
            facts["session_id"] = event.get("sessionId") if isinstance(event.get("sessionId"), str) else None
            facts["exit_code"] = event.get("exitCode") if isinstance(event.get("exitCode"), int) else None
    if last_message is not None:
        facts["last_message"] = last_message
    return facts


def usage_of(document: Any) -> Usage:
    """Tokens summed over `modelMetrics`; `totalNanoAiu` as AI credits (1e-9 units, the unit's name [U]); never
    dollars. An unreadable document is zero usage."""
    if not isinstance(document, dict):
        return Usage()
    sums = {"inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0}
    for metrics in (document.get("modelMetrics") or {}).values():
        usage = metrics.get("usage") if isinstance(metrics, dict) else None
        for key in sums:
            value = usage.get(key) if isinstance(usage, dict) else None
            if isinstance(value, int) and not isinstance(value, bool):
                sums[key] += value
    nano = document.get("totalNanoAiu")
    credits = nano / 1e9 if isinstance(nano, int | float) and not isinstance(nano, bool) and nano > 0 else None
    return Usage(
        input_tokens=sums["inputTokens"], output_tokens=sums["outputTokens"],
        cached_input_tokens=sums["cacheReadTokens"], credits=credits,
        credits_source="copilot.usage_file" if credits is not None else None,
    )  # fmt: skip


def parse(
    text: str,
    *,
    exit_code: int,
    raw_events_path: Path,
    mode: str = "implement",
    stderr_text: str = "",
    usage_document: Any = None,
    result_text: str | None = None,
    schema: dict[str, Any] | None = None,
    timed_out: bool = False,
    interrupted: bool = False,
) -> RunResult:
    facts = stream_facts(events(text))
    result = RunResult(status="error", raw_events_path=raw_events_path, exit_code=exit_code)
    result.session_id, result.final_text = facts.get("session_id"), facts.get("final_text")
    result.last_message, result.model_resolved = facts.get("last_message"), facts.get("model")
    result.permission_denials = facts["denials"]
    result.usage = usage_of(usage_document)
    error = facts.get("error") or {}
    status = error.get("statusCode") if isinstance(error.get("statusCode"), int) else None
    result.api_status = status
    if timed_out or interrupted:
        result.status = "timeout" if timed_out else "cancelled"
        if "rate_limit" in facts["retry_reasons"]:  # the CLI was waiting out a 429 itself [V, BYOK]
            result.status, result.detail = "rate_limited", "copilot was retrying a rate limit when the run was stopped"
            result.limit = LimitSignal(NAME, result.model_resolved, "rate_limit", None, "copilot.turn_retry", "")
        return result
    if exit_code != 0 and not text.strip() and _NO_AUTH.search(stderr_text):
        result.status, result.detail = "auth", f"copilot found no credential (set {CREDENTIAL_VARIABLE})"
        return result
    if error:
        if error.get("errorType") == "authentication" or status in (401, 403):
            result.status, result.detail = "auth", "copilot could not authenticate (the token is missing or rejected)"
            result.limit = LimitSignal(NAME, result.model_resolved, "auth", None, "copilot.session_error", "")
        elif status == 429:
            result.status, result.detail = "rate_limited", "copilot reported a rate limit (session.error 429)"
            result.limit = LimitSignal(NAME, result.model_resolved, "rate_limit", None, "copilot.session_error", "")
        elif status == 402:
            result.status, result.detail = "quota", "copilot reported that the allowance is used up (402)"
            result.limit = LimitSignal(NAME, result.model_resolved, "credits", None, "copilot.session_error", "")
        else:
            result.detail = f"copilot reported an error ({error.get('errorType') or 'unknown'}, status {status})"
            result.transient = status is not None and (status in TRANSIENT_STATUSES or status >= 500)
        return result
    if exit_code != 0:
        result.detail = f"copilot exited with code {exit_code}"
        return result
    if mode == "judge":
        if facts["tools"]:
            result.detail = f"copilot judge called a tool ({facts['tools'][0]})"
            return result
        attach_judge_reply(result, facts.get("final_text"), schema)
    elif mode == "read_only":
        outside = sorted({t for t in facts["tools"] if t not in READ_TOOL_NAMES})
        if outside:
            result.detail = f"copilot delegate called a tool outside the read set ({', '.join(outside)})"
            return result
        attach_read_only_reply(result, facts.get("last_message"), facts.get("final_text"), schema)
    else:
        attach_file_result(result, result_text, schema, "copilot")
    return result


class CopilotCliAdapter:
    """The prototype adapter. `probe` answers the `binary` step only; the other steps are skipped (the spike did not
    design the auth, quota and hello steps against a real Copilot account)."""

    name = NAME
    experimental = True

    def __init__(self, runner: ProcRunner | None = None) -> None:
        self._proc = runner or ProcRunner()

    def capabilities(self) -> AgentCaps:
        # no native schema flag, no max-turns flag (only autopilot continues and a soft --max-ai-credits >= 30)
        return AgentCaps("prompt_contract", True, True, False, False, True, False, True, served_model=True)

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        if step == "binary":
            return _binary("copilot", profile, ctx)[0]
        return ProbeResult(step, True, skipped=True, reason="copilot spike: only the binary step is prototyped")

    def run(self, req: RunRequest) -> RunResult:
        exe = resolve_tool("copilot", req.env, forbid=(req.cwd,))
        if exe is None:
            raise AdapterError("copilot was not found on the agent PATH")
        if not req.prompt.strip():
            raise AdapterError("the prompt is empty")
        mode = req.permission_policy.mode
        step_dir = req.result_path.parent
        step_dir.mkdir(parents=True, exist_ok=True)
        req.result_path.unlink(missing_ok=True)
        usage_path = step_dir / USAGE_FILE
        usage_path.unlink(missing_ok=True)
        session_id = req.preset_session_id or str(uuid.uuid4())
        env = {**req.env, "COPILOT_HOME": str(write_home(step_dir / HOME_DIR))}
        env.pop("COPILOT_ALLOW_ALL", None)  # exactly "true" would also trust the worktree's hooks and MCP servers
        argv = build_command(req, exe=exe, session_id=session_id, usage_path=usage_path)
        workdir = judge_workdir(req) if mode == "judge" else req.cwd
        with credential_loader(req) as load:  # the credential table does not know `copilot` yet: identity here
            cmd = wrap_command(req, load(argv), env, workdir)
            outcome = self._proc.run(
                cmd.argv, cmd.env, workdir, stdout_path=req.raw_events_path,
                stderr_path=req.raw_events_path.with_suffix(".stderr"), stdin=req.prompt, timeout_s=req.timeout_s,
                interrupt=req.interrupt, stall_timeout_s=req.stall_timeout_s, watch=req.watch,
            )  # fmt: skip
        text = _read(req.raw_events_path)
        try:
            usage_document = json.loads(_read(usage_path) or "null")
        except ValueError:
            usage_document = None
        return parse(
            text, exit_code=outcome.returncode, raw_events_path=req.raw_events_path, mode=mode,
            stderr_text=_read(req.raw_events_path.with_suffix(".stderr")), usage_document=usage_document,
            result_text=read_result_file(req.result_path) if mode == "implement" else None, schema=req.result_schema,
            timed_out=outcome.timed_out or outcome.stalled, interrupted=outcome.interrupted,
        )  # fmt: skip


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
