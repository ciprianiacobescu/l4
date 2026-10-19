"""The adapters' read-only mode, the delegate's (L4-DLG-004, SCN-DLG-13): Claude Code in plan mode with Read, Grep and
Glob, Codex with `-s read-only`, both in the worktree and neither with a tool server."""

import json
from pathlib import Path

import pytest

from l4.agents.base import McpServer, PermissionPolicy, RunRequest
from l4.agents.claude_code import ClaudeCodeAdapter
from l4.agents.codex import CodexAdapter
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "claude-code" / "2.1.288"
SCHEMA = {"type": "object", "required": ["decision"], "properties": {"decision": {"enum": ["answer", "escalate"]}}}
OPUS = Profile(adapter="claude-code", model="claude-opus-5-5", auth="subscription", vendor="anthropic")
SOL = Profile(
    adapter="codex", model="gpt-6.1-sol", auth="subscription", vendor="openai", options={"reasoning_effort": "high"}
)


def request(tmp_path: Path, profile: Profile, **kw) -> RunRequest:
    kw.setdefault("permission_policy", PermissionPolicy("read_only"))
    return RunRequest(
        role="delegate", cwd=tmp_path / "wt", prompt="p", result_path=tmp_path / "res" / "result.json",
        raw_events_path=tmp_path / "raw" / "events.jsonl", env={"PATH": str(tmp_path / "bin")}, profile=profile, **kw,
    )  # fmt: skip


def value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def test_claude_read_only_argv(tmp_path):  # SCN-DLG-13
    req = request(tmp_path, OPUS, result_schema=SCHEMA, max_turns=12, max_budget_usd=3.0)
    argv = ClaudeCodeAdapter().build_command(req, exe="/x/claude")
    assert argv[:2] == ["/x/claude", "-p"]
    assert value(argv, "--output-format") == "stream-json" and "--verbose" in argv
    assert value(argv, "--model") == "claude-opus-5-5"
    assert value(argv, "--permission-mode") == "plan"
    assert "--safe-mode" in argv and "--bare" not in argv and "--strict-mcp-config" in argv
    assert value(argv, "--tools") == "Read,Grep,Glob" and value(argv, "--allowedTools") == "Read,Grep,Glob"
    assert json.loads(value(argv, "--json-schema")) == SCHEMA
    assert value(argv, "--max-turns") == "12" and value(argv, "--max-budget-usd") == "3.0"
    joined = " ".join(argv)
    for forbidden in ("Edit", "Write", "Bash", "--mcp-config", "dontAsk"):
        assert forbidden not in joined
    assert "--max-budget-usd" not in ClaudeCodeAdapter().build_command(request(tmp_path, OPUS), exe="/x/claude")


def test_claude_read_only_uses_bare_for_an_api_key(tmp_path):
    api = OPUS.model_copy(update={"auth": "api_key"})
    argv = ClaudeCodeAdapter().build_command(request(tmp_path, api), exe="/x/claude")
    assert "--bare" in argv and "--safe-mode" not in argv


def test_claude_read_only_carries_no_mcp_server_even_when_given_one(tmp_path):
    req = request(tmp_path, OPUS, mcp_servers=(McpServer("serena", "serena", ()),))
    argv = ClaudeCodeAdapter().build_command(req, exe="/x/claude", mcp_config=tmp_path / "mcp.json")
    assert "--mcp-config" not in argv and "mcp__serena" not in " ".join(argv)


def test_codex_read_only_argv(tmp_path):
    req = request(tmp_path, SOL)
    schema = tmp_path / "res" / "schema.json"
    argv = CodexAdapter().build_command(req, exe="/x/codex", schema_path=schema)
    assert argv == [
        "/x/codex", "exec", "--json", "--ephemeral", "-m", "gpt-6.1-sol", "-c", "model_reasoning_effort=high",
        "-s", "read-only", "--ignore-user-config", "--ignore-rules", "-c", "project_doc_max_bytes=0",
        "--output-schema", str(schema), "-o", str(req.result_path), "-",
    ]  # fmt: skip
    assert "--skip-git-repo-check" not in argv and not any(a.startswith("mcp_servers.") for a in argv)


def test_codex_implementer_keeps_its_session(tmp_path):
    req = request(tmp_path, SOL, permission_policy=PermissionPolicy("implement"))
    assert "--ephemeral" not in CodexAdapter().build_command(req, exe="/x/codex", schema_path=None)


class Spy:
    def __init__(self) -> None:
        self.cwds: list[Path | None] = []

    def run(self, argv, env, cwd, **kw):
        self.cwds.append(cwd)
        kw["stdout_path"].parent.mkdir(parents=True, exist_ok=True)
        kw["stdout_path"].write_text("")
        return ProcOutcome(0)


@pytest.mark.parametrize(("adapter", "profile"), [(ClaudeCodeAdapter, OPUS), (CodexAdapter, SOL)])
def test_read_only_runs_in_the_worktree(tmp_path, adapter, profile):
    (tmp_path / "bin").mkdir()
    for exe in ("claude", "codex"):
        (tmp_path / "bin" / exe).write_text("#!/bin/sh\n")
        (tmp_path / "bin" / exe).chmod(0o755)
    spy = Spy()
    adapter(spy).run(request(tmp_path, profile))
    assert spy.cwds == [tmp_path / "wt"]
    assert not (tmp_path / "res" / "judge-cwd").exists()


def test_claude_read_only_reads_the_structured_result(tmp_path):
    text = (RECORDED / "blocked.jsonl").read_text()
    out = ClaudeCodeAdapter().parse(text, exit_code=0, schema=None, raw_events_path=tmp_path / "e")
    assert out.status == "ok" and out.structured and out.structured["status"] == "blocked"
