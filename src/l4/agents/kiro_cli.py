"""Kiro CLI adapter (kiro-cli 2.28.0, logged in on the Mac and on the runner), experimental: SPEC 8.3 gives the argv

    kiro-cli chat --no-interactive --trust-tools=<allow-list> [--agent A] [--model M]
        --output-format stream-json --require-mcp-startup "<prompt>"

except an implementer step without `options.agent`, which runs `--agent l4-implement-<random> --trust-all-tools`
from a private `KIRO_HOME` holding only that harness agent (K3, see `AGENT_TOOLS`). Every argv names the model, `auto`
when the profile has none. A judge instead runs a tool-less harness agent (`l4-judge-<random>`, `judge_agent_config`)
from a private `KIRO_HOME` with no trust flag and its prompt on stdin:

    kiro-cli chat --no-interactive --v2 --agent A --model M --output-format stream-json

The stream-json events (`runStarted`, `metadata`, `sessionUpdate`, `runFinished`, `runError`) are recorded and parsed
for the session id, the final text and a `runError`; the stream never says which model served the run (a judge run
reads it from the session file, D15). The result is still a prompt contract (the file `$L4_RESULT_PATH` names) and the
run is announced once as `agent.experimental`.
Open: the harness agent for the judge and read-only modes (K3, K13), the `~/.kiro` credential mount that the private
`KIRO_HOME` makes unnecessary for an implementer step (K5), `--resume-id`, and exit 4 as a configuration failure that
falls back (K8).
"""

import dataclasses
import json
import re
import secrets
import shutil
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

from l4.agents.activity import kiro_signals
from l4.agents.base import (
    AdapterError,
    AgentCaps,
    LimitSignal,
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
from l4.agents.claude_code import STRUCTURED_DETAIL
from l4.agents.contract import attach_file_result, attach_judge_reply
from l4.agents.credentials import credential_loader
from l4.agents.proc import ProcRunner
from l4.availability.limits import excerpt, parse_reset
from l4.availability.probes import (
    _binary,
    _hello_verdict,
    _timed,
    credential_auth,
    credential_env,
    login_failed,
    probe_env,
    text_class,
)
from l4.availability.quota import kiro_quota
from l4.availability.vendor import built_in_with_reason, is_routed, normalise_model, routed_from_listing
from l4.config.schema import Profile
from l4.fsutil import read_regular_file
from l4.safepath import resolve_tool

MCP_STARTUP_EXIT = 3  # SPEC 8.3, [V doc]
MAX_ARG_BYTES = 100_000  # the prompt is one argv entry; Linux caps a single entry at 128 KiB
# Tool names: on the default agent `fs_read,fs_write,execute_bash` still alias read/write/shell [V, 2.28.0].
# `--trust-tools=` (empty) trusts every tool on 2.28.0 [V: a shell `date > d.txt` ran], so no list is ever empty.
# Under a custom `--agent` the list is ignored (only the agent's `allowedTools` grants trust).
# A judge has no trust list at all: it runs a tool-less harness agent (`judge_agent_config`) and no trust flag.
TRUST_TOOLS = {"implement": "fs_read,fs_write,execute_bash", "read_only": "fs_read"}
# K3: an implementer step without `options.agent` runs a harness agent with these native tools, no MCP server, no
# resources (so no steering) and `--trust-all-tools` (under a custom agent a `--trust-tools` list is ignored), read from
# a private `KIRO_HOME` in the step's private directory that holds nothing else: the user's `~/.kiro` (MCP servers,
# skills, steering, `settings/permissions.yaml`) never reaches the run. The login stays in the CLI data store, which
# `KIRO_HOME` does not move [V, 2.28.0 Mac]. Live: on the default agent 3 of 4 harness-spawned steps had every write
# and shell call denied although the trust list named them; this agent ran the same red prompt with 0 denials.
AGENT_TOOLS = ("read", "write", "shell", "glob", "grep")
AGENT_PREFIX = "l4-implement-"
KIRO_HOME_DIR = "kiro-home"
# D1: a judge runs this agent (no tool, so the request carries no tool specification) from a private `KIRO_HOME`.
JUDGE_PREFIX = "l4-judge-"
JUDGE_SETTINGS = {
    "chat.disableInheritingDefaultResources": True, "chat.agentEngine": "v2",
    "chat.enableAutoAgentUpgrade": False, "app.disableAutoupdates": True,
}  # fmt: skip
AUTO_MODEL = "auto"
SESSION_LIMIT = 1_048_576  # the session file of R11 is read up to 1 MiB (D15)
STDERR_LIMIT = 262_144
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
# R20 is not recorded yet: a standard-error line that mentions the model together with one of these says that Kiro could
# not set the requested model (D15).
_MODEL_WARNING = re.compile(r"warn|could not|cannot|can't|unable|unavailable|not available|failed|fall", re.I)
_CREDITS_WORDS = re.compile(r"credit", re.I)
# Kiro FREE-tier throttling: `runError` (stage "prompt" or "turn") with "Internal error (code -32603): ... The
# request was throttled by the service" [V, dummy-agentic job 6146]. It is a rate limit like a 429: the profile cools
# for the message's own retry hint, else `THROTTLE_COOLDOWN`, and the next implementer takes the step. It can follow a
# whole turn of work (that attempt had cost 1.45 credits), so the step is not retried here: the checkout is discarded
# and the task goes on from its last checkpoint on the next profile, with no attempt consumed (`max_task_attempts`).
_THROTTLE_WORDS = re.compile(r"throttl|too many requests|rate[- ]?limit|\b429\b", re.I)
THROTTLE_COOLDOWN = timedelta(minutes=2)
_EXHAUSTED_WORDS = re.compile(
    r"used (all|up)|exhaust|insufficient|run out|ran out|exceed|no (more |remaining )?credits", re.I
)


class KiroCliAdapter:
    name = "kiro-cli"
    model_unverified: ClassVar[bool] = True
    experimental: ClassVar[bool] = True

    def __init__(self, runner: ProcRunner | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self._proc = runner or ProcRunner()
        self._clock = clock or (lambda: datetime.now(UTC))

    def capabilities(self) -> AgentCaps:
        return AgentCaps("prompt_contract", False, False, False, False, False, False, True, served_model=True)

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        return probe_kiro(profile, step, ctx)

    def build_command(self, req: RunRequest, *, exe: str, harness_agent: str | None = None) -> list[str]:
        """The judge argv (D1) has no prompt (it goes on stdin, D2) and no trust flag; the other modes end with the
        prompt as one argument. Every branch names the model: the profile's, else `auto` (D13)."""
        profile = req.profile
        model = effective_model(profile)
        if req.permission_policy.mode == "judge":
            assert harness_agent is not None
            return [
                exe, "chat", "--no-interactive", "--v2", "--agent", harness_agent, "--model", model,
                "--output-format", "stream-json",
            ]  # fmt: skip
        if len(req.prompt.encode("utf-8")) > MAX_ARG_BYTES:
            raise AdapterError("the prompt is too large to pass as one argument to kiro-cli")
        if harness_agent is not None:
            argv = [exe, "chat", "--no-interactive", "--agent", harness_agent, "--trust-all-tools"]
        else:
            argv = [exe, "chat", "--no-interactive", f"--trust-tools={TRUST_TOOLS[req.permission_policy.mode]}"]
            if agent := profile.options.get("agent"):
                argv += ["--agent", str(agent)]
        argv += ["--model", model]
        return [*argv, "--output-format", "stream-json", "--require-mcp-startup", req.prompt]

    def run(self, req: RunRequest) -> RunResult:
        exe = resolve_tool("kiro-cli", req.env, forbid=(req.cwd,))
        if exe is None:
            raise AdapterError("kiro-cli was not found on the agent PATH")
        judge = req.permission_policy.mode == "judge"
        if judge and not req.prompt.strip():
            raise AdapterError("the judge prompt is empty; kiro-cli would answer with an input error")
        req.result_path.parent.mkdir(parents=True, exist_ok=True)
        req.result_path.unlink(missing_ok=True)  # a leftover from an earlier step must not pass for this one's result
        env = dict(req.env)
        agent = None
        home: Path | None = None
        if judge:
            agent = JUDGE_PREFIX + secrets.token_hex(6)  # a workspace `.kiro/agents/<name>.json` shadows a known name
            home = write_judge_home(req.result_path.parent / KIRO_HOME_DIR, agent, effective_model(req.profile))
            env["KIRO_HOME"] = str(home)
            env.pop("KIRO_LOG_LEVEL", None)  # a trace log holds the whole prompt (R8)
        elif req.permission_policy.mode == "implement" and not req.profile.options.get("agent"):
            agent = AGENT_PREFIX + secrets.token_hex(6)  # a workspace `.kiro/agents/<name>.json` shadows a known name
            env["KIRO_HOME"] = str(write_harness_agent(req.result_path.parent / KIRO_HOME_DIR, agent))
        argv = self.build_command(req, exe=exe, harness_agent=agent)
        workdir = judge_workdir(req) if judge else req.cwd  # HB-13, as codex
        with credential_loader(req) as load:
            cmd = wrap_command(req, load(argv), env, workdir)
            outcome = self._proc.run(
                cmd.argv, cmd.env, workdir, stdout_path=req.raw_events_path,
                stderr_path=req.raw_events_path.with_suffix(".stderr"), stdin=req.prompt if judge else None,
                timeout_s=req.timeout_s, interrupt=req.interrupt, stall_timeout_s=req.stall_timeout_s,
                watch=req.watch, reader=kiro_signals,
            )  # fmt: skip
        try:
            lines = req.raw_events_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        stderr_text = _read_stderr(req.raw_events_path.with_suffix(".stderr")) if judge else None
        return self.parse(
            lines, exit_code=outcome.returncode, timed_out=outcome.timed_out or outcome.stalled,
            interrupted=outcome.interrupted, result_text=None if judge else read_result_file(req.result_path),
            schema=req.result_schema, raw_events_path=req.raw_events_path, judge=judge, kiro_home=home,
            model=effective_model(req.profile), stderr_text=stderr_text,
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
        kiro_home: Path | None = None,
        model: str | None = None,
        stderr_text: str | None = None,
    ) -> RunResult:
        """The exit code and the result file decide; the stream (`lines`, kiro-cli 2.28.0 stream-json) adds the session
        id, the final text and a `runError`: its stage goes into the detail, its message does not (it is kept in the
        raw events file), and a message that says the credits are used up is a credits limit, not a failed attempt.
        A judge run (`judge`) has no result file: its reply is the stream's text (D3), and `kiro_home`, `model` (the
        profile's, `auto` or None for none) and `stderr_text` give the served model and the model warning (D15)."""
        facts = stream_facts(stream_events("\n".join(lines)))
        result = RunResult(status="error", raw_events_path=raw_events_path, exit_code=exit_code)
        result.session_id, result.final_text = facts.get("session_id"), facts.get("final_text")
        run_error = facts.get("run_error")
        result.last_message = facts.get("last_message")
        credits, peak = facts.get("credits"), facts.get("context_peak_percent")
        if credits is not None:  # the stream's own meter, in plan credits (not dollars)
            result.usage = Usage(credits=credits, credits_source="kiro.stream", context_peak_percent=peak)
        elif peak is not None:
            result.usage = Usage(context_peak_percent=peak)
        if run_error and _CREDITS_WORDS.search(run_error[1]) and _EXHAUSTED_WORDS.search(run_error[1]):
            result.limit = LimitSignal("kiro-cli", None, "credits", None, "kiro.run_error", "")  # wording [U]
        throttled = run_error is not None and result.limit is None and _THROTTLE_WORDS.search(run_error[1])
        if throttled:
            result.limit = throttle_signal(run_error[1], self._clock())
        if timed_out:
            result.status = "timeout"
        elif interrupted:
            result.status = "cancelled"
        elif result.limit is not None and result.limit.kind == "rate_limit":
            result.status = "rate_limited"
            result.detail = f"kiro-cli was throttled by the service (runError at {run_error[0] or 'unknown'})"
        elif result.limit is not None:
            result.status = "quota"
            result.detail = "kiro-cli reported that the credits are used up (runError)"
        elif exit_code == MCP_STARTUP_EXIT:
            result.detail = "kiro-cli could not start its MCP servers (exit 3, --require-mcp-startup)"
        elif exit_code != 0:
            result.detail = f"kiro-cli exited with code {exit_code}" + (
                f" (runError at {run_error[0] or 'unknown'})" if run_error else ""
            )
        elif judge:
            self._judge_reply(result, facts, schema, kiro_home, model, stderr_text)
        else:
            attach_file_result(result, result_text, schema, "kiro-cli")
        return result

    @staticmethod
    def _judge_reply(
        result: RunResult,
        facts: dict[str, Any],
        schema: dict[str, Any] | None,
        kiro_home: Path | None,
        model: str | None,
        stderr_text: str | None,
    ) -> None:
        """A judge run that exited 0 (D3, D15): never a verdict after a tool call, on another engine or on another
        selected model; else the reply text sliced into the verdict object."""
        pinned = None if not model or model.strip().lower() == AUTO_MODEL else model.strip()
        if facts.get("tool_name") is not None:
            result.detail = f"kiro-cli judge called a tool ({facts['tool_name']})"
            return
        engine = facts.get("engine")
        if engine is not None and engine != "v2":
            result.detail = f"kiro-cli ran engine {engine}; a judge runs v2"
            return
        served = _served_model(kiro_home, result.session_id)
        if served is not None:
            result.model_resolved = served
        if pinned and served is not None and normalise_model(served) != normalise_model(pinned):
            result.detail = f"model_mismatch: kiro-cli selected {served}, the profile names {pinned}"
            return
        if (
            pinned
            and stderr_text
            and any("model" in line.lower() and _MODEL_WARNING.search(line) for line in stderr_text.splitlines())
        ):
            result.detail = f"model_mismatch: kiro-cli could not set {pinned}"
            return
        if facts.get("status") != "success":
            result.detail = f"kiro-cli judge run did not finish (status {facts.get('status') or 'none'})"
            return
        text = facts.get("final_text")
        if facts.get("final_truncated") or text is None:
            text = facts.get("all_text")
        attach_judge_reply(result, text, schema)
        stop = facts.get("stop_reason")
        missing = result.structured is None and result.detail.startswith(STRUCTURED_DETAIL + " missing:")
        if missing and isinstance(stop, str) and stop and stop != "end_turn":
            result.detail = f"{STRUCTURED_DETAIL} missing: the reply stopped at {stop}"


def _read_stderr(path: Path) -> str:
    try:
        return read_regular_file(path, limit=STDERR_LIMIT).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _served_model(home: Path | None, session_id: str | None) -> str | None:
    """`session_state.rts_model_state.model_info.model_id` of the run's session file (R11), when it is a regular file of
    at most 1 MiB and names a concrete model (not empty, not `auto`); else None (D15)."""
    if home is None or not session_id or not _SESSION_ID.match(session_id):
        return None
    try:
        data = json.loads(read_regular_file(home / "sessions" / "cli" / f"{session_id}.json", limit=SESSION_LIMIT))
    except (OSError, ValueError):
        return None
    try:
        model_id = data["session_state"]["rts_model_state"]["model_info"]["model_id"]
    except (KeyError, TypeError):
        return None
    if not isinstance(model_id, str) or not model_id.strip() or model_id.strip().lower() == AUTO_MODEL:
        return None
    return model_id.strip()


def throttle_signal(message: str, now: datetime) -> LimitSignal:
    """A throttle is a rate limit: it ends at the message's own retry hint, else after `THROTTLE_COOLDOWN`."""
    resets = parse_reset(message, now)
    if resets is None or resets <= now:
        resets = now + THROTTLE_COOLDOWN
    return LimitSignal("kiro-cli", None, "rate_limit", resets, "kiro.run_error", excerpt(message))


def harness_agent_config(name: str) -> dict[str, Any]:
    """The agent file of an implementer step (K3): native tools only, no MCP server, no resources."""
    return {
        "name": name, "description": "L4 harness implementer step: native file and shell tools only", "prompt": None,
        "mcpServers": {}, "tools": list(AGENT_TOOLS), "toolAliases": {}, "allowedTools": [], "resources": [],
        "toolsSettings": {}, "includeMcpJson": False, "model": None,
    }  # fmt: skip


def write_harness_agent(home: Path, name: str) -> Path:
    """A fresh `KIRO_HOME` at `home` holding only `agents/<name>.json`; returns `home`."""
    if home.exists():
        shutil.rmtree(home)
    (home / "agents").mkdir(parents=True)
    (home / "agents" / f"{name}.json").write_text(json.dumps(harness_agent_config(name), indent=2), encoding="utf-8")
    return home


def effective_model(profile: Profile) -> str:
    """The model a run names: the profile's, else `auto`; `auto` in any letter case is `auto` (D13)."""
    model = (profile.model or "").strip()
    return AUTO_MODEL if not model or model.lower() == AUTO_MODEL else model


def judge_agent_config(name: str, model: str) -> dict[str, Any]:
    """The agent file of a judge (D1): no tool, no server, no resource, no hook, the given model."""
    return {
        "name": name, "description": "L4 harness judge: no tools", "prompt": None, "mcpServers": {}, "tools": [],
        "toolAliases": {}, "allowedTools": [], "resources": [], "hooks": {}, "toolsSettings": {},
        "includeMcpJson": False, "model": model,
    }  # fmt: skip


def write_judge_home(home: Path, name: str, model: str) -> Path:
    """A fresh `KIRO_HOME` at `home` holding only `agents/<name>.json` and `settings/cli.json`; returns `home`."""
    if home.exists():
        shutil.rmtree(home)
    (home / "agents").mkdir(parents=True)
    (home / "settings").mkdir()
    (home / "agents" / f"{name}.json").write_text(
        json.dumps(judge_agent_config(name, model), indent=2), encoding="utf-8"
    )
    (home / "settings" / "cli.json").write_text(json.dumps(JUDGE_SETTINGS, indent=2), encoding="utf-8")
    return home


def stream_events(text: str) -> list[dict[str, Any]]:
    """The `{"type", "data"}` events of a `--output-format stream-json` run (recorded on kiro-cli 2.28.0 [V]): lines
    that are not such an object are skipped."""
    events = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and isinstance(event.get("type"), str) and isinstance(event.get("data"), dict):
            events.append(event)
    return events


def stream_facts(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """`session_id`, `final_text` and `status` (`runFinished`), `run_error` (`runError`: stage and message) and
    `credits`: the sum of every `meteringUsage` value in credits (absent when the stream meters nothing),
    `last_message`: the `agent_message_chunk` text after the last `tool_call` or `tool_call_update` (absent when there
    is none; `finalText` holds all of the run's text) and `context_peak_percent`: the largest
    `metadata.contextUsagePercentage`."""
    facts: dict[str, Any] = {}
    chunks: list[str] = []
    every: list[str] = []
    for event in events:
        data = event["data"]
        if event["type"] == "runStarted" and isinstance(data.get("engine"), str):
            facts["engine"] = data["engine"]
        percent = data.get("contextUsagePercentage") if event["type"] == "metadata" else None
        if isinstance(percent, int | float) and not isinstance(percent, bool):
            facts["context_peak_percent"] = max(float(percent), facts.get("context_peak_percent", 0.0))
        update = data.get("update") if event["type"] == "sessionUpdate" else None
        if isinstance(update, dict):
            kind = update.get("sessionUpdate")
            content = update.get("content")
            if kind == "tool_call" and "tool_name" not in facts:
                facts["tool_name"] = _tool_name(update)
            if kind in ("tool_call", "tool_call_update"):
                chunks.clear()
            elif kind == "agent_message_chunk" and isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
                every.append(content["text"])
        for meter in data.get("meteringUsage") or []:
            value = meter.get("value") if isinstance(meter, dict) else None
            if isinstance(value, int | float) and not isinstance(value, bool) and meter.get("unit") == "credit":
                facts["credits"] = facts.get("credits", 0.0) + value
        if isinstance(data.get("sessionId"), str):
            facts["session_id"] = data["sessionId"]
        if event["type"] == "runFinished":
            facts["status"] = data.get("status")
            facts["final_text"] = data.get("finalText") if isinstance(data.get("finalText"), str) else None
            facts["final_truncated"] = data.get("finalTextTruncated") is True
            facts["stop_reason"] = data.get("stopReason") if isinstance(data.get("stopReason"), str) else None
        elif event["type"] == "runError":
            facts["run_error"] = (str(data.get("stage", "")), str(data.get("message", "")))
    if text := "".join(chunks):
        facts["last_message"] = text
    if text := "".join(every):
        facts["all_text"] = text
    return facts


def _tool_name(update: Mapping[str, Any]) -> str:
    """The tool of a `tool_call` update: `_meta.kiro.toolName`, else its `title`, else `unknown`."""
    meta = update.get("_meta")
    kiro = meta.get("kiro") if isinstance(meta, dict) else None
    for name in (kiro.get("toolName") if isinstance(kiro, dict) else None, update.get("title")):
        if isinstance(name, str) and name:
            return name
    return "unknown"


def probe_kiro(profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
    result, exe = _binary("kiro-cli", profile, ctx)
    if step == "binary" or not result.ok:
        return result
    assert exe is not None
    env = probe_env(ctx, credential_env(profile, ctx)[1])
    if step == "auth":
        checked = credential_auth(profile, ctx) or _kiro_auth(profile, exe, env, ctx)
        return _with_routed(checked, profile, exe, env, ctx)
    if step == "quota":
        return kiro_quota(profile, exe, env, ctx)
    argv = [exe, "chat", "--no-interactive", "--trust-tools=read"]  # no tool is needed to say the word; shell is denied
    if profile.model:
        argv += ["--model", profile.model]
    argv += ["--output-format", "stream-json", ctx.hello_prompt]
    done, millis = _timed(ctx, argv, env)
    facts = stream_facts(stream_events(done.stdout or ""))
    failure, kind = None, None
    limit = None
    if "run_error" in facts:
        stage, message = facts["run_error"]
        failure, kind = f"kiro-cli reported runError ({stage or 'unknown'})", text_class(message)
        if _THROTTLE_WORDS.search(message):
            limit = throttle_signal(message, ctx.now() if ctx.now else datetime.now(UTC))
    elif done.returncode not in (0, 124):
        failure, kind = f"kiro-cli exited with code {done.returncode}", "transient"
    return _hello_verdict(facts.get("final_text"), millis, done.returncode == 124, failure, limit, kind)


def _kiro_auth(profile: Profile, exe: str, env: dict[str, str], ctx: ProbeCtx) -> ProbeResult:
    """`kiro-cli whoami --format json`: logged in is exit 0 and a flat object with a non-empty `accountType` string
    (2.27.1 and 2.28.0 [V]); logged out is exit 1 with `{"account": null}` (2.27.1 [V]). The e-mail is never kept."""
    done = ctx.run([exe, "whoami", "--format", "json"], ctx.cwd, env, ctx.timeout_s)
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        return ProbeResult("auth", False, reason="kiro-cli whoami gave an unrecognised answer")
    if done.returncode != 0 or ("account" in answer and answer["account"] is None):
        return login_failed(profile, "kiro-cli installed, not authenticated")
    plan = answer.get("accountType")
    if not isinstance(plan, str) or not plan:
        return ProbeResult("auth", False, reason="kiro-cli whoami gave an unrecognised answer")
    return ProbeResult("auth", True, {"logged_in": True})


def _with_routed(result: ProbeResult, profile: Profile, exe: str, env: dict[str, str], ctx: ProbeCtx) -> ProbeResult:
    """The `auth` step of a profile on `auto`, once the login check passed: the models Kiro may route it to (D14).
    `chat --list-models --format json` lists them; the possible vendors are the makers of the Active ones, widened by
    the built-in set. A failed listing never fails the step: it records the built-in set and why. The record is derived
    data (vendors, normalised ids, a reason), never the raw answer."""
    if not result.ok or not is_routed(profile):
        return result
    why = "kiro-cli chat --list-models failed ({})"
    done = ctx.run([exe, "chat", "--list-models", "--format", "json"], ctx.cwd, env, ctx.timeout_s)
    found = None
    if done.returncode == 124:
        reason = why.format("timed out")
    elif done.returncode != 0:
        reason = why.format(f"exit {done.returncode}")
    else:
        try:
            found = routed_from_listing(json.loads(done.stdout))
        except ValueError:
            found = None
        reason = why.format("no Active model in the answer")
    routed = found or built_in_with_reason(reason)
    return dataclasses.replace(result, detail={**result.detail, "routed": routed.to_detail()})
