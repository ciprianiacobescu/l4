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
from typing import Any, Literal

from l4.agents.activity import copilot_signals
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
from l4.config.defaults import copilot_cache
from l4.config.schema import Profile
from l4.fsutil import read_regular_file
from l4.safepath import resolve_tool

NAME = "copilot-cli"
BINARY = "copilot"
CREDENTIAL_VARIABLE = "COPILOT_GITHUB_TOKEN"  # highest precedence; GH_TOKEN / GITHUB_TOKEN are forge tokens in L4
HOME_DIR = "copilot-home"
USAGE_FILE = "copilot-usage.json"
MCP_FILE = "copilot-mcp.json"
USAGE_LIMIT = 1_048_576  # the largest usage document read (1 MiB)
NO_TOOLS = "l4_no_tools"  # an unknown tool name: the allow-list then admits nothing [V 1.0.102]
READ_TOOLS = ("view", "grep", "glob")  # on gpt models the CLI serves `grep` as `rg` [V]; both names count as reads
READ_TOOL_NAMES = frozenset({*READ_TOOLS, "rg"})
AUTO_MODEL = "auto"
DENIAL_LIMIT = 20  # denied tool calls in a row that stop a run (D7)
HOME_SETTINGS = {
    "autoUpdate": False,
    "disableAllHooks": True,
    "memory": False,
    "includeCoAuthoredBy": False,  # default true: the agent would be told to add a Co-authored-by trailer
}  # read from `$COPILOT_HOME/settings.json` [V: `copilot config --list` shows each]
COMMON_FLAGS = (
    "--output-format", "json", "--no-ask-user", "--no-auto-update", "--no-custom-instructions",
    "--disable-builtin-mcps", "--disable-client-telemetry", "--disallow-temp-dir",
)  # fmt: skip
RUN_CACHE_DIR = "xdg-cache"
_NO_AUTH = re.compile(r"No authentication information found", re.I)
_TOKEN_UNVALIDATED = re.compile(r"Authentication token found but could not be validated", re.I)
_REJECTED_STATUS = re.compile(r"\((?:401|403)\)")
_EXTRACT_FAILED = re.compile(r"Failed to extract bundled package", re.I)
_SOURCE_FAILURE, _SOURCE_RETRY = "copilot.model_call_failure", "copilot.turn_retry"


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


def effective_model(profile: Profile) -> str:
    """The model a run names: the profile's, else `auto`; `auto` in any letter case is `auto` (D2)."""
    model = (profile.model or "").strip()
    return AUTO_MODEL if not model or model.lower() == AUTO_MODEL else model


def write_run_cache(step_dir: Path, environ: Mapping[str, str]) -> Path:
    """A fresh per-run `XDG_CACHE_HOME` at `<step_dir>/xdg-cache` (D14): the CLI finds its warm package through
    `xdg-cache/copilot/pkg`, a link to the harness's read-only Copilot cache (made whether or not that target exists),
    and every other tool of the agent writes under `xdg-cache/<tool>`. The directory is removed first, so a package
    an agent planted in an earlier run's directory is never used. Returns the directory."""
    cache = step_dir / RUN_CACHE_DIR
    if cache.is_symlink():
        cache.unlink()
    elif cache.exists():
        shutil.rmtree(cache)
    (cache / "copilot").mkdir(parents=True)
    (cache / "copilot" / "pkg").symlink_to(copilot_cache(environ) / "copilot" / "pkg")
    return cache


def build_command(
    req: RunRequest, *, exe: str, session_id: str, usage_path: Path, mcp_config: Path | None = None
) -> list[str]:
    """The argv of D2 and D3 to D5. The prompt is not in it (stdin carries it). `mcp_config` is the file of the
    request's MCP servers, used in implement mode only."""
    mode = req.permission_policy.mode
    argv = [exe, *COMMON_FLAGS, "--session-id", session_id, "--usage-output-file", str(usage_path)]
    argv += ["--model", effective_model(req.profile)]
    if mode == "judge":
        return [*argv, f"--available-tools={NO_TOOLS}"]
    if mode == "read_only":
        return [*argv, f"--available-tools={','.join(READ_TOOLS)}"]
    argv += ["--allow-tool=write", *gate_rule(req.permission_policy.gate_prefix)]
    argv += ["--add-dir", str(req.result_path.parent)]
    if mcp_config is not None and req.mcp_servers:
        argv += ["--additional-mcp-config", f"@{mcp_config}"]
        argv += [f"--allow-tool={server.name}" for server in req.mcp_servers]
    return argv


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


def _data(event: Mapping[str, Any], key: str = "data") -> Mapping[str, Any]:
    value = event.get(key)
    return value if isinstance(value, dict) else {}


def _status(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def stream_facts(stream: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """`session_id` (the final `result`), `result_seen` (a `result` event came: a run killed from outside has none),
    `final_text` (the last non-empty assistant content), `last_message` (the content of the last assistant message
    after the last tool call), `model` (the served model of the last assistant message, else the model that
    `session.auto_mode_resolved` chose), `tools` (every tool started, in order), `denials` (`{tool_name}` per denied
    call), `error` (the last `session.error`), `retry_reasons` (every `assistant.turn_retry` reason),
    `call_failure_statuses` (every `model.call_failure` status) and `rate_limit_source` (the limit source of the first
    429 failure or `rate_limit` retry, whichever came first)."""
    facts: dict[str, Any] = {
        "tools": [], "denials": [], "retry_reasons": [], "call_failure_statuses": [], "result_seen": False,
    }  # fmt: skip
    started: dict[str, str] = {}
    last_message: str | None = None
    chosen: str | None = None
    for event in stream:
        kind, data = event["type"], _data(event)
        if kind == "assistant.message":
            content = data["content"] if isinstance(data.get("content"), str) else ""
            if isinstance(data.get("model"), str) and data["model"]:
                facts["model"] = data["model"]
            if content.strip():
                facts["final_text"] = content
                last_message = content
        elif kind == "tool.execution_start":
            name = data["toolName"] if isinstance(data.get("toolName"), str) else "unknown"
            facts["tools"].append(name)
            started[str(data.get("toolCallId"))] = name
            last_message = None  # only text after the last tool call is the last message
        elif kind == "tool.execution_complete":
            error = _data(data, "error")
            if error.get("code") == "denied":
                facts["denials"].append({"tool_name": started.get(str(data.get("toolCallId")), "unknown")})
        elif kind == "session.error":
            facts["error"] = data
        elif kind == "session.auto_mode_resolved":
            if isinstance(data.get("chosenModel"), str) and data["chosenModel"]:
                chosen = data["chosenModel"]
        elif kind == "model.call_failure":
            status = _status(data.get("statusCode"))
            if status is not None:
                facts["call_failure_statuses"].append(status)
            if status == 429:
                facts.setdefault("rate_limit_source", _SOURCE_FAILURE)
        elif kind == "assistant.turn_retry" and isinstance(data.get("reason"), str):
            facts["retry_reasons"].append(data["reason"])
            if data["reason"] == "rate_limit":
                facts.setdefault("rate_limit_source", _SOURCE_RETRY)
        elif kind == "result":
            facts["result_seen"] = True
            facts["session_id"] = event.get("sessionId") if isinstance(event.get("sessionId"), str) else None
    if last_message is not None:
        facts["last_message"] = last_message
    if "model" not in facts and chosen is not None:
        facts["model"] = chosen  # a run that failed after `auto` routing still names its model (F39)
    return facts


def usage_of(document: Any) -> Usage:
    """Tokens summed over `modelMetrics`; `totalNanoAiu` as AI credits (1e-9 units, the unit's name [U]); never
    dollars. An unreadable document is zero usage."""
    if not isinstance(document, dict):
        return Usage()
    sums = {"inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0}
    metrics_by_model = document.get("modelMetrics")
    for metrics in metrics_by_model.values() if isinstance(metrics_by_model, dict) else ():
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


def read_usage(path: Path) -> Any:
    """The usage document at `path`, read as a regular file of at most `USAGE_LIMIT` bytes (a link, a directory, a
    larger file, a missing or unparsable file is None, which `usage_of` turns into zero usage; D8)."""
    try:
        return json.loads(read_regular_file(path, limit=USAGE_LIMIT))
    except (OSError, ValueError, RecursionError):
        return None


class CopilotStop:
    """The `on_line` watcher of D7, passed to `ProcRunner.run`: True stops the run. It stops on the first
    `model.call_failure` with status 429 (or the first `assistant.turn_retry` with reason `rate_limit`, if that comes
    first: `reason` is `rate_limit`, `source` the limit source of the event), and when `DENIAL_LIMIT`
    `tool.execution_complete` events in a row are denied (`reason` is `denials`; any other completion resets the
    count). It keeps no text of a line, ignores a line that is not a JSON object and never raises."""

    def __init__(self) -> None:
        self.reason: Literal["rate_limit", "denials"] | None = None
        self.source: str | None = None
        self._denied = 0

    def __call__(self, line: str) -> bool:
        if self.reason is not None:
            return True
        try:
            return self._watch(json.loads(line))
        except Exception:  # noqa: BLE001 - a hook that raises would take the run's pump thread down
            return False

    def _watch(self, event: Any) -> bool:
        if not isinstance(event, dict):
            return False
        kind, data = event.get("type"), _data(event)
        if kind == "model.call_failure" and _status(data.get("statusCode")) == 429:
            self.reason, self.source = "rate_limit", _SOURCE_FAILURE
        elif kind == "assistant.turn_retry" and data.get("reason") == "rate_limit":
            self.reason, self.source = "rate_limit", _SOURCE_RETRY
        elif kind == "tool.execution_complete":
            error = _data(data, "error")
            self._denied = self._denied + 1 if error.get("code") == "denied" else 0
            if self._denied >= DENIAL_LIMIT:
                self.reason = "denials"
        return self.reason is not None


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
    stop: Literal["rate_limit", "denials"] | None = None,
) -> RunResult:
    """The run's `RunResult` from its stream, exit code and standard error. The status, first match wins (D6, D7):
    the watcher's `stop`; a timeout with a 429 in the stream; timeout or cancel; no stream and a standard error that
    says why (no credential, a rejected token); the last `session.error`; a cold package cache; any other non-zero
    exit; else the mode decides."""
    stream = events(text)
    facts = stream_facts(stream)
    result = RunResult(status="error", raw_events_path=raw_events_path, exit_code=exit_code)
    result.session_id, result.final_text = facts.get("session_id"), facts.get("final_text")
    result.last_message, result.model_resolved = facts.get("last_message"), facts.get("model")
    result.permission_denials = facts["denials"]
    result.usage = usage_of(usage_document)
    error = facts.get("error") or {}
    status = _status(error.get("statusCode"))
    result.api_status = status
    rate_source = facts.get("rate_limit_source")

    def limited(kind: Literal["rate_limit", "auth", "credits"], source: str) -> None:
        result.limit = LimitSignal(NAME, result.model_resolved, kind, None, source, "")

    if stop == "rate_limit":
        result.status = "rate_limited"
        result.detail = f"{NAME} hit a rate limit (HTTP 429); the harness stopped the run (it never waits for a limit)"
        limited("rate_limit", rate_source or _SOURCE_FAILURE)
        return result
    if stop == "denials":
        result.status = "permission_blocked"
        result.detail = (
            f"{NAME} was stopped after {DENIAL_LIMIT} denied tool calls in a row: "
            "its permission rules refuse what it tries"
        )
        return result
    if timed_out and rate_source and not facts["result_seen"]:  # the CLI was waiting out a 429 itself
        result.status, result.detail = "rate_limited", f"{NAME} was waiting out a rate limit when the run timed out"
        limited("rate_limit", rate_source)
        return result
    if timed_out or interrupted:
        result.status = "timeout" if timed_out else "cancelled"
        return result
    if exit_code != 0 and not stream:
        if _NO_AUTH.search(stderr_text):
            result.status, result.detail = "auth", f"{NAME} found no credential (set {CREDENTIAL_VARIABLE})"
        elif _TOKEN_UNVALIDATED.search(stderr_text) and _REJECTED_STATUS.search(stderr_text):
            result.status, result.detail = "auth", _T6
            limited("auth", "copilot.stderr")
        elif _TOKEN_UNVALIDATED.search(stderr_text):  # the CLI's own text says the token may still be valid
            result.detail = f"{NAME} could not validate {CREDENTIAL_VARIABLE} (no 401 or 403: the network?)"
            result.transient = True
        else:
            result = _failed_exit(result, text, stderr_text, exit_code)
        return result
    if error:
        if error.get("errorType") == "authentication" or status in (401, 403):
            result.status, result.detail = "auth", _T6
            limited("auth", "copilot.session_error")
        elif status == 429:
            result.status, result.detail = "rate_limited", f"{NAME} reported a rate limit (session.error 429)"
            limited("rate_limit", "copilot.session_error")
        elif status == 402:
            result.status = "quota"
            result.detail = f"{NAME} reported that the AI credits are used up (session.error 402)"
            limited("credits", "copilot.session_error")
        else:
            result.detail = (
                f"{NAME} reported an error ({error.get('errorType') or 'unknown'}, "
                f"status {status if status is not None else 'none'})"
            )
            result.transient = status is not None and (status in TRANSIENT_STATUSES or status >= 500)
        return result
    if exit_code != 0:
        return _failed_exit(result, text, stderr_text, exit_code)
    if mode == "judge":
        if facts["tools"]:
            result.detail = f"{NAME} judge called a tool ({facts['tools'][0]})"
            return result
        attach_judge_reply(result, facts.get("final_text"), schema)
    elif mode == "read_only":
        outside = sorted({t for t in facts["tools"] if t not in READ_TOOL_NAMES})
        if outside:
            result.detail = f"{NAME} delegate called a tool outside the read set ({', '.join(outside)})"
            return result
        attach_read_only_reply(result, facts.get("last_message"), facts.get("final_text"), schema)
    else:
        attach_file_result(result, result_text, schema, NAME)
    return result


_T6 = f"{NAME} could not authenticate ({CREDENTIAL_VARIABLE} is missing, expired or rejected)"


def _failed_exit(result: RunResult, text: str, stderr_text: str, exit_code: int) -> RunResult:
    """D6 rules 6 and 7: a cold package cache names its fix, any other non-zero exit its code."""
    if _EXTRACT_FAILED.search(text) or _EXTRACT_FAILED.search(stderr_text):
        result.detail = (
            f"{NAME} could not extract its bundled package (the L4 package cache is cold or not writable): "
            "run l4 doctor --fix"
        )
    else:
        result.detail = f"{NAME} exited with code {exit_code}"
    return result


class CopilotCliAdapter:
    """The Copilot CLI adapter. `exe` is a binary path that skips the PATH lookup: only the simulation's replay passes
    it. `probe` answers the `binary` step only until task 4.1."""

    name = NAME
    experimental = True

    def __init__(self, runner: ProcRunner | None = None, exe: str | None = None) -> None:
        self._exe = exe
        self._proc = runner or ProcRunner()

    def capabilities(self) -> AgentCaps:
        # no native schema flag, no resume flag observed, no max-turns flag (only a soft --max-ai-credits >= 30)
        return AgentCaps("prompt_contract", False, True, False, False, True, False, True, served_model=True)

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        if step == "binary":
            return _binary(BINARY, profile, ctx)[0]
        return ProbeResult(step, True, skipped=True, reason="copilot spike: only the binary step is prototyped")

    def run(self, req: RunRequest) -> RunResult:
        exe = self._exe or resolve_tool(BINARY, req.env, forbid=(req.cwd,))
        if exe is None:
            raise AdapterError("copilot was not found on the agent PATH")
        if not req.prompt.strip():
            raise AdapterError(f"the prompt is empty; {NAME} reads its prompt from stdin")
        mode = req.permission_policy.mode
        step_dir = req.result_path.parent
        step_dir.mkdir(parents=True, exist_ok=True)
        req.result_path.unlink(missing_ok=True)  # a leftover from an earlier step must not pass for this one's result
        usage_path = step_dir / USAGE_FILE
        usage_path.unlink(missing_ok=True)
        session_id = req.preset_session_id or str(uuid.uuid4())
        env = {
            **req.env,
            "COPILOT_HOME": str(write_home(step_dir / HOME_DIR)),
            "COPILOT_AUTO_UPDATE": "false",
            "XDG_CACHE_HOME": str(write_run_cache(step_dir, req.host_env)),
        }
        for name in ("COPILOT_ALLOW_ALL", CREDENTIAL_VARIABLE, "GH_TOKEN", "GITHUB_TOKEN", "CI"):
            env.pop(name, None)  # "true" would trust the worktree's hooks and MCP servers; the rest are L4-SEC-001/040
        mcp_config = self._write_mcp_config(req, step_dir / MCP_FILE) if mode == "implement" else None
        argv = build_command(req, exe=exe, session_id=session_id, usage_path=usage_path, mcp_config=mcp_config)
        workdir = judge_workdir(req) if mode == "judge" else req.cwd
        stop = CopilotStop()
        with credential_loader(req) as load:
            cmd = wrap_command(req, load(argv), env, workdir)
            outcome = self._proc.run(
                cmd.argv, cmd.env, workdir, stdout_path=req.raw_events_path,
                stderr_path=req.raw_events_path.with_suffix(".stderr"), stdin=req.prompt, timeout_s=req.timeout_s,
                interrupt=req.interrupt, stall_timeout_s=req.stall_timeout_s, watch=req.watch,
                reader=copilot_signals, on_line=stop,
            )  # fmt: skip
        text = _read(req.raw_events_path)
        return parse(
            text, exit_code=outcome.returncode, raw_events_path=req.raw_events_path, mode=mode,
            stderr_text=_read(req.raw_events_path.with_suffix(".stderr")), usage_document=read_usage(usage_path),
            result_text=read_result_file(req.result_path) if mode == "implement" else None, schema=req.result_schema,
            timed_out=outcome.timed_out or outcome.stalled, interrupted=outcome.interrupted, stop=stop.reason,
        )  # fmt: skip

    @staticmethod
    def _write_mcp_config(req: RunRequest, path: Path) -> Path | None:
        """`{"mcpServers": {<name>: <entry>}}` for the request's servers (D5; the file format is [G], F26)."""
        path.unlink(missing_ok=True)
        if not req.mcp_servers:
            return None
        entries = {server.name: server.config_entry() for server in req.mcp_servers}
        path.write_text(json.dumps({"mcpServers": entries}), encoding="utf-8")
        return path


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
