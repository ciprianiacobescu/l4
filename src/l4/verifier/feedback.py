"""Step 0 reads `feedback.md` (SPEC 6.3, L4-FBK-004, L4-FBK-007; design D3, D7).

`scan_feedback` is pure: the unit's `FeedbackFile` and its folded ledger in, the takeable items and the events step 0
records out. A takeable item is valid, not withdrawn, and either `submitted` or `taken`/`addressed` with content that
hashes differently from the last `feedback.taken`. Each becomes a deterministic blocking `Finding` with source
`"feedback"`, so the round fails at step 0 like a red repository CI job and the fix unit of L4-VER-006 is written.

The take itself (`feedback.taken`, Status `taken`, the Outcome line) happens in `fixloop.after_verdict`, once the fix
unit exists. `pending_feedback` is what a later round reads: the items taken and not yet judged.
"""

from dataclasses import dataclass
from typing import Any

from l4.specs.feedback import FeedbackFile, FeedbackItem, FeedbackStatus, content_sha256, problems
from l4.state.fold import UnitState
from l4.verifier.types import FeedbackRef, Finding, Severity

MAX_REQUEST_CHARS = 1200  # the person's text, whole up to this (L4-FBK-004)
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
    return [i for i in file.items if (s := state.feedback.get(i.id)) is not None and s.status == "taken"]
