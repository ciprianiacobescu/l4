"""Who may retry or restart a stopped unit by label (SPEC L4-SEC-004, L4-CI-004, SCN-RES-01, L4-OPS-008), pure.

The labels `l4:retry`, `l4:resume` (the same) and `l4:restart` are a signal only when the forge itself says a member
set it: the latest `add` event of the label names the user (`LabelEvent.user_id`), and that user must have at least
Developer access (30) and must not be the token's own user. The project's bot is a Developer too (probed live, level
30), so a level check alone would accept the harness's own label; it is excluded by id. One label event is one action:
its id (`label:<id>`) is recorded in `unit.retried{signal}` or `unit.restarted{signal}` and an id already recorded is
never acted on again.
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass

from l4.forge.base import LabelEvent
from l4.state.next_step import JUDGE_VIEW_REJECTED, NO_CONVERTIBLE_FINDING, UNCONVERTED_AND_JUDGE_VIEW, way_out

DEVELOPER = 30  # GitLab's access level for Developer (members with Write access on GitHub)


@dataclass(frozen=True)
class ResumeSignal:
    event_id: int
    signal: str  # `label:<event id>`
    user_id: int
    access_level: int


@dataclass(frozen=True)
class Refusal:
    event_id: int
    signal: str
    why: str


def resume_signal(
    labels: Sequence[str],
    events: Sequence[LabelEvent],
    *,
    label: str,
    own_id: int | None,
    access: Callable[[int], int | None],
    consumed: Collection[str],
    unit: str | None = None,
    command: str = "l4 retry",
) -> ResumeSignal | Refusal | None:
    """`labels` are the MR's labels now, `events` its label history. None: no signal (the label is not on the MR, no
    event set it, or its event was already acted on). A refusal names why the latest event does not count and, when
    `unit` is given, the command that works (`command`: `l4 retry` or `l4 restart`; L4-OPS-008)."""
    if label not in labels:
        return None
    history = sorted((e for e in events if e.label == label), key=lambda e: e.id)
    if not history or history[-1].action != "add":
        return None
    event = history[-1]
    signal = f"label:{event.id}"
    if signal in consumed:
        return None
    run = f"{command} --unit {unit} --reason TEXT" if unit else None

    def refuse(why: str, *, own: bool = False) -> Refusal:
        if run is None:
            return Refusal(event.id, signal, why)
        return Refusal(event.id, signal, f"{why}: use {run}, or ask another member" if own else f"{why}; run {run}")

    if event.user_id is None:
        return refuse("the forge does not say who set the label")
    if own_id is None:
        return refuse("the harness cannot tell which user is its own, so no label is honoured")
    if event.user_id == own_id:
        return refuse("the label was set by the harness's own user", own=True)
    level = access(event.user_id)
    if level is None:
        return refuse("the label was set by a user who is not a member of the project")
    if level < DEVELOPER:
        return refuse(f"the label was set by a member below Developer access (level {level})")
    return ResumeSignal(event.id, signal, event.user_id, level)


def retry_label(label: str) -> str:
    """The `retry` label for a caller that still passes the `resume` label (the two mean the same, L4-OPS-008)."""
    return label.removesuffix("resume") + "retry" if label.endswith("resume") else label


def halted_section(
    phase: str, reason: str, unit: str, label: str, *, feedback: bool = False, reason_code: str | None = None
) -> str:
    """The sticky-note section of a unit that stopped (SPEC L4-ARC-002, L4-CLI-002, L4-OPS-008): why, and what continues
    it: the `retry` label (a `resume` label passed in is named as `retry`) or `l4 retry`, which adds the round itself.
    The halting run writes it with its last mirror sync, and the sweep writes it again around a refusal. `feedback`: the
    unit is escalated at the feedback limit (L4-FBK-006), where the label gives one more feedback round, not a fix
    round."""
    why = " ".join(reason.split())[:300]
    label = retry_label(label)
    command = f"`l4 retry --unit {unit} --reason TEXT`"
    if phase == "escalated" and reason_code in (NO_CONVERTIBLE_FINDING, UNCONVERTED_AND_JUDGE_VIEW):
        return "\n".join([
            f"### Escalated: {why}",
            "",
            f"To go on: {way_out(unit, reason_code)}. The retry is also the label `{label}` on this merge request, "
            "after the feedback is pushed.",
        ])  # fmt: skip
    if phase == "escalated" and reason_code == JUDGE_VIEW_REJECTED:
        return f"### Escalated: {why}\n\nTo go on: {way_out(unit, reason_code)}."
    if phase == "escalated":
        kind = "feedback" if feedback else "fix"
        return "\n".join([
            f"### Escalated: {why}",
            "",
            f"To go on after reading `verification.md`, a member adds the label `{label}` to this merge request (one "
            f"more {kind} round per label event), or runs {command}.",
        ])  # fmt: skip
    return "\n".join([
        f"### Halted: {why}",
        "",
        f"To continue, a member adds the label `{label}` to this merge request, or runs {command}.",
    ])  # fmt: skip


def abandoned_section(unit: str, restart_label: str) -> str:
    """The sticky-note section of a unit whose merge request a person closed without a merge (L4-OPS-009)."""
    return "\n".join([
        "### Abandoned: the merge request was closed without a merge",
        "",
        f"To start the unit over, a member adds the label {restart_label} to this merge request, or runs "
        f"l4 restart --unit {unit} --reason TEXT.",
    ])  # fmt: skip


def resume_refused_note(refused: Mapping[str, str]) -> str:
    """The sticky-note section of the operator labels (`l4:retry`, `l4:resume`, `l4:restart`) the sweep did not honour:
    one line per label event, so the same event is never said twice (M1.11, L4-SEC-004, L4-OPS-008). The header keeps
    its old text, which the runbook names."""
    lines = [f"- `{signal}`: {why}" for signal, why in refused.items()]
    return "\n".join(["### The `l4:resume` label was not honoured", "", *lines])
