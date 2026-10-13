"""The export guard and the laya-evals data set (M16-G11, plan D1 and D8).

`ground_truth_rows` is the only door from the calibration files to training data. It reads `item` and `label`
records and nothing else: an `answer` record, that is anything an engine (Jev, Laya, a judge) said, is never parsed
here, and this module imports neither `score` nor `report` nor the System-One backend (an import-graph test).
A label source outside the allow-list rejects its item. The output holds no clock and no engine value, so any change
to the answers leaves it byte-identical.
"""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from l4.fsutil import atomic_write_bytes
from l4.s1.questions import SETS, UnknownQuestionSet, expected_for, get_set
from l4.s1.records import ItemRecord, LabelRecord, read_records

EXPORT_VERSION = "l4/s1-export@1"
DATASET_SCHEMA = "l4/s1-dataset@1"
SPLITS = ("train", "calib", "test")
RATIOS = (0.70, 0.15, 0.15)  # [G] D8
MAX_CLASS_RATIO = 2  # the larger class of a question holds at most twice the smaller
DETERMINISTIC_CHECKS = ("scope", "diff-coverage", "tests-ran", "traceability")
HUMAN_EVENTS = ("verdict", "audit")
ALLOWED_SOURCES: tuple[str, ...] = (
    *(f"deterministic:{c}" for c in DETERMINISTIC_CHECKS),
    *(f"human:{e}" for e in HUMAN_EVENTS),
)


def source_allowed(source: str | None) -> bool:
    """Exact match: an engine name, `s1:*`, `judge:*` or anything unknown is not a ground-truth source."""
    return source in ALLOWED_SOURCES


@dataclass(frozen=True)
class Row:
    item_key: str
    question_set: str
    state: str
    expected: dict[str, Any]
    unit_hash: str
    tags: tuple[str, ...]


@dataclass
class GroundTruth:
    rows: list[Row] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)


def _tags(item: ItemRecord, human: LabelRecord | None) -> tuple[str, ...]:
    tags = {*item.tags, f"set:{item.question_set}", f"item:{item.item_key}"}
    if item.label_source:
        tags.add(f"label_source:{item.label_source}")
    if human is not None:
        tags.update(
            {f"label_source:{human.source}", "human_overrides_deterministic" if item.expected else "human_only"}
        )
    return tuple(sorted(tags))


def ground_truth_rows(paths: Sequence[Path]) -> GroundTruth:
    out = GroundTruth()
    items: dict[str, list[ItemRecord]] = defaultdict(list)
    labels: dict[str, list[LabelRecord]] = defaultdict(list)
    for path in paths:
        for record in read_records(path, ("item", "label"), out.counts):
            if isinstance(record, ItemRecord):
                items[record.item_key].append(record)
            elif isinstance(record, LabelRecord):
                labels[record.item_key].append(record)
    out.counts["items_read"] = sum(len(v) for v in items.values())
    for key in sorted(items):
        group = items[key]
        first = group[0]
        try:
            qset = get_set(first.question_set)
        except UnknownQuestionSet:
            out.counts["rejected_unknown_question_set"] += 1
            continue
        if any(not source_allowed(i.label_source) for i in group if i.label_source or i.expected):
            out.counts["rejected_label_source"] += 1
            continue
        if any(i.question_sha256 != qset.sha256 for i in group):
            out.counts["rejected_stale_question_set"] += 1
            continue
        if len({json.dumps(i.expected, sort_keys=True) for i in group}) > 1:
            out.counts["dropped_conflicting_labels"] += 1
            continue
        usable = [lab for lab in labels.get(key, ()) if source_allowed(lab.source)]
        out.counts["rejected_label_source"] += len(labels.get(key, ())) - len(usable)
        human = max(usable, key=lambda lab: (lab.ts, json.dumps(lab.truth, sort_keys=True)), default=None)
        expected = first.expected
        if human is not None:
            try:
                expected = expected_for(first.question_set, human.truth)
            except ValueError:
                out.counts["rejected_human_truth"] += 1
                human, expected = None, first.expected
        if not expected:
            out.counts["skipped_unlabelled"] += 1
            continue
        if human is not None and first.expected:
            out.counts["human_overrides_deterministic"] += 1
        out.rows.append(Row(key, first.question_set, first.state, dict(expected), first.unit_hash, _tags(first, human)))
    return out


class ExportError(ValueError):
    """The data set cannot be used as it is: a split is empty or lacks a label of a class question."""


def assign_splits(unit_hashes: Iterable[str], seed: int) -> dict[str, str]:
    """By unit, so that no unit (and no canary derived from it) is in two splits. Units are ranked by
    sha256(seed:unit) and cut 70/15/15 of their count, with at least one unit in calib and in test, so a split is not
    empty by luck of independent buckets (three units or more fill all three splits)."""
    units = sorted(set(unit_hashes), key=lambda u: _rank(seed, u))
    n_calib, n_test = (max(1, round(len(units) * r)) for r in RATIOS[1:])
    n_train = max(0, len(units) - n_calib - n_test)
    order = ["train"] * n_train + ["calib"] * n_calib + ["test"] * n_test
    return dict(zip(units, order, strict=False))


def _rank(seed: int, key: str) -> str:
    return hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()


def balance(rows: Sequence[Row], seed: int) -> tuple[list[Row], int]:
    """Per question set, the larger classes are cut to MAX_CLASS_RATIO times the smallest by stable-hash order.
    The class is the expected label of the set's class question. A set with one class is kept whole."""
    by_set: dict[str, dict[str, list[Row]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        by_set[row.question_set][json.dumps(row.expected.get(get_set(row.question_set).class_question))].append(row)
    kept: list[Row] = []
    for classes in by_set.values():
        smallest = min(len(v) for v in classes.values())
        for members in classes.values():
            members.sort(key=lambda r: _rank(seed, r.item_key))
            kept += members if len(classes) < 2 else members[: MAX_CLASS_RATIO * smallest]
    return kept, len(rows) - len(kept)


def _project(row: Row, split: str) -> dict[str, Any]:
    qset = get_set(row.question_set)
    canonical_only = split != "train"  # train keeps both option orders as augmentation; the others one per item
    # only the questions the ground truth answers: a row never asks what it cannot score
    questions = {qid: spec for qid, spec in qset.wire(canonical_only=canonical_only).items() if qid in row.expected}
    return {
        "state": row.state,
        "questions": questions,
        "expected": {qid: row.expected[qid] for qid in questions},
        "tags": list(row.tags),
        "language": "en",
    }


def _count_tags(rows: Sequence[Row], prefix: str) -> dict[str, int]:
    counter = Counter(t[len(prefix) :] for r in rows for t in r.tags if t.startswith(prefix))
    return dict(sorted(counter.items()))


def split_gaps(by_split: Mapping[str, Sequence[Row]]) -> list[str]:
    """What makes the splits unusable: an empty split, or a label of a question set's class question that calib or
    test never asks (a calibration or a gate on one class means nothing)."""
    gaps = [f"the {split} split is empty" for split in SPLITS if not by_split[split]]
    labels: dict[str, set[str]] = defaultdict(set)
    for rows in by_split.values():
        for row in rows:
            labels[row.question_set].add(json.dumps(row.expected.get(get_set(row.question_set).class_question)))
    for split in SPLITS[1:]:
        for name, wanted in sorted(labels.items()):
            have = {
                json.dumps(r.expected.get(get_set(name).class_question))
                for r in by_split[split]
                if r.question_set == name
            }
            gaps += [f"{name}: no {split} row with label {label}" for label in sorted(wanted - have) if by_split[split]]
    return gaps


def write_dataset(
    truth: GroundTruth,
    out_dir: Path,
    *,
    seed: int,
    extra_manifest: Mapping[str, Any] | None = None,
    allow_gaps: bool = False,
) -> dict[str, Any]:
    """`train.jsonl`, `calib.jsonl`, `test.jsonl` and `manifest.json` in `out_dir`; returns the manifest.
    `ExportError` (nothing written) when a split is empty, and when a split lacks a label unless `allow_gaps`."""
    split_of = assign_splits((r.unit_hash for r in truth.rows), seed)
    by_split: dict[str, list[Row]] = {s: [] for s in SPLITS}
    for row in truth.rows:
        by_split[split_of[row.unit_hash]].append(row)
    capped: dict[str, list[Row]] = {}
    dropped = 0
    for split, rows in by_split.items():
        capped[split], cut = balance(rows, seed)
        dropped += cut
    if empty := [f"the {split} split is empty" for split in SPLITS if not capped[split]]:
        raise ExportError("; ".join(empty) + f" (split seed {seed}; too few units for three splits)")
    if (gaps := split_gaps(capped)) and not allow_gaps:
        raise ExportError("; ".join(gaps) + f" (split seed {seed}; --allow-gaps writes it anyway)")
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, Any]] = {}
    questions: dict[str, dict[str, dict[str, int]]] = {}
    for split in SPLITS:
        rows = sorted(capped[split], key=lambda r: r.item_key)
        lines = [json.dumps(_project(r, split), sort_keys=True, ensure_ascii=False) for r in rows]
        data = ("\n".join(lines) + "\n") if lines else ""
        atomic_write_bytes(out_dir / f"{split}.jsonl", data.encode("utf-8"))
        files[f"{split}.jsonl"] = {"rows": len(rows), "sha256": hashlib.sha256(data.encode("utf-8")).hexdigest()}
        per_question: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in rows:
            for qid, value in _project(row, split)["expected"].items():
                per_question[f"{row.question_set}/{qid}"][value if isinstance(value, str) else json.dumps(value)] += 1
        questions[split] = {k: dict(sorted(v.items())) for k, v in sorted(per_question.items())}
    all_rows = [r for s in SPLITS for r in capped[s]]
    dataset = "".join(f"{name}:{files[name]['sha256']}\n" for name in sorted(files))
    manifest: dict[str, Any] = {
        "schema": DATASET_SCHEMA,
        "split_seed": seed,
        "ratios": dict(zip(SPLITS, RATIOS, strict=True)),
        "files": files,
        "dataset_sha256": hashlib.sha256(dataset.encode("utf-8")).hexdigest(),
        "counts": {
            "rows": {s: files[f"{s}.jsonl"]["rows"] for s in SPLITS},
            "units": {s: len({r.unit_hash for r in capped[s]}) for s in SPLITS},
            "questions": questions,
            "question_sets": dict(sorted(Counter(r.question_set for r in all_rows).items())),
            "origin": _count_tags(all_rows, "origin:"),
            "mutation": _count_tags(all_rows, "mutation:"),
            "label_source": _count_tags(all_rows, "label_source:"),
            "balance_cut": dropped,
            "ingest": dict(sorted(truth.counts.items())),
        },
        "allow_list": list(ALLOWED_SOURCES),
        "generators": {"export": EXPORT_VERSION, "question_sets": {n: s.sha256 for n, s in sorted(SETS.items())}},
    }
    if extra_manifest:
        manifest.update(extra_manifest)
    text = json.dumps(manifest, sort_keys=True, indent=1, ensure_ascii=False) + "\n"
    atomic_write_bytes(out_dir / "manifest.json", text.encode("utf-8"))  # last: a crash leaves the old manifest
    return manifest
