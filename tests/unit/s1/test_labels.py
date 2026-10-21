from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from l4.s1 import export
from l4.s1 import questions as q
from l4.s1 import records as r
from l4.s1.labels import HoldRef, labels_from_verdicts

from ._make import make_item

NOW = datetime(2026, 10, 4, tzinfo=UTC)


@dataclass
class Ev:
    type: str
    data: dict[str, Any] = field(default_factory=dict)


def verdict(target: str, decision: str, by: str = "human") -> Ev:
    return Ev("human.verdict", {"question": "Q-1", "target": target, "decision": decision, "by": by, "reason": "x"})


def test_scope_and_criterion_verdicts_label_and_coverage_hold_does_not():
    holds = {
        "H-aaaaaaaa": HoldRef("file1", "scope"),
        "H-bbbbbbbb": HoldRef("file2", "scope"),
        "H-cccccccc": HoldRef("func1", "coverage"),
    }
    criteria = {"C-11111111": "crit1", "C-22222222": "crit2"}
    events = [
        verdict("H-aaaaaaaa", "reject"),
        verdict("H-bbbbbbbb", "reject"),
        verdict("H-bbbbbbbb", "accept"),  # a later verdict on the same target wins
        verdict("H-cccccccc", "accept"),
        verdict("C-11111111", "accept", by="owner"),
        verdict("C-22222222", "reject"),
        verdict("F-33333333", "accept"),  # a finding: not ground truth for any set
        verdict("H-dddddddd", "accept"),  # a hold that is gone
        Ev("gate.finished", {"target": "H-aaaaaaaa", "decision": "accept"}),
    ]
    got = {lab.item_key: lab for lab in labels_from_verdicts(events, holds, criteria, now=NOW)}
    assert set(got) == {"file1", "file2", "crit1", "crit2"}  # no label for the coverage hold
    assert (got["file1"].truth, got["file1"].label) == ({"relevant": False}, "out_of_scope")
    assert (got["file2"].truth, got["file2"].label) == ({"relevant": True}, "relevant")
    assert got["crit1"].truth == {"satisfied": True} and got["crit1"].by == "owner"
    assert got["crit2"].truth == {"satisfied": False}
    assert {lab.source for lab in got.values()} == {"human:verdict"} and all(
        lab.ts == "2026-10-04T00:00:00Z" for lab in got.values()
    )
    assert all(export.source_allowed(lab.source) for lab in got.values())


def test_a_reject_on_a_scope_hold_overrides_the_deterministic_label_in_the_export(tmp_path):
    item = make_item("file1", set_name=q.FILE_RELEVANT, truth={"relevant": True, "named": False})
    (label,) = labels_from_verdicts([verdict("H-aaaaaaaa", "reject")], {"H-aaaaaaaa": HoldRef("file1", "scope")}, {})
    path = tmp_path / "c.jsonl"
    r.append_records([path], [item, label])
    (row,) = export.ground_truth_rows([path]).rows
    assert row.expected == {"relevant": False, "unrelated": True, "relatedness": 0}
    assert "human_overrides_deterministic" in row.tags


def test_only_a_persons_verdicts_become_labels():  # SCN-DLG-31
    holds = {"H-aaaaaaaa": HoldRef("file1", "scope")}
    criteria = {"C-11111111": "crit1", "C-22222222": "crit2", "C-33333333": "crit3", "C-44444444": "crit4"}
    events = [
        verdict("C-11111111", "accept", by="agent"),
        verdict("C-22222222", "reject", by="delegate"),
        verdict("H-aaaaaaaa", "reject", by="agent"),
        Ev("human.verdict", {"question": "Q-1", "target": "C-33333333", "decision": "accept"}),  # no `by`: a person
        verdict("C-44444444", "accept", by="human"),
    ]
    got = {lab.item_key for lab in labels_from_verdicts(events, holds, criteria, now=NOW)}
    assert got == {"crit3", "crit4"}


def test_a_later_agent_verdict_does_not_leave_the_earlier_persons_label():
    events = [verdict("C-11111111", "accept", by="human"), verdict("C-11111111", "reject", by="agent")]
    assert labels_from_verdicts(events, {}, {"C-11111111": "crit1"}, now=NOW) == []
