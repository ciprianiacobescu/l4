"""A scripted adapter for unit tests: each `run` consumes one `Step`, writes the files the step lists into the
worktree, and leaves a raw events file like the real adapters do."""

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from l4.agents.base import (
    AdapterError,
    AgentCaps,
    LimitSignal,
    ProbeCtx,
    ProbeResult,
    ProbeStep,
    RunRequest,
    RunResult,
    Status,
    Usage,
)
from l4.config.schema import Profile


@dataclass
class Step:
    status: Status = "ok"
    final_text: str | None = None
    structured: dict[str, Any] | None = None
    session_id: str | None = None
    limit: LimitSignal | None = None
    delay_s: float = 0.0
    writes: Mapping[str, str] = field(default_factory=dict)  # worktree-relative path -> content
    deletes: tuple[str, ...] = ()  # worktree-relative paths the step removes (after the writes)
    cost_usd: float | None = None  # reported as the run's usage, for tests of budget accounting
    credits: float | None = None  # plan credits (Kiro), a different unit from dollars
    credits_source: str | None = None
    printed: str = ""  # text the "agent" prints to its event stream and to stderr, as a tool call's output would
    model: str | None = None  # the model the run reports as served (read only when the adapter reports one)
    permission_denials: list[dict[str, Any]] = field(default_factory=list)
    tool_rejections: list[dict[str, str]] = field(default_factory=list)
    transient: bool = False  # an `error` step that is a server-side overload (a 529): the caller may retry it
    api_status: int | None = None
    last_message: str | None = None  # the text after the last tool call, as an adapter reports it
    rejected: dict[str, Any] | None = None  # a structured reply the schema refused
    result_problem: Literal["missing", "not_json", "not_object", "invalid"] | None = None


class FakeAdapter:
    name = "fake"

    def __init__(
        self,
        script: Sequence[Step],
        *,
        probes: Mapping[ProbeStep, ProbeResult] | None = None,
        served_model: bool = False,
    ) -> None:
        self._served_model = served_model
        self._script = list(script)
        self._probes = dict(probes or {})
        self.requests: list[RunRequest] = []

    def capabilities(self) -> AgentCaps:
        return AgentCaps("native", True, True, True, True, False, False, True, served_model=self._served_model)

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        return self._probes.get(step) or ProbeResult(step, True)

    def run(self, req: RunRequest) -> RunResult:
        self.requests.append(req)
        if not self._script:
            raise AdapterError("the fake adapter's script is exhausted")
        step = self._script.pop(0)
        if step.delay_s:
            time.sleep(step.delay_s)
        root = req.cwd.resolve()
        for name, text in step.writes.items():
            target = (root / name).resolve()
            if root not in target.parents:
                raise AdapterError(f"scripted write {name!r} is outside the worktree")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        for name in step.deletes:
            target = (root / name).resolve()
            if root not in target.parents:
                raise AdapterError(f"scripted delete {name!r} is outside the worktree")
            target.unlink(missing_ok=True)
        if step.structured is not None:
            req.result_path.parent.mkdir(parents=True, exist_ok=True)
            req.result_path.write_text(json.dumps(step.structured), encoding="utf-8")
        req.raw_events_path.parent.mkdir(parents=True, exist_ok=True)
        req.raw_events_path.write_text(
            json.dumps({"type": "fake.step", "status": step.status, "files": sorted(step.writes), "out": step.printed})
            + "\n"
        )
        req.raw_events_path.with_suffix(".stderr").write_text(step.printed, encoding="utf-8")
        return RunResult(
            status=step.status, raw_events_path=req.raw_events_path, final_text=step.final_text,
            structured=step.structured, session_id=step.session_id,
            exit_code=0 if step.status == "ok" else 1, limit=step.limit,
            usage=Usage(cost_usd=step.cost_usd, credits=step.credits, credits_source=step.credits_source),
            model_resolved=step.model if self._served_model else None,
            permission_denials=list(step.permission_denials), tool_rejections=list(step.tool_rejections),
            transient=step.transient, api_status=step.api_status,
            last_message=step.last_message, rejected=step.rejected, result_problem=step.result_problem,
        )  # fmt: skip
