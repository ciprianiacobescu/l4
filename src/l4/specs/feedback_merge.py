"""`feedback.md` merged per item id when a base merge conflicts in it (L4-FBK-012).

The base branch is `theirs`, the unit branch `ours`. The result is the union of the items by id. For an id both sides
hold, the person's content (title, kind, places, env, lesson, code, text, when/then and a Status the person set) comes
from the side that changed it since the merge base; when the unit branch changed it, or both did, from the unit
branch. The harness's spans (Status `taken` and `addressed`, the Outcome block, the index) come from the unit branch.
When ours holds every item and theirs adds none, the result is ours byte for byte. The same id holding a different
item on the two sides (no merge base to tell which one is older) is `Escalate`: it stays a conflict.
"""

from l4.specs.feedback import HARNESS_STATUSES, FeedbackFile, FeedbackItem, FeedbackStatus
from l4.specs.questions import Span, _eol, _splice
from l4.vcs.merge import Escalate


def _human(item: FeedbackItem) -> tuple:
    """What the person wrote. `taken` and `addressed` read as `submitted`: the harness moved it, not the person."""
    status = FeedbackStatus.SUBMITTED if item.status in HARNESS_STATUSES else item.status
    return (
        item.title, item.kind_text.lower(), item.places, item.env, item.lesson, item.by, item.code, item.when,
        item.then, item.text, status,
    )  # fmt: skip


def _adopt(ours: FeedbackFile, mine: FeedbackItem, theirs: FeedbackFile, other: FeedbackItem) -> bytes:
    """The base's section of the item, with the unit branch's Status (when it is the harness's and the person did
    not set another) and Outcome body."""
    origin = other.section.start
    edits: list[tuple[Span, bytes]] = []
    keep_status = mine.status in HARNESS_STATUSES and other.status in (FeedbackStatus.SUBMITTED, *HARNESS_STATUSES)
    if keep_status and mine.status_value is not None and other.status_value is not None:
        edits.append((_shift(other.status_value, origin), ours.data[mine.status_value.start : mine.status_value.end]))
    block = mine.outcome_block
    if block is not None and other.outcome_block is not None:
        body = other.outcome_block.body
        edits.append((_shift(body, origin), ours.data[block.body.start : block.body.end]))
    section = theirs.data[other.section.start : other.section.end]
    merged = _splice(section, edits)
    if block is not None and other.outcome_block is None:  # the base side has no Outcome block: bring ours
        eol = _eol(theirs.data)
        merged += eol + eol + ours.data[block.heading.start : block.body.end].rstrip(b"\r\n")
    return merged


def _shift(span: Span, origin: int) -> Span:
    return Span(span.start - origin, span.end - origin)


def merge_feedback(base: bytes | None, ours: bytes, theirs: bytes) -> bytes:
    mine, other = FeedbackFile.parse(ours), FeedbackFile.parse(theirs)
    ancestor = FeedbackFile.parse(base) if base is not None else None
    replace: list[tuple[Span, bytes]] = []
    appended: list[FeedbackItem] = []
    for theirs_item in other.items:
        ours_item = mine.get(theirs_item.id)
        if ours_item is None:
            appended.append(theirs_item)
            continue
        if _human(ours_item) == _human(theirs_item):
            continue  # the harness's spans are ours either way
        base_item = ancestor.get(theirs_item.id) if ancestor is not None else None
        if base_item is None:
            raise Escalate(f"{theirs_item.id} is a different item on the two sides")
        if _human(ours_item) != _human(base_item):
            continue  # the unit branch changed it (alone or with the base): ours
        replace.append((ours_item.section, _adopt(mine, ours_item, other, theirs_item)))
    if not replace and not appended:
        return ours
    data = _splice(ours, replace)
    eol = _eol(ours)
    for item in appended:
        if not data.endswith(b"\n"):
            data += eol
        data += eol + b"---" + eol + eol + theirs[item.section.start : item.section.end] + eol
    return FeedbackFile.parse(data).refresh_index().data
