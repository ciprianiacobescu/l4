"""Serena 1.7.0 as an optional MCP server for the implementer (SPEC L4-MEM-004).

Serena is advisory: whatever goes wrong here becomes `SerenaStatus(ok=False)` and a `memory.serena` event, never a
failed run, and lessons reach the prompt without it. It runs inside the agent sandbox, so everything it writes must
land in the agent's private tmp directory: `SERENA_HOME` (Serena rewrites its config at runtime) and `UV_TOOL_DIR`
(`uvx` starts Pyright and dies under the read-only HOME) [V, M15-G2 probe, docs/runner/README.md]. The agent tmp is
reset before every request, so `serena_env` has to be called after `reset_agent_tmp` and before the request is built.
M1: memory-lessons 4.5 (Kiro's `--require-mcp-startup` filter), 4.7 (the contract test; M15-G2 (b) covers it live).
"""

import contextlib
import json
import os
import queue
import re
import signal
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from l4.agents.base import McpServer, Wrapper
from l4.config.schema import SerenaCfg
from l4.versions import parse_version

SERVER_NAME = "serena"
START_COMMAND = "start-mcp-server"
STARTUP_MS = 30_000  # cold start: Pyright and the project registration take seconds (OpenCode needs >= 20 s)
CHECK_TIMEOUT_S = 60.0
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "l4", "version": "0"}
READ_ONLY_MEMORY = "(?!inbox/).*"
IGNORED_MEMORY = "harness/_archive/.*"
INITIAL_PROMPT = "{{ embed_memory('harness/lessons') }}"
SEED_PROJECT_RELPATH = ".serena/project.yml"
_YAML_WORDS = frozenset({"true", "false", "null", "yes", "no", "on", "off", "y", "n"})
_CONTEXT_BY_ADAPTER = {"codex": "codex", "claude-code": "claude-code", "opencode": "ide", "kiro": "ide"}


@dataclass(frozen=True)
class McpTimeouts:
    startup_ms: int

    @property
    def startup_s(self) -> int:
        return self.startup_ms // 1000


def mcp_timeouts(adapter: str) -> McpTimeouts:
    """What the adapter's MCP client waits for the server to start: Codex `startup_timeout_sec = 30`, OpenCode
    `timeout` of 30000 ms (its default is 5 s). Every adapter gets the same 30 s."""
    return McpTimeouts(STARTUP_MS)


def serena_context(adapter: str, configured: str = "auto") -> str | None:
    """`--context` for the adapter, or None when Serena has no context for it (the fake adapter, unknown names)."""
    if configured != "auto":
        return configured
    return _CONTEXT_BY_ADAPTER.get(adapter)


def serena_argv(binary: str, context: str, project: Path) -> list[str]:
    return [
        binary, START_COMMAND, "--context", context, "--project", str(project),
        "--enable-web-dashboard", "false", "--open-web-dashboard", "false",
        "--mode", "one-shot", "--mode", "no-onboarding",
    ]  # fmt: skip


def serena_env(tmp: Path) -> dict[str, str]:
    """The three variables, and `serena_config.yml` written under `SERENA_HOME`. `base_modes: [editing]` drops the
    interactive mode (its questions would wait for nobody); `projects: []` is required or Serena exits with
    `SerenaConfigError`."""
    home = tmp / "serena-home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "serena_config.yml").write_text(
        yaml.safe_dump({"base_modes": ["editing"], "projects": []}, sort_keys=False), encoding="utf-8"
    )
    return {"SERENA_HOME": str(home), "UV_TOOL_DIR": str(tmp / "uv-tools"), "CI": "true"}


def serena_run_env(environ: Mapping[str, str], tmp: Path) -> dict[str, str]:
    """The whole environment Serena runs with: the agent's own (built without a credential variable, SEC-001) and
    `serena_env`. The MCP entry and `check_serena` both take it from here, so the check runs the Serena the agent's
    CLI starts and not a Serena in a friendlier environment."""
    return {**environ, **serena_env(tmp)}


def mcp_server_for(
    adapter: str, worktree: Path, tmp: Path, *, cfg: SerenaCfg, binary: str, environ: Mapping[str, str]
) -> McpServer | None:
    """The MCP server an implement-mode request carries, or None when Serena is off or the adapter has no context.
    `environ` is the request's own environment (`build_agent_env`)."""
    context = serena_context(adapter, cfg.context) if cfg.enabled else None
    if context is None:
        return None
    argv = serena_argv(binary, context, worktree)
    env = tuple(sorted(serena_run_env(environ, tmp).items()))
    return McpServer(SERVER_NAME, binary, tuple(argv[1:]), env, mcp_timeouts(adapter).startup_s)


def render_seed_project_yml(name: str) -> str:
    """The `.serena/project.yml` that `l4 init` and `l4 upgrade` commit: Serena 1.7.0's own full form with the harness
    keys in it (`serena_project.yml`, made by starting Serena on a file with just those keys). Serena rewrites a short
    or missing file into this form at its start, once in a different form than it ends with, so that the bytes the
    harness saw at its check were not always the bytes the agent's Serena left (live M1.7: a guard violation at every
    agent step). A file that already is in this form stays byte-identical under Serena 1.7.0, whatever its
    `project_name` says. `name` is made a plain YAML word first."""
    word = re.sub(r"[^A-Za-z0-9._-]", "-", name) or "project"
    if not word[0].isalpha() or word.lower() in _YAML_WORDS:
        word = f"project-{word}"
    text = files("l4.memory").joinpath("serena_project.yml").read_text(encoding="utf-8")
    return re.sub(r"^project_name: .*$", f"project_name: {word}", text, count=1, flags=re.M)


def _union(existing: object, wanted: str) -> list[str]:
    items = [str(x) for x in existing] if isinstance(existing, list) else []
    return items if wanted in items else [*items, wanted]


def render_project_yml(existing: str) -> str:
    """`.serena/project.yml` with the harness's three keys merged in and every other key kept (comments are not).
    Idempotent. ValueError when the file is not YAML or not a mapping."""
    try:
        data = yaml.safe_load(existing) if existing.strip() else {}
    except yaml.YAMLError:
        raise ValueError(".serena/project.yml is not valid YAML") from None
    if not isinstance(data, dict):
        raise ValueError(".serena/project.yml is not a YAML mapping")
    data["read_only_memory_patterns"] = _union(data.get("read_only_memory_patterns"), READ_ONLY_MEMORY)
    data["ignored_memory_patterns"] = _union(data.get("ignored_memory_patterns"), IGNORED_MEMORY)
    prompt = str(data.get("initial_prompt") or "")
    if INITIAL_PROMPT not in prompt:
        data["initial_prompt"] = f"{prompt.rstrip()}\n{INITIAL_PROMPT}".strip() + "\n"
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)


@dataclass(frozen=True)
class SerenaStatus:
    ok: bool
    reason: str = ""
    startup_ms: int = 0


def _kill(proc: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        proc.wait(5)


def _spawn(command: Sequence[str], env: Mapping[str, str], cwd: Path, **pipes: Any) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603 - argv list, the sandbox wrapper has already resolved it
        list(command), cwd=cwd, env=dict(env), stderr=subprocess.DEVNULL, start_new_session=True, **pipes
    )


def _version_problem(command: Sequence[str], env: Mapping[str, str], cwd: Path, pin: str, timeout_s: float) -> str:
    try:
        proc = _spawn(command, env, cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    except OSError as exc:
        return f"serena cannot start ({type(exc).__name__})"
    try:
        out, _ = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill(proc)
        return "serena --version timed out"
    finally:
        _kill(proc)
    found = parse_version(out.decode("utf-8", "replace"))
    wanted = parse_version(pin)
    if found is None:
        return "serena --version printed no version"
    if found != wanted:
        return f"serena {'.'.join(map(str, found))} is installed, the pin is {pin}"
    return ""


def _handshake(command: Sequence[str], env: Mapping[str, str], cwd: Path, timeout_s: float) -> tuple[str, int]:
    """(problem or "", milliseconds until the `initialize` reply)."""
    began = time.monotonic()
    try:
        proc = _spawn(command, env, cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    except OSError as exc:
        return f"serena cannot start ({type(exc).__name__})", 0
    lines: queue.Queue[bytes] = queue.Queue()
    assert proc.stdin is not None and proc.stdout is not None
    stdout = proc.stdout

    def pump() -> None:
        for line in stdout:
            lines.put(line)
        lines.put(b"")  # EOF

    threading.Thread(target=pump, daemon=True).start()
    request = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
    }  # fmt: skip
    try:
        with contextlib.suppress(BrokenPipeError, OSError):
            proc.stdin.write((json.dumps(request) + "\n").encode())
            proc.stdin.flush()
        deadline = began + timeout_s
        while (left := deadline - time.monotonic()) > 0:
            try:
                line = lines.get(timeout=min(left, 0.2))
            except queue.Empty:
                continue
            if not line:
                return f"serena exited with code {proc.poll()} before it answered", 0
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("id") == 1:
                if "result" in message:
                    return "", round((time.monotonic() - began) * 1000)
                return "serena answered initialize with an error", 0
        return f"serena initialize timed out after {timeout_s:.0f}s", 0
    finally:
        _kill(proc)


def check_serena(
    binary: str,
    worktree: Path,
    tmp: Path,
    *,
    adapter: str,
    cfg: SerenaCfg,
    wrap: Wrapper,
    environ: Mapping[str, str],
    events: Any | None = None,
    timeout_s: float = CHECK_TIMEOUT_S,
) -> SerenaStatus:
    """The pin check (`serena --version`) and an MCP `initialize`, both through `wrap` (the agent sandbox), once per
    run. `environ` is the agent's own built environment (`build_agent_env`: TMPDIR, proxies, the unit's UV_CACHE_DIR),
    used whole, so that the check passes or fails as the Serena the agent starts would; never `os.environ`.
    It never raises: a failure is `ok=False` with one reason, and one `memory.serena` event says what happened."""
    try:
        status = _check(binary, worktree, tmp, adapter, cfg, wrap, environ, timeout_s)
    except Exception as exc:  # noqa: BLE001 - Serena is optional: nothing here may fail the run
        status = SerenaStatus(False, f"check failed ({type(exc).__name__})")
    if events is not None:
        events.append(
            "memory.serena", status="ok" if status.ok else "failed", reason=status.reason, startup_ms=status.startup_ms
        )
    return status


def _check(
    binary: str, worktree: Path, tmp: Path, adapter: str, cfg: SerenaCfg, wrap: Wrapper, environ: Mapping[str, str],
    timeout_s: float,
) -> SerenaStatus:  # fmt: skip
    context = serena_context(adapter, cfg.context)
    if context is None:
        return SerenaStatus(False, f"serena has no context for adapter {adapter}")
    env = serena_run_env(environ, tmp)
    version = wrap([binary, "--version"], env)
    problem = _version_problem(version.argv, version.env, worktree, cfg.version, timeout_s)
    if problem:
        return SerenaStatus(False, problem)
    start = wrap(serena_argv(binary, context, worktree), env)
    problem, startup_ms = _handshake(start.argv, start.env, worktree, timeout_s)
    return SerenaStatus(not problem, problem, startup_ms)
