"""OpenCode v2 adapter (`@opencode/cli` 2.0.32, binary `opencode2`; experimental, L4-OCV-001 to -014, design
`openspec/changes/opencode-v2`), selected by `options.cli_major: 2`. This module is the command layer:

    opencode2 run --standalone --format json -m <provider/model> --title "l4 <role> <stem>"   # stdin: prompt, EOF

Every v2 call is standalone (without it a per-user daemon serves a later client the first client's environment
[V, row 8]) and has an empty `XDG_STATE_HOME` of its own, so a missed flag still cannot find a shared `service.json`.
`XDG_DATA_HOME` is never redirected: the credentials and `opencode.db` live there. v2 has no `--pure` and no `--dir`;
the cwd is the worktree (implement) or the empty judge directory (judge). The configuration is the native v2 shape,
not v1's, which v2 only normalises in memory (design D5). The parser is below (B5); the run and the probe are B6.

The run is followed by `opencode2 session export --standalone <session id>` (stdin closed, 60 s, the same wrap), whose
`info.outcome` and token counts `parse` reads (design D7, D8). Every v2 call sees EOF on stdin: OpenCode 2 waits without
output while stdin stays open, even with the prompt as an argument [V, 2.0.32 and 2.1.4; amendment E1]. The run gets the
prompt then EOF, the export `stdin=None` (the process runner gives it /dev/null), the probes' steps run through
`ProbeCtx.run`, which also closes stdin.
"""

import json
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from l4.agents.activity import opencode_signals
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
    judge_workdir,
    read_result_file,
    wrap_command,
)
from l4.agents.contract import attach_file_result, attach_judge_reply
from l4.agents.credentials import credential_loader
from l4.agents.opencode import (
    _AUTH_FAILED,
    CONFIG_DIR,
    DISABLE_SWITCHES,
    FREE_PREFIX,
    GIT_WRITES,
    _Stream,
    _tail,
    _unsupported_version,
    error_class,
    error_status,
)
from l4.agents.proc import ProcRunner
from l4.availability.limits import normalise_limit
from l4.availability.probes import (
    _binary,
    _hello_verdict,
    _timed,
    credential_auth,
    credential_env,
    probe_env,
)
from l4.availability.quota import is_openrouter, now_of, openrouter_quota
from l4.availability.steps import step_run, timeout_reason
from l4.config.schema import OpencodeOptions, Profile
from l4.provision.catalog import OPENCODE2_BINARY
from l4.safepath import resolve_tool

JUDGE_STEPS = 3  # one answering step, one tolerated rejected attempt, v2's forced tool-less summary (D6)
IMPLEMENT_STEPS = 200  # about 10x the largest recorded tool-call count: only a model that never ends reaches it
STATE_DIR = "opencode2-state"  # the empty `XDG_STATE_HOME` of the run, in the step's private directory
EXPORT_STATE_DIR = "opencode2-export-state"  # the export's own (SCN-OCV-06: each call has a state directory of its own)
EXPORT_CONFIG_DIR = "opencode2-export-config"  # the export's own config home: the run's is writable by the agent
EXPORT_TIMEOUT_S = 60
EXPORT_LIMIT = 64 * 1024 * 1024  # a longer export is not read: it holds every message and tool output of the session
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")  # becomes an argv word: never an option
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


def _fresh_dir(path: Path) -> Path:
    """An empty private directory at `path`: a leftover of an earlier attempt is removed first. The agent can write the
    step's directory, so a symlink or any other non-directory planted at `path` is unlinked (never followed) and a
    directory is removed with what it holds: this never raises on a planted entry."""
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(mode=0o700, parents=True)
    return path


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


def _usage_max(export: Usage | None, stream: Usage) -> Usage:
    """The export may raise usage over the stream's step_finish sums, never lower it: the agent can write the
    opencode.db the export reads. Field-wise maximum of the values that exist; the stream alone with no export."""
    if export is None:
        return stream
    costs = [c for c in (export.cost_usd, stream.cost_usd) if c is not None]
    peaks = [p for p in (export.context_peak_tokens, stream.context_peak_tokens) if p is not None]
    return Usage(
        max(export.input_tokens, stream.input_tokens), max(export.output_tokens, stream.output_tokens),
        max(export.cached_input_tokens, stream.cached_input_tokens), max(costs) if costs else None,
        context_peak_tokens=max(peaks) if peaks else None,
    )  # fmt: skip


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
        return probe_opencode_v2(profile, step, ctx)

    def build_command(self, req: RunRequest, *, exe: str, workdir: Path | None = None) -> list[str]:
        """`workdir` is the process's cwd (the caller sets it); v2 has no `--dir`, so it is not in the argv."""
        _refuse_read_only(req.permission_policy)
        model = req.profile.model
        if not model:
            raise AdapterError("an opencode profile needs a model (provider/model)")
        title = f"l4 {req.role} {req.raw_events_path.stem}"
        return v2_argv(exe, "run", "--format", "json", "-m", str(model), "--title", title)

    def run(self, req: RunRequest) -> RunResult:
        """The run, then `session export` of its session (design D4, D7): both through the request's wrap, the export
        with the run's environment but a state directory of its own, no credential loader and stdin closed."""
        _refuse_read_only(req.permission_policy)  # before anything is created or started
        exe = resolve_tool(OPENCODE2_BINARY, req.env, forbid=(req.cwd,))
        if exe is None:
            raise AdapterError("opencode2 was not found on the agent PATH")
        model = req.profile.model
        if not model:
            raise AdapterError("an opencode profile needs a model (provider/model)")
        step_dir = req.result_path.parent
        step_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        req.result_path.unlink(missing_ok=True)  # a leftover from an earlier step must not pass for this one's result
        judge = req.permission_policy.mode == "judge"
        workdir = judge_workdir(req) if judge else req.cwd
        options = req.profile.opencode_options()
        bound = step_bound(req.permission_policy, options)
        content = config_content_v2(req.permission_policy, step_dir, model, options)
        config_dir = _fresh_dir(step_dir / CONFIG_DIR)  # empty: no user config can leak in

        def environment(state_name: str, config: Path) -> dict[str, str]:  # each call: its own empty state (SCN-OCV-06)
            return {**req.env, **isolation_env_v2(config, _fresh_dir(step_dir / state_name), content)}

        argv = self.build_command(req, exe=exe, workdir=workdir)
        with credential_loader(req) as load:  # OPENCODE_API_KEY (L4-PRV-028): a 0600 file, never env or argv
            cmd = wrap_command(req, load(argv), environment(STATE_DIR, config_dir), workdir)
            outcome = self._proc.run(
                cmd.argv, cmd.env, workdir, stdout_path=req.raw_events_path,
                stderr_path=req.raw_events_path.with_suffix(".stderr"), stdin=req.prompt, timeout_s=req.timeout_s,
                interrupt=req.interrupt, stall_timeout_s=req.stall_timeout_s, watch=req.watch, reader=opencode_signals,
            )  # fmt: skip
        lines = req.raw_events_path.read_text(encoding="utf-8", errors="replace").splitlines()
        export, problem = None, "no session id"
        if outcome.timed_out or outcome.stalled or outcome.interrupted:
            problem = "the run did not finish"  # D7 rule 1 decides: an export could not change the status
        elif (session := _scan_v2(lines).session) is not None:
            if _SESSION_ID.match(session):
                # the agent may have written the run's config home (a plugin, an `opencode.json`): the export, which
                # runs outside the agent's turn but with its session id, gets a config home created after the run
                export_config = _fresh_dir(step_dir / EXPORT_CONFIG_DIR)
                export, problem = self._export(req, exe, session, environment(EXPORT_STATE_DIR, export_config), workdir)
            else:
                problem = "an unsafe session id"  # never an argv word
        return self.parse(
            lines, exit_code=outcome.returncode, timed_out=outcome.timed_out or outcome.stalled,
            interrupted=outcome.interrupted, step_bound=bound, export=export, export_problem=problem,
            result_text=None if judge else read_result_file(req.result_path), schema=req.result_schema, judge=judge,
            model=model, raw_events_path=req.raw_events_path,
            stderr_tail=_tail(req.raw_events_path.with_suffix(".stderr")),
        )  # fmt: skip

    def _export(
        self, req: RunRequest, exe: str, session: str, env: Mapping[str, str], workdir: Path
    ) -> tuple[dict[str, Any] | None, str | None]:
        """`opencode2 session export --standalone <id>`: the parsed document, else None and why. The output is saved as
        `<stem>.export.json` beside the raw events, so `publish_agent_logs` treats it as it treats the stream's other
        siblings: a redacted copy is published and the raw file deleted (L4-OBS-002)."""
        stem = req.raw_events_path.stem
        saved = req.raw_events_path.with_name(f"{stem}.export.json")
        cmd = wrap_command(req, v2_argv(exe, "session export", session), env, workdir)
        done = self._proc.run(
            cmd.argv, cmd.env, workdir, stdout_path=saved, stderr_path=saved.with_name(f"{stem}.export.stderr"),
            stdin=None, timeout_s=EXPORT_TIMEOUT_S, interrupt=req.interrupt,
        )  # fmt: skip
        if done.timed_out:
            return None, "timeout"
        if done.returncode != 0:
            return None, f"exit {done.returncode}"
        try:
            if saved.stat().st_size > EXPORT_LIMIT:
                return None, f"larger than {EXPORT_LIMIT} bytes"
            document = json.loads(saved.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            return None, "not JSON"
        return (document, None) if isinstance(document, dict) else (None, "not JSON")

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
            usage=_usage_max(usage_from_export(export), stream.usage), permission_denials=stream.denials,
        )  # fmt: skip
        info = export.get("info") if isinstance(export, Mapping) else None
        outcome = info.get("outcome") if isinstance(info, Mapping) else None
        has_outcome = isinstance(info, Mapping) and "outcome" in info
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
        elif has_outcome:  # 5
            if outcome == "succeeded":
                self._attach_result(result, judge, result_text, schema)
            else:  # fallback `not_ok_named` (U7): only `succeeded` has been seen; any other outcome is named, not ok
                shown = outcome if isinstance(outcome, str) else json.dumps(outcome, default=str)[:80]
                result.detail = f"opencode2 session outcome {shown}"
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


# --- the probe (L4-OCV-001 probe part, -010, -011 hello; design D10, D12) ---


def probe_opencode_v2(profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
    """The ladder steps of a `cli_major: 2` profile: `binary` against `opencode2` with the `opencode2` gate key (a v1
    binary there fails with the v2 reason and nothing else runs), `auth` from `auth list --format json`, `quota` as in
    v1 (OpenRouter only) and the hello. Every step's process sees EOF on stdin (`ProbeCtx.run` closes it)."""
    result, exe = _binary(OPENCODE2_BINARY, profile, ctx)
    if step == "binary" or not result.ok:
        return result
    assert exe is not None
    model = profile.model
    if model is None or "/" not in model:
        return ProbeResult(step, False, reason="the opencode profile needs a model (provider/model)")
    options = profile.opencode_options()
    if step == "auth":
        if (decided := credential_auth(profile, ctx)) is not None:  # OPENCODE_API_KEY decides (L4-PRV-028)
            return decided
        if model.startswith(FREE_PREFIX):
            return ProbeResult(step, True, {"provider": "opencode", "login": "not needed"}, skipped=True)
        provider = model.split("/", 1)[0]
        with tempfile.TemporaryDirectory(dir=ctx.cwd, prefix="l4-opencode2-auth-") as scratch:
            config_dir, state = Path(scratch) / "config", Path(scratch) / "state"
            config_dir.mkdir(mode=0o700)  # `~/.config/opencode` is writable by agent runs and this runs on the host:
            state.mkdir(mode=0o700)  # empty config and state of its own; `XDG_DATA_HOME` stays (the credentials)
            content = config_content_v2(PermissionPolicy("judge"), Path(scratch), model, options)
            env = probe_env(ctx, isolation_env_v2(config_dir, state, content))
            done = step_run(ctx, "opencode2", "auth", v2_argv(exe, "auth list", "--format", "json"), env)
        if done.returncode != 0:
            return ProbeResult(step, False, reason=f"opencode2 auth list exited with code {done.returncode}")
        return _auth_result_v2(done.stdout or "", provider)
    if step == "quota":
        return openrouter_quota(profile, ctx) if is_openrouter(profile) else ProbeResult(step, True, skipped=True)
    return _hello_v2(profile, exe, model, ctx, options)


def _clean(message: object) -> str:
    """A CLI-supplied message as one short line: whitespace collapsed, at most 120 characters."""
    return " ".join(str(message).split())[:120]


def _auth_providers_v2(output: str) -> dict[str, str | None] | None:
    """The providers `opencode2 auth list --format json` shows: `[{id, name, connections: [{type, name, status?}]}]`
    [V, row 17]. Each `id` maps to None when one of its connections is usable (no status, or a status other than
    `needs_auth`), else to the `needs_auth` message ("" when it has none). A provider with no connection is not listed.
    None when the output is not a JSON list. Presence only, as in v1: the hello is the authoritative check."""
    try:
        listing = json.loads(output)
    except ValueError:
        return None
    if not isinstance(listing, list):
        return None
    found: dict[str, str | None] = {}
    for entry in listing:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        connections = entry["connections"] if isinstance(entry.get("connections"), list) else []
        blocked: list[str] = []
        usable = False
        for connection in connections:
            status = connection.get("status") if isinstance(connection, dict) else None
            if isinstance(status, dict) and status.get("status") == "needs_auth":
                blocked.append(_clean(status.get("message") or ""))
            elif isinstance(connection, dict):
                usable = True
        if usable:
            found[entry["id"]] = None
        elif blocked and entry["id"] not in found:
            found[entry["id"]] = blocked[0]
    return found


def _auth_result_v2(output: str, provider: str) -> ProbeResult:
    """The auth step's verdict for `provider` from `auth list` output (L4-OCV-010): present with a usable connection,
    `needs_auth` named with its message, absent, or an unrecognised answer."""
    providers = _auth_providers_v2(output)
    if providers is None:
        return ProbeResult("auth", False, reason="opencode2 auth list gave an unrecognised answer")
    if provider not in providers:
        return ProbeResult("auth", False, reason=f"opencode2 has no credential for provider {provider}")
    if (message := providers[provider]) is not None:
        return ProbeResult("auth", False, reason=f"opencode2 reports {provider} needs auth ({message})")
    return ProbeResult("auth", True, {"logged_in": True, "provider": provider})


def _hello_v2(
    profile: Profile, exe: str, model: str, ctx: ProbeCtx, options: OpencodeOptions | None = None
) -> ProbeResult:
    """Isolated like a run (L4-OCV-004): an empty working directory, config directory and state directory, tools off,
    stdin closed, the hello prompt as an argument. No export: the verdict is the exit code, an `error` event and the
    reply (D7's error mapping, `strip_leading_think` already applied by `_scan_v2`; no `step_finish` is required)."""
    with tempfile.TemporaryDirectory(dir=ctx.cwd, prefix="l4-opencode2-probe-") as scratch:
        work, config_dir, state = Path(scratch) / "cwd", Path(scratch) / "config", Path(scratch) / "state"
        work.mkdir()
        config_dir.mkdir(mode=0o700)
        state.mkdir(mode=0o700)
        content = config_content_v2(PermissionPolicy("judge"), work, model, options)
        env = probe_env(ctx, {**credential_env(profile, ctx)[1], **isolation_env_v2(config_dir, state, content)})
        argv = v2_argv(exe, "run", "--format", "json", "-m", model, "--title", "l4 hello", ctx.hello_prompt)
        done, millis = _timed(ctx, argv, env, work)
    stream = _scan_v2((done.stdout or "").splitlines())
    reply = "\n".join(stream.texts) if stream.texts else None
    failure, limit, kind = None, None, None
    if stream.error is not None:
        error = stream.error["error"]
        message = str(error.get("message") or "")
        status = error_status(error.get("status"), message)
        limit = normalise_limit("opencode", model, structured=stream.error, now=now_of(ctx))
        if limit is not None:
            failure = "opencode2 reported a rate limit" if limit.kind == "rate_limit" else "opencode2 is out of credits"
        elif status in (401, 403) or error.get("type") == "provider.auth" or _AUTH_FAILED.search(message):
            failure, kind = "opencode2 authentication failed (login expired or rejected)", "auth"
        else:
            failure = "opencode2 reported an error" + (f" (status {status})" if status else "")
            kind = error_class(status, message)
    elif done.returncode not in (0, 124):
        failure, kind = f"opencode2 exited with code {done.returncode}", "transient"
    return _hello_verdict(
        reply, millis, done.returncode == 124, failure, limit, kind,
        timeout_reason("opencode2", ctx.timeout_s, "hello"),
    )  # fmt: skip
