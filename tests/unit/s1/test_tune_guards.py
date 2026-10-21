import hashlib
import json

import pytest

from ._tune import load

tune = load("laya_tune")


def make_dataset(root, rows=("a", "b", "c")):
    files = {}
    for split in tune.SPLITS:
        text = json.dumps({"split": split, "rows": rows}) + "\n"
        (root / f"{split}.jsonl").write_text(text)
        files[f"{split}.jsonl"] = {"rows": 1, "sha256": hashlib.sha256(text.encode()).hexdigest()}
    manifest = {"dataset_sha256": "ds-1", "files": files, "counts": {"label_source": {"deterministic:scope": 1}}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_check_dataset_refuses_a_split_that_differs_from_the_manifest(tmp_path):
    make_dataset(tmp_path)
    assert tune.check_dataset(tmp_path)["dataset_sha256"] == "ds-1"
    (tmp_path / "test.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="test.jsonl"):
        tune.check_dataset(tmp_path)
    (tmp_path / "calib.jsonl").unlink()
    with pytest.raises(ValueError, match="calib.jsonl|test.jsonl"):
        tune.check_dataset(tmp_path)


def test_gate_target_must_be_the_data_set_the_checkpoint_was_trained_on(tmp_path):
    manifest = make_dataset(tmp_path)
    record = {
        "dataset_sha256": "ds-1",
        "split_sha256": {s: tune.file_sha256(tmp_path / f"{s}.jsonl") for s in tune.SPLITS},
    }
    tune.check_gate_target(record, manifest, tmp_path)
    with pytest.raises(ValueError, match="another data set"):
        tune.check_gate_target({**record, "dataset_sha256": "ds-2"}, manifest, tmp_path)
    swapped = {**record, "split_sha256": {**record["split_sha256"], "test": "0" * 64}}
    with pytest.raises(ValueError, match="test split"):
        tune.check_gate_target(swapped, manifest, tmp_path)


def test_temperatures_are_clamped_to_what_laya_serves_and_bounds_are_flagged():
    applied, on_bound = tune.apply_temperatures([1.0, 10.0, 0.1, 2.5, 5.0], 0.5, 5.0)
    assert applied == [1.0, 5.0, 0.5, 2.5, 5.0] and on_bound == [1, 2, 4]
    assert tune.apply_temperatures([], 0.5, 5.0) == ([], [])


def test_train_record_failures_void_a_pass():
    ok = {"temperatures_raw": [1.0, 2.0, 3.0], "temperatures_on_bound": [], "hyperparameters": {"max_rows": None}}
    assert tune.train_record_failures(ok) == []
    bad = {**ok, "temperatures_raw": [1.0, 10.0, 3.0], "temperatures_on_bound": [1]}
    bad["hyperparameters"] = {"max_rows": 200}
    joined = " ".join(tune.train_record_failures(bad))
    assert "temperature[1]" in joined and "--max-rows 200" in joined
    assert any("raw temperatures" in f for f in tune.train_record_failures({"hyperparameters": {}}))


def rows(correct: int, wrong: int, qid="all_passed"):
    return [{"qid": qid, "type": "noul", "p_true": 0.9, "truth": True}] * correct + [
        {"qid": qid, "type": "noul", "p_true": 0.003, "truth": True}
    ] * wrong


def test_sanity_question_is_a_hard_gate():
    assert tune.sanity_failures(rows(9, 1), rows(6, 4)) == []
    low = tune.sanity_failures(rows(5, 5), rows(5, 5))
    assert len(low) == 1 and "below 0.85" in low[0]
    worse = tune.sanity_failures(rows(18, 2), rows(20, 0), minimum=0.5)
    assert len(worse) == 1 and "below base" in worse[0]
    assert "not measured" in tune.sanity_failures(rows(3, 0, qid="relevant"), [])[0]
