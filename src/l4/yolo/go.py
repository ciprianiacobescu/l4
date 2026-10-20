"""`l4 yolo go PLAN --reason TEXT` (yolo-go, L4-YOLO-080 to L4-YOLO-091): one command that walks a delivery plan from a
committed file to an active plan over the existing commands (preflight, push, check, review, findings, accept,
activate), continues from where the plan is and stops at the first step that cannot pass, with one stop code and one
next command.

This module holds the pure core (the stop codes, the steps, the JSON document, the command line, the decision) and the
command. It records no event of its own: every write is made by the command that makes it today (`l4 yolo review
--local`, `l4 yolo accept`, `l4 yolo activate`), with that command's rules and lease.
"""

import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

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
        return Stop(
            GoStop.REFUSED, "activate", "stopped", f.activation_blocker,
            fix_command(f.activation_blocker) or command_line(f.plan, f.flags),
        )  # fmt: skip
    return Stop(
        GoStop.PERSON, "activate", "person", "activation is a person's decision",
        command_line(f.plan, f.flags, drop=("--local", "--accept-findings"), person=True),
    )  # fmt: skip
