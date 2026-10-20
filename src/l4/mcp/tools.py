"""The tools of the server (L4-MCP-002, L4-MCP-003, L4-MCP-005).

Each tool is one `l4` command run as a subprocess in a repository the instance serves (design D2): the server writes
nothing itself, so every rule the CLI applies to an agent caller holds. A value that reaches the command is passed as
`--option=value` or after `--`, so a value can never be read as an option; the global `--repo` and `--config` options
are never passed (the repository is chosen by `repos.Repos`, nothing else)."""

import contextlib
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from l4.mcp.repos import Refused, Repos
from l4.redact import Redactor

OUTPUT_LIMIT = 64 * 1024  # bytes of output a result carries
READ_LIMIT = 1024 * 1024  # bytes the runner keeps of each stream
READ_SECONDS = 180.0
WRITE_SECONDS = 900.0
REVIEW_SECONDS = 3600.0
KILL_GRACE_SECONDS = 5.0  # between SIGTERM and SIGKILL of a stopped call's process group
AGENT_MARKER = "l4-mcp"
# -P: `python -m` would put the working directory (the served repository) first on sys.path, and a file of that
# repository named yaml.py or click.py would run. The flag is on this child only; PYTHONSAFEPATH would be inherited.
_L4 = [sys.executable, "-P", "-m", "l4"]


class UnknownTool(Exception):
    """`tools/call` named a tool the server does not offer."""


@dataclass(frozen=True)
class CallControl:
    """What a running call can use: `cancelled` (set when the client cancels or goes away) and `progress`."""

    cancelled: threading.Event
    progress: Callable[[str], None]


@dataclass
class Completed:
    returncode: int
    stdout: str
    stderr: str = ""
    timed_out: bool = False
    cancelled: bool = False
    truncated: bool = False  # the runner kept only the start of a stream


Runner = Callable[[list[str], Path, dict[str, str], float, CallControl], Completed]


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _kill(proc: "subprocess.Popen[bytes]") -> None:
    """Stop the call: SIGTERM to its process group; the group then has `KILL_GRACE_SECONDS` of wall-clock time to
    finish, counted from the signal and whether or not the direct child has exited (a descendant may clean up after
    its parent is gone); SIGKILL to what remains, so a descendant that ignores SIGTERM does not keep running."""
    pgid = proc.pid
    deadline = time.monotonic() + KILL_GRACE_SECONDS
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(max(0.0, deadline - time.monotonic()))  # reaps the leader; the group id outlives it
    while time.monotonic() < deadline and _group_alive(pgid):
        time.sleep(0.05)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)
    proc.wait()


def run_subprocess(argv: list[str], cwd: Path, env: dict[str, str], timeout: float, control: CallControl) -> Completed:
    """Run `argv` with no terminal on stdin; stop it on cancel or timeout (its whole process group)."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(
            argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True
        )
        waited = 0.0
        timed_out = cancelled = False
        while True:
            if control.cancelled.is_set():
                cancelled = True
                _kill(proc)
                break
            if waited >= timeout:
                timed_out = True
                _kill(proc)
                break
            try:
                proc.wait(0.1)
                break
            except subprocess.TimeoutExpired:
                waited += 0.1
        streams = []
        truncated = False
        for handle in (out, err):
            handle.seek(0)
            data = handle.read(READ_LIMIT + 1)
            truncated = truncated or len(data) > READ_LIMIT
            streams.append(data[:READ_LIMIT].decode("utf-8", "replace"))
        return Completed(proc.returncode, streams[0], streams[1], timed_out, cancelled, truncated)


# --- tool definitions ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Param:
    name: str
    description: str
    kind: str = "string"  # string | integer | number | boolean
    required: bool = False
    flag: str | None = None  # the option it becomes; None: a positional (after `--`)
    enum: tuple[str, ...] = ()

    def schema(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.kind, "description": self.description}
        if self.enum:
            out["enum"] = list(self.enum)
        return out


@dataclass(frozen=True)
class Tool:
    name: str
    words: tuple[str, ...]  # the l4 command
    description: str
    params: tuple[Param, ...] = ()
    json_flag: str | None = None  # "always", or the name of the boolean parameter that turns JSON on
    consts: tuple[str, ...] = ()  # fixed flags, after the options
    seconds: float = READ_SECONDS

    def schema(self, repo_required: bool) -> dict[str, Any]:
        properties: dict[str, Any] = {"repo": {"type": "string", "description": REPO_HELP}}
        required = ["repo"] if repo_required else []
        for p in self.params:
            properties[p.name] = p.schema()
            if p.required:
                required.append(p.name)
        out: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
        if required:
            out["required"] = required
        return out

    def command(self, arguments: Mapping[str, Any]) -> list[str]:
        argv = list(self.words)
        if self.json_flag == "always" or (self.json_flag and arguments.get(self.json_flag)):
            argv.append("--json")
        positional: list[str] = []
        for p in self.params:
            value = arguments.get(p.name)
            if value is None or value is False:
                continue
            if p.flag is None:
                positional.append(str(value))
            elif value is True:
                argv.append(p.flag)
            else:
                argv.append(f"{p.flag}={value}")
        argv.extend(self.consts)
        if positional:
            argv.extend(["--", *positional])
        return argv

    def check(self, arguments: Mapping[str, Any]) -> str | None:
        known = {p.name for p in self.params} | {"repo"}
        unknown = sorted(set(arguments) - known)
        if unknown:
            return f"unknown argument(s): {', '.join(unknown)}; {self.name} takes: {', '.join(sorted(known))}"
        for p in self.params:
            value = arguments.get(p.name)
            if value is None:
                if p.required:
                    return f"the argument {p.name} is required"
                continue
            if p.kind == "string":
                ok = isinstance(value, str) and (value != "" or not p.required) and "\0" not in value
            elif p.kind == "integer":
                ok = isinstance(value, int) and not isinstance(value, bool)
            elif p.kind == "number":
                ok = isinstance(value, int | float) and not isinstance(value, bool) and _finite(value)
            else:
                ok = isinstance(value, bool)
            if not ok:
                return (
                    f"the argument {p.name} must be a non-empty {p.kind}"
                    if p.kind == "string"
                    else (f"the argument {p.name} must be a {'finite ' if p.kind == 'number' else ''}{p.kind}")
                )
            if p.enum and value not in p.enum:
                return f"the argument {p.name} must be one of: {', '.join(p.enum)}"
        return None


def _finite(value: float) -> bool:
    """A number that is neither NaN nor infinite (an integer too large for a float counts as infinite)."""
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


REPO_HELP = (
    "The repository to run in: its folder name or its path. Required when the server serves several repositories; "
    "only a repository the server was started for (--repo) is accepted."
)
_PLAN = Param("plan", "The plan id (the file name in .l4/plans/ without .json).", required=True)
_UNIT = Param("unit", "The unit id, for example openspec:my-change.", flag="--unit", required=True)
_UNIT_OPT = Param("unit", "The unit id, for example openspec:my-change.", flag="--unit")
_NO_RUN = Param(
    "no_run", "Do not start the harness's CI run on the base branch after the write.", "boolean", flag="--no-run"
)
_ACTIVATE = (
    ' Activating is a person\'s decision and is not offered here: a person runs `l4 yolo activate <plan> --reason "…"`.'
)
_WRITE_NOTE = " CI may be running on this repository while you write: check `l4_status` first."

TOOLS: tuple[Tool, ...] = (
    Tool(
        "l4_status",
        ("status",),
        "Read only. Runs `l4 status --json`: every unit with its phase, cause (`reason`), next step (`next`), open "
        "questions, last verdict and last activity; with `unit`, that unit only. Start here to find out why a unit "
        "stopped.",
        (_UNIT_OPT,),
        json_flag="always",
    ),
    Tool(
        "l4_doctor",
        ("doctor",),
        "Read only. Runs `l4 doctor --json`: checks of the environment, config, specs, git, forge and state. With "
        "`adoption`, the repository's own rows and a dry run of the gates at HEAD. It never fixes anything.",
        (_UNIT_OPT, Param("adoption", "The adoption rows and a gate dry run.", "boolean", flag="--adoption")),
        json_flag="always",
    ),
    Tool(
        "l4_plan_status",
        ("yolo", "status"),
        "Read only. Runs `l4 yolo status [plan] --json`: a delivery plan (or all) with its units, review, acceptances, "
        "usage, the stop or wait, and the next step." + _ACTIVATE,
        (Param("plan", "The plan id; omit for every plan."),),
        json_flag="always",
    ),
    Tool(
        "l4_plan_check",
        ("yolo", "check"),
        "Read only. Runs `l4 yolo check <plan> [--worktree]`: admits the plan and prints the findings and the order of "
        "its units; writes nothing. With `worktree` the plan file and unit folders are read from the working tree, "
        "before they are pushed; without it, from the target branch on origin. Next: `l4_plan_review`.",
        (_PLAN, Param("worktree", "Read the working tree (before the push).", "boolean", flag="--worktree")),
    ),
    Tool(
        "l4_plan_findings",
        ("yolo", "findings"),
        "Read only. Runs `l4 yolo findings <plan> [subject] --json`: the findings of the latest review of a plan, each "
        "with how to resolve it. With `worktree`, the latest dry run of `l4_plan_review` (local cache).",
        (
            _PLAN,
            Param("subject", "One unit or batch of the plan; omit for all."),
            Param("all", "Also READY subjects, minor findings, assumptions and missing.", "boolean", flag="--all"),
            Param("worktree", "The latest working-tree dry run, not the ledger.", "boolean", flag="--worktree"),
        ),
        json_flag="always",
    ),
    Tool(
        "l4_plan_report",
        ("yolo", "report"),
        "Read only. Runs `l4 yolo report <plan>`: the report of a delivery plan (what ran, cost, outcome).",
        (_PLAN,),
    ),
    Tool(
        "l4_questions",
        ("questions", "list"),
        "Read only. Runs `l4 questions list --json`: the open questions of one unit, or of every unit with a branch, "
        "read from the unit branch on origin.",
        (_UNIT_OPT,),
        json_flag="always",
    ),
    Tool(
        "l4_question",
        ("questions", "show"),
        "Read only. Runs `l4 questions show <id> --unit U --json`: one question, what accepting it takes and the "
        "frozen paths it would unfreeze.",
        (_UNIT, Param("id", "The question id, for example Q-001.", required=True)),
        json_flag="always",
    ),
    Tool(
        "l4_unit_events",
        ("status",),
        "Read only. Runs `l4 status --unit U --events --json`: the events of a unit's ledger (oldest first), filtered "
        "by `type` (for example task.attempt_failed, phase.changed) and cut to the newest `last`. Use it to see why "
        "attempts failed.",
        (
            _UNIT,
            Param("type", "Only events of this type.", flag="--type"),
            Param("last", "Only the newest N events.", "integer", flag="--last"),
        ),
        json_flag="always",
        consts=("--events",),
    ),
    Tool(
        "l4_verification",
        ("status",),
        "Read only. Runs `l4 status --unit U --verification`: the unit's latest verification.md (the verifier's "
        "evidence: gate results, judge findings) from its branch on origin, else the working tree.",
        (_UNIT,),
        consts=("--verification",),
    ),
    Tool(
        "l4_plan_draft",
        ("yolo", "draft"),
        "WRITES the plan file .l4/plans/<plan>.json in the working tree only (after fetching the unit refs); it does "
        "not commit and does not push to origin. Runs `l4 yolo draft`. Next: edit, commit, `l4_plan_check` with "
        "`worktree`." + _WRITE_NOTE,
        (
            _PLAN,
            Param("target", "The plan's target branch (default: forge.base_branch).", flag="--target"),
            Param("merge", "The merge mode (default human).", flag="--merge", enum=("human", "auto")),
            Param(
                "update",
                "Add the specs no plan lists to the existing file; change nothing else.",
                "boolean",
                flag="--update",
            ),
        ),
    ),
    Tool(
        "l4_plan_review",
        ("yolo", "review"),
        "Asks a judge to review a plan. COSTS judge tokens and takes minutes. Runs `l4 yolo review <plan>`: without "
        "`worktree` it starts the harness's CI run on origin, which records the review in the plan's ledger on origin "
        "(it pushes nothing of yours; CI may already be running); with `worktree` it reviews the working tree here, "
        "before the push, as a dry run that records nothing on origin and prints the findings." + _ACTIVATE,
        (
            _PLAN,
            Param("worktree", "Review the working tree (dry run, before the push).", "boolean", flag="--worktree"),
            _NO_RUN,
        ),
        json_flag="worktree",
        seconds=REVIEW_SECONDS,
    ),
    Tool(
        "l4_plan_go",
        ("yolo", "go"),
        "Walks a delivery plan toward activation as far as an agent may. COSTS judge tokens when the plan is not "
        "reviewed yet. Runs `l4 yolo go <plan> --reason R --json --no-push`: preflight, check, then the review (it "
        "asks the harness's CI for one and waits for it in the plan's ledger on origin, up to `wait`, default 30m: "
        'pass a shorter `wait` such as "9m"; exit 24 means run it again), then the findings. It never pushes: '
        "when only the plan file and its unit folders are ahead of origin, the stop (exit 21) gives you `git push "
        "origin <base>` as your own command; when any other file is ahead (a config change, for one), the push is a "
        "person's (exit 27, `next_by` person). It never accepts findings, never "
        "force-accepts and never activates: at each of those it stops and the result's `next_command` is a person's "
        "command (exit 27, or exit 28 when another plan holds the target): never run a `next_command` whose "
        "`next_by` is `person`, give it to the person. The JSON result holds `exit`, the seven steps "
        "with their status, `next_command` and `next_by`." + _ACTIVATE,
        (
            _PLAN,
            Param(
                "reason",
                "Why the plan goes ahead: the reason a person's run would record.",
                required=True,
                flag="--reason",
            ),
            Param("wait", "How long to wait for the CI review: 0 or a duration such as 30s, 9m, 1h.", flag="--wait"),
        ),
        json_flag="always",
        consts=("--no-push",),
        seconds=REVIEW_SECONDS,
    ),
    Tool(
        "l4_question_answer",
        ("questions", "answer"),
        "WRITES an answer into questions.md of the unit and pushes one commit to the unit's branch on origin (no "
        "force, [skip ci]); then starts a CI run unless `no_run`. Runs `l4 questions answer <id> --unit U --text T`. "
        "As for any agent, the CLI refuses a question that clarifier.answer_by_agents does not let an agent answer; "
        "that refusal comes back as an error. With `no_push` nothing is written: it prints the diff." + _WRITE_NOTE,
        (
            _UNIT,
            Param("id", "The question id, for example Q-001.", required=True),
            Param("text", "The answer.", flag="--text", required=True),
            Param("replace", "Replace the answer of an answered verdict question.", "boolean", flag="--replace"),
            Param("no_push", "Print the diff and the commit message; write nothing.", "boolean", flag="--no-push"),
            _NO_RUN,
        ),
        seconds=WRITE_SECONDS,
    ),
    Tool(
        "l4_retry",
        ("retry",),
        "WRITES to the unit's branch and PUSHES it to origin: continues a halted or escalated unit from where it "
        "stopped, then starts a CI run unless `no_run`. Runs `l4 retry --unit U --reason R`. Read `l4_status` and "
        "`l4_unit_events` first: the reason is read by the implementer." + _WRITE_NOTE,
        (
            _UNIT,
            Param("reason", "Why the unit can continue (at most 300 characters).", flag="--reason", required=True),
            Param("rounds", "At a fix-round limit: how many rounds to add (default 1).", "integer", flag="--rounds"),
            _NO_RUN,
        ),
        seconds=WRITE_SECONDS,
    ),
    Tool(
        "l4_plan_resume",
        ("yolo", "resume"),
        "WRITES to origin: records the resume in the plan's ledger on origin and starts a CI run unless `no_run`. "
        "Runs `l4 yolo resume <plan> --reason R`: resumes a stopped or waiting plan once its cause is gone; the "
        "extend options raise a limit that stopped it." + _WRITE_NOTE,
        (
            _PLAN,
            Param("reason", "Why the plan resumes.", flag="--reason", required=True),
            Param("extend_cost", "Raise the cost limit by this many dollars.", "number", flag="--extend-cost"),
            Param("extend_runs", "Raise the run limit by N.", "integer", flag="--extend-runs"),
            Param(
                "extend_attempts", "Raise the attempts limit of every unit by N.", "integer", flag="--extend-attempts"
            ),
            Param("extend_deadline", "A later deadline, ISO 8601.", flag="--extend-deadline"),
            _NO_RUN,
        ),
        seconds=WRITE_SECONDS,
    ),
)
BY_NAME = {tool.name: tool for tool in TOOLS}


@dataclass
class Toolbox:
    repos: Repos
    environ: Mapping[str, str]
    redactor: Redactor
    runner: Runner = field(default=run_subprocess)

    def served(self) -> str:
        """The repositories this instance serves, named by folder and path (what tells instances apart)."""
        try:
            roots = self.repos.served()
        except Refused:
            return ""
        return "; ".join(f"{r.name} = {r}" for r in roots)

    def specs(self) -> list[dict[str, Any]]:
        required = self.repos.needs_repo_argument
        served = self.served()
        note = f" Serves: {served}." if served else ""
        return [{"name": t.name, "description": t.description + note, "inputSchema": t.schema(required)} for t in TOOLS]

    def _error(self, text: str, **extra: Any) -> dict[str, Any]:
        text = self.redactor.redact_text(text)
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": {"error": text, **extra},
            "isError": True,
        }

    def call(self, name: str, arguments: dict[str, Any], control: CallControl) -> dict[str, Any]:
        tool = BY_NAME.get(name)
        if tool is None:
            raise UnknownTool(name)
        try:
            root = self.repos.select(arguments.get("repo"))
        except Refused as exc:
            return self._error(f"{name}: {exc}")
        problem = tool.check(arguments)
        if problem:
            return self._error(f"repo: {root}\n{name}: {problem}", repo=str(root))
        words = tool.command(arguments)
        env = {**self.environ, "AI_AGENT": AGENT_MARKER}
        done = self.runner([*_L4, *words], root, env, tool.seconds, control)
        return self._result(root, words, done)

    def _result(self, root: Path, words: list[str], done: Completed) -> dict[str, Any]:
        body = done.stdout
        if done.stderr.strip():
            body = f"{body}{'' if body.endswith(chr(10)) or not body else chr(10)}[stderr]\n{done.stderr}"
        data = self.redactor.redact_text(body).encode("utf-8")
        truncated = done.truncated or len(data) > OUTPUT_LIMIT
        shown = data[:OUTPUT_LIMIT].decode("utf-8", "ignore")
        if len(data) > OUTPUT_LIMIT:
            shown += f"\n[output cut at {OUTPUT_LIMIT} bytes; {len(data)} bytes in all]"
        elif done.truncated:
            shown += f"\n[output cut at {READ_LIMIT} bytes]"
        notes = []
        if done.timed_out:
            notes.append("the command timed out and was stopped")
        if done.cancelled:
            notes.append("the command was cancelled")
        command = "l4 " + " ".join(words)
        head = f"repo: {root}\n$ {self.redactor.redact_text(command)}\nexit code: {done.returncode}"
        text = "\n".join([head, *notes, "", shown]).rstrip("\n")
        structured: dict[str, Any] = {
            "repo": str(root),
            "command": self.redactor.redact_text(command),
            "exit_code": done.returncode,
            "truncated": truncated,
        }
        if notes:
            structured["notes"] = notes
        if not truncated:
            try:
                parsed = json.loads(self.redactor.redact_text(done.stdout))
            except ValueError:
                parsed = None
            if isinstance(parsed, dict | list):
                structured["json"] = parsed
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": structured,
            "isError": done.returncode != 0 or done.timed_out or done.cancelled,
        }
