"""Probe steps (SPEC L4-AVL-001) for codex and claude-code, and the ladder that runs them (`ProbeLadder`).

Nothing here records an e-mail, an organisation, a key fragment or raw CLI output: every `detail` and `reason` is built
from fields this module chose. Probes run on the host in an empty scratch directory with a minimal environment.
`mcp` and `custom` steps are skipped (M1: agent-factory 7.3, 7.4).
"""

import json
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from l4.agents.base import (
    TRANSIENT_STATUSES,
    AdapterError,
    AgentAdapter,
    FailureClass,
    LimitSignal,
    ProbeCtx,
    ProbeResult,
    ProbeStep,
)
from l4.agents.credentials import credential_in, profile_credential_variable
from l4.availability.limits import normalise_limit
from l4.availability.quota import Window, claude_quota, codex_quota, now_of, rate_limit_event_windows
from l4.availability.rpc import run_rpc_session
from l4.availability.steps import StepTimedOut, step_run, step_seconds, timeout_reason
from l4.config.schema import Profile
from l4.provision.catalog import ADAPTER_BINARIES, ADAPTER_PINS, SUPPORTED_MAJORS, major_problem
from l4.safepath import resolve_tool, safe_path
from l4.versions import major_of, version_at_least

OK_REPLY = "L4-OK"
_FENCE = re.compile(r"\A```[A-Za-z0-9_+-]*\n(.*?)\n?```\Z", re.DOTALL)
_VERSION = re.compile(r"\d+\.\d+\.\d+")
BINARIES = {"codex": "codex", "claude-code": "claude"}


def normalise_hello(text: str) -> str:
    """Trim; remove one wrapping layer (a whole code fence, or a matching backtick/quote pair); trim."""
    text = text.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    elif len(text) >= 2 and text[0] == text[-1] and text[0] in "`\"'":
        text = text[1:-1]
    return text.strip()


def probe_env(ctx: ProbeCtx, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = {"PATH": safe_path(ctx.environ, forbid=ctx.forbid)}
    for name in ("HOME", "USER", "LANG", "TZ", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
        if ctx.environ.get(name):
            env[name] = ctx.environ[name]
    env.setdefault("LANG", "C.UTF-8")
    env.update(extra or {})
    return env


def _binary(name: str, profile: Profile, ctx: ProbeCtx) -> tuple[ProbeResult, str | None]:
    exe = resolve_tool(name, ctx.environ, forbid=ctx.forbid)
    if exe is None:
        return ProbeResult("binary", False, reason=f"{name} not found on PATH"), None
    done = step_run(ctx, name, "binary", [exe, "--version"], probe_env(ctx))
    found = _VERSION.search(done.stdout or "")
    if done.returncode != 0 or not found:
        return ProbeResult("binary", False, reason=f"{name} --version did not report a version"), exe
    detail: dict[str, Any] = {"version": found.group(0)}
    adapter = next((a for a, b in ADAPTER_BINARIES.items() if b == name), name)
    if adapter in SUPPORTED_MAJORS:  # the major first, whatever min_version says (L4-OCG-002)
        if (wrong := major_problem(adapter, name, done.stdout or "", ADAPTER_PINS[adapter])) is not None:
            return ProbeResult("binary", False, reason=wrong), exe
        detail["major"] = major_of(done.stdout or "")
    if profile.min_version and version_at_least(found.group(0), profile.min_version) is False:
        return ProbeResult("binary", False, reason=f"version {found.group(0)} < min_version {profile.min_version}"), exe
    return ProbeResult("binary", True, detail), exe


def credential_env(profile: Profile, ctx: ProbeCtx) -> tuple[str | None, dict[str, str]]:
    """The profile's credential variable (L4-PRV-024) and, when the host has it set, the one-entry environment to add
    to this profile's auth, quota and hello calls (and no other profile's): `(NAME, {NAME: value})`, else `(NAME, {})`.
    """
    variable = profile_credential_variable(profile)
    value = credential_in(ctx.environ, variable)
    return variable, ({variable: value} if variable and value else {})


def credential_auth(profile: Profile, ctx: ProbeCtx) -> ProbeResult | None:
    """The auth step when the environment decides it: a set variable passes (the hello step proves it works, no status
    or login command runs); an unset api_key variable fails naming it. None: a file login decides."""
    variable, extra = credential_env(profile, ctx)
    if extra:
        return ProbeResult("auth", True, {"auth_method": "env"})
    if variable and profile.auth == "api_key":
        return ProbeResult("auth", False, reason=f"{variable} is not set")
    return None


def login_failed(profile: Profile, reason: str) -> ProbeResult:
    """A failed file-login check; a profile with a credential variable is told it may set it instead."""
    variable = profile_credential_variable(profile)
    return ProbeResult("auth", False, reason=f"{reason} (or set {variable})" if variable else reason)


def _timed(ctx: ProbeCtx, argv: list[str], env: dict[str, str], cwd: Path | None = None) -> tuple[Any, int]:
    started = time.monotonic()
    done = ctx.run(argv, cwd or ctx.cwd, env, ctx.timeout_s)
    return done, int((time.monotonic() - started) * 1000)


_AUTH_TEXT = re.compile(r"\b40[13]\b|unauthori[sz]ed|forbidden|authentication|permission denied", re.I)
_TRANSIENT_TEXT = re.compile(r"\b5\d\d\b|unavailable|overloaded|timed? ?out|connection (reset|refused|closed)", re.I)


def status_class(status: object) -> FailureClass:
    """The class of an HTTP status a vendor CLI reported: 401/403 auth, 429 limit, 5xx transient, else other."""
    if isinstance(status, int) and not isinstance(status, bool):
        if status in (401, 403):
            return "auth"
        if status == 429:
            return "limit"
        if status >= 500:
            return "transient"
    return "other"


def text_class(text: str) -> FailureClass:
    """The class of a failure that only came with words (no status): auth wording, then server-side wording."""
    if _AUTH_TEXT.search(text):
        return "auth"
    return "transient" if _TRANSIENT_TEXT.search(text) else "other"


def _hello_verdict(
    reply: str | None,
    millis: int,
    timed_out: bool,
    failure: str | None,
    limit: LimitSignal | None = None,
    failure_class: FailureClass | None = None,
    timeout_text: str = "timeout",
) -> ProbeResult:
    """`failure_class` is what the caller learned about a failure (a status, a message); a limit and a timeout decide
    their own class here, and a reply that is not the hello answer is `other`: the model answered, wrongly."""
    if timed_out:
        return ProbeResult("hello", False, reason=timeout_text, failure_class="transient")
    if failure:
        return ProbeResult(
            "hello", False, reason=failure, limit=limit, failure_class="limit" if limit else failure_class or "other"
        )
    if reply is None or normalise_hello(reply) != OK_REPLY:
        return ProbeResult("hello", False, reason="unexpected reply", failure_class="other")
    return ProbeResult("hello", True, {"ms": millis})


_CODEX_ACCOUNT = (
    {"method": "initialize", "id": 1, "params": {"clientInfo": {"name": "l4-probe", "version": "0.0.1"}}},
    {"method": "initialized"},
    {"method": "account/read", "id": 2, "params": {"refreshToken": False}},
)


def _codex_auth(profile: Profile, exe: str, env: dict[str, str], ctx: ProbeCtx) -> ProbeResult:
    """`account/read` of the zero-token app-server: only `type` and `planType` are kept (never the e-mail or ids)."""
    seconds, started = step_seconds(ctx), time.monotonic()
    answers = (ctx.rpc or run_rpc_session)([exe, "app-server"], ctx.cwd, env, seconds, _CODEX_ACCOUNT)
    reply = answers.get(2)
    if reply is None and time.monotonic() - started >= seconds:
        raise StepTimedOut(timeout_reason("codex", seconds, "auth"))
    result = reply.get("result") if isinstance(reply, dict) else None
    if not isinstance(result, dict) or "account" not in result:
        return ProbeResult("auth", False, reason="codex app-server gave an unrecognised account answer")
    account = result["account"]
    if not isinstance(account, dict):
        return ProbeResult("auth", False, reason="codex is not logged in (ChatGPT login required)")
    if account.get("type") != "chatgpt":
        return ProbeResult("auth", False, reason="codex is not logged in with ChatGPT (subscription login required)")
    plan = account.get("planType")
    return ProbeResult(
        "auth", True, {"logged_in": True, "auth_method": "chatgpt", "plan": plan if isinstance(plan, str) else None}
    )


def probe_codex(profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
    result, exe = _binary("codex", profile, ctx)
    if step == "binary" or not result.ok:
        return result
    assert exe is not None
    env = probe_env(ctx, credential_env(profile, ctx)[1])
    if step == "auth":
        return credential_auth(profile, ctx) or _codex_auth(profile, exe, env, ctx)
    if step == "quota":
        return (
            ProbeResult("quota", True, skipped=True)
            if profile.auth == "api_key"
            else codex_quota(profile, exe, env, ctx)
        )
    # the probe runs in the cache root or a temp dir, never a git repo: codex refuses to start there without the flag
    argv = [exe, "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules"]
    argv += ["-s", "read-only"]
    if profile.model:
        argv += ["-m", profile.model]
    argv += ["-c", "model_reasoning_effort=low", ctx.hello_prompt]
    done, millis = _timed(ctx, argv, env)
    reply, failure, failure_text, kind = None, None, None, None
    for line in (done.stdout or "").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "turn.failed":
            failure = "codex reported turn.failed"
            error = event.get("error")
            failure_text = str(error.get("message", "")) if isinstance(error, dict) else str(error or "")
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
            reply = item.get("text") if isinstance(item.get("text"), str) else None
    if done.returncode not in (0, 124) and failure is None:
        failure = f"codex exited with code {done.returncode}"
        kind = "transient"  # nothing was said: the run did not get as far as an answer
    if failure_text:
        kind = text_class(failure_text)
    limit = normalise_limit("codex", profile.model, text=failure_text, now=now_of(ctx)) if failure_text else None
    if limit is not None:
        failure = "codex usage limit reached"
    return _hello_verdict(
        reply, millis, done.returncode == 124, failure, limit, kind, timeout_reason("codex", ctx.timeout_s, "hello")
    )


def _claude_events(stdout: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The last `result` event and the last `rate_limit_event` info of a stream-json run."""
    final: dict[str, Any] | None = None
    info: dict[str, Any] | None = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result":
            final = event
        elif event.get("type") == "rate_limit_event" and isinstance(event.get("rate_limit_info"), dict):
            info = event["rate_limit_info"]
    return final, info


HELLO_RETRY_WAIT_S = 20.0


def _overloaded(final: Mapping[str, Any] | None) -> bool:
    """A failed result with a transient server status (`TRANSIENT_STATUSES`) or the text `overloaded_error`."""
    if final is None or not final.get("is_error"):
        return False
    text = final.get("result")
    return final.get("api_error_status") in TRANSIENT_STATUSES or (isinstance(text, str) and "overloaded_error" in text)


def probe_claude(profile: Profile, step: ProbeStep, ctx: ProbeCtx, *, latest: Sequence[Window] = ()) -> ProbeResult:
    """`latest`: windows of the newest `rate_limit_event` the adapter saw (the quota step prefers them)."""
    result, exe = _binary("claude", profile, ctx)
    if step == "binary" or not result.ok:
        return result
    assert exe is not None
    env = probe_env(ctx, {"CLAUDE_CODE_MAX_RETRIES": "1", **credential_env(profile, ctx)[1]})
    if step == "quota":
        return claude_quota(profile, exe, env, ctx, latest=latest)
    if step == "auth":
        if (decided := credential_auth(profile, ctx)) is not None:
            return decided
        done = step_run(ctx, "claude", "auth", [exe, "auth", "status"], env)
        try:
            status = json.loads(done.stdout)
        except ValueError:
            return ProbeResult(step, False, reason="claude auth status gave an unrecognised answer")
        if not isinstance(status, dict) or not isinstance(status.get("loggedIn"), bool):
            return ProbeResult(step, False, reason="claude auth status gave an unrecognised answer")
        if not status["loggedIn"]:
            return login_failed(profile, "claude is not logged in")
        method, plan = status.get("authMethod"), status.get("subscriptionType")
        return ProbeResult(
            step, True,
            {"logged_in": True, "auth_method": method if isinstance(method, str) else None,
             "plan": plan if isinstance(plan, str) else None},
        )  # fmt: skip
    argv = [exe, "-p", "--safe-mode", "--no-session-persistence"]
    if profile.model:
        argv += ["--model", profile.model]
    argv += ["--tools", "", "--max-turns", "1", "--output-format", "stream-json", "--verbose", ctx.hello_prompt]
    done, millis = _timed(ctx, argv, env)
    final, info = _claude_events(done.stdout or "")
    if _overloaded(final):  # a server-side 529 or 503 is not a dead profile: one more try after a short wait
        (ctx.sleep or time.sleep)(HELLO_RETRY_WAIT_S)
        done, millis = _timed(ctx, argv, env)
        final, info = _claude_events(done.stdout or "")
    failure, limit, kind = None, None, None
    if final is None and done.returncode != 124:
        failure, kind = "claude printed no result", "transient"
    elif final is not None and final.get("is_error"):
        failure = f"claude reported an error (api_error_status {final.get('api_error_status')})"
        kind = status_class(final.get("api_error_status"))
        if info is not None and info.get("status") == "rejected":
            limit = normalise_limit("claude-code", profile.model, structured=info, now=now_of(ctx))
        elif final.get("api_error_status") == 429:
            limit = LimitSignal("claude-code", profile.model, "rate_limit", None, "claude.http_429", "")
    reply = final.get("result") if final and isinstance(final.get("result"), str) else None
    return _hello_verdict(
        reply, millis, done.returncode == 124, failure, limit, kind, timeout_reason("claude", ctx.timeout_s, "hello")
    )


def claude_windows_of(stdout: str) -> list[Window]:
    """Windows of the newest `rate_limit_event` in a claude stream (for `ClaudeCodeAdapter` to remember)."""
    _, info = _claude_events(stdout)
    return rate_limit_event_windows(info) if info else []


@dataclass
class LadderReport:
    """What one run of the ladder found: every step that ran, in order, and the first that failed."""

    steps: dict[str, ProbeResult] = field(default_factory=dict)

    @property
    def failed(self) -> ProbeResult | None:
        return next((r for r in self.steps.values() if not r.ok), None)

    @property
    def ok(self) -> bool:
        return self.failed is None

    def to_json(self) -> dict[str, Any]:
        return {"steps": [{"name": name, **_result_json(result)} for name, result in self.steps.items()]}

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "LadderReport":
        report = cls()
        for entry in raw.get("steps", []):
            report.steps[entry["name"]] = _result_from_json(entry)
        return report


def _limit_json(limit: LimitSignal) -> dict[str, Any]:
    return {
        "tool": limit.tool, "model": limit.model, "kind": limit.kind,
        "resets_at": limit.resets_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if limit.resets_at else None,
        "source": limit.source, "raw_excerpt": limit.raw_excerpt, "window_minutes": limit.window_minutes,
        "used_percent": limit.used_percent,
    }  # fmt: skip


def _result_json(result: ProbeResult) -> dict[str, Any]:
    return {
        "ok": result.ok, "skipped": result.skipped, "reason": result.reason, "detail": result.detail,
        "limit": _limit_json(result.limit) if result.limit else None, "failure_class": result.failure_class,
    }  # fmt: skip


def _result_from_json(entry: Mapping[str, Any]) -> ProbeResult:
    raw = entry.get("limit")
    limit = None
    if isinstance(raw, dict):
        when = (
            datetime.strptime(raw["resets_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            if raw.get("resets_at")
            else None
        )
        limit = LimitSignal(
            raw["tool"], raw.get("model"), raw["kind"], when, raw["source"], raw.get("raw_excerpt", ""),
            raw.get("window_minutes"), raw.get("used_percent"),
        )  # fmt: skip
    return ProbeResult(
        cast(ProbeStep, entry["name"]), bool(entry["ok"]), dict(entry.get("detail") or {}), entry.get("reason"),
        limit, bool(entry.get("skipped")), entry.get("failure_class"),
    )  # fmt: skip


class ProbeLadder:
    """Runs a profile's steps cheapest first, in `availability.default_ladder` order, and stops at the first failure
    (L4-AVL-001). `mcp` and `custom` are skipped (not built yet). Whether a failure starts a cool-down is not decided
    here: only a step that returned a `LimitSignal` can, and the selector records it."""

    NOT_BUILT = ("mcp", "custom")

    def __init__(self, ctx: ProbeCtx, steps: Sequence[str]) -> None:
        self._ctx = ctx
        self._steps = list(steps)

    def run(self, adapter: AgentAdapter, profile: Profile) -> LadderReport:
        report = LadderReport()
        for name in self._steps:
            if name in self.NOT_BUILT or name not in ("binary", "auth", "quota", "hello"):
                report.steps[name] = ProbeResult(cast(ProbeStep, name), True, skipped=True)
                continue
            step = cast(ProbeStep, name)
            try:
                result = adapter.probe(profile, step, self._ctx)
            except StepTimedOut as exc:
                result = ProbeResult(step, False, reason=exc.reason, failure_class="transient")
            except (AdapterError, OSError) as exc:
                result = ProbeResult(step, False, reason=f"{name} probe failed ({type(exc).__name__})")
            report.steps[name] = result
            if not result.ok:
                break
        return report
