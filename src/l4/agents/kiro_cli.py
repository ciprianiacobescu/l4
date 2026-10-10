"""Kiro CLI adapter (kiro-cli 2.28.0, logged in on the Mac and on the runner), experimental: SPEC 8.3 gives the argv

    kiro-cli chat --no-interactive --trust-tools=<allow-list> [--agent A] [--model M]
        --output-format stream-json --require-mcp-startup "<prompt>"

except an implementer step without `options.agent`, which runs `--agent l4-implement-<random> --trust-all-tools`
from a private `KIRO_HOME` holding only that harness agent (K3, see `AGENT_TOOLS`).

The stream-json events (`runStarted`, `metadata`, `sessionUpdate`, `runFinished`, `runError`) are recorded and parsed
for the session id, the final text and a `runError`; the stream never says which model served the run. The result is
still a prompt contract (the file `$L4_RESULT_PATH` names) and the run is announced once as `agent.experimental`.
Open: the harness agent for the judge and read-only modes (K3, K13), the `~/.kiro` credential mount that the private
`KIRO_HOME` makes unnecessary for an implementer step (K5), `--resume-id`, and exit 4 as a configuration failure that
falls back (K8).
"""

import json
import re
import secrets
import shutil
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

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
from l4.agents.contract import attach_file_result
from l4.agents.proc import ProcRunner
from l4.availability.limits import excerpt, parse_reset
from l4.availability.probes import _binary, _hello_verdict, _timed, probe_env, text_class
from l4.availability.quota import kiro_quota
from l4.config.schema import Profile
from l4.safepath import resolve_tool

MCP_STARTUP_EXIT = 3  # SPEC 8.3, [V doc]
MAX_ARG_BYTES = 100_000  # the prompt is one argv entry; Linux caps a single entry at 128 KiB
# Tool names: on the default agent `fs_read,fs_write,execute_bash` still alias read/write/shell [V, 2.28.0].
# The judge list MUST NOT be empty: `--trust-tools=` trusts every tool [V, 2.28.0: a shell `date > d.txt` ran]; `read`
# alone denies shell [V]. Under a custom `--agent` the list is ignored (only the agent's `allowedTools` grants trust).
TRUST_TOOLS = {"implement": "fs_read,fs_write,execute_bash", "read_only": "fs_read", "judge": "read"}
# K3: an implementer step without `options.agent` runs a harness agent with these native tools, no MCP server, no
# resources (so no steering) and `--trust-all-tools` (under a custom agent a `--trust-tools` list is ignored), read from
# a private `KIRO_HOME` in the step's private directory that holds nothing else: the user's `~/.kiro` (MCP servers,
# skills, steering, `settings/permissions.yaml`) never reaches the run. The login stays in the CLI data store, which
# `KIRO_HOME` does not move [V, 2.28.0 Mac]. Live: on the default agent 3 of 4 harness-spawned steps had every write
# and shell call denied although the trust list named them; this agent ran the same red prompt with 0 denials.
AGENT_TOOLS = ("read", "write", "shell", "glob", "grep")
AGENT_PREFIX = "l4-implement-"
KIRO_HOME_DIR = "kiro-home"
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
        return AgentCaps("prompt_contract", False, False, False, False, False, False, True)

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        return probe_kiro(profile, step, ctx)

    def build_command(self, req: RunRequest, *, exe: str, harness_agent: str | None = None) -> list[str]:
        if len(req.prompt.encode("utf-8")) > MAX_ARG_BYTES:
            raise AdapterError("the prompt is too large to pass as one argument to kiro-cli")
        profile = req.profile
        if harness_agent is not None:
            argv = [exe, "chat", "--no-interactive", "--agent", harness_agent, "--trust-all-tools"]
        else:
            argv = [exe, "chat", "--no-interactive", f"--trust-tools={TRUST_TOOLS[req.permission_policy.mode]}"]
            if agent := profile.options.get("agent"):
                argv += ["--agent", str(agent)]
        if profile.model:
            argv += ["--model", profile.model]
        return [*argv, "--output-format", "stream-json", "--require-mcp-startup", req.prompt]

    def run(self, req: RunRequest) -> RunResult:
        exe = resolve_tool("kiro-cli", req.env, forbid=(req.cwd,))
        if exe is None:
            raise AdapterError("kiro-cli was not found on the agent PATH")
        req.result_path.parent.mkdir(parents=True, exist_ok=True)
        req.result_path.unlink(missing_ok=True)  # a leftover from an earlier step must not pass for this one's result
        env = dict(req.env)
        agent = None
        if req.permission_policy.mode == "implement" and not req.profile.options.get("agent"):
            agent = AGENT_PREFIX + secrets.token_hex(6)  # a workspace `.kiro/agents/<name>.json` shadows a known name
            env["KIRO_HOME"] = str(write_harness_agent(req.result_path.parent / KIRO_HOME_DIR, agent))
        argv = self.build_command(req, exe=exe, harness_agent=agent)
        workdir = judge_workdir(req) if req.permission_policy.mode == "judge" else req.cwd  # HB-13, as codex
        cmd = wrap_command(req, argv, env, workdir)
        outcome = self._proc.run(
            cmd.argv, cmd.env, workdir, stdout_path=req.raw_events_path,
            stderr_path=req.raw_events_path.with_suffix(".stderr"), stdin=None, timeout_s=req.timeout_s,
            interrupt=req.interrupt, stall_timeout_s=req.stall_timeout_s,
        )  # fmt: skip
        try:
            lines = req.raw_events_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        return self.parse(
            lines, exit_code=outcome.returncode, timed_out=outcome.timed_out or outcome.stalled,
            interrupted=outcome.interrupted, result_text=read_result_file(req.result_path), schema=req.result_schema,
            raw_events_path=req.raw_events_path,
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
    ) -> RunResult:
        """The exit code and the result file decide; the stream (`lines`, kiro-cli 2.28.0 stream-json) adds the session
        id, the final text and a `runError`: its stage goes into the detail, its message does not (it is kept in the
        raw events file), and a message that says the credits are used up is a credits limit, not a failed attempt."""
        facts = stream_facts(stream_events("\n".join(lines)))
        result = RunResult(status="error", raw_events_path=raw_events_path, exit_code=exit_code)
        result.session_id, result.final_text = facts.get("session_id"), facts.get("final_text")
        run_error = facts.get("run_error")
        if (credits := facts.get("credits")) is not None:  # the stream's own meter, in plan credits (not dollars)
            result.usage = Usage(credits=credits, credits_source="kiro.stream")
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
        else:
            attach_file_result(result, result_text, schema, "kiro-cli")
        return result


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
    `credits`: the sum of every `meteringUsage` value in credits (absent when the stream meters nothing)."""
    facts: dict[str, Any] = {}
    for event in events:
        data = event["data"]
        for meter in data.get("meteringUsage") or []:
            value = meter.get("value") if isinstance(meter, dict) else None
            if isinstance(value, int | float) and not isinstance(value, bool) and meter.get("unit") == "credit":
                facts["credits"] = facts.get("credits", 0.0) + value
        if isinstance(data.get("sessionId"), str):
            facts["session_id"] = data["sessionId"]
        if event["type"] == "runFinished":
            facts["status"] = data.get("status")
            facts["final_text"] = data.get("finalText") if isinstance(data.get("finalText"), str) else None
        elif event["type"] == "runError":
            facts["run_error"] = (str(data.get("stage", "")), str(data.get("message", "")))
    return facts


def probe_kiro(profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
    result, exe = _binary("kiro-cli", profile, ctx)
    if step == "binary" or not result.ok:
        return result
    assert exe is not None
    env = probe_env(ctx)
    if step == "auth":
        return _kiro_auth(exe, env, ctx)
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


def _kiro_auth(exe: str, env: dict[str, str], ctx: ProbeCtx) -> ProbeResult:
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
        return ProbeResult("auth", False, reason="kiro-cli installed, not authenticated")
    plan = answer.get("accountType")
    if not isinstance(plan, str) or not plan:
        return ProbeResult("auth", False, reason="kiro-cli whoami gave an unrecognised answer")
    return ProbeResult("auth", True, {"logged_in": True})
