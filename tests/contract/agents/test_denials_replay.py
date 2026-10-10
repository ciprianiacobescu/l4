"""HB-6: the recorded denials replayed through the adapters become the facts `agent.finished` and
`agent.tool_rejected` carry (SPEC §8.3, L4-STA-001)."""

from pathlib import Path

from l4.agents.base import denial_facts
from l4.agents.claude_code import ClaudeCodeAdapter
from l4.agents.codex import rejections_from_stderr

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded"


def test_claude_dontask_denials_count_and_name_the_tools(tmp_path):
    text = (RECORDED / "claude-code" / "2.1.288" / "perm-dontask-denials.jsonl").read_text()
    run = ClaudeCodeAdapter().parse(text, exit_code=0, raw_events_path=tmp_path / "e")
    assert run.status == "ok"
    assert denial_facts(run) == {"permission_denials": 3, "denied_tools": ["Bash", "Write"]}
    assert "ls /" not in str(denial_facts(run))  # tool inputs never reach the ledger


def test_codex_rejected_lines_become_tool_rejections():
    stderr = (RECORDED / "codex" / "0.160.0" / "sandbox-rm-f-rejected-and-no-network.stderr").read_text()
    [one] = rejections_from_stderr(stderr)
    assert one["tool"] == "exec_command"
    assert one["reason"] == "rm -f style commands are not permitted. Use a safer approach"


def test_stderr_without_a_rejection_gives_none():
    assert rejections_from_stderr("2026-10-03T14:39:31Z WARN something else\n") == []
