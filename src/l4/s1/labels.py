"""Human labels from verdicts (verifier 4.3, human outcome): what a person decided becomes ground truth.

`labels_from_verdicts` turns m13's `human.verdict` events into `label` records:
* `accept` / `reject` on a scope hold: the file was `relevant` / `out_of_scope`;
* `accept` / `reject` on a criterion: `satisfied` true / false;
* nothing for a coverage hold: there `accept` means "acceptable", not "covered".

Reads no engine answer and imports no engine code.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from l4.s1.records import LabelRecord

SOURCE = "human:verdict"


class VerdictEvent(Protocol):
    type: str
    data: Mapping[str, Any]


@dataclass(frozen=True)
class HoldRef:
    item_key: str  # the `file-relevant` or `change-covered` item the hold was about
    kind: Literal["scope", "coverage"]


def labels_from_verdicts(
    events: Iterable[VerdictEvent],
    hold_map: Mapping[str, HoldRef],
    criterion_map: Mapping[str, str],
    *,
    now: datetime | None = None,
) -> list[LabelRecord]:
    """`hold_map`: hold target (`H-` + 8 hex) to its item; `criterion_map`: criterion target (`C-` + 8 hex) to its
    item key. The latest verdict per target wins. A target in neither map yields nothing (findings, gone holds)."""
    latest: dict[str, Mapping[str, Any]] = {}
    for event in events:
        if event.type == "human.verdict" and event.data.get("decision") in ("accept", "reject"):
            latest[str(event.data.get("target"))] = event.data
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: list[LabelRecord] = []
    for target, data in sorted(latest.items()):
        accept = data["decision"] == "accept"
        by = str(data.get("by") or "human")
        if target in hold_map:
            ref = hold_map[target]
            if ref.kind == "scope":
                name = "relevant" if accept else "out_of_scope"
                out.append(LabelRecord(ref.item_key, {"relevant": accept}, name, SOURCE, by, stamp))
        elif target in criterion_map:
            name = "satisfied" if accept else "not_satisfied"
            out.append(LabelRecord(criterion_map[target], {"satisfied": accept}, name, SOURCE, by, stamp))
    return out
