"""Step 0 reads `feedback.md` (SPEC 6.3, L4-FBK-004, L4-FBK-007; design D3, D7).

`scan_feedback` is pure: the unit's `FeedbackFile` and its folded ledger in, the takeable items and the events step 0
records out. A takeable item is valid, not withdrawn, and either `submitted` or `taken`/`addressed` with content that
hashes differently from the last `feedback.taken`. Each becomes a deterministic blocking `Finding` with source
`"feedback"`, so the round fails at step 0 like a red repository CI job and the fix unit of L4-VER-006 is written.

The take itself (`feedback.taken`, Status `taken`, the Outcome line) happens in `fixloop.after_verdict`, once the fix
unit exists. `pending_feedback` is what a later round reads: the items taken and not yet judged.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from l4.redact import Redactor
from l4.specs.feedback import FeedbackFile, FeedbackItem, FeedbackStatus, content_sha256, problems
from l4.state.fold import UnitState
from l4.verifier.judge import FeedbackAnswer
from l4.verifier.types import FeedbackOutcome, FeedbackRef, Finding, Severity, VerifyResult

MAX_REQUEST_CHARS = 1200  # the person's text, whole up to this (L4-FBK-004)
MAX_EVIDENCE_CHARS = 300  # the judge's evidence in a title, an Outcome line and an event
NOT_ANSWERED = "not answered"
NO_STATUS = "no Status line"
Event = tuple[str, dict[str, Any]]


@dataclass(frozen=True)
class FeedbackScan:
    takeable: tuple[FeedbackItem, ...] = ()
    events: tuple[Event, ...] = ()  # `feedback.changed|invalid|withdrawn`, each once (not recorded already)


def _flat(text: str, limit: int) -> str:
    one = " ".join(text.split())
    return one if len(one) <= limit else one[: limit - 3].rstrip() + "..."


def scan_feedback(file: FeedbackFile | None, state: UnitState) -> FeedbackScan:
    takeable: list[FeedbackItem] = []
    events: list[Event] = []
    for copy in file.duplicates if file is not None else ():
        problem = f"duplicate id {copy.id}"  # the first section is the item; the copy is never taken
        if (known := state.feedback.get(copy.id)) is None or known.duplicate != problem:
            event = ("feedback.invalid", {"id": copy.id, "problem": problem, "duplicate": True})
            if event not in events:
                events.append(event)
    for item in file.items if file is not None else ():
        known = state.feedback.get(item.id)
        was_taken = known is not None and known.sha256 is not None
        if item.status is FeedbackStatus.WITHDRAWN:
            if was_taken and known is not None and known.status != "withdrawn":
                events.append(("feedback.withdrawn", {"id": item.id}))
            continue
        digest = content_sha256(item)
        if item.status is FeedbackStatus.SUBMITTED:
            candidate = True
        elif item.status in (FeedbackStatus.TAKEN, FeedbackStatus.ADDRESSED):
            # no take in the ledger: nothing to compare with (a Status written by hand, or a follow-up's take)
            candidate = was_taken and known is not None and digest != known.sha256
        else:
            candidate = False
        if not candidate:
            continue
        if found := problems(item):
            problem = "; ".join(found)
            if known is None or known.status != "invalid" or known.problem != problem:
                events.append(("feedback.invalid", {"id": item.id, "problem": problem}))
            continue
        if known is not None and was_taken and digest not in (known.sha256, known.changed_sha256):
            events.append(("feedback.changed", {"id": item.id, "previous_sha256": known.sha256, "sha256": digest}))
        takeable.append(item)
    return FeedbackScan(tuple(takeable), tuple(events))


def feedback_ref(item: FeedbackItem) -> FeedbackRef:
    return FeedbackRef(
        item.id, item.kind.value if item.kind else item.kind_text, item.title, item.text, item.by,
        tuple(p.label for p in item.places), item.env, item.when, item.then, item.code, content_sha256(item),
    )  # fmt: skip


def feedback_findings(scan: FeedbackScan) -> list[Finding]:
    """One blocking major finding per takeable item: the title names the item, the detail is the person's text."""
    found = []
    for item in scan.takeable:
        ref = feedback_ref(item)
        title = f"Feedback {item.id} ({ref.kind}): {_flat(item.title, 120)}"
        found.append(Finding(Severity.MAJOR, title, _flat(item.text, MAX_REQUEST_CHARS), "feedback", feedback=ref))
    return found


def pending_feedback(state: UnitState, file: FeedbackFile | None) -> list[FeedbackItem]:
    """The items of `file` that the ledger shows taken and not yet addressed or judged not addressed (the judge check
    of L4-FBK-007 builds its `<l4:data kind="feedback">` block from these)."""
    if file is None:
        return []
    return [
        i
        for i in file.items
        if i.status is not FeedbackStatus.WITHDRAWN  # a withdrawal not yet recorded by step 0 stops the check too
        and (s := state.feedback.get(i.id)) is not None
        and s.status == "taken"
    ]


def contains_name(name: str, text: str) -> bool:
    """`name` as a whole identifier in `text`: `PACK_ROUNDING` is not in `PACK_ROUNDING_MODE`."""
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text) is not None


def _answer(replies: Sequence[Sequence[FeedbackAnswer]], fid: str) -> tuple[bool, str]:
    """(every judge said yes, the evidence): the first `false` speaks, else a missing answer, else the first `true`."""
    evidence: list[str] = []
    for reply in replies:
        mine = [a for a in reply if a.id == fid]
        if not mine:
            return False, NOT_ANSWERED
        if (no := next((a for a in mine if not a.addressed), None)) is not None:
            return False, _flat(no.evidence, MAX_EVIDENCE_CHARS) or NOT_ANSWERED
        evidence.append(_flat(mine[0].evidence, MAX_EVIDENCE_CHARS))
    if not replies:
        return False, NOT_ANSWERED
    return True, next((e for e in evidence if e), "addressed")


def decide_feedback(
    asked: Sequence[FeedbackRef], replies: Sequence[Sequence[FeedbackAnswer]], has_name: Callable[[str], bool]
) -> list[FeedbackOutcome]:
    """L4-FBK-007: an item is addressed when every judge that got the block says so (a missing answer is `false`,
    "not answered"); a `config` item also needs its variable in the changed non-test code (`has_name`), and without it
    no judge answer can close it."""
    found = []
    for ref in asked:
        addressed, evidence = _answer(replies, ref.id)
        if ref.kind == "config" and ref.env and not has_name(ref.env):
            addressed, evidence = False, f"{ref.env} not found in the changed code"
        found.append(FeedbackOutcome(ref.id, addressed, evidence))
    return found


def not_addressed_findings(outcomes: Sequence[FeedbackOutcome], asked: Sequence[FeedbackRef]) -> list[Finding]:
    """One blocking major finding per item that was not addressed. It carries the item, so the round fails into the
    next feedback fix unit like a step 0 finding does."""
    refs = {r.id: r for r in asked}
    return [
        Finding(
            Severity.MAJOR, f"{o.id} not addressed: {o.evidence}",
            f"Judged not addressed: {o.evidence}\n\n{_flat(refs[o.id].text, MAX_REQUEST_CHARS)}",
            "feedback", feedback=refs[o.id],
        )  # fmt: skip
        for o in outcomes
        if not o.addressed and o.id in refs
    ]


def record_no_status(ledger: Any, state: UnitState, ids: Sequence[str]) -> None:
    """`feedback.invalid{id, problem: "no Status line"}` for each id, once: an item whose Status line the person
    deleted cannot be written to (review #9). `ledger` has `append(type, **data)`."""
    for fid in ids:
        known = state.feedback.get(fid)
        if known is None or known.status != "invalid" or known.problem != NO_STATUS:
            ledger.append("feedback.invalid", id=fid, problem=NO_STATUS)


def apply_addressed(
    unit_dir: Path, result: VerifyResult, redactor: Redactor, *, skipped: list[str] | None = None
) -> list[Path]:
    """Status `addressed` and the Outcome line `Addressed in round N at <sha10>: <evidence>` for each item the round
    found addressed, in the parent's `feedback.md` (committed with the round's evidence). The paths written. An item
    with no Status line is skipped (its id goes to `skipped`): the harness's writes never raise."""
    done = [o for o in result.feedback_outcomes if o.addressed]
    file = FeedbackFile.load(unit_dir) if done else None
    if file is None:
        return []
    for outcome in done:
        if (item := file.get(outcome.id)) is not None and item.status_value is None:
            if skipped is not None:
                skipped.append(outcome.id)
        elif item is not None:
            line = f"Addressed in round {result.round} at {result.head_sha[:10]}: {outcome.evidence}"
            file = file.set_status(outcome.id, FeedbackStatus.ADDRESSED).set_outcome(
                outcome.id, line, redactor=redactor
            )
    file.save()
    assert file.path is not None
    return [file.path]
