"""Claude Code adapter (claude 2.1.288), invoked as SPEC 8.3.1 / spikes/00-summary 3.1 confirm.

Used for the judge in M0 (`PermissionPolicy("judge")`: tool-less, native schema, one JSON document); the implementer
mode is built from the confirmed command but not exercised live. Isolation flags are inline: for subscription auth
`--setting-sources "" --disable-slash-commands` (+ `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`) for the implementer and
`--safe-mode` for the judge and the reader (HB-X1), `--bare` for api_key, `--strict-mcp-config` for all (L4-SEC-002).
M1: sandbox-security 1.17 (`isolation_flags`), agent-factory 1.9 (rate-limit interrupt), 1.8 (recorded replays).
"""

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
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
    wrap_command,
)
from l4.agents.credentials import credential_loader
from l4.agents.proc import ProcRunner
from l4.availability.probes import claude_windows_of, probe_claude
from l4.availability.quota import Window
from l4.config.schema import Profile
from l4.safepath import resolve_tool
from l4.schemacheck import validate

IMPLEMENT_TOOLS = "Read,Edit,Write,Glob,Grep,Bash"
READ_TOOLS = "Read,Grep,Glob"
MCP_CONFIG_FILE = "mcp.json"
JUDGE_MAX_TURNS = 3  # structured output costs one extra turn
AUTH_STATUSES = (401, 403)
EVENT_WINDOWS_TTL_S = 300  # how long the windows of a `rate_limit_event` stand in for a `/usage` call
# The factory builds a new adapter for every selection and probe, so the windows a run saw live at module level, per
# auth mode (one claude login per mode on a machine).
_LATEST_WINDOWS: dict[str | None, tuple[float, list[Window]]] = {}
STRUCTURED_DETAIL = "structured output"  # `RunResult.detail` of a reply that has no usable structured output


def _compact(schema: dict[str, Any]) -> str:
    return json.dumps(schema, separators=(",", ":"))


def _context_peak(documents: Sequence[Mapping[str, Any]]) -> int | None:
    """The largest per-call input of the `assistant` events: input + cache read + cache creation tokens."""
    peak: int | None = None
    for document in documents:
        message = document.get("message") if document.get("type") == "assistant" else None
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            continue
        parts = [usage.get(k) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")]
        total = sum(v for v in parts if isinstance(v, int) and not isinstance(v, bool))
        peak = total if peak is None else max(peak, total)
    return peak


def _documents(text: str) -> list[dict[str, Any]]:
    """Every JSON object in claude's stdout: one JSON document (`--output-format json`, an object or an array of
    events) or JSON lines (`stream-json`)."""
    try:
        whole = json.loads(text)
    except ValueError:
        whole = None
    if isinstance(whole, dict):
        return [whole]
    if isinstance(whole, list):
        return [item for item in whole if isinstance(item, dict)]
    out = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


class ClaudeCodeAdapter:
    name = "claude-code"
    extra_env: Mapping[str, str] = {
        "CLAUDE_CODE_MAX_RETRIES": "1",  # never CLAUDE_CODE_RETRY_WATCHDOG (waits out limits)
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",  # `--setting-sources` does not stop the auto-memory [V live, HB-X1]
    }

    def __init__(self, runner: ProcRunner | None = None) -> None:
        self._proc = runner or ProcRunner()

    def capabilities(self) -> AgentCaps:
        return AgentCaps("native", True, True, True, True, True, True, True, served_model=True)

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        seen = _LATEST_WINDOWS.get(profile.auth)
        fresh = seen[1] if seen and time.monotonic() - seen[0] < EVENT_WINDOWS_TTL_S else []
        return probe_claude(profile, step, ctx, latest=fresh)

    def build_command(self, req: RunRequest, *, exe: str, mcp_config: Path | None = None) -> list[str]:
        profile = req.profile
        mode = req.permission_policy.mode
        # `--safe-mode` keeps the stored login and loads no repo or user guidance, but silently drops `--mcp-config`
        # (Serena); only an implementer carries servers, so it runs with no settings source at all instead: no
        # CLAUDE.md, AGENTS.md, skills, hooks or commands, Serena connected [V live, claude 2.1.288, HB-X1]
        if profile.auth == "api_key":
            isolation = ["--bare"]
        elif mode == "implement":
            isolation = ["--setting-sources", "", "--disable-slash-commands"]
        else:
            isolation = ["--safe-mode"]
        if mode == "judge":
            argv = [exe, "-p", *(["--model", profile.model] if profile.model else [])]
            argv += ["--output-format", "json"]
            if req.result_schema is not None:
                argv += ["--json-schema", _compact(req.result_schema)]
            return [*argv, *isolation, "--strict-mcp-config", "--tools", "", "--no-session-persistence",
                    "--max-turns", str(req.max_turns or JUDGE_MAX_TURNS)]  # fmt: skip
        argv = [exe, "-p", "--output-format", "stream-json", "--verbose"]
        if profile.model:
            argv += ["--model", profile.model]
        if req.max_turns is not None:
            argv += ["--max-turns", str(req.max_turns)]
        if req.max_budget_usd is not None:
            argv += ["--max-budget-usd", str(req.max_budget_usd)]
        if req.resume_session_id:
            argv += ["--resume", req.resume_session_id]
        elif req.preset_session_id:
            argv += ["--session-id", req.preset_session_id]
        # `--mcp-config` names the only servers there are: `--strict-mcp-config` ignores every other source
        # and only an implement-mode request has any (a reader or judge gets no tool server)
        armed = mode == "implement"
        servers = ["--mcp-config", str(mcp_config)] if mcp_config is not None and armed else []
        tools = [f"mcp__{server.name}" for server in req.mcp_servers] if armed else []  # a server-wide allow rule
        if mode == "read_only":
            argv += ["--permission-mode", "plan", *isolation, *servers, "--strict-mcp-config", "--tools", READ_TOOLS]
            argv += ["--allowedTools", ",".join([READ_TOOLS, *tools])]
        else:
            # Edit is scoped to the worktree and the private result dir: a bare `Edit`/`Write` rule would match paths
            # outside the cwd (spikes/01), and `Bash` is limited to the gate command.
            rules = ["Read", "Glob", "Grep", "Edit(./**)", f"Edit(/{req.result_path.parent}/**)"]
            if req.permission_policy.gate_prefix:
                rules.append(f"Bash({req.permission_policy.gate_prefix}:*)")
            argv += ["--permission-mode", "dontAsk", *isolation, *servers, "--strict-mcp-config"]
            argv += ["--tools", IMPLEMENT_TOOLS]
            argv += ["--allowedTools", ",".join([*rules, *tools])]
        if req.result_schema is not None:
            argv += ["--json-schema", _compact(req.result_schema)]
        return argv

    @staticmethod
    def _write_mcp_config(req: RunRequest) -> Path:
        """Next to the result file: the agent's private tmp, which the sandbox mounts writable."""
        path = req.result_path.parent / MCP_CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        entries = {server.name: server.config_entry() for server in req.mcp_servers}
        path.write_text(json.dumps({"mcpServers": entries}), encoding="utf-8")
        return path

    def run(self, req: RunRequest) -> RunResult:
        exe = resolve_tool("claude", req.env, forbid=(req.cwd,))
        if exe is None:
            raise AdapterError("claude was not found on the agent PATH")
        armed = bool(req.mcp_servers) and req.permission_policy.mode == "implement"
        mcp_config = self._write_mcp_config(req) if armed else None
        argv = self.build_command(req, exe=exe, mcp_config=mcp_config)
        workdir = judge_workdir(req) if req.permission_policy.mode == "judge" else req.cwd
        with credential_loader(req) as load:
            cmd = wrap_command(req, load(argv), req.env, workdir)
            outcome = self._proc.run(
                cmd.argv, cmd.env, workdir, stdout_path=req.raw_events_path,
                stderr_path=req.raw_events_path.with_suffix(".stderr"), stdin=req.prompt, timeout_s=req.timeout_s,
                interrupt=req.interrupt,
                # the judge's `--output-format json` prints once, at the end: silence is normal there
                stall_timeout_s=None if req.permission_policy.mode == "judge" else req.stall_timeout_s,
            )  # fmt: skip
        text = req.raw_events_path.read_text(encoding="utf-8", errors="replace")
        if windows := claude_windows_of(text):
            _LATEST_WINDOWS[req.profile.auth] = (time.monotonic(), windows)
        return self.parse(
            text, exit_code=outcome.returncode, timed_out=outcome.timed_out or outcome.stalled,
            interrupted=outcome.interrupted, schema=req.result_schema, raw_events_path=req.raw_events_path,
        )  # fmt: skip

    def parse(
        self,
        text: str,
        *,
        exit_code: int,
        raw_events_path: Path,
        timed_out: bool = False,
        interrupted: bool = False,
        schema: dict[str, Any] | None = None,
    ) -> RunResult:
        """Status from `is_error` + `api_error_status`, never from `subtype` (a bad model says `success`); the only
        legitimate use of `subtype` is max turns / budget, where `result` is null (L4-FAC-002). Pure."""
        documents = _documents(text)
        results = [d for d in documents if d.get("type") == "result"]
        final = results[-1] if results else None
        result = RunResult(status="error", raw_events_path=raw_events_path, exit_code=exit_code)
        if final is not None:
            self._fill(result, final)
            result.usage = replace(result.usage, context_peak_tokens=_context_peak(documents))
        if timed_out:
            result.status = "timeout"
            return result
        if interrupted:
            result.status = "cancelled"
            return result
        if final is None:
            result.detail = "no result event in claude's output"
            return result
        failed = bool(final.get("is_error")) or str(final.get("subtype", "success")).startswith("error")
        rejected = next(
            (
                d["rate_limit_info"]
                for d in documents
                if d.get("type") == "rate_limit_event"
                and isinstance(d.get("rate_limit_info"), dict)
                and d["rate_limit_info"].get("status") == "rejected"
            ),
            None,
        )
        http = final.get("api_error_status")
        subtype = final.get("subtype")
        if failed and rejected is not None:
            result.status = "quota"
            result.limit = self._limit(rejected)
        elif failed and http in AUTH_STATUSES:
            result.status = "auth"
        elif failed and http == 429:
            result.status = "rate_limited"
            result.limit = LimitSignal("claude-code", result.model_resolved, "rate_limit", None, "claude.http_429", "")
        elif subtype == "error_max_turns":
            result.status = "max_turns"
        elif subtype == "error_max_budget_usd":
            result.status = "budget"
        elif failed:
            result.detail = f"claude reported an error (api_error_status {http})"
            result.api_status = http if isinstance(http, int) and not isinstance(http, bool) else None
            result.transient = http in TRANSIENT_STATUSES or "overloaded_error" in (result.final_text or "")
        elif exit_code != 0:
            result.detail = f"claude exited with code {exit_code}"
        else:
            self._attach_structured(result, final, schema)
        return result

    @staticmethod
    def _limit(info: Mapping[str, Any]) -> LimitSignal:
        resets = info.get("resetsAt")
        when = datetime.fromtimestamp(resets, UTC) if isinstance(resets, int | float) else None
        kind = "usage_limit" if info.get("rateLimitType") in ("five_hour", "seven_day") else "rate_limit"
        return LimitSignal("claude-code", None, kind, when, "claude.rate_limit_event", "")

    @staticmethod
    def _fill(result: RunResult, final: Mapping[str, Any]) -> None:
        text = final.get("result")
        result.final_text = text if isinstance(text, str) else None
        result.last_message = result.final_text
        session = final.get("session_id")
        result.session_id = session if isinstance(session, str) else None
        usage = final.get("usage") if isinstance(final.get("usage"), dict) else {}
        cost = final.get("total_cost_usd")
        result.usage = Usage(
            input_tokens=int(usage.get("input_tokens", 0)), output_tokens=int(usage.get("output_tokens", 0)),
            cached_input_tokens=int(usage.get("cache_read_input_tokens", 0)),
            cost_usd=float(cost) if isinstance(cost, int | float) else None,
        )  # fmt: skip
        served = final.get("modelUsage")
        if isinstance(served, dict) and served:
            result.model_resolved = max(
                served, key=lambda m: served[m].get("outputTokens", 0) if isinstance(served[m], dict) else 0
            )
        denials = final.get("permission_denials")
        result.permission_denials = [d for d in denials if isinstance(d, dict)] if isinstance(denials, list) else []

    @staticmethod
    def _attach_structured(result: RunResult, final: Mapping[str, Any], schema: dict[str, Any] | None) -> None:
        structured = final.get("structured_output")
        if schema is None:
            result.structured = structured if isinstance(structured, dict) else None
            if result.structured is None:
                result.result_problem = "missing"
            result.status = "ok"
            return
        if not isinstance(structured, dict):
            result.detail = f"{STRUCTURED_DETAIL} missing although a schema was requested"
            result.result_problem = "missing"
            return
        problems = validate(structured, schema)
        if problems:
            result.detail = f"{STRUCTURED_DETAIL} invalid: " + "; ".join(problems[:3])
            result.rejected = structured
            result.result_problem = "invalid"
            return
        result.structured = structured
        result.status = "ok"
