"""A unit that an older harness left in `awaiting_human` on a NEEDS_HUMAN round without verdict questions
(SPEC L4-VER-013, SCN-VER-47): nobody can answer a question that was never asked, so the next run asks it.

The questions come from the round's stored `verdict.json` (the judge-only blocker and major findings, the criteria
that were `needs_human` or `disputed`, the holds), through the same `raise_verdict_questions` as a fresh NEEDS_HUMAN,
so ids, format and ledger events are the same. A round that stored nothing to ask about (a judge that failed without
findings, or no `verdict.json`) gets one hold, "re-verify?": its answer, whichever it is, sends the unit back to
`verifying`, where the judge is called again. No implementer step and no judge call happens here.

The stored record is data from the branch: one that no current harness can read (a finding without a severity, a
gate with unknown keys, a hold that is not text) is treated as a round that stored nothing, never as a crash of every
later run.
"""

import logging
from collections.abc import Sequence

from l4.services import HookContext
from l4.specs.questions import QUESTIONS_FILENAME, QuestionsFile
from l4.verifier.evidence import read_verdict, restore_round
from l4.verifier.types import CriterionEvidence, CriterionOutcome, Finding
from l4.verifier.verdicts import raise_verdict_questions

log = logging.getLogger("l4.verify")
# what reading a malformed record raises; `raise_verdict_questions` writes nothing before its batch is rendered
_UNREADABLE = (KeyError, TypeError, ValueError, AttributeError)


def reverify_hold(round_no: int) -> str:
    return (
        f"Round {round_no} ended NEEDS_HUMAN under an earlier harness version and left nothing to answer: "
        "re-verify the unit?"
    )


def _outcomes(stored: dict) -> list[CriterionOutcome]:
    return [
        CriterionOutcome(str(c["id"]), str(c.get("alias", "")), c["result"], c.get("judge"), str(c.get("reason", "")))
        for c in stored.get("criteria", [])
        if isinstance(c, dict) and "id" in c and "result" in c
    ]


def raise_legacy_verdicts(ctx: HookContext, round_no: int, consumed: Sequence[str]) -> list[str]:
    """The ids of the verdict questions raised for `round_no`, each with its `question.raised{kind: verdict, round}`."""
    from l4.verifier.fixloop import family_of  # imports the services: kept out of the planner's import chain

    s = ctx.services
    stored = read_verdict(s.ref.path, round_no)
    criteria = family_of(ctx).criteria(s.ref)
    existing = QuestionsFile.load(s.ref.path / QUESTIONS_FILENAME)

    def raise_(
        outcomes: Sequence[CriterionOutcome],
        findings: Sequence[Finding],
        trace: Sequence[CriterionEvidence],
        held: Sequence[str],
    ) -> list[str]:
        return raise_verdict_questions(
            s.ref.path, s.ref.name, outcomes=outcomes, criteria=criteria, trace=trace, findings=findings,
            existing=existing, consumed=consumed, ledger=s.ledger, round_no=round_no, redactor=s.app.redactor,
            holds=held,
        )  # fmt: skip

    if stored is not None:
        try:
            restored = restore_round(stored, s.ref.id, round_no)
            asked = raise_(_outcomes(stored), restored.findings, restored.trace, restored.holds)
        except _UNREADABLE as exc:
            log.warning(
                "%s: round %d's verdict.json cannot be read (%s: %s): asking to re-verify",
                s.ref.id, round_no, type(exc).__name__, str(exc)[:200],
            )  # fmt: skip
            asked = []
        if asked:
            return asked
    return raise_([], [], [], [reverify_hold(round_no)])
