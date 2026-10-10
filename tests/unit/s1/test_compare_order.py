import json
from pathlib import Path

import pytest

from l4.s1 import report as rp
from l4.s1 import score as sc

from .test_report import dataset, noul, scores


def gate_doc(ds: Path, *, accuracy: float, sha: str | None = None, passed: bool = True) -> dict:
    return {
        "schema": "l4/s1-gate@1", "passed": passed, "test_sha256": sha or sc.file_sha256(ds),
        "tuned": {"slices": {"qid": {"all_passed": {"noul_accuracy": accuracy}}}},
    }  # fmt: skip


def write_gate(tmp_path: Path, doc: dict) -> Path:
    path = tmp_path / f"gate-{len(list(tmp_path.glob('gate-*.json')))}.json"
    path.write_text(json.dumps(doc))
    return path


def answers() -> dict:
    # right, right, right, wrong: accuracy 0.75 on the four noul rows
    return {0: {"all_passed": noul(0.9)}, 1: {"all_passed": noul(0.6)}, 2: {"all_passed": noul(0.3)},
            3: {"all_passed": noul(0.7)}}  # fmt: skip


def test_refuses_before_gate_and_on_sha_mismatch(tmp_path: Path):
    ds = dataset(tmp_path)
    tuned = scores(tmp_path, ds, "laya-tuned", answers())
    with pytest.raises(ValueError, match="gate.json"):
        rp.build_report([tuned], ds, tuned=["laya-tuned"])
    good = write_gate(tmp_path, gate_doc(ds, accuracy=0.75))
    report = rp.build_report([tuned], ds, tuned=["laya-tuned"], gate=good)
    assert report["gate"]["passed"] is True and report["gate"]["cross_check"] == "ok"
    # a failed gate still allows the comparison (the report says so)
    failed = write_gate(tmp_path, gate_doc(ds, accuracy=0.75, passed=False))
    assert rp.build_report([tuned], ds, tuned=["laya-tuned"], gate=failed)["gate"]["passed"] is False
    bad_sha = write_gate(tmp_path, gate_doc(ds, accuracy=0.75, sha="0" * 64))
    with pytest.raises(ValueError, match="another data set"):
        rp.build_report([tuned], ds, tuned=["laya-tuned"], gate=bad_sha)


def test_cross_check_against_the_gate_numbers(tmp_path: Path):
    ds = dataset(tmp_path)
    tuned = scores(tmp_path, ds, "laya-tuned", answers())
    within = write_gate(tmp_path, gate_doc(ds, accuracy=0.745))
    assert rp.build_report([tuned], ds, tuned=["laya-tuned"], gate=within)["gate"]["cross_check"] == "ok"
    off = write_gate(tmp_path, gate_doc(ds, accuracy=0.60))
    with pytest.raises(ValueError, match="all_passed.*0.600"):
        rp.build_report([tuned], ds, tuned=["laya-tuned"], gate=off)
    text = rp.render_markdown(rp.build_report([tuned], ds, tuned=["laya-tuned"], gate=within))
    assert "gate: passed" in text


def test_a_checkpoint_stamped_score_file_cannot_be_reported_without_its_gate(tmp_path: Path):
    ds = dataset(tmp_path)
    ident = {"checkpoint_id": "ck", "checkpoint_sha256": "a" * 64, "checkpoint_dataset_sha256": "d" * 64}
    tuned = scores(tmp_path, ds, "laya-tuned", answers(), **ident)  # a profile name that does not say "tuned"
    with pytest.raises(ValueError, match="after its gate"):
        rp.build_report([tuned], ds)  # no --gate and no --profile: the old hole
    doc = gate_doc(ds, accuracy=0.75) | {"checkpoint_sha256": "a" * 64, "dataset_sha256": "d" * 64}
    report = rp.build_report([tuned], ds, gate=write_gate(tmp_path, doc))
    assert report["gate"]["cross_check"] == "ok"  # treated as tuned although --profile was not given
    other = gate_doc(ds, accuracy=0.75) | {"checkpoint_sha256": "b" * 64, "dataset_sha256": "d" * 64}
    with pytest.raises(ValueError, match="different checkpoint"):
        rp.build_report([tuned], ds, gate=write_gate(tmp_path, other))
    foreign = gate_doc(ds, accuracy=0.75) | {"checkpoint_sha256": "a" * 64, "dataset_sha256": "e" * 64}
    with pytest.raises(ValueError, match="not trained on the data set"):
        rp.build_report([tuned], ds, gate=write_gate(tmp_path, foreign))
    off = gate_doc(ds, accuracy=0.60) | {"checkpoint_sha256": "a" * 64, "dataset_sha256": "d" * 64}
    with pytest.raises(ValueError, match="all_passed"):
        rp.build_report([tuned], ds, gate=write_gate(tmp_path, off))  # cross-checked without --profile too


def test_no_engine_is_reported_on_an_exported_calib_or_test_file_before_the_gate(tmp_path: Path):
    from l4.s1 import export as ex
    from l4.s1 import records as rec

    from ._make import make_item

    items = [make_item(f"k{n:030d}", unit=f"openspec:u{n}", truth={"tests_ok": n % 2 == 0}) for n in range(30)]
    cal = tmp_path / "cal.jsonl"
    rec.append_records([cal], items)
    out = tmp_path / "ds"
    ex.write_dataset(ex.ground_truth_rows([cal]), out, seed=5)
    ds = out / "test.jsonl"
    jev = scores(tmp_path, ds, "jev", {})  # an untuned engine, no checkpoint stamp
    with pytest.raises(ValueError, match="before the gate"):
        rp.build_report([jev], ds)
    assert rp.build_report([jev], ds, gate=write_gate(tmp_path, gate_doc(ds, accuracy=0.5)))["gate"]["passed"]
    with pytest.raises(ValueError, match="before the gate"):
        rp.build_report([scores(tmp_path, out / "calib.jsonl", "jev", {})], out / "calib.jsonl")


def test_a_cross_check_that_compared_nothing_is_not_ok(tmp_path: Path):
    ds = dataset(tmp_path)
    tuned = scores(tmp_path, ds, "laya-tuned", answers())
    empty = gate_doc(ds, accuracy=0.75) | {"tuned": {"slices": {"qid": {}}}}
    with pytest.raises(ValueError, match="cross-checked"):
        rp.build_report([tuned], ds, tuned=["laya-tuned"], gate=write_gate(tmp_path, empty))
