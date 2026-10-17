"""One verdict from the replies of a diff judged in parts (L4-VER-042).

Per criterion a `fail` of any part wins, else a `pass`, else a `not_verifiable`, else `insufficient_evidence`: a part
that does not show the code answers `insufficient_evidence` by rule, so a worst-first merge could never pass a unit
over the cap. A `fail` must cite code of its part and, without a reproduced counterexample, is `needs_human` in
aggregation, so a wrong part `fail` costs a question, never a FAIL. A feedback, accepted or satisfied item is true when
a part says true and no part says false with evidence other than `not in this part`.
"""

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from l4.verifier.aggregate import pick_verdicts
from l4.verifier.judge import NOT_IN_PART, CriterionVerdict, JudgeVerdict, TestAdequacy

_ORDER = ("fail", "pass", "not_verifiable", "insufficient_evidence")
T = TypeVar("T")


def _seen_elsewhere(evidence: str) -> bool:
    """The evidence of a part that did not show the item's code."""
    return evidence.strip().lower().startswith(NOT_IN_PART)


def _criteria(replies: Sequence[JudgeVerdict]) -> list[CriterionVerdict]:
    per_part = [pick_verdicts(r) for r in replies]
    ids = list(dict.fromkeys(i for part in per_part for i in part))
    merged = []
    for cid in ids:
        answers = [part[cid] for part in per_part if cid in part]
        merged.append(next(a for word in _ORDER for a in answers if a.verdict == word))
    return merged


def _adequacy(replies: Sequence[JudgeVerdict]) -> list[TestAdequacy]:
    found: dict[tuple[str, str], TestAdequacy] = {}
    for reply in replies:
        for item in reply.test_adequacy:
            key = (item.test, item.criterion)
            if key not in found or (found[key].adequate and not item.adequate):
                found[key] = item
    return list(found.values())


def _findings(replies: Sequence[JudgeVerdict]) -> list[Any]:
    found: dict[tuple[str, str | None, str], Any] = {}
    for reply in replies:
        for item in reply.findings:
            found.setdefault((item.severity, item.criterion, " ".join(item.title.lower().split())), item)
    return list(found.values())


def _assumptions(replies: Sequence[JudgeVerdict]) -> list[str]:
    """The parts' first, then their second, …: the first three distinct strings (repeats fill up when fewer remain)."""
    turns = [text for rank in range(3) for r in replies for text in r.riskiest_assumptions[rank : rank + 1]]
    chosen = list(dict.fromkeys(turns))[:3]
    for text in turns:
        if len(chosen) == 3:
            break
        chosen.append(text)
    return chosen


def _items(lists: Sequence[list[T] | None], key: Callable[[T], str], flag: str) -> list[T] | None:
    """Merge the answers per item: true when a part says true and none says false with evidence of its own."""
    present = [items for items in lists if items is not None]
    if not present:
        return None
    ids = list(dict.fromkeys(key(i) for items in present for i in items))
    merged = []
    for item_id in ids:
        answers = [i for items in present for i in items if key(i) == item_id]
        real_false = [a for a in answers if not getattr(a, flag) and not _seen_elsewhere(a.evidence)]  # type: ignore[attr-defined]
        trues = [a for a in answers if getattr(a, flag)]
        merged.append(trues[0] if trues and not real_false else (real_false or answers)[0])
    return merged


def merge_part_verdicts(replies: Sequence[JudgeVerdict]) -> JudgeVerdict:
    """The verdict of a diff judged in parts; one reply comes back unchanged."""
    if len(replies) == 1:
        return replies[0]
    return JudgeVerdict(
        criteria=_criteria(replies),
        test_adequacy=_adequacy(replies),
        findings=_findings(replies),
        riskiest_assumptions=_assumptions(replies),
        feedback=_items([r.feedback for r in replies], lambda a: a.id, "addressed"),
        accepted=_items([r.accepted for r in replies], lambda a: a.id, "addressed"),
        satisfied=_items([r.satisfied for r in replies], lambda a: a.task, "holds"),
    )
