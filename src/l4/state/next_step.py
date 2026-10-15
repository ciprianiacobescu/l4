"""What `l4 status` says about a unit that waits (L4-OPS-006, design D6): the REASON of the table and the one `Next:`
step that moves the unit.

Both are pure functions of the planner's `UnitFacts`, the same facts `l4 plan` reads, so the two commands cannot
disagree. The planner imports `l4.state.status`, so the facts are only named here for the type checker.
"""

from typing import TYPE_CHECKING

from l4.state.lifecycle import Phase

if TYPE_CHECKING:
    from l4.planner import UnitFacts

CONTINUES = "nothing: the harness continues at the next run"
RUNBOOK_CORRUPT = "see docs/runbook.md section 7.9"
CORRUPT_PHASE = "corrupt"  # `l4.state.status.CORRUPT_PHASE`: a status value, not a lifecycle phase
_STOPPED = (Phase.HALTED.value, Phase.ESCALATED.value)


def _unique(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for group in groups for item in group))


def open_questions(facts: "UnitFacts") -> tuple[str, ...]:
    """The ids a person has to answer: the blocking questions and the verdict questions that are still open."""
    return _unique(facts.open_blocking_questions, facts.verdicts_open)


def reason(facts: "UnitFacts") -> str | None:
    """The cause the table shows, whole (the table cuts it): `halt_detail` for a stopped unit, the open question ids
    for `awaiting_human`, the fix unit's open questions for `fixing`, `until <retry_after>` for `waiting_capacity`,
    the ledger fault for `corrupt`; None for every other phase."""
    phase = facts.phase
    if phase in _STOPPED:
        return facts.halt_detail
    if phase == Phase.AWAITING_HUMAN.value:
        return ", ".join(open_questions(facts) or facts.verdicts_invalid) or None
    if phase == Phase.FIXING.value and facts.fix_questions_open:
        return f"fix unit questions: {', '.join(facts.fix_questions_open)}"
    if phase == Phase.WAITING_CAPACITY.value and facts.retry_after:
        return f"until {facts.retry_after}"
    if phase == Phase.IN_REVIEW.value and facts.misdirected:
        return facts.misdirected  # L4-YOLO-007: the merge went to another branch, so the unit is not merged
    if phase == CORRUPT_PHASE:
        return facts.corrupt
    return None


def _answer_step(facts: "UnitFacts", branch: str, questions_path: str) -> str:
    """The `awaiting_human` step: say what is wrong with an answer before asking for one."""
    where = f"{questions_path} on {branch}"
    if facts.verdicts_invalid:
        ids = ", ".join(facts.verdicts_invalid)
        return f"fix the answer of {ids} in {where}: start it with accept or reject, then push"
    if facts.verdicts_dismissed:
        ids = ", ".join(facts.verdicts_dismissed)
        return (
            f"answer {ids} in {where}: a verdict question cannot be dismissed, "
            "start the answer with accept or reject, then push"
        )
    ids = open_questions(facts)
    if not ids:
        return CONTINUES  # the answers are in: the next run reads them
    draft = f" ({', '.join(facts.drafts)}: the answer is written but Status is still open)" if facts.drafts else ""
    return f"answer {', '.join(ids)} in {where} (Status answered), then push{draft}"


def next_step(facts: "UnitFacts", *, branch: str, questions_path: str) -> str:
    """The one command or action that moves the unit. `branch` and `questions_path` say where an answer goes. The
    command stays bare (`l4 retry --unit U --reason TEXT`); the label that does the same is `label_for`."""
    phase, unit = facts.phase, facts.unit
    if phase in _STOPPED:
        return f"l4 retry --unit {unit} --reason TEXT"
    if phase == Phase.ABANDONED.value:
        return f"l4 restart --unit {unit} --reason TEXT"
    if phase == Phase.AWAITING_HUMAN.value:
        return _answer_step(facts, branch, questions_path)
    if phase == Phase.WAITING_CAPACITY.value:
        until = f"until {facts.retry_after}" if facts.retry_after else "for the cool-down to end"
        return f"wait {until}, or l4 retry --unit {unit} --reason TEXT"
    if phase == Phase.IN_REVIEW.value:
        if facts.misdirected:
            return f"the PR {facts.misdirected}: move the change to the base, or l4 restart --unit {unit} --reason TEXT"
        return "review and merge the PR, or ask for changes with l4 feedback add"
    if phase == CORRUPT_PHASE:
        return RUNBOOK_CORRUPT
    if phase == Phase.MERGED.value:
        if not facts.follow_up_items:
            return "nothing"
        ids = ", ".join(facts.follow_up_items)
        if facts.follow_up_open:
            return f"nothing: feedback {ids} waits for the open follow-up {facts.follow_up_open}"
        return f"nothing: feedback {ids} becomes a follow-up unit at the next run"
    return CONTINUES


def label_for(facts: "UnitFacts", prefix: str) -> str | None:
    """The forge label that does what `next_step` names, for the units a label moves (D2, D4); None for the others."""
    if facts.phase in _STOPPED:
        return f"{prefix}retry"
    if facts.phase == Phase.ABANDONED.value:
        return f"{prefix}restart"
    return None
