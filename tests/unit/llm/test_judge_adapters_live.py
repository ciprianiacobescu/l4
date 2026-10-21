"""G18 smoke test: the real judge and clarifier schemas against the real opencode (free `opencode/big-pickle`) and
codex, on the operator's machine. `L4_LIVE=1`; a missing CLI skips its case. Nothing here touches a repository."""

import os
import shutil
from pathlib import Path

import pytest

from l4.agents.base import PermissionPolicy, RunRequest
from l4.agents.codex import CodexAdapter
from l4.agents.opencode import OpenCodeAdapter
from l4.clarifier.answer import CLARIFIER_ANSWER_SCHEMA, AnswerInvalid, validate_answer
from l4.config.schema import Profile
from l4.llm.agent_judge import AgentJudge, Msg
from l4.schemacheck import validate
from l4.verifier.judge import JUDGE_SCHEMA

pytestmark = pytest.mark.live

JUDGE_USER = (
    "Criterion C-0a1b2c3d: `add(2, 3)` returns 5.\n"
    "Evidence: tests/test_calc.py::test_add passed in the harness run; src/calc/__init__.py contains `return a + b`.\n"
    "Judge whether the criterion is met."
)
CLARIFIER_USER = (
    "A task says: `the discount code may be lower case`. The specification says codes are upper case only.\n"
    "Question 1: is a lower-case code accepted? Options: yes / no. Answer it if the sources decide it."
)

CASES = [
    ("opencode", Profile(adapter="opencode", model="opencode/big-pickle", vendor="unknown"), OpenCodeAdapter),
    ("codex", Profile(adapter="codex", model=os.environ.get("L4_LIVE_CODEX_MODEL"), vendor="openai"), CodexAdapter),
]


def judge_for(tmp_path: Path, profile: Profile, adapter_cls) -> AgentJudge:
    if not shutil.which(profile.adapter or ""):
        pytest.skip(f"{profile.adapter} is not installed")
    home = os.environ["HOME"]
    (tmp_path / "wt").mkdir(exist_ok=True)

    def make(prompt: str, schema: dict, timeout_s: int) -> RunRequest:
        return RunRequest(
            profile=profile, role="judge", cwd=tmp_path / "wt", prompt=prompt,
            result_path=tmp_path / "res" / "result.json", raw_events_path=tmp_path / "raw" / "events.jsonl",
            result_schema=schema, timeout_s=timeout_s, permission_policy=PermissionPolicy("judge"),
            env={"PATH": os.environ["PATH"], "HOME": home, "USER": os.environ.get("USER", "l4"), "LANG": "C.UTF-8",
                 "TMPDIR": str(tmp_path / "res")},
        )  # fmt: skip

    return AgentJudge(adapter_cls(), make)


@pytest.mark.parametrize(("name", "profile", "adapter_cls"), CASES, ids=[c[0] for c in CASES])
def test_the_judge_schema_is_met(tmp_path, name, profile, adapter_cls):
    judge = judge_for(tmp_path, profile, adapter_cls)
    out = judge.complete_structured(
        "You are a strict verifier.", [Msg("user", JUDGE_USER)], JUDGE_SCHEMA, timeout_s=240
    )
    assert out.status == "ok", (out.status, out.detail)
    assert out.parsed is not None and validate(out.parsed, JUDGE_SCHEMA) == []


@pytest.mark.parametrize(("name", "profile", "adapter_cls"), CASES, ids=[c[0] for c in CASES])
def test_the_clarifier_schema_is_met(tmp_path, name, profile, adapter_cls):
    judge = judge_for(tmp_path, profile, adapter_cls)
    out = judge.complete_structured("You answer questions from sources.", [Msg("user", CLARIFIER_USER)],
                                    CLARIFIER_ANSWER_SCHEMA, timeout_s=240)  # fmt: skip
    assert out.status == "ok", (out.status, out.detail)
    assert out.parsed is not None
    assert not isinstance(validate_answer(out.parsed), AnswerInvalid)
