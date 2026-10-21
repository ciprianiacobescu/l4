"""The real `claude -p` judge call (about 15 s and $0.06 on a subscription): L4_LIVE=1 and a logged-in `claude`."""

import os
import shutil
from pathlib import Path

import pytest

from l4.agents.base import PermissionPolicy, RunRequest
from l4.agents.claude_code import ClaudeCodeAdapter
from l4.config.schema import Profile
from l4.llm.agent_judge import AgentJudge, Msg
from l4.verifier.judge import JUDGE_SCHEMA, JudgeVerdict, parse_judge_output

pytestmark = pytest.mark.live

CRITERION = "C-0a1b2c3d"
EVIDENCE = f"""Criterion {CRITERION}: `double(x)` returns twice its argument.
Diff:
+def double(x):
+    return x * 2
Gate report: tests.test_double::test_double_three  passed
Give one verdict for {CRITERION}; test_adequacy may be empty; list three riskiest assumptions."""


def test_the_real_claude_judge_answers_in_the_verdict_schema(tmp_path: Path):
    # the variables of `build_agent_env`: without USER the macOS keychain login is not found ("Not logged in")
    env = {k: os.environ[k] for k in ("PATH", "HOME", "USER") if k in os.environ}
    env |= {"LANG": "C.UTF-8", "TMPDIR": str(tmp_path)}
    work = tmp_path / "wt"
    work.mkdir()

    def make(prompt: str, schema: dict, timeout_s: int) -> RunRequest:
        return RunRequest(
            profile=Profile(adapter="claude-code", model="sonnet", auth="subscription", vendor="anthropic"),
            role="judge", cwd=work, prompt=prompt, result_path=tmp_path / "result.json",
            raw_events_path=tmp_path / "raw" / "judge.jsonl", env={**env, **ClaudeCodeAdapter.extra_env},
            result_schema=schema, permission_policy=PermissionPolicy("judge"), timeout_s=timeout_s,
        )  # fmt: skip

    if shutil.which("claude") is None:
        pytest.skip("claude is not installed")
    result = AgentJudge(ClaudeCodeAdapter(), make).complete_structured(
        "You are a verifier. Reply with the JSON object only.", [Msg("user", EVIDENCE)], JUDGE_SCHEMA,
        effort=None, max_tokens=0, timeout_s=180,
    )  # fmt: skip
    assert result.status == "ok", result.detail
    verdict = parse_judge_output(result.parsed or {})
    assert isinstance(verdict, JudgeVerdict) and result.model_resolved and result.model_resolved.startswith("claude")
