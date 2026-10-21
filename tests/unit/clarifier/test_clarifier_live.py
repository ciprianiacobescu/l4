"""The real `claude -p` calls of the clarifier and of the boolean S1 stand-in (about 15 s and $0.06 each on a
subscription): L4_LIVE=1 and a logged-in `claude`."""

import os
import shutil
from pathlib import Path

import pytest

from l4.agents.base import PermissionPolicy, RunRequest
from l4.agents.claude_code import ClaudeCodeAdapter
from l4.clarifier.answer import ClarifierAnswer
from l4.clarifier.backend import BackendClarifier
from l4.clarifier.context import CodeExcerpt, ContextBuilder
from l4.clarifier.ports import QuestionView
from l4.clarifier.router import LlmBooleanJudge, S1Query, citation_question, resolve_citation, router_question
from l4.config.schema import Profile
from l4.llm.agent_judge import AgentJudge
from l4.specs.questions import QuestionKind, QuestionStatus

pytestmark = pytest.mark.live

CODE = "def to_cents(euros):\n    return round(euros * 100)\n"
DESIGN = "# Design\n\nAmounts are stored as integer cents. Prices are never floats.\n"
QUESTION = QuestionView(
    "Q-001", "Are amounts stored as floats or as integer cents?", QuestionStatus.OPEN, QuestionKind.TECHNICAL,
    ("1.1",), "The task adds a total() function and does not say how amounts are represented.", (), "", "", None,
)  # fmt: skip


def judge(tmp_path: Path) -> AgentJudge:
    env = {k: os.environ[k] for k in ("PATH", "HOME", "USER") if k in os.environ}
    env |= {"LANG": "C.UTF-8", "TMPDIR": str(tmp_path), **ClaudeCodeAdapter.extra_env}
    work = tmp_path / "wt"
    work.mkdir(exist_ok=True)
    calls: list[int] = []

    def make(prompt: str, schema: dict, timeout_s: int) -> RunRequest:
        calls.append(1)
        return RunRequest(
            profile=Profile(adapter="claude-code", model="sonnet", auth="subscription", vendor="anthropic"),
            role="judge", cwd=work, prompt=prompt, result_path=tmp_path / "result.json",
            raw_events_path=tmp_path / "raw" / f"{len(calls)}.jsonl", env=env, result_schema=schema,
            permission_policy=PermissionPolicy("judge"), timeout_s=timeout_s,
        )  # fmt: skip

    if shutil.which("claude") is None:
        pytest.skip("claude is not installed")
    return AgentJudge(ClaudeCodeAdapter(), make)


def test_the_real_claude_answers_in_the_clarifier_schema(tmp_path: Path, git_for, make_repo):
    repo = make_repo("live")
    (repo / "src").mkdir()
    (repo / "src" / "money.py").write_text(CODE)  # untracked: the excerpt below is what the model sees
    builder = ContextBuilder(repo, git_for(repo), budget_tokens=4000, redact=lambda t: t)
    prompt = builder.build_prompt(
        QUESTION, documents=[("design.md", DESIGN)], base_specs=[], answered="",
        code=[CodeExcerpt("src/money.py", 1, "1: def to_cents(euros):\n2:     return round(euros * 100)")],
    )  # fmt: skip
    reply = BackendClarifier(judge(tmp_path), redact=lambda t: t, timeout_s=180).answer(QUESTION, prompt)
    assert reply.status == "ok", reply.detail
    assert isinstance(reply.answer, ClarifierAnswer) and reply.answer.question_id == "Q-001"
    assert reply.answer.kind == "technical" and reply.answer.citations
    unit = tmp_path / "unit"
    unit.mkdir()
    (unit / "design.md").write_text(DESIGN)
    checks = [resolve_citation(c, [unit, repo]) for c in reply.answer.citations]
    assert all(c.ok for c in checks), [
        (c.reason, c) for c in checks if not c.ok
    ]  # refs are bare paths, quotes verbatim


def test_the_real_claude_answers_the_boolean_s1_schema(tmp_path: Path):
    s1 = LlmBooleanJudge(judge(tmp_path))
    technical = router_question(QUESTION, max_tokens=450)
    product = router_question(
        QuestionView(
            "Q-002",
            "Which VAT rate should the shop charge in Romania?",
            QuestionStatus.OPEN,
            QuestionKind.PRODUCT,
            ("1.2",),
            "The spec names no rate. The owner must pick one.",
            ("19%", "9%"),
            "",
            "",
            None,
        ),  # fmt: skip
        max_tokens=450,
    )
    assert s1.ask(technical) == 0.0 and s1.ask(product) == 1.0
    supported = citation_question("Amounts are integer cents.", DESIGN, max_tokens=450)
    unsupported = citation_question("Amounts are stored as floats.", DESIGN, max_tokens=450)
    assert s1.ask(supported) == 1.0 and s1.ask(unsupported) == 0.0
    assert isinstance(technical, S1Query)
