"""Codex CLI adapter (codex-cli 0.160.0), invoked exactly as SPEC 8.3.1 / spikes/00-summary 3.2 confirm:

    codex exec --json -m M -c model_reasoning_effort=E -s workspace-write --ignore-user-config --ignore-rules
        -c project_doc_max_bytes=0 --output-schema <strict> -o <result> -        # stdin: the prompt, then EOF

Fresh runs only (no resume), never `--full-auto` (removed in 0.160.0). The result arrives through `-o`, not the
stream (the stream is not an audit trail). M1: agent-factory 4.3 (quota probe), session resume.
"""

import contextlib
import copy
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from l4.agents.activity import codex_signals
from l4.agents.base import (
    AdapterError,
    AgentCaps,
    LimitSignal,
    McpServer,
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
from l4.agents.claude_code import STRUCTURED_DETAIL
from l4.agents.credentials import credential_loader
from l4.agents.proc import ProcRunner
from l4.availability.limits import parse_reset
from l4.availability.probes import probe_codex
from l4.config.schema import Profile
from l4.safepath import resolve_tool
from l4.schemacheck import validate

STRICT_SCHEMA_FILE = "output-schema.strict.json"


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    if "type" in schema:
        kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        return {**schema, "type": kinds if "null" in kinds else [*kinds, "null"]}
    if "enum" in schema:
        return {**schema, "enum": schema["enum"] if None in schema["enum"] else [*schema["enum"], None]}
    return {"anyOf": [schema, {"type": "null"}]}


def _item_donors(schema: dict[str, Any], found: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Property name -> the `items` of the first array of that name that has some, anywhere in the schema."""
    for name, sub in schema.get("properties", {}).items():
        if sub.get("type") == "array" and isinstance(sub.get("items"), dict):
            found.setdefault(name, sub["items"])
        _item_donors(sub, found)
    if isinstance(schema.get("items"), dict):
        _item_donors(schema["items"], found)
    return found


def _strictify(schema: dict[str, Any], donors: dict[str, dict[str, Any]], name: str | None) -> dict[str, Any]:
    out = {key: copy.deepcopy(value) for key, value in schema.items() if key not in ("$id", "$schema")}
    if "properties" in schema:
        required = set(schema.get("required", []))
        properties = {}
        for prop, sub in schema["properties"].items():
            strict = _strictify(sub, donors, prop)
            properties[prop] = strict if prop in required else _nullable(strict)
        out["properties"] = properties
        out["required"] = list(properties)
        out["additionalProperties"] = False
    if isinstance(schema.get("items"), dict):
        out["items"] = _strictify(schema["items"], donors, None)
    elif schema.get("type") == "array":
        # a strict backend rejects an array that does not say what it holds ("array schema missing items"); the judge
        # verdict schema leaves `findings[].evidence` open, so it holds what `criteria[].evidence` holds [V live]
        donor = donors.get(name or "")
        if donor is None:
            raise AdapterError(f"the array {name or '<root>'!r} has no `items` and a strict schema needs them")
        out["items"] = _strictify(donor, donors, None)
    return out


def strictify_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """The copy OpenAI-strict structured output accepts (L4-FAC-009): `additionalProperties: false` on every object,
    every property required, the originally optional ones nullable, `$id` removed, every array given its `items`.
    A copy; the input is untouched."""
    return _strictify(schema, _item_donors(schema, {}), None)


def drop_nulls(value: Any) -> Any:
    """`null` back to absent: the inverse of making optional properties nullable."""
    if isinstance(value, dict):
        return {key: drop_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [drop_nulls(item) for item in value]
    return value


_REJECTED = re.compile(r"codex_core::tools::router\b.*?error=(?P<tool>\w+) failed:.*?Rejected\((?P<inner>.*)\)\"")
_POLICY_REASON = re.compile(r"`\s+rejected:\s+(?P<reason>.*?)\\?\"?$")


def rejections_from_stderr(text: str) -> list[dict[str, str]]:
    """The policy-rejected tool calls the `--json` stream omits (SPEC §8.3): one `{tool, reason}` per stderr line
    `codex_core::tools::router … Rejected(…)`. Only the policy's own wording is kept (it follows the quoted command
    line); a line without it says just `rejected`, because the command line may carry a secret."""
    found = []
    for line in text.splitlines():
        m = _REJECTED.search(line)
        if m is None:
            continue
        why = _POLICY_REASON.search(m.group("inner"))
        found.append({"tool": m.group("tool"), "reason": why.group("reason")[:200] if why else "rejected"})
    return found


def _events(lines: Sequence[str]) -> list[dict[str, Any]]:
    out = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue  # codex also prints plain-text notices; only JSON objects are events
        if isinstance(event, dict):
            out.append(event)
    return out


def _failure_text(events: list[dict[str, Any]], exit_code: int) -> str | None:
    """The `turn.failed` message, else (only when codex exited non-zero: it also sends non-fatal `error` notices
    such as reconnects in a run that succeeds) the last top-level `error` event's message."""
    for event in reversed(events):
        if event.get("type") == "turn.failed":
            error = event.get("error")
            return str(error.get("message", "")) if isinstance(error, dict) else str(error or "")
    if exit_code != 0:
        for event in reversed(events):
            if event.get("type") == "error":
                return str(event.get("message") or "")
    return None


def _usage(events: list[dict[str, Any]]) -> Usage:
    for event in reversed(events):
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            raw = event["usage"]
            return Usage(
                input_tokens=int(raw.get("input_tokens", 0)),
                output_tokens=int(raw.get("output_tokens", 0)),
                cached_input_tokens=int(raw.get("cached_input_tokens", 0)),
            )
    return Usage()


_MCP_NAME = re.compile(r"[A-Za-z0-9_-]+")


_URL_USERINFO = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]*@")


def _toml(value: str) -> str:
    """A JSON string is a TOML basic string, except for DEL: JSON leaves it raw and TOML forbids it."""
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _argv_safe(value: str) -> str:
    """The override rides on argv, which any local user can read with `ps`: a URL's credentials (`http://u:p@host`
    in a proxy variable) stay out of it."""
    return _URL_USERINFO.sub(r"\1", value)


def _mcp_overrides(server: McpServer) -> list[str]:
    """`-c mcp_servers.<name>.*` for one server. `--ignore-user-config` leaves the config file out, so these are the
    only MCP servers the run has."""
    if not _MCP_NAME.fullmatch(server.name):
        raise AdapterError(f"{server.name!r} is not a usable MCP server name")
    base = f"mcp_servers.{server.name}"
    env = ", ".join(f"{_toml(name)} = {_toml(_argv_safe(value))}" for name, value in server.env)
    rows = [
        f"{base}.command={_toml(server.command)}",
        f"{base}.args=[{', '.join(_toml(a) for a in server.args)}]",
        f"{base}.env={{{env}}}",
        f"{base}.startup_timeout_sec={server.startup_timeout_s}",
    ]
    return [arg for row in rows for arg in ("-c", row)]


class CodexAdapter:
    name = "codex"

    def __init__(self, runner: ProcRunner | None = None) -> None:
        self._proc = runner or ProcRunner()

    def capabilities(self) -> AgentCaps:
        return AgentCaps("native", False, False, False, False, False, True, True)

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        return probe_codex(profile, step, ctx)

    def build_command(self, req: RunRequest, *, exe: str, schema_path: Path | None) -> list[str]:
        profile = req.profile
        mode = req.permission_policy.mode
        sandbox = "workspace-write" if mode == "implement" else "read-only"
        # a judge leaves no session and runs in an empty directory, which is no git repository (`exec` refuses one); a
        # reader (the delegate) runs in a worktree, so it needs no such flag, but it leaves no session either
        argv = [exe, "exec", "--json"]
        if mode in ("judge", "read_only"):
            argv.append("--ephemeral")
        if mode == "judge":
            argv.append("--skip-git-repo-check")
        if profile.model:
            argv += ["-m", profile.model]
        effort = profile.options.get("reasoning_effort")
        if effort:
            argv += ["-c", f"model_reasoning_effort={effort}"]
        # `project_doc_max_bytes=0` is the only switch that keeps the repository's AGENTS.md out of the prompt
        # ("# AGENTS.md instructions for <wt>"); no switch removes `.agents/skills` or `.codex/skills` (the sandbox
        # masks those, L4-SEC-002) [V live, l4-runner, HB-X1]
        argv += ["-s", sandbox, "--ignore-user-config", "--ignore-rules", "-c", "project_doc_max_bytes=0"]
        for server in req.mcp_servers if mode == "implement" else ():  # a judge or reader gets no tool server
            argv += _mcp_overrides(server)
        if schema_path is not None:
            argv += ["--output-schema", str(schema_path)]
        return [*argv, "-o", str(req.result_path), "-"]

    def run(self, req: RunRequest) -> RunResult:
        exe = resolve_tool("codex", req.env, forbid=(req.cwd,))
        if exe is None:
            raise AdapterError("codex was not found on the agent PATH")
        req.result_path.parent.mkdir(parents=True, exist_ok=True)
        req.result_path.unlink(missing_ok=True)  # a leftover from an earlier step must not pass for this one's result
        schema_path = None
        if req.result_schema is not None:
            schema_path = req.result_path.parent / STRICT_SCHEMA_FILE
            schema_path.write_text(json.dumps(strictify_schema(req.result_schema)), encoding="utf-8")
        argv = self.build_command(req, exe=exe, schema_path=schema_path)
        workdir = judge_workdir(req) if req.permission_policy.mode == "judge" else req.cwd
        stderr_path = req.raw_events_path.with_suffix(".stderr")
        with credential_loader(req) as load:
            cmd = wrap_command(req, load(argv), req.env, workdir)
            outcome = self._proc.run(
                cmd.argv, cmd.env, workdir, stdout_path=req.raw_events_path, stderr_path=stderr_path,
                stdin=req.prompt, timeout_s=req.timeout_s, interrupt=req.interrupt,
                stall_timeout_s=req.stall_timeout_s,
                watch=req.watch, reader=codex_signals,
            )  # fmt: skip
        result_text = read_result_file(req.result_path)
        result = self.parse(
            req.raw_events_path.read_text(encoding="utf-8", errors="replace").splitlines(),
            exit_code=outcome.returncode, timed_out=outcome.timed_out or outcome.stalled,
            interrupted=outcome.interrupted, result_text=result_text, schema=req.result_schema,
            raw_events_path=req.raw_events_path, judge=req.permission_policy.mode == "judge",
        )  # fmt: skip
        with contextlib.suppress(OSError):  # no stderr file: nothing to report
            result.tool_rejections = rejections_from_stderr(stderr_path.read_text(encoding="utf-8", errors="replace"))
        return result

    def parse(
        self,
        lines: Sequence[str],
        *,
        exit_code: int,
        raw_events_path: Path,
        timed_out: bool = False,
        interrupted: bool = False,
        result_text: str | None = None,
        schema: dict[str, Any] | None = None,
        judge: bool = False,
        now: datetime | None = None,
    ) -> RunResult:
        """Status from the events and the exit code together (L4-FAC-002). Pure: recorded output replays through it.
        `judge`: a reply that is missing or breaks the schema is reported as a structured-output problem, which the
        judge turns into one repair round instead of "cannot run"."""
        events = _events(lines)
        thread = next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None)
        messages = [
            e["item"].get("text")
            for e in events
            if e.get("type") == "item.completed"
            and isinstance(e.get("item"), dict)
            and e["item"].get("type") == "agent_message"
        ]
        result = RunResult(
            status="error", raw_events_path=raw_events_path, final_text=messages[-1] if messages else None,
            last_message=messages[-1] if messages else None, session_id=thread, exit_code=exit_code,
            usage=_usage(events),
        )  # fmt: skip
        if timed_out:
            result.status = "timeout"
            return result
        if interrupted:
            result.status = "cancelled"
            return result
        failure = _failure_text(events, exit_code)
        if failure is not None:
            self._classify_failure(result, failure, now or datetime.now(UTC))
            return result
        if exit_code != 0:
            result.detail = f"codex exited with code {exit_code}"
            return result
        if not any(e.get("type") == "turn.completed" for e in events):
            result.detail = "the stream ended without turn.completed"
            return result
        return self._attach_result(result, result_text, schema, STRUCTURED_DETAIL if judge else "result")

    @staticmethod
    def _classify_failure(result: RunResult, message: str, now: datetime) -> None:
        text = message.replace("’", "'").lower()
        if "invalid_json_schema" in text:
            result.detail = "codex rejected the output schema (configuration error)"
        elif "usage limit" in text:
            result.status = "quota"
            result.limit = LimitSignal(
                "codex", None, "usage_limit", parse_reset(message, now), "text", re.sub(r"\s+", " ", message)[:200]
            )
        elif "not supported" in text:
            result.detail = "codex rejected the model (configuration error)"
        else:
            result.detail = "codex reported a failure"

    @staticmethod
    def _attach_result(
        result: RunResult, result_text: str | None, schema: dict[str, Any] | None, label: str
    ) -> RunResult:
        if result_text is None:
            if schema is not None:
                result.detail = f"{label} missing: codex wrote no -o file"
                result.result_problem = "missing"
                return result
            result.status = "ok"
            return result
        try:
            parsed = drop_nulls(json.loads(result_text))
        except ValueError:
            result.detail = f"{label} invalid: not JSON"
            result.result_problem = "not_json"
            return result
        problems = validate(parsed, schema) if schema is not None else []
        if not isinstance(parsed, dict) or problems:
            result.detail = f"{label} invalid: " + "; ".join(problems[:3] or ["not an object"])
            result.rejected = parsed if isinstance(parsed, dict) else None
            result.result_problem = "invalid"
            return result
        result.structured = parsed
        result.status = "ok"
        return result
