import stat
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from l4.agents.base import McpServer
from l4.config.schema import SerenaCfg
from l4.memory.serena import (
    check_serena,
    mcp_server_for,
    mcp_timeouts,
    render_project_yml,
    serena_argv,
    serena_env,
    serena_run_env,
)
from l4.sandbox.base import WrappedCommand

FAKE = """\
#!{python}
import json, sys, time
mode = {mode!r}
if sys.argv[1:] == ["--version"]:
    print({version!r}); sys.exit(0)
if mode == "crash":
    sys.exit(3)
if mode == "hang":
    time.sleep(60)
line = sys.stdin.readline()
req = json.loads(line)
info = {{"name": "Serena", "version": "1.28.1"}}
print(json.dumps({{"jsonrpc": "2.0", "id": req["id"], "result": {{"serverInfo": info}}}}), flush=True)
sys.stdin.read()
"""


AGENT_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/agent/home", "TMPDIR": "/agent/tmp", "UV_CACHE_DIR": "/unit/uv"}


def fake_serena(tmp_path: Path, mode="ok", version="serena 1.7.0") -> str:
    path = tmp_path / "bin" / "serena"
    path.parent.mkdir(exist_ok=True)
    path.write_text(FAKE.format(python=sys.executable, mode=mode, version=version))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def identity_wrap(argv, env) -> WrappedCommand:
    return WrappedCommand(list(argv), dict(env))


class Events:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict]] = []

    def append(self, event_type: str, /, **data):
        self.rows.append((event_type, data))


def test_argv_env_and_config_exact(tmp_path: Path):
    worktree = tmp_path / "wt"
    assert serena_argv("/bin/serena", "codex", worktree) == [
        "/bin/serena", "start-mcp-server", "--context", "codex", "--project", str(worktree),
        "--enable-web-dashboard", "false", "--open-web-dashboard", "false",
        "--mode", "one-shot", "--mode", "no-onboarding",
    ]  # fmt: skip
    tmp = tmp_path / "agent-tmp"
    env = serena_env(tmp)
    assert env == {"SERENA_HOME": str(tmp / "serena-home"), "UV_TOOL_DIR": str(tmp / "uv-tools"), "CI": "true"}
    config = yaml.safe_load((tmp / "serena-home" / "serena_config.yml").read_text())
    assert config == {"base_modes": ["editing"], "projects": []}


def test_project_yml_merge_keeps_other_keys():
    existing = "project_name: demo\nlanguages: [python]\nread_only_memory_patterns: ['keep-me']\n"
    merged = yaml.safe_load(render_project_yml(existing))
    assert merged["project_name"] == "demo" and merged["languages"] == ["python"]
    assert merged["read_only_memory_patterns"] == ["keep-me", "(?!inbox/).*"]
    assert merged["ignored_memory_patterns"] == ["harness/_archive/.*"]
    assert "embed_memory('harness/lessons')" in merged["initial_prompt"]
    assert render_project_yml(render_project_yml(existing)) == render_project_yml(existing)  # idempotent
    assert yaml.safe_load(render_project_yml("")) ["ignored_memory_patterns"] == ["harness/_archive/.*"]
    with pytest.raises(ValueError):
        render_project_yml("- a list\n")
    with pytest.raises(ValueError, match="not valid YAML"):
        render_project_yml("key: [unclosed\n")


def test_mcp_timeouts_tolerate_cold_start():
    assert mcp_timeouts("opencode").startup_ms >= 20_000
    assert mcp_timeouts("codex").startup_ms == 30_000 and mcp_timeouts("codex").startup_s == 30
    assert mcp_timeouts("claude-code").startup_ms >= 20_000


def test_mcp_server_for_adapters(tmp_path: Path):
    cfg = SerenaCfg()
    kw = {"cfg": cfg, "binary": "/bin/serena", "environ": AGENT_ENV}
    codex = mcp_server_for("codex", tmp_path / "wt", tmp_path / "t", **kw)
    assert isinstance(codex, McpServer) and codex.name == "serena" and codex.command == "/bin/serena"
    assert codex.args[:5] == ("start-mcp-server", "--context", "codex", "--project", str(tmp_path / "wt"))
    assert dict(codex.env)["SERENA_HOME"].startswith(str(tmp_path / "t"))
    claude = mcp_server_for("claude-code", tmp_path / "wt", tmp_path / "t", **kw)
    assert claude is not None and claude.args[2] == "claude-code"
    ide = mcp_server_for("opencode", tmp_path / "wt", tmp_path / "t", **kw)
    assert ide is not None and ide.args[2] == "ide"
    assert mcp_server_for("fake", tmp_path / "wt", tmp_path / "t", **kw) is None
    off = SerenaCfg(enabled=False)
    assert mcp_server_for("codex", tmp_path / "wt", tmp_path / "t", **{**kw, "cfg": off}) is None
    forced = SerenaCfg(context="ide")
    pinned = mcp_server_for("codex", tmp_path / "wt", tmp_path / "t", **{**kw, "cfg": forced})
    assert pinned is not None and pinned.args[2] == "ide"


def test_scn_fac_50_a_copilot_implementer_gets_serena_with_its_own_context(tmp_path: Path):
    """Serena 1.7.0 ships a `copilot-cli` context; without an entry a Copilot implementer got no Serena at all."""
    kw = {"cfg": SerenaCfg(), "binary": "/bin/serena", "environ": AGENT_ENV}
    server = mcp_server_for("copilot-cli", tmp_path / "wt", tmp_path / "t", **kw)
    assert server is not None and server.name == "serena"
    assert server.args[:5] == ("start-mcp-server", "--context", "copilot-cli", "--project", str(tmp_path / "wt"))


def run_check(tmp_path: Path, binary: str, events: Events, **kw):
    (tmp_path / "wt").mkdir(exist_ok=True)
    return check_serena(
        binary, tmp_path / "wt", tmp_path / "agent", adapter="codex", cfg=SerenaCfg(), wrap=identity_wrap,
        environ={"PATH": "/usr/bin:/bin"}, events=events, **kw,
    )  # fmt: skip


def test_handshake_passes_and_is_recorded(tmp_path: Path):
    events = Events()
    status = run_check(tmp_path, fake_serena(tmp_path), events, timeout_s=20)
    assert status.ok and status.reason == "" and status.startup_ms >= 0
    assert events.rows == [("memory.serena", {"status": "ok", "reason": "", "startup_ms": status.startup_ms})]


@pytest.mark.parametrize(
    ("mode", "version", "reason"),
    [("crash", "serena 1.7.0", "exited"), ("hang", "serena 1.7.0", "timed out"), ("ok", "serena 1.8.0", "1.8.0")],
)
def test_failure_degrades_without_failing_run(tmp_path: Path, mode, version, reason):
    events = Events()
    status = run_check(tmp_path, fake_serena(tmp_path, mode, version), events, timeout_s=2)
    assert not status.ok and reason in status.reason
    assert [(t, d["status"]) for t, d in events.rows] == [("memory.serena", "failed")]


def test_missing_binary_is_a_failed_start_not_an_exception(tmp_path: Path):
    events = Events()
    status = run_check(tmp_path, str(tmp_path / "nope"), events, timeout_s=2)
    assert not status.ok and events.rows[0][1]["status"] == "failed"
    assert textwrap.dedent(status.reason)  # a reason is always given


def test_version_mismatch_is_soft_failure(tmp_path: Path):
    events = Events()
    status = run_check(tmp_path, fake_serena(tmp_path, version="Serena 1.7.1"), events, timeout_s=5)
    assert not status.ok and "1.7.1" in status.reason and "1.7.0" in status.reason
    assert events.rows[0][1]["status"] == "failed"  # a failed start for the run to carry on without, never an exception
    assert run_check(tmp_path, fake_serena(tmp_path, version="Serena 1.7.0"), Events(), timeout_s=5).ok


def test_the_check_runs_serena_in_the_agents_environment(tmp_path: Path):
    seen = []

    def spy_wrap(argv, env) -> WrappedCommand:
        seen.append(dict(env))
        return WrappedCommand(list(argv), dict(env))

    (tmp_path / "wt").mkdir()
    agent_env = {"PATH": "/usr/bin:/bin", "TMPDIR": "/agent/tmp", "UV_CACHE_DIR": "/agent/uv"}
    check_serena(
        fake_serena(tmp_path), tmp_path / "wt", tmp_path / "agent", adapter="codex", cfg=SerenaCfg(), wrap=spy_wrap,
        environ=agent_env, timeout_s=20,
    )  # fmt: skip
    assert seen and all(e["UV_CACHE_DIR"] == "/agent/uv" and e["TMPDIR"] == "/agent/tmp" for e in seen)
    assert all(e["CI"] == "true" for e in seen)  # serena_env is added on top


def test_the_mcp_entry_carries_exactly_the_environment_the_check_runs_with(tmp_path: Path):
    """Decision 4 (A-B review): Codex starts Serena with the entry's env, so that is the env `check_serena` tests."""
    (tmp_path / "wt").mkdir()
    tmp = tmp_path / "agent"
    server = mcp_server_for("codex", tmp_path / "wt", tmp, cfg=SerenaCfg(), binary="/bin/serena", environ=AGENT_ENV)
    assert server is not None and server.startup_timeout_s == 30
    assert dict(server.env) == serena_run_env(AGENT_ENV, tmp)
    assert dict(server.env)["UV_CACHE_DIR"] == "/unit/uv" and dict(server.env)["PATH"] == "/usr/bin:/bin"
    seen: list[dict[str, str]] = []

    def spy(argv, env) -> WrappedCommand:
        seen.append(dict(env))
        return WrappedCommand(list(argv), dict(env))

    check_serena(
        fake_serena(tmp_path), tmp_path / "wt", tmp, adapter="codex", cfg=SerenaCfg(), wrap=spy, environ=AGENT_ENV,
        timeout_s=20,
    )  # fmt: skip
    assert seen and all(env == dict(server.env) for env in seen)
