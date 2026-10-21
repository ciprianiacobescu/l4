"""The opencode and kiro-cli adapters of the delegate's tests, replayed from stream lines. Their `run` replays scripted
lines through the real `parse` in read-only mode: argv and configuration are asserted in tests/unit/agents, the pass
here sees what a run of the CLI would have given it."""

import json
from collections.abc import Callable
from typing import Any

import pytest

from l4.agents.base import ProbeResult, RunRequest
from l4.agents.factory import ADAPTERS
from l4.agents.kiro_cli import KiroCliAdapter, effective_model
from l4.agents.opencode import OpenCodeAdapter

from ..agents.cli_streams import SESSION

OPENCODE_PROFILE = {"adapter": "opencode", "vendor": "deepseek", "model": "opencode-go/deepseek-v4.1-flash"}
ZEN_PROFILE = {"adapter": "opencode", "vendor": "unknown", "model": "opencode/free-model"}
KIRO_PROFILE = {"adapter": "kiro-cli", "vendor": "anthropic", "model": "claude-sonnet-4.5"}


class ScriptedOpenCode(OpenCodeAdapter):
    def __init__(self, script: list[list[str]], probes: dict | None = None, inspect: Callable | None = None) -> None:
        super().__init__()
        self.script, self.probes, self.inspect = list(script), dict(probes or {}), inspect
        self.requests: list[RunRequest] = []

    def probe(self, profile, step, ctx):
        return self.probes.get(step) or ProbeResult(step, True)

    def run(self, req: RunRequest):
        self.requests.append(req)
        if self.inspect is not None:
            self.inspect(req)
        lines = self.script.pop(0)
        req.raw_events_path.parent.mkdir(parents=True, exist_ok=True)
        req.raw_events_path.write_text("\n".join(lines))
        return self.parse(
            lines, exit_code=0, raw_events_path=req.raw_events_path, read_only=True, schema=req.result_schema,
            model=req.profile.model,
        )  # fmt: skip


class ScriptedKiro(KiroCliAdapter):
    """`served`: the model id of the session file the run left in its private home (None: no file)."""

    def __init__(
        self, script: list[list[str]], probes: dict | None = None, served: str | None = None,
        inspect: Callable | None = None,
    ) -> None:  # fmt: skip
        super().__init__()
        self.script, self.probes, self.served = list(script), dict(probes or {}), served
        self.inspect = inspect
        self.requests: list[RunRequest] = []

    def probe(self, profile, step, ctx):
        return self.probes.get(step) or ProbeResult(step, True)

    def run(self, req: RunRequest):
        self.requests.append(req)
        if self.inspect is not None:
            self.inspect(req)
        lines = self.script.pop(0)
        req.raw_events_path.parent.mkdir(parents=True, exist_ok=True)
        req.raw_events_path.write_text("\n".join(lines))
        home = req.result_path.parent / "scripted-kiro-home"
        if self.served is not None:
            path = home / "sessions" / "cli" / f"{SESSION}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            state = {"session_state": {"rts_model_state": {"model_info": {"model_id": self.served}}}}
            path.write_text(json.dumps(state), encoding="utf-8")
        return self.parse(
            lines, exit_code=0, raw_events_path=req.raw_events_path, read_only=True, schema=req.result_schema,
            kiro_home=home, model=effective_model(req.profile), stderr_text="",
        )  # fmt: skip


@pytest.fixture
def install_cli(monkeypatch: pytest.MonkeyPatch) -> Callable[[str, Any], Any]:
    """`install_cli("opencode", adapter)`: this adapter object serves every profile of that adapter name."""

    def install(name: str, adapter: Any) -> Any:
        monkeypatch.setitem(ADAPTERS, name, lambda: adapter)
        return adapter

    return install
