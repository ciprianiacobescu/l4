"""Shared agent types (SPEC 8.1, L4-FAC-001). Adapters build commands and parse output; they never wait for a limit."""

import shutil
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from l4.config.schema import Profile
from l4.fsutil import UnsafeFile, read_regular_file
from l4.sandbox.base import WrappedCommand

ProbeStep = Literal["binary", "auth", "quota", "hello"]
Status = Literal[
    "ok", "max_turns", "budget", "permission_blocked", "auth", "quota", "rate_limited", "error", "timeout", "cancelled"
]


class AdapterError(Exception):
    """A configuration or contract failure of an adapter (not a run outcome, which is a `RunResult.status`)."""


class EventSink(Protocol):
    """Satisfied by `l4.state.ledger.LedgerWriter`."""

    def append(self, event_type: str, /, **data: Any) -> object: ...


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cost_usd: float | None = None  # None where the CLI reports tokens only (codex)
    credits: float | None = None  # plan credits a CLI metered (Kiro): not dollars, never added to `cost_usd`
    credits_source: str | None = None  # where `credits` came from ("kiro.stream"); another source may disagree


@dataclass(frozen=True)
class LimitSignal:
    tool: str
    model: str | None
    kind: Literal["usage_limit", "rate_limit", "spend_limit", "credits", "auth", "model_mismatch"]
    resets_at: datetime | None  # tz-aware UTC
    source: str
    raw_excerpt: str  # redacted by the caller, at most 200 characters
    window_minutes: int | None = None
    used_percent: float | None = None


@dataclass(frozen=True)
class McpServer:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    startup_timeout_s: int = 30  # how long the CLI waits for the server to start (Codex's own default is 10)

    def config_entry(self) -> dict[str, Any]:
        """The server as an `mcpServers` entry of a Claude-style `--mcp-config` file."""
        return {"command": self.command, "args": list(self.args), "env": dict(self.env)}


@dataclass(frozen=True)
class PermissionPolicy:
    """`implement` edits the worktree and runs `gate_prefix`; `read_only` only reads; `judge` has no tools at all
    (a tool-less structured-output call, SPEC 8.1 "CLI judge")."""

    mode: Literal["implement", "read_only", "judge"]
    gate_prefix: str | None = None  # e.g. ".venv/bin/python -m pytest"; the only shell command an implementer may run


@dataclass(frozen=True)
class AgentCaps:
    schema_mode: Literal["native", "prompt_contract"]
    resume: bool
    preset_session_id: bool
    max_turns: bool
    budget_cap: bool
    mcp_injection: bool
    quota_query: bool
    worktree_cwd: bool
    served_model: bool = False  # the run reports the model that served it (claude-code `modelUsage`)


Runner = Callable[[Sequence[str], Path, Mapping[str, str], float], Any]
# (argv, cwd, env, timeout_s, messages) -> the JSON-RPC responses by request id: one stdio session, messages written
# up front (`codex app-server`, the only probe that needs a conversation rather than one command)
RpcRunner = Callable[[Sequence[str], Path, Mapping[str, str], float, Sequence[Mapping[str, Any]]], dict[int, Any]]
Wrapper = Callable[..., WrappedCommand]  # (argv, env[, cwd=<dir>]): `Sandbox.wrap` bound to the spec

JUDGE_DIR = "judge-cwd"  # an empty directory inside the step's private dir (always mounted by the sandbox)


def judge_workdir(req: "RunRequest") -> Path:
    """A tool-less call reads only its prompt, so it starts in an empty directory: a CLI cannot auto-load the
    repository's AGENTS.md or CLAUDE.md (written by an earlier agent step) into the independent check."""
    workdir = req.result_path.parent / JUDGE_DIR
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    return workdir


def wrap_command(req: "RunRequest", argv: Sequence[str], env: Mapping[str, str], workdir: Path) -> WrappedCommand:
    """The command to spawn: sandboxed when the request has a wrapper (told to start in `workdir` when that is not the
    request's own cwd), else as is."""
    if req.wrap is None:
        return WrappedCommand(list(argv), dict(env))
    return req.wrap(argv, env) if workdir == req.cwd else req.wrap(argv, env, cwd=workdir)


@dataclass(frozen=True)
class ProbeCtx:
    """What a probe may use: the host environment, a working directory outside any checkout, a runner."""

    environ: Mapping[str, str]
    cwd: Path
    run: Runner
    timeout_s: float = 60.0
    hello_prompt: str = "Reply with exactly: L4-OK"
    forbid: tuple[Path, ...] = ()  # checkouts a binary must not resolve into
    min_remaining_percent: float = 10  # `availability.min_remaining_percent`, set by the Factory
    min_remaining_usd: float = 0.50  # `availability.min_remaining_usd`, set by the Factory
    rpc: RpcRunner | None = None  # None: the real subprocess session (`l4.availability.rpc`)
    now: Callable[[], datetime] | None = None  # the Factory's clock; None: the system clock
    sleep: Callable[[float], None] | None = None  # the wait before the one retry of a transient hello; None: real


FailureClass = Literal["limit", "auth", "transient", "other"]


@dataclass
class ProbeResult:
    step: ProbeStep
    ok: bool
    detail: dict[str, Any] = field(default_factory=dict)  # never an e-mail, a token or raw CLI output
    reason: str | None = None
    limit: LimitSignal | None = None
    skipped: bool = False
    # a failed `hello` only (L4-AVL-005): how long the failure is remembered. None is `other`.
    failure_class: FailureClass | None = None


@dataclass
class RunRequest:
    profile: Profile
    role: str
    cwd: Path
    prompt: str
    result_path: Path
    raw_events_path: Path
    env: dict[str, str]  # allow-listed (SEC-001); forge tokens are never passed
    result_schema: dict[str, Any] | None = None
    resume_session_id: str | None = None
    preset_session_id: str | None = None
    mcp_servers: list[McpServer] = field(default_factory=list)
    permission_policy: PermissionPolicy = field(default_factory=lambda: PermissionPolicy("implement"))
    timeout_s: int = 1800
    stall_timeout_s: float | None = None  # kill a run that prints nothing for this long; None: only `timeout_s`
    max_turns: int | None = None
    max_budget_usd: float | None = None
    interrupt: threading.Event = field(default_factory=threading.Event)
    wrap: Wrapper | None = None  # `Sandbox.wrap` bound to this run's spec; None only in unit tests
    # The harness's own environment, for an adapter that must read a credential variable the sandbox never gets (it
    # lands in a 0600 file in the step's private directory instead). Never copied into `env`, never logged.
    host_env: Mapping[str, str] = field(default_factory=dict, repr=False)


TRANSIENT_STATUSES = (529, 503)  # server-side overload: not a usage limit, a wait inside the run may cure it


@dataclass
class RunResult:
    status: Status
    raw_events_path: Path
    final_text: str | None = None
    structured: dict[str, Any] | None = None
    rejected: dict[str, Any] | None = None  # a structured reply the schema refused: for a repair, never a result
    session_id: str | None = None
    exit_code: int | None = None
    usage: Usage = field(default_factory=Usage)
    limit: LimitSignal | None = None
    model_resolved: str | None = None
    permission_denials: list[dict[str, Any]] = field(default_factory=list)
    tool_rejections: list[dict[str, str]] = field(default_factory=list)  # codex stderr `Rejected(…)`: {tool, reason}
    detail: str | None = None  # one redacted line saying why a non-ok status happened
    transient: bool = False  # an `error` that a short wait may cure (a server-side 529 or 503): not a limit
    retry_after_s: float | None = None  # the wait the adapter was told to make, when it was told
    api_status: int | None = None  # the HTTP status the agent reported with a failed run, when it said


def denial_facts(run: RunResult) -> dict[str, Any]:
    """What `agent.finished` records of a run's permission denials: how many and which tools, never their inputs (a
    denied `Bash` input is a command line, which may carry a secret)."""
    tools = sorted({str(d.get("tool_name")) for d in run.permission_denials if d.get("tool_name")})
    return {"permission_denials": len(run.permission_denials), "denied_tools": tools}


class AgentAdapter(Protocol):
    name: str

    def capabilities(self) -> AgentCaps: ...

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult: ...

    def run(self, req: RunRequest) -> RunResult: ...


MAX_RESULT_BYTES = 1_000_000


def read_result_file(path: Path) -> str | None:
    """The agent-written result file, or None when it is missing, a symlink, not a regular file or too large: the
    agent controls this path, and a link must not make the harness read a file the sandbox hides (L4-SEC-006)."""
    try:
        return read_regular_file(path, limit=MAX_RESULT_BYTES).decode("utf-8", errors="replace")
    except (OSError, UnsafeFile):
        return None
