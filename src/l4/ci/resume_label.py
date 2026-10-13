"""Who may resume a halted or escalated unit by label (SPEC L4-SEC-004, L4-CI-004, SCN-RES-01), pure.

The `l4:resume` label is a signal only when the forge itself says a member set it: the latest `add` event of the label
names the user (`LabelEvent.user_id`), and that user must have at least Developer access (30) and must not be the
token's own user. The project's bot is a Developer too (probed live, level 30), so a level check alone would accept
the harness's own label; it is excluded by id. One label event is one resume: its id (`label:<id>`) is recorded in
`unit.resumed{signal}` and an id already recorded is never acted on again.
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass

from l4.forge.base import LabelEvent

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
) -> ResumeSignal | Refusal | None:
    """`labels` are the MR's labels now, `events` its label history. None: no signal (the label is not on the MR, no
    event set it, or its event was already acted on). A refusal names why the latest event does not count."""
    if label not in labels:
        return None
    history = sorted((e for e in events if e.label == label), key=lambda e: e.id)
    if not history or history[-1].action != "add":
        return None
    event = history[-1]
    signal = f"label:{event.id}"
    if signal in consumed:
        return None
    if event.user_id is None:
        return Refusal(event.id, signal, "the forge does not say who set the label")
    if own_id is None:
        return Refusal(event.id, signal, "the harness cannot tell which user is its own, so no label is honoured")
    if event.user_id == own_id:
        return Refusal(event.id, signal, "the label was set by the harness's own user")
    level = access(event.user_id)
    if level is None:
        return Refusal(event.id, signal, "the label was set by a user who is not a member of the project")
    if level < DEVELOPER:
        return Refusal(event.id, signal, f"the label was set by a member below Developer access (level {level})")
    return ResumeSignal(event.id, signal, event.user_id, level)


def halted_section(phase: str, reason: str, unit: str, label: str, *, feedback: bool = False) -> str:
    """The sticky-note section of a unit that stopped (SPEC L4-ARC-002, L4-CLI-002): why, and what continues it. The
    halting run writes it with its last mirror sync, and the sweep writes it again around a refusal. `feedback`: the
    unit is escalated at the feedback limit (L4-FBK-006), where the label and `l4 resume` extend the feedback rounds,
    not the fix rounds."""
    why = " ".join(reason.split())[:300]
    if phase == "escalated" and feedback:
        return "\n".join([
            f"### Escalated: {why}",
            "",
            f"To go on after reading `verification.md`, a member adds the label `{label}` to this merge request (one "
            f"more feedback round per label event), or runs `l4 resume --unit {unit} --reason TEXT "
            "--extend-feedback-rounds N`.",
        ])  # fmt: skip
    if phase == "escalated":
        return "\n".join([
            f"### Escalated: {why}",
            "",
            f"To go on after reading `verification.md`, a member adds the label `{label}` to this merge request (one "
            f"more fix round per label event), or runs `l4 resume --unit {unit} --reason TEXT --extend-fix-rounds N`.",
        ])  # fmt: skip
    return "\n".join([
        f"### Halted: {why}",
        "",
        f"To continue, a member adds the label `{label}` to this merge request, or runs "
        f"`l4 resume --unit {unit} --reason TEXT`.",
    ])  # fmt: skip


def resume_refused_note(refused: Mapping[str, str]) -> str:
    """The sticky-note section of the `l4:resume` labels the sweep did not honour: one line per label event, so the
    same event is never said twice (M1.11, L4-SEC-004)."""
    lines = [f"- `{signal}`: {why}" for signal, why in refused.items()]
    return "\n".join(["### The `l4:resume` label was not honoured", "", *lines])
