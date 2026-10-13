"""Join line 29: what a person decided on a hold becomes a `label` record for the S1 data set.

`record_human_labels` runs in `verify_hook` right after `consume_verdicts`: for the verdicts recorded in this very
call it looks up the round that raised the question, builds the hold map from that round's evidence (`holds[].id`,
`.subjects`, and `items`: `<question set>|<subject>` -> item key) and appends the labels `labels_from_verdicts` gives.
A coverage hold gives none. S1 decides nothing: a failure here is logged and the round goes on.
"""

import logging
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any

from l4.s1 import questions as q
from l4.s1.labels import HoldRef, labels_from_verdicts
from l4.s1.records import append_records
from l4.state.ledger import LedgerEvent, read_ledger
from l4.verifier.evidence import read_verdict

log = logging.getLogger("l4.verify")

_SET_OF = {"scope": q.FILE_RELEVANT, "coverage": q.CHANGE_COVERED}


def hold_map(evidence: Mapping[str, Any]) -> dict[str, HoldRef]:
    """hold id -> the item the hold was about, from an `l4/evidence@1` object. A hold with no item (shadow was off in
    that round, an `unsafe` name, a hold about the run) is left out."""
    items = evidence.get("items") or {}
    out: dict[str, HoldRef] = {}
    for hold in evidence.get("holds") or []:
        kind = hold.get("kind")
        subjects = hold.get("subjects") or []
        if kind not in _SET_OF or not subjects:
            continue
        key = items.get(f"{_SET_OF[kind]}|{subjects[0]}")
        if key:
            out[str(hold["id"])] = HoldRef(str(key), kind)
    return out


def record_human_labels(unit_dir: Path, recorded: Collection[str], paths: Sequence[Path]) -> int:
    """Append the labels of the verdicts recorded for the question ids `recorded` to every file of `paths` (the
    runner's cache file and the job's artefact); returns how many."""
    if not recorded:
        return 0
    try:
        events = read_ledger(unit_dir).events
        rounds = {
            str(e.data.get("id")): e.data.get("round")
            for e in events
            if e.type == "question.raised" and e.data.get("kind") == "verdict"
        }
        fresh: dict[int, list[LedgerEvent]] = defaultdict(list)
        for e in events:
            round_no = rounds.get(str(e.data.get("question")))
            if e.type == "human.verdict" and str(e.data.get("question")) in recorded and isinstance(round_no, int):
                fresh[round_no].append(e)
        labels = []
        for round_no, verdicts in sorted(fresh.items()):
            stored = read_verdict(unit_dir, round_no)
            holds = hold_map((stored or {}).get("evidence") or {})
            labels += labels_from_verdicts(verdicts, holds, {})
        append_records(paths, labels)
        return len(labels)
    except Exception as exc:  # noqa: BLE001 - S1 decides nothing: its trouble stops nothing
        log.warning("human labels not recorded: %s", exc)
        return 0
