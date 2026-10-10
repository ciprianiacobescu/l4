"""HB-X1 (canary measured live on l4-runner, 2026-10-05): the switches that keep repository guidance out of an
agent step, pinned per adapter. A CLI update that changes the effect is a doctor/canary matter; a change to the
argv or environment here is a SPEC §8.3 / L4-SEC-002 change."""

from pathlib import Path

import pytest

from l4.agents.base import PermissionPolicy, RunRequest
from l4.agents.codex import CodexAdapter
from l4.agents.opencode import isolation_env
from l4.config.schema import Profile

CODEX = Profile(adapter="codex", model="gpt-6-luna", vendor="openai")


def request(tmp_path: Path, profile: Profile, mode: str) -> RunRequest:
    return RunRequest(
        role="implementer", cwd=tmp_path / "wt", prompt="p", result_path=tmp_path / "res" / "result.json",
        raw_events_path=tmp_path / "raw" / "events.jsonl", env={"PATH": "/usr/bin"}, profile=profile,
        permission_policy=PermissionPolicy(mode),
    )  # fmt: skip


@pytest.mark.parametrize("mode", ["implement", "read_only", "judge"])
def test_codex_loads_no_repo_agents_md_in_any_mode(tmp_path, mode):
    """The implementer auto-loaded `AGENTS.md` ("# AGENTS.md instructions for <wt>") until the project doc budget was 0;
    that also holds for the judge, which has no tools but would still be handed a doc found above its cwd."""
    argv = CodexAdapter().build_command(request(tmp_path, CODEX, mode), exe="codex", schema_path=None)
    pairs = [(argv[i], argv[i + 1]) for i in range(len(argv) - 1)]
    assert ("-c", "project_doc_max_bytes=0") in pairs
    assert argv.count("project_doc_max_bytes=0") == 1


def test_opencode_sets_all_four_disable_switches_and_nothing_else_of_the_family(tmp_path):
    """`PROJECT_CONFIG` blocks AGENTS.md, CLAUDE.md and `.opencode` skills; `EXTERNAL_SKILLS` blocks `.agents/skills`;
    `CLAUDE_CODE` blocks the Claude-compatible sources; `AUTOUPDATE` keeps the CLI at the pinned version."""
    env = isolation_env(tmp_path / "opencode-config", "{}")
    assert {k: v for k, v in env.items() if k.startswith("OPENCODE_DISABLE_")} == {
        "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
        "OPENCODE_DISABLE_CLAUDE_CODE": "1",
        "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
    }
