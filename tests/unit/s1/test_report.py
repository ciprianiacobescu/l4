import json
import math
from pathlib import Path

import pytest

from l4.s1 import report as rp
from l4.s1 import score as sc

TESTS_OK = "l4/tests-ok@2"
CRIT = "l4/criterion-satisfied@2"
OPTIONS = {"implemented": "a", "not_implemented": "b", "contradicted": "c"}


def dataset(tmp_path: Path) -> Path:
    rows = []
    for expected, origin in (
        (True, "origin:live"),
        (True, "origin:canary"),
        (False, "origin:canary"),
        (False, "origin:canary"),
    ):
        rows.append({
            "state": f"s{len(rows)}", "language": "en", "expected": {"all_passed": expected},
            "questions": {"all_passed": {"type": "noul", "instructions": "ok?"}},
            "tags": [f"set:{TESTS_OK}", origin, "mutation:none" if expected else "mutation:break_test"],
        })  # fmt: skip
    for label in ("implemented", "not_implemented"):
        rows.append({
            "state": f"c-{label}", "language": "en", "expected": {"status_fwd": label},
            "questions": {"status_fwd": {"type": "choice", "instructions": "state?", "criteria": OPTIONS}},
            "tags": [f"set:{CRIT}", "origin:live"],
        })  # fmt: skip
    path = tmp_path / "test.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def scores(tmp_path: Path, ds: Path, profile: str, answers: dict[int, dict], **header) -> Path:
    lines = [{"schema": sc.SCORES_SCHEMA, "kind": "header", "profile": profile, "engine": "jev", "model": "m",
              "dataset_sha256": sc.file_sha256(ds), **header}]  # fmt: skip
    lines += [
        {"schema": sc.SCORES_SCHEMA, "kind": "row", "row": i, "answers": a, "latency_ms": 1} for i, a in answers.items()
    ]
    path = tmp_path / f"{profile}.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return path


def noul(p: float) -> dict:
    return {"kind": "noul", "p_true": p}


def choice(**probs: float) -> dict:
    return {"kind": "choice", "choice": max(probs, key=probs.get), "probabilities": probs}


def test_metrics_match_hand_computed_values(tmp_path: Path):
    ds = dataset(tmp_path)
    answers = {
        0: {"all_passed": noul(0.9)}, 1: {"all_passed": noul(0.6)}, 2: {"all_passed": noul(0.3)},
        3: {"all_passed": noul(0.7)},
        4: {"status_fwd": choice(implemented=0.7, not_implemented=0.2, contradicted=0.1),
            "status_fwd__rev": choice(implemented=0.5, not_implemented=0.4, contradicted=0.1)},
        5: {"status_fwd": choice(implemented=0.5, not_implemented=0.4, contradicted=0.1),
            "status_fwd__rev": choice(implemented=0.3, not_implemented=0.6, contradicted=0.1)},
    }  # fmt: skip
    report = rp.build_report([scores(tmp_path, ds, "jev", answers)], ds)
    questions = report["engines"]["jev"]["questions"]
    m = questions[f"{TESTS_OK}/all_passed"]["canonical"]
    # right, right, right, wrong; confidence .9 .6 .7 .7; Brier (.01+.16+.09+.49)/4; ECE .1 + .025 + .1
    assert m["n"] == 4 and m["accuracy"] == 0.75
    assert m["brier"] == pytest.approx(0.1875, abs=1e-4) and m["ece"] == pytest.approx(0.225, abs=1e-4)
    assert m["wilson95"] == [pytest.approx(0.3006, abs=1e-3), pytest.approx(0.9544, abs=1e-3)]
    c = questions[f"{CRIT}/status_fwd"]
    assert c["canonical"]["accuracy"] == 0.5 and c["averaged"]["accuracy"] == 1.0
    # canonical Brier: row 4 = .09+.04+.01, row 5 = .25+.36+.01 ; averaged: row 4 = .16+.09+.01, row 5 = .16+.25+.01
    assert c["canonical"]["brier"] == pytest.approx((0.14 + 0.62) / 2, abs=1e-4)
    assert c["averaged"]["brier"] == pytest.approx((0.26 + 0.42) / 2, abs=1e-4)
    slices = report["engines"]["jev"]["slices"]
    assert slices["origin:canary"][f"{TESTS_OK}/all_passed"]["n"] == 3
    assert slices["mutation:break_test"][f"{TESTS_OK}/all_passed"]["accuracy"] == 0.5
    text = rp.render_markdown(report)
    assert "| l4/tests-ok@2/all_passed | 4 | 0.750 | 0.30-0.95 | 0.225 | 0.188 | - |" in text
    assert rp.wilson(0, 0) == (0.0, 1.0) and rp.ece([]) == 0.0
    assert math.isclose(rp.wilson(10, 10)[1], 1.0)


def test_report_reads_expected_only_as_reference(tmp_path: Path):
    ds = dataset(tmp_path)
    one = {0: {"all_passed": noul(0.9)}}
    path = scores(tmp_path, ds, "jev", one)
    before = ds.read_bytes()
    report = rp.build_report([path], ds)
    assert ds.read_bytes() == before and set(tmp_path.iterdir()) == {ds, path}  # nothing written, nothing derived
    assert "c-implemented" not in json.dumps(report) and "s0" not in json.dumps(report)  # no state leaves in a report
    # the answers decide the metrics: the same file scored against flipped expectations flips accuracy
    flipped = [json.loads(line) for line in ds.read_text().splitlines()]
    flipped[0]["expected"]["all_passed"] = False
    other = tmp_path / "flipped.jsonl"
    other.write_text("\n".join(json.dumps(r) for r in flipped) + "\n")
    stale = scores(tmp_path, other, "jev2", one)
    flipped_report = rp.build_report([stale], other)
    assert flipped_report["engines"]["jev2"]["questions"][f"{TESTS_OK}/all_passed"]["canonical"]["accuracy"] == 0.0
    # answers scored on another data set are refused, and so is a file that is not a scores file
    with pytest.raises(ValueError, match="another data set"):
        rp.build_report([path], other)
    junk = tmp_path / "junk.jsonl"
    junk.write_text('{"schema": "l4/s1-calibration@2", "kind": "answer"}\n')
    with pytest.raises(ValueError, match="not an"):
        rp.build_report([junk], ds)
    import ast

    tree = ast.parse(Path(rp.__file__).read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "l4.s1.export" not in imported and "l4.s1.records" not in imported


def test_the_gate_cross_check_says_so_when_no_tuned_engine_was_compared(tmp_path: Path):
    from .test_compare_order import gate_doc, write_gate

    ds = dataset(tmp_path)
    jev = scores(tmp_path, ds, "jev", {0: {"all_passed": noul(0.9)}})
    report = rp.build_report([jev], ds, gate=write_gate(tmp_path, gate_doc(ds, accuracy=0.5)))
    assert report["gate"]["cross_check"] == "no tuned engine compared"
    text = rp.render_markdown(report)
    assert "no tuned engine compared" in text and "laya-evals ok" not in text


def test_rows_are_also_sliced_by_project(tmp_path: Path):
    """Real and synthetic source repositories are reported apart: the project key is a slice like origin and
    mutation."""
    rows = [
        {"state": f"s{i}", "language": "en", "expected": {"all_passed": exp},
         "questions": {"all_passed": {"type": "noul", "instructions": "ok?"}},
         "tags": [f"set:{TESTS_OK}", "origin:canary", f"project:{proj}"]}
        for i, (exp, proj) in enumerate(((True, "git-real"), (False, "git-real"), (True, "git-synth")))
    ]  # fmt: skip
    ds = tmp_path / "rows.jsonl"
    ds.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    answers = {0: {"all_passed": noul(0.9)}, 1: {"all_passed": noul(0.8)}, 2: {"all_passed": noul(0.9)}}
    slices = rp.build_report([scores(tmp_path, ds, "jev", answers)], ds)["engines"]["jev"]["slices"]
    assert slices["project:git-real"][f"{TESTS_OK}/all_passed"]["n"] == 2
    assert slices["project:git-real"][f"{TESTS_OK}/all_passed"]["accuracy"] == 0.5
    assert slices["project:git-synth"][f"{TESTS_OK}/all_passed"]["accuracy"] == 1.0
