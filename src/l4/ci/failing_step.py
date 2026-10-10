"""The failing step of a red project CI job, derived and vetted, pure (M1.10 decisions 2 and 4; L4-ARC-002 (d),
L4-SEC-004).

The recorded step is data from a log that agent-written code printed into, so it only *selects* a command: the command
that is re-run is the matching entry of the project's CI file at H, which is member-written. Anything that cannot be
run safely without a shell is skipped, with a reason; a skipped step leaves the judge alone to check the fix.
"""

import re
import shlex
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal

from l4.ci.gitlab_jobs import JobScript, ScriptRefusal
from l4.state.ledger import LedgerEvent
from l4.verifier.types import finding_id

COLLAPSED = "# collapsed multi-line command"
_ECHO = "$ "
_DENY_WORDS = frozenset({
    "docker", "docker-compose", "podman", "kubectl", "helm", "ssh", "scp", "rsync", "curl", "wget", "sudo", "apt",
    "apt-get", "apk", "yum", "dnf", "brew", "twine", "terraform", "aws", "gcloud", "az",
})  # fmt: skip
_DENY_PAIRS = (
    ("git", "push"), ("git", "fetch"), ("git", "clone"), ("git", "pull"), ("pip", "install"), ("uv", "sync"),
    ("uv", "pip"), ("uv", "publish"), ("npm", "install"), ("npm", "ci"), ("npm", "publish"), ("poetry", "install"),
    ("poetry", "publish"), ("cargo", "publish"),
)  # fmt: skip
_DENY_PARTS = ("deploy", "release", "publish", "upload")
# a shell given a command string: its one quoted argument would hide every operator and denied word from the checks
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "mksh", "ash", "fish", "csh", "tcsh", "pwsh", "powershell"})
_UNQUOTED_META = frozenset("$`|&;<>()*?[{~\\")
_DOUBLE_META = frozenset("$`\\")
_TIMING = re.compile(r"\bin \d+(?:\.\d+)?\s*s\b", re.IGNORECASE)
_GENERIC = re.compile(
    r"^(?:found \d+ errors?\.?|\d+ (?:failed|passed|errors?)\b.*|all checks passed!?|"
    r"(?:error: )?job failed: exit code \d+|executing .*step_script.*)$",
    re.IGNORECASE,
)
MIN_SHARED_CHARS = 10
_REVIEW_EDGES = frozenset({"repository_ci_failed", "commit_after_handoff", "spec_edit_after_handoff"})


@dataclass(frozen=True)
class CiStep:
    """What step 0 decided for one failing job: a `command` to re-run, or the `reason` it is not."""

    job: str
    command: str | None
    reason: str | None = None


def echoed_step(tail: str) -> str | None:
    """The last `$ ` line of a log tail, without the `$ ` (the fallback for a ledger that recorded no step)."""
    found = None
    for line in tail.splitlines():
        if line.startswith(_ECHO) and line[len(_ECHO) :].strip():
            found = line[len(_ECHO) :].strip()
    return found


def _scan(command: str) -> str | None:
    """A reason when `command` holds shell syntax outside the quotes that no-shell execution would read differently."""
    quote = ""
    start = True  # at the start of a word
    for char in command:
        if quote == "'":
            if char == "'":
                quote = ""
            continue
        if quote == '"':
            if char == '"':
                quote = ""
            elif char in _DOUBLE_META:
                return f"{char!r} inside double quotes"
            continue
        if char in "'\"":
            quote, start = char, False
            continue
        if char in _UNQUOTED_META:
            return f"shell syntax {char!r}"
        if char == "#" and start:
            return "a shell comment"
        start = char.isspace()
    return "an unterminated quote" if quote else None


def _inline_shell(tokens: Sequence[str], names: Sequence[str]) -> str | None:
    """The shell of `sh -c '...'` (any position: `env sh -c`, `busybox sh -c`; `-lc`, `-o pipefail -c`, `--command`,
    `-Command`); None when no shell is given a command string (`bash scripts/check.sh` runs a file, like python)."""
    for index, name in enumerate(names):
        if name not in _SHELLS:
            continue
        for option in tokens[index + 1 :]:
            if option.lower() in ("--command", "-command") or (
                option.startswith("-") and not option.startswith("--") and "c" in option[1:]
            ):
                return name
    return None


def unrunnable(command: str) -> str | None:
    """Why `command` cannot be re-run in the gate sandbox without a shell and without side effects; None when it can."""
    if not command.strip():
        return "an empty command"
    if "\n" in command or "\r" in command:
        return "a multi-line command"
    if (found := _scan(command)) is not None:
        return f"not run without a shell: {found}"
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return f"not run without a shell: {exc}"
    if not tokens:
        return "an empty command"
    if "=" in tokens[0] and not tokens[0].startswith(("-", "=")) and "/" not in tokens[0].split("=")[0]:
        return "an environment assignment before the command"
    names = [t.rsplit("/", 1)[-1].lower() for t in tokens]
    if (shell := _inline_shell(tokens, names)) is not None:
        return f"not run without a shell: an explicit `{shell} -c`"
    for word in names:
        if word in _DENY_WORDS:
            return f"{word} is not run in the gate sandbox"
    for index, word in enumerate(names):
        nxt = [n for n in names[index + 1 :] if not n.startswith("-")][:2]  # `git -C repo fetch`
        for first, second in _DENY_PAIRS:
            if word == first and second in nxt:
                return f"{first} {second} is not run in the gate sandbox"
    for token in names:
        for part in _DENY_PARTS:
            if part in token:
                return f"a command that mentions {part} is not run in the gate sandbox"
    return None


def named_step(recorded: object, tail: str) -> str | None:
    """The step a job's failure names: the one the sweep recorded, else the tail's last `$` line."""
    text = recorded.strip() if isinstance(recorded, str) else ""
    return text or echoed_step(tail)


def derive_step(job: str, step: str | None, tail: str, script: JobScript | ScriptRefusal) -> CiStep:
    """Decision 2: the step the log names, found as one whole entry of the job's `before_script` + `script` at H, and
    vetted by `unrunnable`. The tail's last `$ ` line stands in when no step was recorded."""
    named = named_step(step, tail)
    if not named:
        return CiStep(job, None, "no failing step in the log (no recorded step, no `$` line in the tail)")
    if isinstance(script, ScriptRefusal):
        return CiStep(job, None, script.reason)
    if named.endswith(COLLAPSED):
        return CiStep(job, None, "the failing step is a multi-line command")
    entries = [e.strip() for e in (*script.before, *script.script)]
    if named not in entries:
        return CiStep(job, None, "the log and the CI file disagree: the logged step is no entry of the job's script")
    if (why := unrunnable(named)) is not None:
        return CiStep(job, None, why)
    return CiStep(job, named, None)


def _normalised(log: str) -> set[str]:
    found: set[str] = set()
    for raw in log.splitlines():
        line = " ".join(raw.split())
        if len(line) < MIN_SHARED_CHARS or not any(c.isalnum() for c in line):
            continue
        if line.startswith(_ECHO) or _TIMING.search(line) or _GENERIC.match(line):
            continue
        found.add(line)
    return found


def shared_error_line(ci_tail: str, step: str, local_log: str) -> bool:
    """Decision 4: the local run reproduces the CI failure when it printed at least one line of the CI log that came
    after the step's own `$` line (the whole tail when that line fell out of it). Lines are compared with whitespace
    collapsed; short lines, timing lines and generic summaries do not count."""
    lines = ci_tail.splitlines()
    echo = _ECHO + step.strip()
    after = lines
    for index in range(len(lines) - 1, -1, -1):
        if " ".join(lines[index].split()) == " ".join(echo.split()):
            after = lines[index + 1 :]
            break
    return bool(_normalised("\n".join(after)) & _normalised(local_log))


# --- the chore: reproduce, then require (decisions 4 and 5) ----------------------------------------------------------

STEP_GATE_PREFIX = "repository-ci:"
_RUNNABLE_STATUSES = frozenset({"derived", "reproduced"})


@dataclass(frozen=True)
class ChoreCiStep:
    """A job's step as the ledger last said: what a chore must reproduce, or already has."""

    job: str
    head: str
    step: str | None
    command: str
    status: str  # derived | reproduced
    tail: str  # the job's log tail at the edge: what the local run is compared with


def _ordered(events: Sequence[LedgerEvent]) -> list[LedgerEvent]:
    return sorted(events, key=lambda e: (e.ts, e.run_id, e.seq))


def last_ci_steps(events: Sequence[LedgerEvent]) -> dict[tuple[str, str], LedgerEvent]:
    """The last `ci.step` per `(head, job)`."""
    found: dict[tuple[str, str], LedgerEvent] = {}
    for event in _ordered(events):
        if event.type == "ci.step":
            found[(str(event.data.get("head")), str(event.data.get("job")))] = event
    return found


def _edge_tails(events: Sequence[LedgerEvent]) -> dict[tuple[str, str], str]:
    tails: dict[tuple[str, str], str] = {}
    for event in _ordered(events):
        if event.type == "phase.changed" and event.data.get("trigger") == "repository_ci_failed":
            for job in event.data.get("jobs") or []:
                if isinstance(job, dict) and job.get("name"):
                    tails[(str(event.data.get("head")), str(job["name"]))] = str(job.get("tail") or "")
    return tails


def chore_ci_steps(events: Sequence[LedgerEvent], findings: Collection[str]) -> list[ChoreCiStep]:
    """The `derived` or `reproduced` steps of the jobs whose `repository CI failed: <job>` finding the chore carries
    (the harness-written `.l4/fix.json`, never the task's text). The newest head of a job wins."""
    tails = _edge_tails(events)
    newest: dict[str, LedgerEvent] = {}
    for (_, job), event in last_ci_steps(events).items():
        newest[job] = event  # the dict keeps ledger order: the last head of a job wins
    steps: list[ChoreCiStep] = []
    for job, event in newest.items():
        command = event.data.get("command")
        if finding_id(f"repository CI failed: {job}") not in findings:
            continue
        if event.data.get("status") not in _RUNNABLE_STATUSES or not isinstance(command, str) or not command:
            continue
        head = str(event.data.get("head"))
        step = event.data.get("step")
        steps.append(
            ChoreCiStep(job, head, step if isinstance(step, str) else None, command, str(event.data["status"]),
                        tails.get((head, job), ""))
        )  # fmt: skip
    return steps


def active_ci_steps(events: Sequence[LedgerEvent]) -> list[ChoreCiStep]:
    """Decision 5: the `reproduced` steps of the window that opened at the last review edge when its trigger is
    `repository_ci_failed`. It ends at the first PASS verdict after that edge, and at a later edge of any other
    trigger (`pr.ready` is not the marker: the branch never holds it)."""
    ordered = _ordered(events)
    start: int | None = None
    for index, event in enumerate(ordered):
        if event.type == "phase.changed" and event.data.get("trigger") in _REVIEW_EDGES:
            start = index if event.data.get("trigger") == "repository_ci_failed" else None
        elif start is not None and event.type == "verify.verdict" and event.data.get("verdict") == "PASS":
            start = None
    if start is None:
        return []
    window = ordered[start:]
    tails = _edge_tails(window)
    reproduced: dict[tuple[str, str], LedgerEvent] = {}
    for key, event in last_ci_steps(window).items():
        reproduced[key] = event
    found: dict[str, ChoreCiStep] = {}
    for (head, job), event in reproduced.items():
        command = event.data.get("command")
        if event.data.get("status") == "reproduced" and isinstance(command, str) and command:
            step = event.data.get("step")
            found[job] = ChoreCiStep(job, head, step if isinstance(step, str) else None, command, "reproduced",
                                     tails.get((head, job), ""))  # fmt: skip
    return list(found.values())


def reproduction(
    *, exit_code: int | None, timed_out: bool, reason: str, ci_tail: str, step: str, local_log: str
) -> tuple[Literal["reproduced", "skipped"], str | None]:
    """Decision 4: did the step fail in the gate sandbox the way it failed in CI? A skip names why not."""
    if timed_out:
        return "skipped", f"not runnable in the gate sandbox: {reason}"
    if exit_code is None:
        return "skipped", f"not runnable in the gate sandbox: {reason}"
    if exit_code in (126, 127):
        return "skipped", f"exit {exit_code}: not runnable in the gate sandbox"
    if exit_code == 0:
        return "skipped", "passes at the fix's base: does not reproduce"
    if not shared_error_line(ci_tail, step, local_log):
        return "skipped", "fails differently in the gate sandbox (no line of the CI error)"
    return "reproduced", None
