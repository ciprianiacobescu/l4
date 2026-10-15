from collections.abc import Sequence
from typing import Any

from l4.agents.base import RunResult, Usage
from l4.llm.agent_judge import Msg, StructuredResult

# the fixtures of `test_hook.py`, which runs the real orchestrator against the fake forge
from ..archive.conftest import forge_env, use_fake_gitlab  # noqa: F401
from ..forge.conftest import gitlab  # noqa: F401
from ..orchestrator.conftest import fake_clock, install_hooks, openspec_stand_in, run_l4  # noqa: F401


class ScriptedBackend:
    """An `LLMBackend` that answers from a script and records every call."""

    def __init__(self, *replies: StructuredResult) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def complete_structured(
        self,
        system: str,
        messages: Sequence[Msg],
        json_schema: dict[str, Any],
        *,
        effort: str | None,
        max_tokens: int,
        timeout_s: int,
    ) -> StructuredResult:
        self.calls.append(
            {
                "system": system, "messages": list(messages), "schema": json_schema,
                "max_tokens": max_tokens, "timeout_s": timeout_s,
            }
        )  # fmt: skip
        return self.replies.pop(0)


def ok(parsed: dict[str, Any], *, cost: float = 0.01) -> StructuredResult:
    return StructuredResult("ok", parsed=parsed, model_resolved="claude-x", usage=Usage(cost_usd=cost))


def limit_run() -> RunResult:
    from pathlib import Path

    return RunResult("quota", Path("/dev/null"), detail="usage limit")
