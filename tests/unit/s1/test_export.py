import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pytest

import l4.s1.export as export
from l4.s1 import questions as q
from l4.s1 import records as r

from ._make import make_item


def build(tmp_path: Path):
    items = []
    for n in range(300):
        unit = f"openspec:u{n % 41}"  # coprime with the 4:1 skew: every unit holds both classes
        covered = n % 5 != 0  # 4:1 skew, so the cap has to cut
        items.append(make_item(f"c{n}", unit=unit, set_name=q.CHANGE_COVERED, truth={"covered": covered},
                               tags=("origin:canary", "mutation:none" if covered else "mutation:x")))  # fmt: skip
        items.append(make_item(f"p{n}", unit=unit, set_name=q.CRITERION, truth={"satisfied": True},
                               tags=("origin:live",)))  # fmt: skip
    path = tmp_path / "cal.jsonl"
    r.append_records([path], items)
    return export.ground_truth_rows([path])


def read(out: Path, split: str) -> list[dict]:
    text = (out / f"{split}.jsonl").read_text()
    return [json.loads(line) for line in text.splitlines()]


def test_no_unit_hash_in_two_splits_and_balance_cap(tmp_path: Path):
    truth = build(tmp_path)
    manifest = export.write_dataset(truth, tmp_path / "out", seed=1606)
    split_of = export.assign_splits((row.unit_hash for row in truth.rows), 1606)
    units = {s: {u for u, split in split_of.items() if split == s} for s in export.SPLITS}
    assert all(units.values())
    assert not (units["train"] & units["calib"] or units["train"] & units["test"] or units["calib"] & units["test"])
    for split in export.SPLITS:
        counts = Counter(
            row["expected"]["exercised"] for row in read(tmp_path / "out", split) if "exercised" in row["expected"]
        )
        if len(counts) == 2:
            assert max(counts.values()) <= export.MAX_CLASS_RATIO * min(counts.values()), (split, counts)
    assert manifest["counts"]["balance_cut"] > 0
    assert manifest["counts"]["ingest"]["items_read"] == 600


def test_manifest_counts_match_files(tmp_path: Path):
    out = tmp_path / "out"
    manifest = export.write_dataset(build(tmp_path), out, seed=3)
    total = 0
    for split in export.SPLITS:
        data = (out / f"{split}.jsonl").read_bytes()
        rows = read(out, split)
        assert manifest["files"][f"{split}.jsonl"] == {"rows": len(rows), "sha256": hashlib.sha256(data).hexdigest()}
        assert manifest["counts"]["rows"][split] == len(rows)
        total += len(rows)
        assert all(row["language"] == "en" and set(row) == {"state", "questions", "expected", "tags", "language"}
                   for row in rows)  # fmt: skip
        if split != "train":  # one choice order per item outside the training split
            assert all("status_rev" not in row["questions"] for row in rows)
        else:
            assert all(("status_rev" in row["questions"]) == ("status_fwd" in row["questions"]) for row in rows)
        assert all(set(row["expected"]) == set(row["questions"]) for row in rows)
    assert sum(manifest["counts"]["question_sets"].values()) == total
    blob = "".join(f"{n}:{manifest['files'][n]['sha256']}\n" for n in sorted(manifest["files"]))
    assert manifest["dataset_sha256"] == hashlib.sha256(blob.encode()).hexdigest()
    assert manifest["allow_list"] == list(export.ALLOWED_SOURCES)
    assert set(manifest["generators"]["question_sets"]) == set(q.SETS)
    assert manifest["counts"]["mutation"] and manifest["counts"]["origin"]
    assert json.loads((out / "manifest.json").read_text()) == manifest
    assert not re.search(r"\d{4}-\d\d-\d\dT", json.dumps(manifest))  # no clock in the data set


def unit_rows(tmp_path: Path, units: int):
    items = []
    for n in range(units * 4):
        covered = (n // units) % 2 == 0  # every unit holds both classes
        items.append(make_item(f"x{n}", unit=f"openspec:u{n % units}", set_name=q.CHANGE_COVERED,
                               truth={"covered": covered}, tags=("origin:canary",)))  # fmt: skip
    path = tmp_path / "small.jsonl"
    r.append_records([path], items)
    return export.ground_truth_rows([path])


def test_splits_are_cut_by_rank_so_no_split_is_empty_by_luck():
    for seed in range(1600, 1700):
        for n in (3, 8, 20):
            got = export.assign_splits((f"u{i}" for i in range(n)), seed)
            counts = Counter(got.values())
            assert set(counts) == set(export.SPLITS) and len(got) == n
            assert counts["calib"] == counts["test"] == max(1, round(n * 0.15))
    assert export.assign_splits(["a", "b", "c"], 5) == export.assign_splits(["c", "b", "a"], 5)


def test_an_empty_split_is_an_error_and_writes_nothing(tmp_path: Path):
    truth = unit_rows(tmp_path, 2)
    out = tmp_path / "out"
    with pytest.raises(export.ExportError, match=r"the (train|calib|test) split is empty"):
        export.write_dataset(truth, out, seed=1606)
    assert not out.exists()
    with pytest.raises(export.ExportError, match="split is empty"):  # --allow-gaps waives a missing label, not this
        export.write_dataset(truth, out, seed=1606, allow_gaps=True)
    assert not out.exists()


def test_a_split_without_one_label_of_the_class_question_is_an_error(tmp_path: Path):
    truth = unit_rows(tmp_path, 8)
    assert export.write_dataset(truth, tmp_path / "ok", seed=1606)
    split_of = export.assign_splits((row.unit_hash for row in truth.rows), 1606)
    lopsided = [r for r in truth.rows if split_of[r.unit_hash] == "train" or r.expected["exercised"] is True]
    with pytest.raises(export.ExportError, match="no (calib|test) row with label"):
        export.write_dataset(export.GroundTruth(lopsided), tmp_path / "bad", seed=1606)
