"""`l4 yolo go PLAN --reason TEXT` (yolo-go, L4-YOLO-080 to L4-YOLO-091): one command that walks a delivery plan from a
committed file to an active plan over the existing commands (preflight, push, check, review, findings, accept,
activate), continues from where the plan is and stops at the first step that cannot pass, with one stop code and one
next command.

This module holds the pure core (the stop codes, the steps, the JSON document, the command line, the decision) and the
command. It records no event of its own: every write is made by the command that makes it today (`l4 yolo review
--local`, `l4 yolo accept`, `l4 yolo activate`), with that command's rules and lease.
"""

import shlex
from dataclasses import dataclass
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
