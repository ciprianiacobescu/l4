"""`l4 yolo go PLAN --reason TEXT` (yolo-go, L4-YOLO-080 to L4-YOLO-091): one command that walks a delivery plan from a
committed file to an active plan over the existing commands (preflight, push, check, review, findings, accept,
activate), continues from where the plan is and stops at the first step that cannot pass, with one stop code and one
next command.

This module holds the pure core (the stop codes, the steps, the JSON document, the command line, the decision) and the
command. It records no event of its own: every write is made by the command that makes it today (`l4 yolo review
--local`, `l4 yolo accept`, `l4 yolo activate`), with that command's rules and lease.
"""

import contextlib
import io
import json
import re
import shlex
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, TextIO

import click

from l4 import cancel
from l4.config.schema import duration_seconds
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.pushfail import explain_push_failure, push_platform
from l4.outcome import CommandResult
from l4.state.retry import how_to_start, start_run_result
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.yolo import accept as accepting
from l4.yolo import commands, preflight
from l4.yolo.model import PlanEvent, PlanState
from l4.yolo.plans import plan_files_at
from l4.yolo.state import fold_plan
from l4.yolo.store import list_plans

SCHEMA = "l4/yolo-go@1"
STEPS = ("preflight", "push", "check", "review", "findings", "accept", "activate")
STATUSES = ("ok", "done", "skipped", "pending", "stopped", "person", "not_reached")


class GoStop(IntEnum):
    """The exit code of a run. Not members of `ExitCode` (its table is closed, L4-CLI-001): `go` is an operator's
    command and never a CI step, so `l4 ci map-exit` reports these as codes outside its table."""

    ACTIVE = 0
    PREFLIGHT = 20
    PUSH = 21
    NOT_ADMITTED = 22
    PLAN_STATE = 23
    REVIEW_PENDING = 24
    REVIEW_FAILED = 25
    FINDINGS = 26
    PERSON = 27
    REFUSED = 28
    NOT_CONFIRMED = 29


@dataclass
class Step:
    name: str
    status: str = "not_reached"
    detail: str = ""


@dataclass
class GoResult:
    plan: str
    steps: list[Step]
    next_command: str
    exit: int
    next_by: str = "caller"  # `person` when the command is a person's step, which an agent never runs

    @property
    def step_reached(self) -> str:
        """The last step whose status is not `not_reached`; empty when none was reached."""
        reached = [s.name for s in self.steps if s.status != "not_reached"]
        return reached[-1] if reached else ""

    def as_json(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "plan": self.plan,
            "step_reached": self.step_reached,
            "steps": [{"name": s.name, "status": s.status, "detail": s.detail} for s in self.steps],
            "next_command": self.next_command,
            "next_by": self.next_by,
            "exit": int(self.exit),
        }


@dataclass(frozen=True)
class Flags:
    """The options of one run, after the usage rules; `wait` is the text the caller gave, `wait_s` its seconds."""

    reason: str
    accept_findings: bool
    force: bool
    yes: bool
    as_json: bool
    no_push: bool
    local: bool
    wait: str
    wait_s: int


DEFAULT_WAIT = "30m"
# the order the go command repeats its flags in (D9)
_FLAG_ORDER = ("--accept-findings", "--force", "--yes", "--json", "--local", "--no-push", "--wait")
_PERSON_FLAGS = ("--accept-findings", "--force")  # the only flags a person's command can need


def command_line(
    plan_id: str, flags: Flags, *, drop: tuple[str, ...] = (), add: tuple[str, ...] = (), person: bool = False
) -> str:
    """The go command again: `--reason` quoted for the shell, then the flags the caller gave (less `drop`, plus `add`)
    in a fixed order. A person's command (exit 27) carries only the flag its step needs: never `--yes`, `--json`,
    `--no-push`, `--local` or `--wait`."""
    given = {
        "--accept-findings": flags.accept_findings,
        "--force": flags.force,
        "--yes": flags.yes,
        "--json": flags.as_json,
        "--local": flags.local,
        "--no-push": flags.no_push,
        "--wait": flags.wait != DEFAULT_WAIT,
    }
    on = {name for name, value in given.items() if value} - set(drop)
    on |= set(add)
    if person:
        on &= set(_PERSON_FLAGS)
    words = ["l4", "yolo", "go", plan_id, "--reason", shlex.quote(flags.reason)]
    for name in _FLAG_ORDER:
        if name not in on:
            continue
        words.append(name)
        if name == "--wait":
            words.append(shlex.quote(flags.wait))
    return " ".join(words)


# --- the decision (D5 to D8): pure, no I/O ----------------------------------------------------------------------------

PERSON_DECISION = "acceptance is a person's decision"  # the text of `accept.check` for an agent that may not accept
_NOT_PLANS_STOP = ("inputs_changed", "unit_rejected")  # the stops a review and an activation are the way on from


@dataclass(frozen=True)
class Facts:
    """What `decide` reads, gathered once per round. `plan` is the plan id. `status`, `stop_reason` (for a waiting plan:
    the wait reason), `status_next` (the status's own next step, for a plan that is stopped for good),
    `rejected_unchanged` (a rejected unit whose spec has not changed, R8), `plan_found`/`plan_valid`/`admission` (the
    lines of what keeps the plan from being admitted at the target), `review_kind` (`none`, `stale`, `current`),
    `review_detail` (the text of the review step: when CI was asked, or the lines of its refusal), `covered` (a force
    acceptance holds for every subject), `problems` (the lines of the subjects that are not READY and not cleared),
    `refusals`/`person_refusals` (problem subject, in plan order, to the refusal of `accept.check` for this caller and
    for a person, None when it may accept), `blocked` (the problem subjects whose verdict is BLOCKED),
    `activation_blocker` (what `run_activate` would refuse after the review), `asked`/`waited_out`/`refused_after_ask`
    (the CI review of this run)."""

    plan: str
    actor: tuple[str, str | None]
    flags: Flags
    status: str
    stop_reason: str | None = None
    status_next: str = ""
    rejected_unchanged: bool = False
    plan_found: bool = True
    plan_valid: bool = True
    admission: tuple[str, ...] = ()
    review_kind: str = "none"
    review_detail: str = ""
    covered: bool = False
    problems: tuple[str, ...] = ()
    refusals: Mapping[str, str | None] = field(default_factory=dict)
    person_refusals: Mapping[str, str | None] = field(default_factory=dict)
    blocked: tuple[str, ...] = ()
    activation_blocker: str | None = None
    asked: bool = False
    waited_out: bool = False
    refused_after_ask: bool = False
    activated_by: str | None = None
    activated_at: str | None = None


@dataclass(frozen=True)
class Stop:
    """The run ends here: `code` (a `GoStop`), the `step` it stops at with its `status` (`stopped`, `person`,
    `pending`), the `detail` lines and the one `next_command` (exit 27: a person's)."""

    code: GoStop
    step: str
    status: str
    detail: str
    next_command: str
    person_step: bool = False  # the next command is a person's although the code is not 27 (cancelling a plan)


@dataclass(frozen=True)
class Active:
    """The plan is active, waiting or completed: exit 0, nothing to do."""

    detail: str
    next_command: str


@dataclass(frozen=True)
class Do:
    """The next write: `review_ci`, `review_local`, `accept` (the `subjects`), `force_accept` or `activate`."""

    kind: str
    subjects: tuple[str, ...] = ()


def fix_command(text: str) -> str | None:
    """The command of the last `Fix:` line of a refusal when that line holds exactly one command."""
    fixes = [line[len("Fix:") :].strip() for line in text.splitlines() if line.startswith("Fix:")]
    if not fixes:
        return None
    line = fixes[-1]
    if not line.startswith(("l4 ", "git ")) or any(mark in line for mark in (";", ", ", " or ", "(")):
        return None
    return line


CANCEL_NOTE = "(stop here: cancelling a plan is a person's decision)"
_CANCEL = re.compile(r"\brun (l4 yolo cancel (\S+) --reason TEXT) first\b")


def cancel_command(text: str) -> tuple[str, str] | None:
    """The cancel command that the refusal of an activation names for another plan holding the target, and that plan's
    id: `(l4 yolo cancel p2 --reason TEXT, p2)`. The refusal carries no `Fix:` line, so its words are read."""
    found = _CANCEL.search(text)
    return (found.group(1), found.group(2)) if found else None


def _refusal_lines(refusals: Mapping[str, str | None]) -> str:
    return "\n".join(f"{s}: {r}".replace("\nFix: ", "; fix: ") for s, r in refusals.items() if r is not None)


def decide(f: Facts) -> Stop | Active | Do:
    """The first rule of D5 to D8 that applies, in step order."""
    plan, flags = f.plan, f.flags
    person = f.actor[0] == "person"
    if flags.force and not person:  # D1: a force acceptance is a person's decision, before anything is read
        return Stop(
            GoStop.PERSON, "accept", "person", "--force is a person's decision, never an agent's",
            command_line(plan, flags, person=True),
        )  # fmt: skip
    status = f.status
    if status in ("active", "waiting"):  # D5.1: before the admission is looked at
        if status == "active":
            detail = f"active since {f.activated_at} by {f.activated_by}"
        else:
            detail = f"waiting: {f.stop_reason}"
        return Active(detail, f"l4 yolo status {plan}")
    if status == "completed":
        return Active("completed", f"l4 yolo report {plan}")
    rejected_same = status == "stopped" and f.stop_reason == "unit_rejected" and f.rejected_unchanged
    stopped_for_good = status == "stopped" and f.stop_reason not in _NOT_PLANS_STOP
    if status == "cancelled" or stopped_for_good or rejected_same:  # D5.3
        return Stop(
            GoStop.PLAN_STATE, "check", "stopped", f.status_next or f"{plan} is {status}", f"l4 yolo status {plan}"
        )
    if not f.plan_found or not f.plan_valid or f.admission:  # D5.4
        return Stop(
            GoStop.NOT_ADMITTED, "check", "stopped", "\n".join(f.admission) or f"{plan}: not admitted",
            f"l4 yolo check {plan} --worktree",
        )  # fmt: skip
    if not f.covered and f.review_kind != "current" and not flags.force:  # D6
        if flags.local:
            return Do("review_local")
        if f.refused_after_ask:
            return Stop(
                GoStop.NOT_ADMITTED, "review", "stopped", f.review_detail or f"{plan}: not admitted",
                f"l4 yolo check {plan} --worktree",
            )  # fmt: skip
        if not (f.asked and f.waited_out):
            return Do("review_ci")
        asked = f"{f.review_detail}; " if f.review_detail else ""
        return Stop(
            GoStop.REVIEW_PENDING, "review", "pending", f"{asked}no review recorded within {flags.wait}",
            command_line(plan, flags),
        )  # fmt: skip
    problems = f.problems
    if flags.force:  # D7.3
        if not problems and (f.covered or f.review_kind == "current"):
            return _activation(f)
        return Do("force_accept")
    if problems:  # D7.2, D7.4
        return _findings(f)
    return _activation(f)


def _findings(f: Facts) -> Stop | Do:
    plan, flags = f.plan, f.flags
    person = f.actor[0] == "person"
    if not flags.accept_findings:
        detail = list(f.problems)
        if person and f.blocked:  # the reviewed alternative comes first (force-accept D10)
            detail.append(f'when no model can judge it, a person may run: l4 yolo go {plan} --reason "..." --force')
        if f.refusals and all(r is None for r in f.refusals.values()):
            add = ("--accept-findings",) if person else ("--accept-findings", "--yes")
            return Stop(GoStop.FINDINGS, "findings", "stopped", "\n".join(detail), command_line(plan, flags, add=add))
        return Stop(GoStop.FINDINGS, "findings", "stopped", "\n".join(detail), f"l4 yolo findings {plan}")
    refused = {s: r for s, r in f.refusals.items() if r is not None}
    if refused:  # all or nothing: nothing is recorded when one subject cannot be accepted by this caller
        only_a_person = all(r.startswith(PERSON_DECISION) for r in refused.values())
        if only_a_person and all(r is None for r in f.person_refusals.values()):
            return Stop(
                GoStop.PERSON, "accept", "person", _refusal_lines(refused),
                command_line(plan, flags, add=("--accept-findings",), person=True),
            )  # fmt: skip
        return Stop(GoStop.FINDINGS, "findings", "stopped", _refusal_lines(refused), f"l4 yolo findings {plan}")
    if not person and not flags.yes:
        return Stop(
            GoStop.NOT_CONFIRMED, "accept", "stopped",
            "an agent that may accept passes --yes: there is no terminal to ask the plan id on",
            command_line(plan, flags, add=("--yes",)),
        )  # fmt: skip
    return Do("accept", tuple(f.refusals))


def _activation(f: Facts) -> Stop | Do:
    """D8: a person's run activates; an agent's run stops, after checking that the activation would not be refused."""
    if f.actor[0] == "person":
        return Do("activate")
    if f.activation_blocker:
        cancel = cancel_command(f.activation_blocker)
        if cancel is not None:  # an agent never cancels a plan: the next line is a person's step
            return Stop(
                GoStop.REFUSED, "activate", "stopped",
                f"{f.activation_blocker}\ncancelling plan {cancel[1]} is a person's decision", cancel[0], True,
            )  # fmt: skip
        return Stop(
            GoStop.REFUSED, "activate", "stopped", f.activation_blocker,
            fix_command(f.activation_blocker) or command_line(f.plan, f.flags),
        )  # fmt: skip
    return Stop(
        GoStop.PERSON, "activate", "person", "activation is a person's decision",
        command_line(f.plan, f.flags, drop=("--local", "--accept-findings"), person=True),
    )  # fmt: skip


# --- the command ------------------------------------------------------------------------------------------------------

MAX_MOVED = 3  # lost plan leases per run (D11)
POLL_S = 15.0  # how often the wait reads the plan ledger for the CI review (D6.5)
_sleep = time.sleep  # the wait's clock and sleep: tests replace them, so a wait ends without real time passing
_clock = time.monotonic
_SKIP_CI = ("[skip ci]", "[ci skip]")

_STEP_OF = {
    "review_ci": "review", "review_local": "review", "accept": "accept", "force_accept": "accept",
    "activate": "activate",
}  # fmt: skip


def _usage(
    plan: str, reason: str, accept_findings: bool, force: bool, yes: bool, as_json: bool, no_push: bool, local: bool,
    wait: str,
) -> tuple[str, Flags]:  # fmt: skip
    """D1: the usage rules, in this order, before anything is read or fetched (exit 2)."""
    plan_id = commands._plan_id(plan)
    text = reason.strip()
    if not text:
        raise L4Exit(ExitCode.USAGE_ERROR, "go: --reason must say why")
    if len(text) > commands.MAX_REASON:
        raise L4Exit(ExitCode.USAGE_ERROR, f"go: --reason has {len(text)} characters; at most {commands.MAX_REASON}")
    if accept_findings and force:
        raise L4Exit(
            ExitCode.USAGE_ERROR, "go: --accept-findings and --force exclude each other: choose how the findings go"
        )
    if force and local:
        raise L4Exit(ExitCode.USAGE_ERROR, "go: --force reviews nothing, so --local does not apply with it")
    try:
        seconds = duration_seconds(wait)
    except ValueError:
        raise L4Exit(
            ExitCode.USAGE_ERROR, f"go: --wait {wait!r} is neither 0 nor a duration such as 30s, 30m or 1h"
        ) from None
    return plan_id, Flags(text, accept_findings, force, yes, as_json, no_push, local, wait, seconds)


class _LineRelay(io.TextIOBase):
    """Stands in for stdout while a called command runs (D2): keeps every line (the step's detail), drops its `Next:`
    lines (the run prints one) and forwards the rest to `to` at once, line by line, so a person reads the findings
    before the prompt that follows them."""

    def __init__(self, lines: list[str], to: TextIO | None, indent: str) -> None:
        self.lines, self.to, self.indent, self._pending = lines, to, indent, ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._line(line)
        return len(text)

    def flush(self) -> None:
        if self.to is not None:
            self.to.flush()

    def finish(self) -> None:
        if self._pending:
            self._line(self._pending)
            self._pending = ""

    def _line(self, line: str) -> None:
        if line.startswith("Next:"):
            return
        self.lines.append(line)
        if self.to is not None:
            self.to.write(f"{self.indent}{line}\n")
            self.to.flush()


@contextlib.contextmanager
def _relay(lines: list[str], to: TextIO | None, indent: str = "  ") -> Iterator[None]:
    writer = _LineRelay(lines, to, indent)
    with contextlib.redirect_stdout(writer):
        try:
            yield
        finally:
            writer.finish()


@dataclass
class _Seen:
    """What a round saw besides the facts: for the step lines."""

    rev: str = ""
    order: tuple[str, ...] = ()
    cleared: int = 0  # acceptances that hold
    forced: int = 0  # force items that hold
    events: Sequence[PlanEvent] = ()
    state: PlanState | None = None
    parsed: Any = None  # the plan, its file text and the unit digests now: what the wait reads the ledger against
    text: str = ""
    now: Mapping[str, str] = field(default_factory=dict)


class _Go:
    """One run: the steps as they end, the output, and the actions already taken."""

    def __init__(self, app: AppContext, plan: str, flags: Flags, actor: tuple[str, str | None]) -> None:
        self.app, self.plan, self.flags, self.actor = app, plan, flags, actor
        self.steps = [Step(name) for name in STEPS]
        self.cursor = 0
        self.did: list[str] = []
        self.moved = 0  # plan leases lost so far in this run (D11)
        self.asked = False
        self.waited_out = False
        self.ask_detail = ""
        self.events_at_ask = 0
        self.stdout: TextIO = sys.stdout
        self.ctx: Any = None  # the commands' context, once opened
        self.rev = ""  # the target head the last fetch saw
        self.pushed = False  # this run pushed the base branch (CI then runs on it)
        self.pushed_message = ""  # the message of the commit it pushed

    def redact(self, text: str) -> str:
        return self.app.redactor.redact_text(text)

    # the steps
    def finish(self, name: str, status: str, detail: str = "", *, rest: bool = True) -> None:
        index = STEPS.index(name)
        step = self.steps[index]
        step.status, step.detail = status, self.redact(detail)
        self.cursor = max(self.cursor, index + 1)
        if self.flags.as_json:
            return
        head, *more = step.detail.splitlines() or [""]
        click.echo(f"{name}: {status}" + (f": {head}" if head else ""))
        if rest:
            for line in more:
                click.echo(f"  {line}")

    def pass_through(self, upto: str, facts: Facts, seen: _Seen) -> None:
        """End the steps before `upto` that the run has not ended, with the status the facts give them."""
        for name in STEPS[self.cursor : STEPS.index(upto)]:
            status, detail = self.passed(name, facts, seen)
            self.finish(name, status, detail)

    def passed(self, name: str, f: Facts, seen: _Seen) -> tuple[str, str]:
        if name == "check":
            return "ok", f"admitted at origin/{self.ctx.target} {seen.rev[:10]}; order: {', '.join(seen.order)}"
        if name == "review":
            if f.covered:
                return "skipped", "force-accepted: no review is needed"
            if f.review_kind == "current":
                return "ok", f.review_detail
            return "skipped", "--force accepts without a review; nothing is judged"
        if name == "findings":
            if f.review_kind != "current":
                if f.covered:
                    return "ok", "every subject is force-accepted"
                return "skipped", "there is no review to read"
            if f.problems:
                note = ["overridden by --force"] if f.flags.force else []
                return "ok", "\n".join([*note, *f.problems])
            if seen.cleared:
                return "ok", f"every subject is READY or accepted ({seen.cleared} accepted)"
            return "ok", "every subject is READY"
        if name == "accept":
            if seen.cleared:
                return "ok", f"{seen.cleared} acceptance(s) hold"
            if seen.forced:
                return "ok", "the force acceptance holds"
            if f.flags.force:
                return "skipped", "the review is READY: nothing to force"
            return "skipped", "nothing to accept"
        return "ok", ""

    # the end
    def end(self, code: int, next_command: str, person_step: bool = False) -> CommandResult:
        by = "person" if code == GoStop.PERSON or person_step else "caller"
        if self.flags.as_json:
            doc = GoResult(self.plan, self.steps, next_command, int(code), by).as_json()
            click.echo(self.redact(json.dumps(doc, indent=2)), file=self.stdout)
        else:
            if code == GoStop.PERSON:
                text = f"a person runs: {next_command}"
            elif person_step:
                text = f"a person runs: {next_command} {CANCEL_NOTE}"
            else:
                text = next_command
            click.echo(self.redact(f"Next: {text}"))
        return CommandResult(int(code))

    def stop(self, stop: Stop, facts: Facts | None = None, seen: _Seen | None = None) -> CommandResult:
        if facts is not None and seen is not None:
            self.pass_through(stop.step, facts, seen)
        self.finish(stop.step, stop.status, stop.detail)
        return self.end(stop.code, stop.next_command, stop.person_step)

    # the relay
    def relay(self, lines: list[str], *, prompting: bool) -> contextlib.AbstractContextManager[None]:
        if self.flags.as_json:
            return _relay(lines, sys.stderr if prompting else None)
        return _relay(lines, self.stdout)


def run_go(
    app: AppContext,
    *,
    plan: str,
    reason: str,
    accept_findings: bool = False,
    force: bool = False,
    yes: bool = False,
    as_json: bool = False,
    no_push: bool = False,
    local: bool = False,
    wait: str = "30m",
) -> CommandResult:
    """`l4 yolo go PLAN --reason TEXT` (L4-YOLO-080): see the module's docstring. Exits 2 for a usage error and 16 for a
    signal, as every command; the other ends are the stop codes of `GoStop` and a next command."""
    plan_id, flags = _usage(plan, reason, accept_findings, force, yes, as_json, no_push, local, wait)
    actor = accepting.actor(app.environ, commands._stdin_tty())
    go = _Go(app, plan_id, flags, actor)
    with contextlib.redirect_stdout(sys.stderr) if as_json else contextlib.nullcontext():
        return _run(go)


def _run(go: _Go) -> CommandResult:
    flags = go.flags
    if flags.force and go.actor[0] != "person":  # D1: before anything is read
        stop = Stop(
            GoStop.PERSON, "accept", "person", "--force is a person's decision, never an agent's",
            command_line(go.plan, flags, person=True),
        )  # fmt: skip
        return go.stop(stop)
    ctx = commands._open(go.app)
    go.ctx = ctx
    early = _preflight(go)
    if early is not None:
        return early
    try:
        return _walk(go)
    except L4Exit as exc:  # a fault after the run began is a stop with the document and a next line (D9)
        return _stopped_by(go, exc)


def _walk(go: _Go) -> CommandResult:
    flags = go.flags
    early = _push_step(go)
    if early is not None:
        return early
    while True:
        facts, seen = _gather(go)
        action = decide(facts)
        if isinstance(action, Stop):
            return go.stop(action, facts, seen)
        if isinstance(action, Active):
            go.finish("check", "ok", f"{go.plan} is {facts.status}")
            for name in ("review", "findings", "accept"):
                go.finish(name, "skipped", f"the plan is {facts.status}")
            go.finish("activate", "ok", action.detail)
            return go.end(GoStop.ACTIVE, action.next_command)
        if action.kind in go.did:  # a guard against a loop, never expected (D2)
            stop = Stop(
                GoStop.REFUSED, _STEP_OF[action.kind], "stopped",
                f"no progress: {action.kind} ran and the plan did not change", command_line(go.plan, flags),
            )  # fmt: skip
            return go.stop(stop, facts, seen)
        go.pass_through(_STEP_OF[action.kind], facts, seen)
        outcome = _act(go, action, facts, seen)
        if outcome is _AGAIN:  # the lease was lost: read the plan again and decide again (D11)
            continue
        go.did.append(action.kind)
        if outcome is not None:
            return outcome
        if action.kind == "activate":
            return go.end(GoStop.ACTIVE, f"l4 yolo status {go.plan}")


def _sync_fix(ctx: Any, text: str) -> str:
    if "no origin" in text:
        return "git remote add origin <url>"
    if "not on origin" in text:
        return f"git push -u origin {ctx.target}"
    return "git fetch origin"


def _stopped_by(go: _Go, exc: L4Exit) -> CommandResult:
    """An `L4Exit` that no step handled, after preflight: a harness or network fault (exit 1) keeps its code and an
    exit 2 (the fetch found no origin or no base branch) is a stop, both with the document and one next line. The step
    is the one the run was at. Any other code (a signal) goes on."""
    if exc.code not in (ExitCode.INTERNAL_ERROR, ExitCode.USAGE_ERROR):
        raise exc
    step = STEPS[min(go.cursor, len(STEPS) - 1)]
    text = go.redact(str(exc))
    if exc.code == ExitCode.INTERNAL_ERROR:
        go.finish(step, "stopped", text)
        return go.end(int(ExitCode.INTERNAL_ERROR), command_line(go.plan, go.flags))
    code = GoStop.PUSH if step == "push" else GoStop.REFUSED
    return go.stop(Stop(code, step, "stopped", text, fix_command(text) or _sync_fix(go.ctx, text)))


def _preflight(go: _Go) -> CommandResult | None:
    """D3: the local checks of the skill script, then the fetch (no origin, or no base branch on it, stops too)."""
    ctx = go.ctx
    roots = {"openspec_root": ctx.cfg.spec.openspec.root, "kiro_root": ctx.cfg.spec.kiro.root}
    found = preflight.problems(ctx.app.repo, ctx.git, go.plan, base_ref=ctx.target_ref, **roots)
    if found:
        detail = "\n".join(f"{p.code}: {p.text}" for p in found)
        return go.stop(Stop(GoStop.PREFLIGHT, "preflight", "stopped", detail, found[0].fix))
    try:
        go.rev = commands._sync(ctx, who="go")
    except L4Exit as exc:
        if exc.code != ExitCode.USAGE_ERROR:  # a network or harness fault keeps its meaning
            raise
        text = go.redact(str(exc))
        return go.stop(Stop(GoStop.PREFLIGHT, "preflight", "stopped", text, _sync_fix(ctx, text)))
    folders = preflight.unit_folders(ctx.app.repo, go.plan, **roots)
    go.finish(
        "preflight",
        "ok",
        f"the tree is clean; .l4/plans/{go.plan}.json and {len(folders)} unit folder(s) are committed",
    )
    return None


def _push(git: Git, args: Sequence[str], config: Sequence[tuple[str, str]] = ()) -> None:
    """The one git push `go` makes (a test spies on it): a plain fast-forward push, hooks run, never forced."""
    git.run(*args, config=config)


def _paths_ahead(git: Git, ref: str) -> list[str]:
    """Every path any commit ahead of `ref` touches, renames off: a rename lists both its old and its new path (the
    push deletes the old one on origin), which `git diff --name-only` would not."""
    out = git.run("log", "--format=", "--name-only", "--no-renames", f"{ref}..HEAD", check=False).stdout
    return list(dict.fromkeys(line for line in out.splitlines() if line))


def _other_plan_touched(ctx: Any, plan: str, names: Sequence[str]) -> tuple[str, list[str]] | None:
    """The other plan on origin that is active or waiting and whose plan file or unit folder a commit ahead touches,
    with those paths: a push of them would stop it with `inputs_changed` (D4.3)."""
    files = {f.plan_id: f for f in plan_files_at(ctx.git, ctx.target_ref)}
    try:
        others = list_plans(ctx.git, ctx.fetch_cfg)
    except GitError as exc:  # the guard cannot be checked: a network fault (exit 1), not a push
        raise L4Exit(ExitCode.INTERNAL_ERROR, f"cannot list the plans on origin: {exc.stderr.strip()}") from None
    for other in others:
        if other == plan or fold_plan(other, ctx.store(other).read().events).status not in ("active", "waiting"):
            continue
        file = files.get(other)
        ids = file.plan.unit_ids() if file is not None and file.plan is not None else []
        folders = [preflight.unit_folder(u, ctx.cfg.spec.openspec.root, ctx.cfg.spec.kiro.root) for u in ids]
        touched = [n for n in names if n == f".l4/plans/{other}.json" or any(n.startswith(f"{f}/") for f in folders)]
        if touched:
            return other, touched
    return None


def _count(git: Git, span: str) -> int | None:
    done = git.run("rev-list", "--count", span, check=False)
    try:
        return int(done.stdout.strip())
    except ValueError:
        return None


def _push_step(go: _Go) -> CommandResult | None:
    """D4: push the base branch when HEAD is ahead of `origin/<base>`, as a fast-forward and never forced."""
    ctx, plan, flags = go.ctx, go.plan, go.flags
    base, ref = ctx.target, ctx.target_ref
    git = ctx.git
    ahead, behind = _count(git, f"{ref}..HEAD"), _count(git, f"HEAD..{ref}")
    if ahead is None or behind is None:
        text = f"cannot count the commits of HEAD against origin/{base}"
        return go.stop(Stop(GoStop.PUSH, "push", "stopped", text, "git status"))
    if ahead == 0:
        if behind == 0:
            go.finish("push", "ok", f"origin/{base} has HEAD")
        else:
            go.finish("push", "ok", f"the checkout is {behind} commit(s) behind origin/{base}; go reads origin")
        return None
    pull = f"git pull --rebase origin {base}"
    if behind > 0:
        text = f"HEAD and origin/{base} have diverged: {ahead} commit(s) only on HEAD, {behind} only on origin/{base}"
        return go.stop(Stop(GoStop.PUSH, "push", "stopped", text, pull))
    branch = git.run("symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()
    if branch != base:
        text = (
            f"go pushes only the branch {base}; HEAD is {branch or 'detached'} with {ahead} commit(s) not on "
            f"origin/{base}"
        )
        return go.stop(Stop(GoStop.PUSH, "push", "stopped", text, f"git switch {base}"))
    names = _paths_ahead(git, ref)
    folders = preflight.unit_folders(
        ctx.app.repo, plan, openspec_root=ctx.cfg.spec.openspec.root, kiro_root=ctx.cfg.spec.kiro.root
    )
    own = f".l4/plans/{plan}.json"
    state = fold_plan(plan, ctx.store(plan).read().events)
    touches = [n for n in names if n == own or any(n.startswith(f"{f}/") for f in folders)]
    if state.status in ("active", "waiting") and touches:  # it would stop the plan with inputs_changed
        text = f"pushing this stops the active plan {plan} with inputs_changed: {', '.join(touches[:3])}"
        return go.stop(Stop(GoStop.PUSH, "push", "stopped", text, f"l4 yolo status {plan}"))
    other = _other_plan_touched(ctx, plan, names)
    if other is not None:  # only one plan is active on a target: its inputs are guarded for every run
        text = f"pushing this stops the active plan {other[0]} with inputs_changed: {', '.join(other[1][:3])}"
        return go.stop(Stop(GoStop.PUSH, "push", "stopped", text, f"l4 yolo status {other[0]}"))
    if flags.no_push:
        text = f"--no-push: {ahead} commit(s) of {base} are not on origin/{base}"
        return go.stop(Stop(GoStop.PUSH, "push", "stopped", text, f"git push origin {base}"))
    if go.actor[0] != "person":  # D12: an agent pushes the hand-off the skill gives it, nothing else
        outside = [n for n in names if n != own and not any(n.startswith(f"{f}/") for f in folders)]
        if outside:
            text = (
                f"the commits ahead change files outside the hand-off (the plan file and its unit folders): "
                f"{', '.join(outside[:3])}{' ...' if len(outside) > 3 else ''}"
            )
            return go.stop(Stop(GoStop.PERSON, "push", "person", text, f"git push origin {base}"))
    lines: list[str] = []
    with _relay(lines, None):
        code = commands._check_worktree(ctx, plan, git.rev_parse(ref) or "")
    if code != ExitCode.OK:  # no plan the working-tree admission refuses, and no spec no plan covers, is pushed
        return go.stop(
            Stop(GoStop.NOT_ADMITTED, "push", "stopped", "\n".join(lines), f"l4 yolo check {plan} --worktree")
        )
    cancel.check()
    try:
        hooks = ("core.hooksPath", git.repo_hooks_path())  # D4.7: the person's own pre-push hooks run
        _push(git, ["push", "origin", f"refs/heads/{base}:refs/heads/{base}"], [*ctx.push_cfg, hooks])
    except GitError as exc:
        failed = explain_push_failure(
            exc,
            branch=base,
            token_env=ctx.cfg.forge.token_env,
            environ=go.app.environ,
            redact=go.redact,
            platform=push_platform(ctx.cfg, go.app.environ, go.app.repo),
        )
        low = exc.stderr.lower()
        moved = "non-fast-forward" in low or "fetch first" in low
        return go.stop(Stop(GoStop.PUSH, "push", "stopped", str(failed), pull if moved else f"git push origin {base}"))
    go.rev = commands._sync(ctx, who="go")
    sha = git.rev_parse(ref) or ""
    go.pushed = True
    go.pushed_message = git.run("log", "-1", "--format=%B", "HEAD", check=False).stdout
    go.finish("push", "done", f"pushed {ahead} commit(s) to origin/{base} ({sha[:10]})")
    return None


def _refusal_text(go: _Go, exc: L4Exit) -> str:
    return go.redact(str(exc))


def _refused(go: _Go, step: str, exc: L4Exit) -> Stop:
    """D9: a called command's refusal. Its `Fix:` line is the next command when it holds one command."""
    text = _refusal_text(go, exc)
    flags = go.flags
    if step == "review" and exc.code == ExitCode.WAITING_CAPACITY:
        return Stop(GoStop.REVIEW_FAILED, "review", "stopped", text, command_line(go.plan, flags, drop=("--local",)))
    if step in ("accept", "activate") and (
        "the plan id was not typed" in text or "no terminal to ask the plan id on" in text
    ):
        add = ("--yes",) if go.actor[0] != "person" else ()
        return Stop(GoStop.NOT_CONFIRMED, step, "stopped", text, command_line(go.plan, flags, add=add))
    cancel = cancel_command(text)  # another plan holds the target
    if fix_command(text) is None and cancel is not None:
        agent = go.actor[0] != "person"
        return Stop(GoStop.REFUSED, step, "stopped", text, cancel[0], agent)
    return Stop(GoStop.REFUSED, step, "stopped", text, fix_command(text) or command_line(go.plan, flags))


_AGAIN = CommandResult(-1)  # `_act`'s answer to a lost plan lease: not an end of the run


def _act(go: _Go, action: Do, facts: Facts, seen: _Seen) -> CommandResult | None:
    """Run the existing command for `action`; the step ends `done`, or the run ends with the stop it maps to."""
    step = _STEP_OF[action.kind]
    flags, app, plan = go.flags, go.app, go.plan
    lines: list[str] = []
    try:
        if action.kind == "review_ci":
            return _review_ci(go, facts, seen)
        if action.kind == "review_local":
            with go.relay(lines, prompting=False):
                code = commands.run_review(app, plan=plan, local=True)
            if code != ExitCode.OK:
                stop = Stop(
                    GoStop.NOT_ADMITTED, "review", "stopped", "\n".join(lines), f"l4 yolo check {plan} --worktree"
                )
                return go.stop(stop)
            go.finish(
                "review", "done", next((x.strip() for x in lines if "reviewed here" in x), "reviewed here"), rest=False
            )
        elif action.kind == "accept":
            for subject in action.subjects:
                with go.relay(lines, prompting=True):
                    commands.run_accept(
                        app, plan=plan, subject=subject, reason=flags.reason, withdraw=False, yes=flags.yes
                    )
            go.finish("accept", "done", f"accepted {len(action.subjects)} subject(s)")
        elif action.kind == "force_accept":
            with go.relay(lines, prompting=True):
                commands.run_accept(
                    app, plan=plan, subject=None, reason=flags.reason, withdraw=False, yes=flags.yes,
                    all_subjects=True, force=True,
                )  # fmt: skip
            done = next((x.strip() for x in lines if x.startswith("force-accepted:")), "force-accepted every subject")
            go.finish("accept", "done", done, rest=False)
        else:
            if go.actor[0] == "person" and not flags.yes:  # B1: a person types the plan id before activation
                commands._confirm(go.ctx, plan, f"Type the plan id ({plan}) to activate {plan}", "go")
            with go.relay(lines, prompting=False):
                commands.run_activate(app, plan=plan, reason=flags.reason, no_run=False)
            done = next((x.strip() for x in lines if " activated on " in x), f"{plan}: activated")
            go.finish("activate", "done", done, rest=False)
    except L4Exit as exc:
        if exc.code == ExitCode.INTERNAL_ERROR:  # a harness or network fault is no refusal: exit 1 (`_stopped_by`)
            raise
        if str(exc) == commands._MOVED and go.moved < MAX_MOVED:  # D11: another writer won the lease
            go.moved += 1
            return _AGAIN
        return go.stop(_refused(go, step, exc))
    return None


def _gather(go: _Go) -> tuple[Facts, _Seen]:
    """Read where the plan is: the ledger, the plan file at the target, the review and who may accept (D2). Writes
    nothing."""
    ctx, plan = go.ctx, go.plan
    rev = commands._sync(ctx, who="go")
    read = ctx.store(plan).read()
    state = fold_plan(plan, read.events)
    seen = _Seen(rev=rev, events=read.events, state=state)
    status = state.status
    activated = next((e for e in reversed(read.events) if e.type == "plan.activated"), None)
    base: dict[str, Any] = {
        "plan": plan, "actor": go.actor, "flags": go.flags, "status": status,
        "stop_reason": state.wait_reason if status == "waiting" else state.stop_reason,
        "activated_by": state.activated_by, "activated_at": activated.at if activated else None,
    }  # fmt: skip
    pre_activation = status in ("new", "refused", "admitted", "reviewed") or (
        status == "stopped" and state.stop_reason in ("inputs_changed", "unit_rejected")
    )
    if not pre_activation:
        if status == "cancelled":
            base["status_next"] = commands._next_line(plan, state, None, None)
        elif status == "stopped":
            base["status_next"] = _status_next(ctx, rev, read, plan)
        return Facts(**base), seen
    try:
        at = commands._admission_at(ctx, plan, rev, state)
    except L4Exit as exc:
        if exc.code != ExitCode.USAGE_ERROR:  # only an admission refusal is `not_admitted`
            raise
        return Facts(**base, plan_found=False, admission=(go.redact(str(exc)),)), seen
    if at.plan is None or at.units is None or at.admission is None:
        assert at.file.invalid is not None
        lines = (*at.file.invalid.errors, f"{plan}: not a plan")
        return Facts(**base, plan_valid=False, admission=tuple(lines)), seen
    if not at.admission.ok:
        return Facts(**base, admission=tuple(commands._findings_text(at.admission, plan))), seen
    seen.order = tuple(at.admission.order)
    now = commands._digests(ctx, at.plan, at.units)
    seen.parsed, seen.text, seen.now = at.plan, at.file.text, now
    view = commands._review_view(at.plan, at.file.text, state, read.events, now)
    seen.cleared, seen.forced = len(view.cleared), len(view.forced)
    rejected = commands._rejected_at(read.events, state)
    base["rejected_unchanged"] = rejected is not None and now.get(state.stop_unit or "") == rejected
    if base["rejected_unchanged"]:  # the run stops at check with the status's own next step (R8)
        base["status_next"] = _status_next(ctx, rev, read, plan)
    refusals: dict[str, str | None] = {}
    person_refusals: dict[str, str | None] = {}
    latest = commands._latest_review(read.events)
    if view.kind == "current" and view.problem_subjects and latest is not None:
        target = commands._review_cfg(ctx, state)[0]
        for subject in view.problem_subjects:
            refusals[subject] = _accept_refusal(plan, state, read.events, subject, latest, target, go.actor)
            person_refusals[subject] = _accept_refusal(
                plan, state, read.events, subject, latest, target, ("person", None)
            )
    blocked = tuple(s for s in view.problem_subjects if state.review.get(s) == "BLOCKED")
    blocker = None
    if go.actor[0] != "person" and not view.problems and (view.kind == "current" or view.covered):
        blocker = commands._activation_blocker(ctx, plan, at.plan)  # an agent is told, a person's activation checks
    detail = ""
    if view.kind == "current":
        wanted = [*at.plan.unit_ids(), *(f"batch:{b.id}" for b in at.plan.batches if len(b.units) > 1)]
        ready = sum(1 for w in wanted if state.review.get(w) == "READY")
        event = next((e for e in reversed(read.events) if e.type == "plan.reviewed"), None)
        source = (event.data.get("source") if event else None) or "ci"
        detail = f"reviewed at {event.at if event else '?'} ({source}): {ready} READY, {len(wanted) - ready} not READY"
    refused: list[PlanEvent] = []
    if go.asked and view.kind != "current":
        refused = [e for e in read.events[go.events_at_ask :] if e.type == "plan.refused"]
        detail = _refused_lines(refused[-1], plan) if refused else go.ask_detail
    return Facts(
        **base, review_kind=view.kind, review_detail=detail, covered=view.covered, problems=view.problems,
        refusals=refusals, person_refusals=person_refusals, blocked=blocked, activation_blocker=blocker,
        asked=go.asked, waited_out=go.waited_out, refused_after_ask=bool(refused),
    ), seen  # fmt: skip


def _refused_lines(event: PlanEvent, plan: str) -> str:
    """The findings of a `plan.refused` as `<code>: <text>` lines, the subject added when the text does not name it."""
    lines = []
    for item in event.data.get("findings") or []:
        if not isinstance(item, dict):
            continue
        code, subject, text = item.get("code"), item.get("subject"), str(item.get("text"))
        named = subject in (plan, *text.split())
        lines.append(f"{code}: {text}" if named else f"{code}: {subject}: {text}")
    return "\n".join(lines) or "the plan was refused"


def _poll(go: _Go, seen: _Seen) -> tuple[str, PlanEvent | None]:
    """One read of the plan ref during the wait: `review` (with the `plan.reviewed` event) when the review at the
    digests gathered before the wait is recorded, `refused` when CI recorded a refusal after the ask, else empty. The
    ledger is what activation reads."""
    ctx = go.ctx
    read = ctx.store(go.plan).read()
    state = fold_plan(go.plan, read.events)
    view = commands._review_view(seen.parsed, seen.text, state, read.events, seen.now)
    if view.kind == "current":
        return "review", next((e for e in reversed(read.events) if e.type == "plan.reviewed"), None)
    if any(e.type == "plan.refused" for e in read.events[go.events_at_ask :]):
        return "refused", None
    return "", None


def _review_ci(go: _Go, facts: Facts, seen: _Seen) -> CommandResult | None:
    """D6.5: CI reviews. This run's own push starts CI on the base branch (unless its head says `[skip ci]`); else the
    forge is asked for a run. Then the plan ledger is read every `POLL_S` until the review is recorded, a refusal is, or
    `--wait` ends (nothing is written meanwhile)."""
    ctx, flags = go.ctx, go.flags
    if not go.asked:
        if go.pushed and not any(mark in go.pushed_message.lower() for mark in _SKIP_CI):
            go.ask_detail = f"the push started CI on {ctx.target}"
        else:
            answer, line = start_run_result(go.app, ctx.cfg)
            if answer not in ("started", "already_queued"):
                text = f"CI could not be asked ({answer}): {line}\nthen run the go command again"
                return go.stop(
                    Stop(GoStop.REVIEW_PENDING, "review", "pending", text, how_to_start(go.app, ctx.cfg, ctx.target))
                )
            go.ask_detail = f"CI was asked at {commands._stamp()} ({answer})"
        go.asked, go.events_at_ask = True, len(seen.events)
    if flags.wait_s == 0:
        go.waited_out = True
        return None
    note = f"review: waiting: {go.ask_detail}; polling the plan ledger every {POLL_S:g}s for up to {flags.wait}"
    click.echo(go.redact(note), err=flags.as_json)
    deadline = _clock() + flags.wait_s
    while _clock() < deadline:
        _sleep(min(POLL_S, max(deadline - _clock(), 0.0)))
        cancel.check()
        found, event = _poll(go, seen)
        if found == "review":
            when = f"at {event.at}" if event else "now"
            source = (event.data.get("source") if event else None) or "ci"
            go.finish("review", "done", f"reviewed in CI {when}" if source == "ci" else f"reviewed {when} ({source})")
            return None
        if found == "refused":
            return None
    go.waited_out = True
    return None


def _status_next(ctx: Any, rev: str, read: Any, plan: str) -> str:
    """The `next` line of `l4 yolo status` for a plan that is stopped: the step that clears the stop."""
    files = {f.plan_id: f for f in plan_files_at(ctx.git, ctx.target_ref)}
    file = files.get(plan)
    units = commands._read_units(ctx, rev, file.plan.known_ids() if file and file.plan else [], intake=False)
    return str(commands._describe(ctx, rev, file, read, plan, units)["next"])


def _accept_refusal(
    plan: str, state: PlanState, events: Sequence[PlanEvent], subject: str, review: Mapping[str, Any],
    target: Any, who: tuple[str, str | None],
) -> str | None:  # fmt: skip
    """The refusal of `l4 yolo accept PLAN SUBJECT` for `who`, as a message and a `Fix:` line; None if it may."""
    entry = commands._entry_of(review, subject)
    if entry is None:
        return f"{subject} is not in the latest review\nFix: l4 yolo review {plan}"
    refusal = accepting.check(state, events, subject, entry, target, who)
    if refusal is not None:
        return f"{refusal.message}\nFix: {refusal.fix}"
    if entry.get("material") is None:
        return (
            f"the review of {subject} predates material keys, so an acceptance could not be bound to it\n"
            f"Fix: l4 yolo review {plan}"
        )
    return None
