"""An agent CLI used as a tool-less structured-output backend (SPEC 8.1 "CLI judge", L4-FAC-003; gap G3).

`LLMBackend.complete_structured` is the surface the verifier's `run_judge` consumes. M0 has no API-key backend (the
runner has subscription logins only), so the one implementation runs an adapter in its judge mode: for `claude-code`
that is `claude -p --output-format json --json-schema <schema> --safe-mode --tools "" --no-session-persistence` with
the prompt on stdin, the reply read from `structured_output` and the served model from `modelUsage`.
`effort` and `max_tokens` have no flag on `claude -p`; they are part of the protocol for the API backends (M1:
agent-factory 3.x). The reply is validated here again, whatever the adapter did: validation is mandatory.
"""

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from l4 import deadline
from l4.agents.base import AgentAdapter, EventSink, PermissionPolicy, RunRequest, RunResult, Usage
from l4.agents.claude_code import STRUCTURED_DETAIL
from l4.agents.factory import Factory, Selected
from l4.config.roles import JUDGE_ADAPTERS
from l4.config.schema import Profile
from l4.sandbox.env import build_agent_env
from l4.schemacheck import validate

if TYPE_CHECKING:
    from l4.implementer.workbench import Workbench

MAX_PROBLEMS = 5
LIMIT_STATUSES = ("quota", "rate_limited", "auth")
# A server-side overload (claude: 529, 503, `overloaded_error`) is not a usage limit: the call is made again in the run,
# 3 tries with these waits between them (L4-AVL-006, M1.11). An adapter that reports its own wait overrides them.
TRANSIENT_TRIES = 3
TRANSIENT_WAITS_S = (20.0, 60.0)
MAX_TRANSIENT_WAIT_S = 60.0


# an adapter with no native schema flag (opencode) is told the shape in the prompt and its reply is sliced and checked
SCHEMA_INSTRUCTION = (
    "\n\nDo not call any tool: answer from this prompt alone. Reply with a single JSON object that conforms to "
    "this JSON Schema, and nothing after it (no code fence, no prose):\n"
)


# a read-only request (the delegate, L4-DLG-015): the model reads the repository with its read tools, then replies
READ_THEN_REPLY = (
    "\n\nRead the files you need with your read-only tools; you cannot change files or run commands. Then reply with "
    "a single JSON object that conforms to this JSON Schema as the last thing you write, with nothing after it (no "
    "prose, no tool call):\n"
)


def schema_suffix(schema: dict[str, Any], reading: bool = False) -> str:
    """What a prompt-contract adapter gets after the prompt document: the instruction and the compact schema. It is
    not part of the document that `prompt_sha256` hashes and `.prompt.md` publishes (L4-VER-005). `reading`: the
    read-then-reply instruction of a read-only request, which must not say to call no tool."""
    return (READ_THEN_REPLY if reading else SCHEMA_INSTRUCTION) + json.dumps(schema, separators=(",", ":"))


def strip_suffix(prompt: str, schema: dict[str, Any]) -> str:
    """The prompt document without the suffix of either kind (what is hashed and published)."""
    return prompt.removesuffix(schema_suffix(schema, reading=True)).removesuffix(schema_suffix(schema))


@dataclass(frozen=True)
class Msg:
    role: Literal["user", "assistant"]
    content: str


@dataclass
class StructuredResult:
    """`limit` is the agent run that reported a usage limit or a lost login (the caller turns it into exit 12);
    `schema_invalid` carries the violated paths in `detail`, never the values."""

    status: Literal["ok", "schema_invalid", "timeout", "error", "limit"]
    parsed: dict[str, Any] | None = None
    model_resolved: str | None = None
    usage: Usage = field(default_factory=Usage)
    detail: str = ""
    run: RunResult | None = None
    raw: dict[str, Any] | None = None  # the structured reply a `schema_invalid` rejected, for the repair prompt
    length_stop: bool = False  # an `error` whose run stopped at the model's output limit (`RunResult.length_stop`)


class LLMBackend(Protocol):
    def complete_structured(
        self,
        system: str,
        messages: Sequence[Msg],
        json_schema: dict[str, Any],
        *,
        effort: str | None,
        max_tokens: int,
        timeout_s: int,
    ) -> StructuredResult: ...


# builds the `RunRequest` of one call (cwd, env, sandbox wrapper and log paths belong to the caller)
RequestFactory = Callable[[str, dict[str, Any], int], RunRequest]


def render_prompt(system: str, messages: Sequence[Msg]) -> str:
    """One stdin document: `claude -p` has no message list. An earlier reply of the model is labelled as such."""
    parts = [system]
    parts += [m.content if m.role == "user" else f"Your previous reply was:\n{m.content}" for m in messages]
    return "\n\n".join(parts)


class AgentJudge:
    def __init__(
        self,
        adapter: AgentAdapter,
        make_request: RequestFactory,
        *,
        events: EventSink | None = None,
        role: str = "judge",
        profile: str = "",
        sleep: Callable[[float], None] | None = None,
        reading: bool = False,
    ) -> None:
        """`events`, `role` and `profile` say where and for whom each retry of a transient error is recorded
        (`availability.transient`). `reading`: the request is read-only (the delegate), so a prompt-contract adapter
        is told to read first and reply last; the flag is the constructor's because `complete_structured` composes
        the prompt before `make_request` builds the request."""
        self._reading = reading
        self._adapter = adapter
        self._make_request = make_request
        self._events, self._role, self._profile = events, role, profile
        self._sleep = sleep

    def _run(self, prompt: str, json_schema: dict[str, Any], timeout_s: int) -> RunResult:
        """One call, made again after a transient server error (3 tries, 20 s then 60 s): the cost of an overload is a
        short wait inside the run, not a unit parked for 30 minutes (live wave A jobs 5703 and 5709)."""
        run = self._adapter.run(self._make_request(prompt, json_schema, timeout_s))
        for attempt in range(1, TRANSIENT_TRIES):
            if run.status != "error" or not run.transient:
                break
            wait = TRANSIENT_WAITS_S[min(attempt, len(TRANSIENT_WAITS_S)) - 1]
            if run.retry_after_s is not None and run.retry_after_s >= 0:
                wait = min(run.retry_after_s, MAX_TRANSIENT_WAIT_S)
            if self._events is not None:
                self._events.append(
                    "availability.transient", role=self._role, profile=self._profile,
                    status=run.api_status or "overloaded_error", attempt=attempt, wait_s=wait,
                )  # fmt: skip
            (self._sleep or time.sleep)(wait)
            run = self._adapter.run(self._make_request(prompt, json_schema, timeout_s))
        if run.status == "cancelled" and deadline.fired():  # the soft deadline stopped the judge (L4-IMP-068)
            self._record_cost(run)  # the stopped call was metered and paid for: no verdict, but its cost counts
            raise deadline.DeadlineReached("during", during="judge")
        return run

    def _record_cost(self, run: RunResult) -> None:
        """`budget.cost` of a call that gives no result to the caller (the same fields as a call that does)."""
        if self._events is None:
            return
        if run.usage.cost_usd:
            self._events.append("budget.cost", usd=run.usage.cost_usd, profile=self._profile, role=self._role)
        if run.usage.credits:  # plan credits, never dollars (kiro-judge L4-KJD-004)
            self._events.append(
                "budget.cost", credits=round(run.usage.credits, 6), credits_source=run.usage.credits_source,
                profile=self._profile, role=self._role,
            )  # fmt: skip

    def complete_structured(
        self,
        system: str,
        messages: Sequence[Msg],
        json_schema: dict[str, Any],
        *,
        effort: str | None = None,
        max_tokens: int = 0,
        timeout_s: int = 600,
    ) -> StructuredResult:
        prompt = render_prompt(system, messages)
        if self._adapter.capabilities().schema_mode != "native":
            prompt += schema_suffix(json_schema, reading=self._reading)
        run = self._run(prompt, json_schema, timeout_s)
        base = {"model_resolved": run.model_resolved, "usage": run.usage, "run": run}
        if run.status in LIMIT_STATUSES:
            return StructuredResult("limit", detail=run.detail or run.status, **base)
        if run.status == "timeout":
            return StructuredResult("timeout", detail=f"no answer within {timeout_s}s", **base)
        if run.status in ("max_turns", "budget"):  # structured-output retries used up: one repair, not "cannot run"
            return StructuredResult(
                "schema_invalid", detail=run.detail or f"the judge run ended with status {run.status}", **base
            )  # fmt: skip
        if run.status == "ok" and run.structured is not None:
            problems = validate(run.structured, json_schema)
            if problems:
                return StructuredResult(
                    "schema_invalid", detail="; ".join(problems[:MAX_PROBLEMS]), raw=run.structured, **base
                )
            return StructuredResult("ok", parsed=run.structured, **base)
        if run.status == "ok" or (run.detail or "").startswith(STRUCTURED_DETAIL):
            return StructuredResult(
                "schema_invalid", detail=run.detail or "the reply has no structured output", raw=run.rejected, **base
            )
        return StructuredResult(
            "error", detail=run.detail or f"the judge run ended with status {run.status}", length_stop=run.length_stop,
            **base,
        )  # fmt: skip


@dataclass(frozen=True)
class RoleJudge:
    judge: AgentJudge
    selected: Selected


def open_role_judge(
    factory: Factory, role: str, unit: str, make_request: Callable[[Selected], RequestFactory]
) -> RoleJudge:
    """The tool-less structured-output backend of an optional role (`clarifier`, `s1_judge`; gap G10): the role's first
    profile, probed. `RoleUnavailable` when the chain is empty, the profile is not an adapter that can judge, or a
    probe fails; the caller decides what that degrades to (clarifier: ask a human; S1: no auto-accept)."""
    selected = factory.for_role(role, unit, serves=JUDGE_ADAPTERS)
    return RoleJudge(AgentJudge(selected.impl, make_request(selected)), selected)


def workbench_request_factory(
    wb: "Workbench", profile: Profile, *, stem: str, logs: list[tuple[Path, Path]], publish_prompts: bool = False
) -> RequestFactory:
    """One judge call: the agent's own login is the only one visible, no tool is allowed, the worktree is only the
    working directory. Raw streams stay private; `publish_agent_logs` writes the redacted copies. Each call appends
    its (raw, published) log pair to `logs` under `<stem>-<n>`; with `publish_prompts` the prompt document goes next
    to it under the same stem (the caller has redacted it): what a native adapter is sent, and what a prompt-contract
    adapter is sent before the `schema_suffix` appended to it, so the file hashes to `prompt_sha256` (L4-VER-005)."""
    spec = wb.agent_spec()
    extra = dict(getattr(wb.impl, "extra_env", {}))

    def make(prompt: str, schema: dict[str, Any], timeout_s: int) -> RunRequest:
        tmp = wb.reset_agent_tmp()
        raw, published = wb.agent_log_paths(f"{stem}-{len(logs) + 1}")
        logs.append((raw, published))
        if publish_prompts:
            wb.publish_prompt(published, strip_suffix(prompt, schema))
        return RunRequest(
            profile=profile, role="judge", cwd=wb.worktree, prompt=prompt, result_path=tmp / "result.json",
            raw_events_path=raw, env=build_agent_env(wb.host_env, spec, extra=extra), result_schema=schema,
            permission_policy=PermissionPolicy("judge"), timeout_s=timeout_s,
            wrap=lambda argv, env, cwd=None: wb.sandbox.wrap(argv, spec, env, cwd), host_env=wb.host_env,
        )  # fmt: skip

    return make
