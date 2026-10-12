"""What a person sees of each item of `feedback.md` (L4-FBK-011, design D12): the file says draft, submitted and
withdrawn and whether the item is valid; the fold says what the harness did (taken, waiting, addressed, not addressed,
invalid). The fold wins for the harness's states. The sticky note and `l4 status` read the same view."""

from dataclasses import dataclass

from l4.specs.feedback import FeedbackFile, FeedbackStatus, content_sha256, problems
from l4.state.fold import FeedbackState, UnitState

SHORT_SHA = 10
STATES = ("draft", "submitted", "taken", "waiting", "addressed", "not_addressed", "invalid", "withdrawn")
_WAIT_REASONS = {"fix_unit_full": "fix unit full", "follow_up_open": "follow-up open"}


@dataclass(frozen=True)
class ItemView:
    id: str
    kind: str
    place: str | None  # the first *Where* line
    state: str  # one of STATES
    text: str  # the state in words, as the sticky note says it


def _of_harness(fs: FeedbackState, current_sha: str) -> tuple[str, str] | None:
    """The state the ledger gives an item, None when the ledger has nothing to say about it any more."""
    changed = fs.status in ("taken", "addressed", "not_addressed") and bool(fs.sha256) and fs.sha256 != current_sha
    if changed:  # D7: an edit after the take makes the item takeable again
        after = f"changed after round {fs.round}; " if fs.round is not None else "changed; "
        return "submitted", f"submitted ({after}waiting for the next round)"
    match fs.status:
        case "taken":
            return "taken", f"taken into {fs.fix_unit}" if fs.fix_unit else "taken"
        case "addressed":
            at = f" at {fs.sha[:SHORT_SHA]}" if fs.sha else ""
            return "addressed", f"addressed in round {fs.round}{at}"
        case "not_addressed":
            evidence = f": {fs.evidence}" if fs.evidence else ""
            return "not_addressed", f"not addressed in round {fs.round}{evidence}"
        case "waiting":
            why = _WAIT_REASONS.get(fs.reason or "", (fs.reason or "").replace("_", " "))
            return "waiting", "waiting for the next round" + (f" ({why})" if why else "")
        case "invalid":
            return "invalid", f"invalid: {fs.problem}" if fs.problem else "invalid"
    return None


def item_views(file: FeedbackFile | None, state: UnitState) -> list[ItemView]:
    views = []
    for item in file.items if file else ():
        kind = item.kind.value if item.kind else item.kind_text or "?"
        place = item.places[0].label if item.places else None
        found = problems(item)
        fs = state.feedback.get(item.id)
        if item.status is FeedbackStatus.WITHDRAWN:
            key, text = "withdrawn", "withdrawn"
        elif item.status is FeedbackStatus.DRAFT:
            key, text = "draft", "draft (not sent)"
        elif (fs is not None and (harness := _of_harness(fs, content_sha256(item)))
              and not (harness[0] == "invalid" and not found)):  # fmt: skip
            key, text = harness
        elif found:
            key, text = "invalid", "invalid: " + "; ".join(found)
        elif item.status is FeedbackStatus.TAKEN:
            key, text = "taken", "taken"
        elif item.status is FeedbackStatus.ADDRESSED:
            key, text = "addressed", "addressed"
        else:
            key, text = "submitted", "submitted (waiting for the next round)"
        views.append(ItemView(item.id, kind, place, key, text))
    return views


def counts(views: list[ItemView]) -> dict[str, int]:
    """Items per state, the states that have none left out."""
    return {name: n for name in STATES if (n := sum(v.state == name for v in views))}
