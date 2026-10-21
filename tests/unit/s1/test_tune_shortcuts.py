"""Gate rules against a checkpoint that learned the canary templates (review round 2), and the checkpoint file table."""

import pytest

from ._tune import load

tune = load("laya_tune")


def case(qid: str, expected, correct: bool | None, *tags: str) -> dict:
    return {"qid": qid, "expected": expected, "correct": correct, "tags": list(tags)}


def test_a_template_shortcut_is_caught_on_the_slice_it_fails():
    # right on every synthetic mutation, wrong on the real untouched covered function
    tuned = [case("exercised", True, False, "mutation:none"), case("exercised", True, False, "mutation:none")]
    tuned += [case("exercised", False, True, "mutation:template_edit") for _ in range(12)]
    base = [case("exercised", True, True, "mutation:none"), case("exercised", True, True, "mutation:none")]
    base += [case("exercised", False, True, "mutation:template_edit") for _ in range(12)]
    failures = tune.shortcut_failures(tuned, base)
    assert any("mutation:none on exercised" in f and "n=2" in f for f in failures)
    assert any("exercised, label true: recall 0.00" in f for f in failures)
    assert not any("template_edit" in f for f in failures)


def test_origin_slices_count_and_a_clean_checkpoint_passes():
    cases = [case("exercised", v, True, "origin:live", "mutation:none") for v in (True, False)]
    assert tune.shortcut_failures(cases, cases) == []
    worse = [case("exercised", True, False, "origin:live")] + cases[1:]
    assert any("origin:live" in f for f in tune.shortcut_failures(worse, cases))


def test_score_questions_are_not_judged_by_recall():
    assert tune.shortcut_failures([case("relatedness", 1, None, "mutation:none")], []) == []


def test_the_accuracy_floor_applies_to_noul_and_choice_alike():
    assert tune.accuracy_floors({"noul_accuracy": 0.9, "choice_accuracy": 0.7}) == {
        "noul_accuracy": tune.MIN_ACCURACY, "choice_accuracy": tune.MIN_ACCURACY,
    }  # fmt: skip
    assert tune.accuracy_floors({"noul_accuracy": 0.9}) == {"noul_accuracy": tune.MIN_ACCURACY}


def test_checkpoint_files_cover_everything_and_drift_is_named(tmp_path):
    (tmp_path / "tokenizer").mkdir()
    (tmp_path / "tokenizer" / "tokenizer_config.json").write_text("{}")
    (tmp_path / "model.safetensors").write_bytes(b"w")
    (tmp_path / "l4-train.json").write_text("{}")
    files = tune.checkpoint_files(tmp_path)
    assert sorted(files) == ["model.safetensors", "tokenizer/tokenizer_config.json"]
    record = {"files": files}
    assert tune.checkpoint_drift(tmp_path, record) == []
    (tmp_path / "tokenizer" / "tokenizer_config.json").write_text('{"x":1}')
    (tmp_path / "extra.json").write_text("{}")
    (tmp_path / "model.safetensors").unlink()
    drift = tune.checkpoint_drift(tmp_path, record)
    assert len(drift) == 3 and any("tokenizer_config.json differs" in d for d in drift)
    assert any("model.safetensors" in d and "gone" in d for d in drift) and any("extra.json" in d for d in drift)


def test_a_symlink_in_a_checkpoint_is_refused(tmp_path):
    (tmp_path / "w").write_bytes(b"w")
    (tmp_path / "link").symlink_to(tmp_path / "w")
    with pytest.raises(ValueError, match="symlink"):
        tune.checkpoint_files(tmp_path)


def test_default_cache_is_outside_the_repository(monkeypatch, tmp_path):
    monkeypatch.setenv("L4_CACHE", str(tmp_path / "c"))
    assert tune.default_cache() == tmp_path / "c" / "s1" / "bases"
    monkeypatch.delenv("L4_CACHE")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "x"))
    assert tune.default_cache() == tmp_path / "x" / "l4" / "s1" / "bases"
    assert tune.HERE not in tune.default_cache().parents


def test_write_atomic_leaves_no_temp_file(tmp_path):
    target = tmp_path / "gate.json"
    target.write_text("old")
    tune.write_atomic(target, "new")
    assert target.read_text() == "new" and [p.name for p in tmp_path.iterdir()] == ["gate.json"]


def test_gate_with_a_missing_record_exits_2_with_one_line(tmp_path, capsys):
    from .test_tune_guards import make_dataset

    data, ckpt = tmp_path / "ds", tmp_path / "ckpt"
    data.mkdir()
    ckpt.mkdir()
    make_dataset(data)
    code = tune.main(["gate", "--ckpt", str(ckpt), "--data", str(data), "--json", str(tmp_path / "g.json")])
    err = capsys.readouterr().err
    assert code == 2 and err.startswith("laya_tune: FileNotFoundError") and len(err.splitlines()) == 1
    assert not (tmp_path / "g.json").exists()
    (ckpt / "l4-train.json").write_text("{not json")
    assert tune.main(["gate", "--ckpt", str(ckpt), "--data", str(data), "--json", str(tmp_path / "g.json")]) == 2
