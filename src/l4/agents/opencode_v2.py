"""OpenCode v2 adapter (`@opencode/cli` 2.0.32, binary `opencode2`; experimental, L4-OCV-001 to -014, design
`openspec/changes/opencode-v2`), selected by `options.cli_major: 2`. This module is the command layer:

    opencode2 run --standalone --format json -m <provider/model> --title "l4 <role> <stem>"   # stdin: prompt, EOF

Every v2 call is standalone (without it a per-user daemon serves a later client the first client's environment
[V, row 8]) and has an empty `XDG_STATE_HOME` of its own, so a missed flag still cannot find a shared `service.json`.
`XDG_DATA_HOME` is never redirected: the credentials and `opencode.db` live there. v2 has no `--pure` and no `--dir`;
the cwd is the worktree (implement) or the empty judge directory (judge). The configuration is the native v2 shape,
not v1's, which v2 only normalises in memory (design D5). The parser is below (B5); the run and the probe are B6.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from l4.agents.base import (
    AdapterError,
    AgentCaps,
    PermissionPolicy,
    ProbeCtx,
    ProbeResult,
    ProbeStep,
    RunRequest,
    RunResult,
    Usage,
)
from l4.agents.contract import attach_file_result, attach_judge_reply
from l4.agents.opencode import _AUTH_FAILED, DISABLE_SWITCHES, FREE_PREFIX, GIT_WRITES, _Stream, _unsupported_version
from l4.agents.proc import ProcRunner
from l4.availability.limits import normalise_limit
from l4.config.schema import OpencodeOptions, Profile

JUDGE_STEPS = 3  # one answering step, one tolerated rejected attempt, v2's forced tool-less summary (D6)
IMPLEMENT_STEPS = 200  # about 10x the largest recorded tool-call count: only a model that never ends reaches it
STATE_DIR = "opencode2-state"  # the empty `XDG_STATE_HOME` of a run or an export, in the step's private directory
SWITCHES = (*DISABLE_SWITCHES, "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS")  # v2 reads the skills switch; ignores one more
# the only subcommands the harness starts, as words: there is no `debug config`, `serve`, `service`, `api`, `pair` or
# `models` (each starts or reaches the shared daemon)
SUBCOMMANDS = (("run",), ("auth", "list"), ("session", "export"))
# v1 tool name -> v2 permission action, for `options.tools`; `list` has none (glob and read cover it, refused at load)
TOOL_ACTIONS = {
    "bash": "shell", "edit": "edit", "write": "edit", "patch": "edit", "read": "read", "glob": "glob", "grep": "grep",
}  # fmt: skip


def v2_argv(exe: str, subcommand: str, *args: str) -> list[str]:
    """The one builder of every v2 argv: `--standalone` right after the subcommand words. `subcommand` may be one
    string of words (`"auth list"`) or the first of them. A subcommand outside `SUBCOMMANDS` raises, so nothing
    that could reach the shared daemon is ever started."""
    words = [*subcommand.split(), *args]
    for known in SUBCOMMANDS:
        if tuple(words[: len(known)]) == known:
            return [exe, *known, "--standalone", *words[len(known) :]]
    raise AdapterError(
        f"opencode2 {subcommand} is not a subcommand the harness starts (run, auth list, session export)"
    )


def isolation_env_v2(config_dir: Path, state_dir: Path, content: str) -> dict[str, str]:
    """The isolation of one v2 call: an empty `XDG_CONFIG_HOME`, the call's own `XDG_STATE_HOME` (never shared, never
    `XDG_DATA_HOME`), the five disable switches and `OPENCODE_CONFIG_CONTENT`."""
    return {
        "XDG_CONFIG_HOME": str(config_dir), "XDG_STATE_HOME": str(state_dir), **{name: "1" for name in SWITCHES},
        "OPENCODE_CONFIG_CONTENT": content,
    }  # fmt: skip


def _refuse_read_only(policy: PermissionPolicy) -> None:
    """The read-only mode serves the delegate only, and nothing of it is recorded on v2 (amendment E4, L4-OCV-014):
    a path that skipped the load check still fails closed."""
    if policy.mode == "read_only":
        raise AdapterError(
            "the OpenCode v2 adapter has no read-only mode (the delegate is not served by options.cli_major: 2, "
            "L4-OCV-014)"
        )


def step_bound(policy: PermissionPolicy, options: OpencodeOptions | None) -> int:
    """`agents.build.steps` (L4-OCV-006): `options.steps.judge` (default 3) for every judge-mode call and the hello,
    `options.steps.implement` (default 200) for an implementer step."""
    _refuse_read_only(policy)
    steps = options.steps if options is not None else None
    if policy.mode == "judge":
        return steps.judge if steps is not None and steps.judge is not None else JUDGE_STEPS
    return steps.implement if steps is not None and steps.implement is not None else IMPLEMENT_STEPS


def _rule(action: str, effect: str, resource: str = "*") -> dict[str, str]:
    return {"action": action, "resource": resource, "effect": effect}


def _permissions(
    policy: PermissionPolicy, result_dir: Path, refuse: str, options: OpencodeOptions | None
) -> list[dict[str, str]]:
    """The ordered `permissions` array (design D5): the last matching rule wins, so broad rules come first and the
    `external_directory` deny-all precedes the allows for the private result directory [pinned by a test]."""
    if policy.mode == "judge":
        if refuse == "ask":  # a full deny gets a 403 from the free tier on v2 [V]; run mode refuses an ask on the spot
            return [_rule("*", "deny"), _rule("read", "ask"), _rule("shell", "ask")]
        return [_rule("*", "deny")]
    rules: list[dict[str, str]] = []
    if options is not None and options.tools:
        # Fallback `tools_by_permission` (U2): whether a v2 deny drops the tool's schema from the request is not
        # recorded, so the intent of `options.tools` is a deny-all and the listed tools' allows. v2's own normalisation
        # of the v1 form would allow `shell` again after them [V, recorded], which is why the array is native.
        if "list" in options.tools:
            raise AdapterError("options.tools: list has no OpenCode v2 permission action (glob and read cover it)")
        actions = list(dict.fromkeys(TOOL_ACTIONS[tool] for tool in options.tools))
        rules += [_rule("*", "deny"), *(_rule(action, "allow") for action in actions)]
    else:
        actions = ["edit", "read", "glob", "grep", "shell"]
        rules += [_rule(action, "allow") for action in actions]
    if "shell" in actions:  # the harness commits, never the agent
        rules += [_rule("shell", "deny", pattern) for pattern in GIT_WRITES]
    rules += [
        _rule("external_directory", "deny"), _rule("external_directory", "allow", f"{result_dir}/**"),
        _rule("external_directory", "allow", f"{result_dir}/*"),
        _rule("webfetch", "deny"), _rule("websearch", "deny"), _rule("question", "deny"),
        # Fallback `deny_skill_and_mask` (U6): v2 has two actions v1 never named. Skills are guidance the harness does
        # not choose and a subagent is a background child session, so both get the profile's refuse value (`ask` on a
        # free model, whose tier answers a removed tool with a 403 [I, as for bash]).
        _rule("skill", refuse), _rule("subagent", refuse),
    ]  # fmt: skip
    return rules


def config_content_v2(
    policy: PermissionPolicy, result_dir: Path, model: str, options: OpencodeOptions | None = None
) -> str:
    """`OPENCODE_CONFIG_CONTENT` in the native v2 shape (L4-OCV-005): `$schema`, `snapshots`, `share`, `update`, the
    ordered `permissions` and `agents.build.steps`. No v1 key (`permission`, `tools`, `snapshot`, `autoupdate`) and no
    `list` or `doom_loop` rule, which are not v2 actions. A read-only policy raises (amendment E4)."""
    steps = step_bound(policy, options)
    refuse = "ask" if model.startswith(FREE_PREFIX) else "deny"
    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json", "snapshots": False, "share": "disabled", "update": "disable",
        "permissions": _permissions(policy, result_dir, refuse, options), "agents": {"build": {"steps": steps}},
    }  # fmt: skip
    return json.dumps(config, separators=(",", ":"))


@dataclass
class _StreamV2(_Stream):
    step_starts: int = 0  # one `step_start` per step [V]: the count that detects a run stopped at its bound


def strip_leading_think(text: str) -> str:
    """Fallback `strip_leading_think` (U9, L4-OCV-011): 1 of 6 recorded v2 hellos was `...</think>L4-OK`, a closing tag
    with no opening one [V once, cause I]. A text that holds `</think>` before any `<think>` loses everything up to
    and including the first `</think>` and is trimmed: by its closing tag, what goes was reasoning, not the answer.
    Any other text (an opening tag first, or no tag) is returned unchanged. A reply of only reasoning stays empty."""
    close, opened = text.find("</think>"), text.find("<think>")
    if close == -1 or (opened != -1 and opened < close):
        return text
    return text[close + len("</think>") :].strip()


def _is_denial(state: Mapping[str, Any]) -> bool:
    """A refused call: `Permission denied: <action>` (a deny rule) or the auto-reject of an `ask` [V, rows 10, 11]."""
    error = state.get("error")
    return (
        state.get("status") == "error"
        and isinstance(error, str)
        and (error.startswith("Permission denied:") or "cannot ask the user for permission" in error)
    )


def _scan_v2(lines: Sequence[str]) -> _StreamV2:
    """The events of one v2 run: the v1 envelope `{type, sessionID, part}` [V, row 15]; `error` events carry
    `{type, message, status, response}`. Each text part loses a leaked leading reasoning (`strip_leading_think`)."""
    out = _StreamV2()
    tokens = [0, 0, 0]
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if out.session is None and isinstance(event.get("sessionID"), str):
            out.session = event["sessionID"]
        part = event.get("part") if isinstance(event.get("part"), dict) else {}
        kind = event.get("type")
        if kind == "step_start":
            out.step_starts += 1
        elif kind == "text" and isinstance(part.get("text"), str):
            reply = strip_leading_think(part["text"])
            out.texts.append(reply)
            out.after_tool.append(reply)
        elif kind == "step_finish":
            out.last_reason = part.get("reason") if isinstance(part.get("reason"), str) else None
            if isinstance(part.get("cost"), int | float):
                out.cost = (out.cost or 0.0) + float(part["cost"])
            raw = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
            cache = raw.get("cache") if isinstance(raw.get("cache"), dict) else {}
            call = int(raw.get("input", 0)) + int(cache.get("read", 0)) + int(cache.get("write", 0))
            if raw:
                out.peak = max(out.peak or 0, call)
            tokens = [tokens[0] + int(raw.get("input", 0)), tokens[1] + int(raw.get("output", 0)),
                      tokens[2] + int(cache.get("read", 0))]  # fmt: skip
        elif kind == "tool_use":
            out.after_tool.clear()
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            if _is_denial(state):
                out.denials.append({"tool_name": part.get("tool"), "tool_input": state.get("input")})
            else:
                out.ran.append(str(part.get("tool") or "unknown"))
        elif kind == "error" and isinstance(event.get("error"), dict):
            out.error = event
    out.usage = Usage(tokens[0], tokens[1], tokens[2], out.cost, context_peak_tokens=out.peak)
    return out


def _number(value: object) -> int | float:
    return value if isinstance(value, int | float) and not isinstance(value, bool) else 0


def usage_from_export(export: Mapping[str, Any] | None) -> Usage | None:
    """Usage from `session export` (L4-OCV-008): per assistant message `tokens.input`, `tokens.output` and
    `tokens.cache.read` are summed, the cost is `info.cost` else the messages' sum, and the context peak is the
    largest `input + cache.read + cache.write` of one message. Fallback `sum_messages` (U11): whether a multi-step run
    exports one message per step is not recorded; the recorded single message equals `info.tokens`, which this sum
    also gives. None when the export holds no assistant message (the stream's `step_finish` sums stand in)."""
    if not isinstance(export, Mapping):
        return None
    messages = [m for m in export.get("messages") or () if isinstance(m, Mapping) and m.get("type") == "assistant"]
    if not messages:
        return None
    totals, peak, costs = [0, 0, 0], None, []
    for message in messages:
        raw = message.get("tokens") if isinstance(message.get("tokens"), Mapping) else {}
        cache = raw.get("cache") if isinstance(raw.get("cache"), Mapping) else {}
        read, write = int(_number(cache.get("read"))), int(_number(cache.get("write")))
        totals = [totals[0] + int(_number(raw.get("input"))), totals[1] + int(_number(raw.get("output"))),
                  totals[2] + read]  # fmt: skip
        if raw:  # `Usage` has no cache-write field: the writes only count toward the peak, as in v1
            peak = max(peak or 0, int(_number(raw.get("input"))) + read + write)
        if isinstance(message.get("cost"), int | float) and not isinstance(message.get("cost"), bool):
            costs.append(float(message["cost"]))
    info = export.get("info") if isinstance(export.get("info"), Mapping) else {}
    info_cost = info.get("cost")
    if isinstance(info_cost, int | float) and not isinstance(info_cost, bool):
        cost: float | None = float(info_cost)
    else:
        cost = sum(costs) if costs else None
    return Usage(totals[0], totals[1], totals[2], cost, context_peak_tokens=peak)


def _classify_v2(result: RunResult, event: dict[str, Any], model: str | None, now: datetime) -> None:
    """An `error` event `{type, message, status, response.body}` (L4-OCV-009): a limit by its status alone (402,
    429; `limits._opencode_v2`, never `text`, so no reset is guessed), `auth`, a retryable 5xx, else a named error."""
    error = event["error"]
    message = str(error.get("message") or "")
    kind = str(error.get("type") or "unknown")
    raw_status = error.get("status")
    status = raw_status if isinstance(raw_status, int) and not isinstance(raw_status, bool) else None
    limit = normalise_limit("opencode", model, structured=event, now=now)
    if limit is not None:
        result.limit = limit
        result.status = "rate_limited" if limit.kind == "rate_limit" else "quota"
    elif status in (401, 403) or kind == "provider.auth" or _AUTH_FAILED.search(message):
        # Fallback `auth_by_status` (U4): the OAuth refresh failure text is not recorded on v2, so the status and the
        # type decide, with v1's wording as a last resort. Both recorded free-tier 403s land here [V, rows 13, 24].
        result.status = "auth"
        result.detail = "opencode2 could not authenticate (the provider login is missing, expired or rejected)"
    else:
        result.detail = f"opencode2 reported an error ({kind}" + (f", status {status})" if status else ")")
        if status is not None and status >= 500:
            result.detail += ", retryable"


class OpenCodeV2Adapter:
    name = "opencode"  # both majors are the `opencode` adapter; the factory tells them apart by `cli_major`
    model_unverified: ClassVar[bool] = True  # SPEC 8.1: run mode does not report the served model
    experimental: ClassVar[bool] = True  # announced once per profile until B9 removes it (L4-OCV-013)

    def __init__(self, runner: ProcRunner | None = None) -> None:
        self._proc = runner or ProcRunner()

    def capabilities(self) -> AgentCaps:
        return AgentCaps("prompt_contract", False, False, False, False, False, False, True)

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        raise NotImplementedError("B6")  # the v2 probe; the v1 probe would start the wrong binary

    def build_command(self, req: RunRequest, *, exe: str, workdir: Path | None = None) -> list[str]:
        """`workdir` is the process's cwd (the caller sets it); v2 has no `--dir`, so it is not in the argv."""
        _refuse_read_only(req.permission_policy)
        model = req.profile.model
        if not model:
            raise AdapterError("an opencode profile needs a model (provider/model)")
        title = f"l4 {req.role} {req.raw_events_path.stem}"
        return v2_argv(exe, "run", "--format", "json", "-m", str(model), "--title", title)

    def run(self, req: RunRequest) -> RunResult:
        _refuse_read_only(req.permission_policy)  # before anything is created or started
        raise NotImplementedError("B6")

    def parse(
        self,
        lines: Sequence[str],
        *,
        exit_code: int,
        raw_events_path: Path,
        step_bound: int,
        export: Mapping[str, Any] | None = None,
        export_problem: str | None = None,
        timed_out: bool = False,
        interrupted: bool = False,
        result_text: str | None = None,
        schema: dict[str, Any] | None = None,
        judge: bool = False,
        model: str | None = None,
        now: datetime | None = None,
        stderr_tail: str = "",
    ) -> RunResult:
        """Status by design D7, the first rule that applies (L4-OCV-007). `export` is the parsed `session export`
        document, None when it is unavailable (`export_problem` says why: no session id, exit, timeout, not JSON).
        `step_bound` is `agents.build.steps` of the run (required: a forgotten bound would fail open). Pure. There is no
        read-only parse: the delegate is not served on v2 (amendment E4)."""
        stream = _scan_v2(lines)
        result = RunResult(
            status="error", raw_events_path=raw_events_path, final_text="\n".join(stream.texts) or None,
            last_message="\n".join(stream.after_tool) or None, session_id=stream.session, exit_code=exit_code,
            usage=usage_from_export(export) or stream.usage, permission_denials=stream.denials,
        )  # fmt: skip
        info = export.get("info") if isinstance(export, Mapping) else None
        outcome = info.get("outcome") if isinstance(info, Mapping) else None
        if timed_out:  # 1
            result.status = "timeout"
        elif interrupted:  # fallback `harness_interrupt` (U10): SIGINT's exit 130 is not recorded; the flag decides
            result.status = "cancelled"
        elif stream.error is not None:  # 2
            _classify_v2(result, stream.error, model, now or datetime.now(UTC))
        elif exit_code != 0:  # 3
            result.detail = _unsupported_version(stderr_tail) or f"opencode2 exited with code {exit_code}"
        elif stream.step_starts >= step_bound:
            # 4: fallback `not_ok_named` (U7): a bounded run's export outcome is not recorded, so a run that reached
            # `agents.build.steps` is never ok, whatever the export says
            if stream.denials:
                result.status = "permission_blocked"
                tools = sorted({str(d["tool_name"]) for d in stream.denials})
                result.detail = f"opencode2's permission rules rejected a tool call ({', '.join(tools)})"
            else:
                result.detail = f"step_bound: opencode2 stopped at agents.build.steps {step_bound}"
        elif isinstance(outcome, str):  # 5
            if outcome == "succeeded":
                self._attach_result(result, judge, result_text, schema)
            else:  # fallback `not_ok_named` (U7): only `succeeded` has been seen; any other outcome is named, not ok
                result.detail = f"opencode2 session outcome {outcome}"
        elif stream.last_reason == "stop":  # 6
            # fallback `export_decides` (U5): how often the final `step_finish` is missing on long runs is not recorded
            # (3 of 16 recorded runs emit it), so it counts only when the export cannot decide: the v1 rule
            self._attach_result(result, judge, result_text, schema)
        elif stream.denials:
            result.status = "permission_blocked"
            tools = sorted({str(d["tool_name"]) for d in stream.denials})
            result.detail = f"opencode2's permission rules rejected a tool call ({', '.join(tools)})"
        else:
            why = export_problem or ("no export" if export is None else "the export has no info.outcome")
            result.detail = f"opencode2 session export failed ({why}) and the stream has no final stop"
        return result

    @staticmethod
    def _attach_result(result: RunResult, judge: bool, result_text: str | None, schema: dict[str, Any] | None) -> None:
        """A judge replies in its last message (the text after the last tool call: a v2 judge may write prose around a
        rejected attempt before it answers), sliced and validated by the one shared slicer; an implementer by file."""
        if judge:
            attach_judge_reply(result, result.last_message, schema)
        else:
            attach_file_result(result, result_text, schema, "opencode2")
