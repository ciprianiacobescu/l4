"""OpenCode adapter (opencode 1.18.x), invoked as SPEC 8.3.1 confirms:

    opencode run --pure --format json -m <provider/model> --dir <worktree> --title "l4 ..."   # stdin: prompt, EOF

Isolation (L4-SEC-002) is an empty per-step `XDG_CONFIG_HOME` (never `XDG_DATA_HOME`: `auth.json` lives there), the four
`OPENCODE_DISABLE_*` switches and an explicit `OPENCODE_CONFIG_CONTENT`. The permission map has allow and deny only: an
`ask` is auto-rejected and ends the run with exit 0. The result is a prompt contract (the file named in the prompt);
the tool-less judge mode (gap G18) reads its JSON out of the reply text instead. The run mode does not report the
served model, so the profile's declared vendor stands in for it (`model_unverified`).
M1: agent-factory 3.1 (serve mode), 3.3 (native schema), metered providers' `limit` block.
"""

import json
import re
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
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
from l4.agents.contract import attach_file_result, attach_judge_reply, attach_read_only_reply
from l4.agents.credentials import credential_loader
from l4.agents.opencode_provider import key_from, provider_config, provider_host, reachable, write_key_file
from l4.agents.proc import ProcRunner
from l4.availability.limits import normalise_limit
from l4.availability.probes import (
    _binary,
    _hello_verdict,
    _timed,
    credential_auth,
    credential_env,
    probe_env,
    status_class,
)
from l4.availability.quota import is_openrouter, now_of, openrouter_quota
from l4.availability.steps import step_run, timeout_reason
from l4.config.schema import OpencodeOptions, Profile
from l4.safepath import resolve_tool

FREE_PREFIX = "opencode/"  # OpenCode Zen's own models: no login needed [V, runner]
DISABLE_SWITCHES = (
    "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_DISABLE_CLAUDE_CODE",
    "OPENCODE_DISABLE_EXTERNAL_SKILLS", "OPENCODE_DISABLE_AUTOUPDATE",
)  # fmt: skip
READ_TOOLS = ("read", "glob", "grep")  # the whole tool surface of a read-only (delegate) run
GIT_WRITES = ("git commit*", "git push*", "git reset*", "git checkout*")  # the harness commits, never the agent
CONFIG_DIR = "opencode-config"
_REJECTED = re.compile(r"rejected permission|prevents you from using this specific tool call", re.I)
# OpenCode v2 removed `--pure` and `--dir` (L4-OCG-003); stderr names the flag, the run help is on stdout
_UNRECOGNIZED = re.compile(r"Unrecognized flag: --(pure|dir)\b")
STDERR_TAIL = 8192
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_BRACKET_STATUS = re.compile(r"\[(\d{3})\]")
_AUTH_FAILED = re.compile(r"token refresh failed|unauthori[sz]ed|\b40[13]\b", re.I)
# a custom provider's server compiles the tools' JSON schemas into a decoding grammar and can refuse (400), and the
# machine behind it may sleep: both are "this provider cannot serve now", retryable, not a verdict on the work
_GRAMMAR = re.compile(r"grammar binding failed", re.I)
_UNREACHABLE = re.compile(
    r"ECONNREFUSED|ECONNRESET|ETIMEDOUT|EHOSTUNREACH|ENETUNREACH|unable to connect|fetch failed", re.I
)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def config_content(
    policy: PermissionPolicy, result_dir: Path, model: str,
    options: OpencodeOptions | None = None, key_path: Path | None = None,
) -> str:  # fmt: skip
    """`OPENCODE_CONFIG_CONTENT`. Key order is part of the contract: OpenCode applies the last matching rule, so the
    `external_directory` deny-all precedes the allow for the private result directory [I, pinned by a test].

    OpenCode Zen's free models answer 403 "free tier can only be used from within OpenCode" when `bash` or `read` is
    denied (the tool is then missing from the request) [V live, 1.18.33 and the runner's 1.18.34, 2026-10-04]. For
    them a denial is written as `ask`, which run mode rejects on the spot without running anything."""
    refuse = "ask" if model.startswith(FREE_PREFIX) else "deny"
    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json", "snapshot": False, "share": "disabled", "autoupdate": False,
    }  # fmt: skip
    if options is not None and options.provider is not None and key_path is not None:
        config["provider"] = provider_config(options, model, key_path)
    if policy.mode == "judge":
        if refuse == "ask":
            config["permission"] = {"*": "deny", "read": "ask", "bash": "ask"}
        else:
            config |= {"tools": {"*": False}, "permission": {"*": "deny"}}
        return json.dumps(config, separators=(",", ":"))
    writing = policy.mode == "implement"
    if options is not None and options.tools:  # a small tool set keeps the server's grammar under its limit
        config["tools"] = {"*": False, **dict.fromkeys(options.tools, True)}
    config["permission"] = {
        "edit": "allow" if writing else "deny", "read": "allow", "glob": "allow", "grep": "allow", "list": "allow",
        "bash": {"*": "allow", **{rule: "deny" for rule in GIT_WRITES}} if writing else refuse,
        "external_directory": {"*": "deny", f"{result_dir}/**": "allow", f"{result_dir}/*": "allow"},
        "webfetch": "deny", "websearch": "deny", "question": "deny", "doom_loop": "deny",
    }  # fmt: skip
    return json.dumps(config, separators=(",", ":"))


def isolation_env(config_dir: Path, content: str) -> dict[str, str]:
    return {
        "XDG_CONFIG_HOME": str(config_dir), **{name: "1" for name in DISABLE_SWITCHES},
        "OPENCODE_CONFIG_CONTENT": content,
    }  # fmt: skip


@dataclass
class _Stream:
    session: str | None = None
    texts: list[str] = field(default_factory=list)
    after_tool: list[str] = field(default_factory=list)  # the text parts since the last `tool_use`
    peak: int | None = None  # the largest input + cache read + cache write of one `step_finish`
    cost: float | None = None
    usage: Usage = field(default_factory=Usage)
    last_reason: str | None = None
    error: dict[str, Any] | None = None  # the last `error` event
    denials: list[dict[str, Any]] = field(default_factory=list)
    ran: list[str] = field(default_factory=list)  # the tool of every `tool_use` that was not refused before it ran


def _scan(lines: Sequence[str]) -> _Stream:
    out = _Stream()
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
        if kind == "text" and isinstance(part.get("text"), str):
            out.texts.append(part["text"])
            out.after_tool.append(part["text"])
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
            if state.get("status") == "error" and _REJECTED.search(str(state.get("error") or "")):
                out.denials.append({"tool_name": part.get("tool"), "tool_input": state.get("input")})
            else:
                out.ran.append(str(part.get("tool") or "unknown"))
        elif kind == "error" and isinstance(event.get("error"), dict):
            out.error = event
    out.usage = Usage(tokens[0], tokens[1], tokens[2], out.cost, context_peak_tokens=out.peak)
    return out


def _error_data(event: dict[str, Any]) -> dict[str, Any]:
    data = event["error"].get("data")
    return data if isinstance(data, dict) else {}


def _has_provider(options: OpencodeOptions | None) -> bool:
    return options is not None and options.provider is not None


def _unsupported_version(stderr: str) -> str | None:
    """The reason when stderr says the binary rejected a v1 flag, else None."""
    found = _UNRECOGNIZED.search(stderr)
    if found is None:
        return None
    return (
        f"unsupported_version: opencode rejected --{found.group(1)}: the binary on PATH is not OpenCode v1 "
        "(run opencode --version)"
    )


def _tail(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - STDERR_TAIL))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


class OpenCodeAdapter:
    name = "opencode"
    model_unverified: ClassVar[bool] = True  # SPEC 8.1: run mode does not report the served model

    def __init__(self, runner: ProcRunner | None = None) -> None:
        self._proc = runner or ProcRunner()

    def capabilities(self) -> AgentCaps:
        return AgentCaps("prompt_contract", False, False, False, False, False, False, True)

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        return probe_opencode(profile, step, ctx)

    def build_command(self, req: RunRequest, *, exe: str, workdir: Path) -> list[str]:
        title = f"l4 {req.role} {req.raw_events_path.stem}"
        return [exe, "run", "--pure", "--format", "json", "-m", str(req.profile.model), "--dir", str(workdir),
                "--title", title]  # fmt: skip

    def run(self, req: RunRequest) -> RunResult:
        exe = resolve_tool("opencode", req.env, forbid=(req.cwd,))
        if exe is None:
            raise AdapterError("opencode was not found on the agent PATH")
        model = req.profile.model
        if not model:
            raise AdapterError("an opencode profile needs a model (provider/model)")
        step_dir = req.result_path.parent
        step_dir.mkdir(mode=0o700, parents=True, exist_ok=True)  # the key's directory is the step's own (L4-PRV-040)
        req.result_path.unlink(missing_ok=True)  # a leftover from an earlier step must not pass for this one's result
        config_dir = step_dir / CONFIG_DIR
        shutil.rmtree(config_dir, ignore_errors=True)
        config_dir.mkdir(mode=0o700)
        judge = req.permission_policy.mode == "judge"
        read_only = req.permission_policy.mode == "read_only"
        # no tool can read the repository, and its AGENTS.md need not be loaded as instructions either
        workdir = judge_workdir(req) if judge else req.cwd
        options = req.profile.opencode_options()
        key_path = write_key_file(config_dir, key_from(req.host_env, options)) if _has_provider(options) else None
        try:
            env = {
                **req.env,
                **isolation_env(config_dir, config_content(req.permission_policy, step_dir, model, options, key_path)),
            }
            argv = self.build_command(req, exe=exe, workdir=workdir)
            with credential_loader(req) as load:  # OPENCODE_API_KEY (L4-PRV-028): a 0600 file, never env or argv
                cmd = wrap_command(req, load(argv), env, workdir)
                outcome = self._proc.run(
                    cmd.argv, cmd.env, workdir, stdout_path=req.raw_events_path,
                    stderr_path=req.raw_events_path.with_suffix(".stderr"), stdin=req.prompt, timeout_s=req.timeout_s,
                    interrupt=req.interrupt, stall_timeout_s=req.stall_timeout_s,
                    watch=req.watch, reader=opencode_signals,
                )  # fmt: skip
        finally:
            if key_path is not None:
                key_path.unlink(missing_ok=True)  # the credential does not outlive the step
        return self.parse(
            req.raw_events_path.read_text(encoding="utf-8", errors="replace").splitlines(),
            exit_code=outcome.returncode, timed_out=outcome.timed_out or outcome.stalled,
            interrupted=outcome.interrupted,
            result_text=None if judge or read_only else read_result_file(req.result_path),
            schema=req.result_schema, judge=judge, read_only=read_only, model=req.profile.model,
            raw_events_path=req.raw_events_path, stderr_tail=_tail(req.raw_events_path.with_suffix(".stderr")),
        )  # fmt: skip

    def parse(
        self,
        lines: Sequence[str],
        *,
        exit_code: int,
        raw_events_path: Path,
        timed_out: bool = False,
        interrupted: bool = False,
        result_text: str | None = None,
        schema: dict[str, Any] | None = None,
        judge: bool = False,
        read_only: bool = False,
        model: str | None = None,
        now: datetime | None = None,
        stderr_tail: str = "",
    ) -> RunResult:
        """Status from the events and the exit code together (L4-FAC-002): an `error` event decides before any
        `step_finish` does, and only a last reason of `stop` is a finished run. Pure. A `read_only` run (the delegate,
        L4-DLG-015) replies in its last message: a call refused before it ran voids nothing (the reply must be valid),
        a tool outside the read set that did run voids the run."""
        stream = _scan(lines)
        result = RunResult(
            status="error", raw_events_path=raw_events_path, final_text="\n".join(stream.texts) or None,
            last_message="\n".join(stream.after_tool) or None,
            session_id=stream.session, exit_code=exit_code, usage=stream.usage,
            permission_denials=stream.denials,
        )  # fmt: skip
        if timed_out:
            result.status = "timeout"
        elif interrupted:
            result.status = "cancelled"
        elif stream.error is not None:
            self._classify_error(result, stream.error, model, now or datetime.now(UTC))
        elif exit_code != 0:
            result.detail = _unsupported_version(stderr_tail) or f"opencode exited with code {exit_code}"
        elif stream.last_reason == "stop":
            self._attach_result(result, judge, result_text, schema, read_only, stream)
        elif stream.denials:
            result.status = "permission_blocked"
            tools = sorted({str(d["tool_name"]) for d in stream.denials})
            result.detail = f"opencode's permission rules rejected a tool call ({', '.join(tools)})"
        else:
            result.detail = f"the stream ended without a final stop (last reason: {stream.last_reason or 'none'})"
        return result

    @staticmethod
    def _classify_error(result: RunResult, event: dict[str, Any], model: str | None, now: datetime) -> None:
        data = _error_data(event)
        message = str(data.get("message") or "")
        status = data.get("statusCode") or (m.group(1) if (m := _BRACKET_STATUS.search(message)) else None)
        limit = normalise_limit("opencode", model, structured=event, text=message, now=now)
        if limit is not None:
            result.limit = limit
            result.status = "rate_limited" if limit.kind == "rate_limit" else "quota"
        elif _GRAMMAR.search(message) or _UNREACHABLE.search(message):
            result.detail = "provider_unavailable: the custom provider could not serve the request"
            result.detail += " (grammar binding failed)" if _GRAMMAR.search(message) else " (connection failed)"
            result.detail += ", retryable"
        elif status in (401, 403) or _AUTH_FAILED.search(message):
            result.status = "auth"
            result.detail = "opencode could not authenticate (the provider login is missing, expired or rejected)"
        else:
            result.detail = "opencode reported an error" + (f" (status {status})" if status else "")
            if data.get("isRetryable") or "overloaded" in message.lower():
                result.detail += ", retryable"

    @staticmethod
    def _attach_result(
        result: RunResult, judge: bool, result_text: str | None, schema: dict[str, Any] | None,
        read_only: bool = False, stream: _Stream | None = None,
    ) -> None:  # fmt: skip
        if read_only:
            outside = sorted({tool for tool in (stream.ran if stream else ()) if tool not in READ_TOOLS})
            if outside:
                result.detail = f"opencode called a tool outside the read set ({', '.join(outside)})"
            else:
                attach_read_only_reply(result, result.last_message, result.final_text, schema)
                if result.structured is None and stream is not None and stream.denials:
                    refused = sorted({str(d["tool_name"]) for d in stream.denials})
                    result.rejected = None
                    result.detail = (
                        f"opencode's permission rules rejected a tool call ({', '.join(refused)}) and the run "
                        "ended without a valid reply"
                    )  # a refused call that no reply redeems is an adapter error (a deferral), not a bad reply
            return
        if judge:
            attach_judge_reply(result, result.final_text, schema)
            return
        attach_file_result(result, result_text, schema, "opencode")


def _auth_providers(output: str) -> set[str]:
    """Provider names `opencode auth list` shows, stored credentials and environment variables alike. Presence only:
    the list shows display names ("OpenRouter", "OpenCode Go"); an expired OAuth login stays listed [V, spikes/05]."""
    found = set()
    for raw in _ANSI.sub("", output).splitlines():
        words = raw.strip().removeprefix("●").split()
        if raw.strip().startswith("●") and len(words) >= 2:
            found.add(_norm("".join(words[:-1])))
    return found


def probe_opencode(profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
    result, exe = _binary("opencode", profile, ctx)
    if step == "binary" or not result.ok:
        return result
    assert exe is not None
    model = profile.model
    if model is None or "/" not in model:
        return ProbeResult(step, False, reason="the opencode profile needs a model (provider/model)")
    options = profile.opencode_options()
    if step == "auth":
        if _has_provider(options):
            return _provider_auth(options, ctx)
        if (decided := credential_auth(profile, ctx)) is not None:  # OPENCODE_API_KEY decides (L4-PRV-028)
            return decided
        if model.startswith(FREE_PREFIX):
            return ProbeResult(step, True, {"provider": "opencode", "login": "not needed"}, skipped=True)
        provider = model.split("/", 1)[0]
        done = step_run(ctx, "opencode", "auth", [exe, "auth", "list"], probe_env(ctx))
        if done.returncode == 0 and _norm(provider) in _auth_providers(done.stdout or ""):
            return ProbeResult(step, True, {"logged_in": True, "provider": provider})
        reason = f"opencode has no credential for provider {provider} (opencode auth login)"
        return ProbeResult(step, False, reason=reason)
    if step == "quota":
        return openrouter_quota(profile, ctx) if is_openrouter(profile) else ProbeResult(step, True, skipped=True)
    return _hello(profile, exe, model, ctx, options)


def _provider_auth(options: OpencodeOptions | None, ctx: ProbeCtx) -> ProbeResult:
    """A provider key is a variable of the harness's environment, not an `opencode auth` login: presence only (the
    value is never read into a result). Whether the key works shows at the hello, which goes through the provider."""
    assert options is not None and options.provider is not None
    try:
        key_from(ctx.environ, options)
    except AdapterError as error:
        return ProbeResult("auth", False, reason=str(error))
    detail = {"provider": options.provider.id, "host": provider_host(options.provider.base_url), "key": "present"}
    return ProbeResult("auth", True, detail)


def _hello(
    profile: Profile, exe: str, model: str, ctx: ProbeCtx, options: OpencodeOptions | None = None
) -> ProbeResult:
    """Isolated like a run (SPEC 8.3.1): an empty working directory and config directory, tools off. This is also the
    auth check for OAuth providers: an expired login surfaces only here, as `Token refresh failed: 401`."""
    key: str | None = None
    if options is not None and options.provider is not None:
        try:
            key = key_from(ctx.environ, options)
        except AdapterError as error:
            return ProbeResult(
                "hello", False, reason=str(error), failure_class="auth"
            )  # no usable key: a human fixes it
        up, why = reachable(options.provider.base_url)
        if not up:  # a machine that sleeps is unavailable, so the walk goes on to the next profile
            return ProbeResult("hello", False, reason=f"provider unreachable: {why}", failure_class="transient")
    with tempfile.TemporaryDirectory(dir=ctx.cwd, prefix="l4-opencode-probe-") as scratch:
        work, config_dir = Path(scratch) / "cwd", Path(scratch) / "config"
        work.mkdir()
        config_dir.mkdir(mode=0o700)  # the scratch directory is 0700 already (tempfile); the key's own is too
        key_path = write_key_file(config_dir, key) if key is not None else None
        content = config_content(PermissionPolicy("judge"), work, model, options, key_path)
        env = probe_env(ctx, {**credential_env(profile, ctx)[1], **isolation_env(config_dir, content)})
        argv = [exe, "run", "--pure", "--format", "json", "-m", model, "--title", "l4 hello", ctx.hello_prompt]
        done, millis = _timed(ctx, argv, env, work)
    stream = _scan((done.stdout or "").splitlines())
    reply = "\n".join(stream.texts) if stream.texts else None
    failure, limit, kind = None, None, None
    if stream.error is not None:
        data = _error_data(stream.error)
        message = str(data.get("message") or "")
        limit = normalise_limit("opencode", model, structured=stream.error, text=message, now=now_of(ctx))
        if limit is not None:
            failure = "opencode reported a rate limit" if limit.kind == "rate_limit" else "opencode is out of credits"
        elif data.get("statusCode") in (401, 403) or _AUTH_FAILED.search(message):
            failure, kind = "opencode authentication failed (login expired or rejected)", "auth"
        else:
            status = data.get("statusCode")
            failure = "opencode reported an error" + (f" (status {status})" if status else "")
            kind = status_class(status)
    elif done.returncode not in (0, 124):
        rejected = _unsupported_version(done.stderr or "")
        failure = rejected or f"opencode exited with code {done.returncode}"
        kind = "unsupported_version" if rejected else "transient"
    return _hello_verdict(
        reply, millis, done.returncode == 124, failure, limit, kind, timeout_reason("opencode", ctx.timeout_s, "hello")
    )
