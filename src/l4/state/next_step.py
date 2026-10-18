"""What `l4 status` says about a unit that waits (L4-OPS-006, design D6): the REASON of the table and the one `Next:`
step that moves the unit.

Both are pure functions of the planner's `UnitFacts`, the same facts `l4 plan` reads, so the two commands cannot
disagree. The planner imports `l4.state.status`, so the facts are only named here for the type checker.
"""

from typing import TYPE_CHECKING

from l4.state.lifecycle import Phase

if TYPE_CHECKING:
    from l4.planner import UnitFacts

NO_CONVERTIBLE_FINDING = "no_convertible_finding"  # `phase.changed{to: escalated, reason}` of the fix loop (L4-OPS-022)
JUDGE_VIEW_REJECTED = "judge_view_rejected"  # a person rejected a hold on the judge's view of the diff (L4-VER-044)
UNCONVERTED_AND_JUDGE_VIEW = "no_convertible_finding_and_judge_view_rejected"  # both causes in one round (L4-VER-044)
CONTINUES = "nothing: the harness continues at the next run"
RUNBOOK_CORRUPT = "see docs/runbook.md section 7.9"
CORRUPT_PHASE = "corrupt"  # `l4.state.status.CORRUPT_PHASE`: a status value, not a lifecycle phase
_STOPPED = (Phase.HALTED.value, Phase.ESCALATED.value)


def feedback_way_out(unit: str) -> str:
    """The step of a unit escalated with `no_convertible_finding` (L4-OPS-022): the round failed on a human finding that
    no fix task can be derived from, and a retry alone repeats the same verdict. The feedback is the concrete fix."""
    return (
        "a retry alone repeats the same verdict; first give the fix the human's finding asks for as feedback: "
        f"l4 feedback add --unit {unit} --kind behaviour --when ... --then ... --text ... "
        f"(then the git lines it prints), then l4 retry --unit {unit} --reason TEXT"
    )


def judge_view_way_out(unit: str) -> str:
    """The step of a unit escalated with `judge_view_rejected` (L4-VER-044): a fix unit cannot shrink the diff the judge
    could not see, so the change is split, or a person who checked the files replaces the answer with an accept."""
    return (
        "a fix unit cannot shrink the diff the judge could not see; split the change into smaller units (then "
        f"l4 restart --unit {unit} --reason TEXT), or, once you checked the files the hold names, replace the answer: "
        f'l4 questions answer Q-NNN --unit {unit} --text "accept ..." --replace, then l4 retry --unit {unit} '
        "--reason TEXT"
    )


def way_out(unit: str, halt_reason: str | None) -> str | None:
    """The unit's own way out of an escalation: `feedback_way_out` for `no_convertible_finding`, `judge_view_way_out`
    for `judge_view_rejected`, None for every other reason."""
    if halt_reason == NO_CONVERTIBLE_FINDING:
        return feedback_way_out(unit)
    if halt_reason == JUDGE_VIEW_REJECTED:
        return judge_view_way_out(unit)
    if halt_reason == UNCONVERTED_AND_JUDGE_VIEW:  # each cause keeps its own way out
        return (
            f"two causes. For the finding no fix task can be derived from: {feedback_way_out(unit)}. "
            f"For the hold on the judge's view: {judge_view_way_out(unit)}"
        )
    return None


def _unique(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for group in groups for item in group))


def open_questions(facts: "UnitFacts") -> tuple[str, ...]:
    """The ids a person has to answer: the blocking questions and the verdict questions that are still open."""
    return _unique(facts.open_blocking_questions, facts.verdicts_open)


def _harness_reason(qid: str, title: str, why: str) -> str:
    return f"{qid}: {title}" + (f" ({why})" if why else "")


def reason(facts: "UnitFacts") -> str | None:
    """The cause the table shows, whole (the table cuts it): `halt_detail` for a stopped unit, the open question ids
    for `awaiting_human`, the fix unit's open questions for `fixing`, `until <retry_after>` for `waiting_capacity`,
    the ledger fault for `corrupt`; None for every other phase."""
    phase = facts.phase
    if phase in _STOPPED:
        return facts.halt_detail
    if phase == Phase.AWAITING_HUMAN.value:
        harness = {qid: (title, why) for qid, title, why in facts.harness_open}
        ids = open_questions(facts) or facts.verdicts_invalid
        if any(qid in harness for qid in ids):  # a check L4 could not decide: name it and its cause (L4-OPS-006)
            return "; ".join(_harness_reason(qid, *harness[qid]) if qid in harness else qid for qid in ids)
        return ", ".join(ids) or None
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
    if facts.harness_invalid:
        ids = ", ".join(facts.harness_invalid)
        return f"fix the answer of {ids} in {where}: start it with accept or retry, then push"
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
    harness = [qid for qid, _, _ in facts.harness_open if qid in ids]
    if harness:
        answers = "; ".join(
            f'l4 questions answer {qid} --unit {facts.unit} --text "accept: <why>" (takes the claim on the evidence of '
            f'the real run) or --text "retry: <note>" (runs the check again)'
            for qid in harness
        )
        others = [qid for qid in ids if qid not in harness]
        rest = f"; answer {', '.join(others)} in {where} (Status answered), then push" if others else ""
        return f"{answers}{rest}"
    draft = f" ({', '.join(facts.drafts)}: the answer is written but Status is still open)" if facts.drafts else ""
    return f"answer {', '.join(ids)} in {where} (Status answered), then push{draft}"


def next_step(facts: "UnitFacts", *, branch: str, questions_path: str) -> str:
    """The one command or action that moves the unit. `branch` and `questions_path` say where an answer goes. The
    command stays bare (`l4 retry --unit U --reason TEXT`); the label that does the same is `label_for`."""
    phase, unit = facts.phase, facts.unit
    if phase == Phase.ESCALATED.value and (own := way_out(unit, facts.halt_reason)) is not None:
        return own
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
