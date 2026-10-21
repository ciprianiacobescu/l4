import ast
import random
from pathlib import Path

import pytest

import l4.s1.export as export
from l4.s1 import questions as q
from l4.s1 import records as r

from ._make import make_item


def write(path: Path, *records: r.Record) -> Path:
    r.append_records([path], list(records))
    return path


def test_engine_label_source_is_rejected(tmp_path: Path):
    good = make_item("good")
    bad = [make_item(f"bad{i}", source=s) for i, s in enumerate(("jev", "s1:jev", "laya-local", "engine:jev"))]
    truth = export.ground_truth_rows([write(tmp_path / "c.jsonl", good, *bad)])
    assert [row.item_key for row in truth.rows] == ["good"]
    assert truth.counts["rejected_label_source"] == 4


def test_judge_and_unknown_sources_rejected(tmp_path: Path):
    sources = ["judge:claude", "judge:codex", "deterministic:vibes", "human:", "human:guess", "", "x", "deterministic"]
    items = [make_item(f"i{n}", source=s) for n, s in enumerate(sources)]
    ok = [make_item("ok-det"), make_item("ok-human", source="human:verdict")]
    truth = export.ground_truth_rows([write(tmp_path / "c.jsonl", *items, *ok)])
    assert sorted(row.item_key for row in truth.rows) == ["ok-det", "ok-human"]
    assert truth.counts["rejected_label_source"] == len(sources)
    # a human label with an engine source does not label the item either
    bare = make_item("bare", expected={}, source=None)
    lab = r.LabelRecord("bare", {"tests_ok": True}, "tests_ok", "jev", "jev", "2026-10-04T00:00:00Z")
    truth = export.ground_truth_rows([write(tmp_path / "d.jsonl", bare, lab)])
    assert truth.rows == [] and truth.counts["rejected_label_source"] == 1 and truth.counts["skipped_unlabelled"] == 1


def test_unlabelled_human_override_conflict_unknown_set_and_stale_sha(tmp_path: Path):
    unlabelled = make_item("unlabelled", set_name=q.CRITERION, expected={}, source=None)
    overridden = make_item("overridden", set_name=q.FILE_RELEVANT, truth={"relevant": False, "named": False})
    human = r.LabelRecord(
        "overridden", {"relevant": True}, "relevant", "human:verdict", "human", "2026-10-04T00:00:00Z"
    )
    label_for_unlabelled = r.LabelRecord("unlabelled", {"satisfied": True}, "satisfied", "human:verdict", "human", "t")
    twin_a = make_item("twin", expected={"all_passed": True})
    twin_b = make_item("twin", expected={"all_passed": False})
    unknown = make_item("unknown")
    unknown = r.ItemRecord(**{**unknown.__dict__, "question_set": "l4/tests-ok@9"})
    stale = make_item("stale")
    stale = r.ItemRecord(**{**stale.__dict__, "question_sha256": "0" * 64})
    path = write(
        tmp_path / "c.jsonl", unlabelled, overridden, human, label_for_unlabelled, twin_a, twin_b, unknown, stale
    )
    truth = export.ground_truth_rows([path])
    by_key = {row.item_key: row for row in truth.rows}
    assert set(by_key) == {"overridden", "unlabelled"}
    assert by_key["overridden"].expected == {"relevant": True, "unrelated": False}  # the human label wins
    assert "relatedness" not in by_key["overridden"].expected
    assert {"label_source:deterministic:scope", "label_source:human:verdict", "human_overrides_deterministic"} <= set(
        by_key["overridden"].tags
    )
    assert by_key["unlabelled"].expected == {
        "satisfied": True,
        "status_fwd": "implemented",
        "status_rev": "implemented",
    }
    c = truth.counts
    assert (c["dropped_conflicting_labels"], c["rejected_unknown_question_set"], c["rejected_stale_question_set"]) == (
        1,
        1,
        1,
    )
    assert c["human_overrides_deterministic"] == 1


def test_randomised_answers_give_byte_identical_export(tmp_path: Path):
    items = [make_item(f"k{i}", unit=f"openspec:u{i % 9}", truth={"tests_ok": i % 2 == 0}) for i in range(60)]
    plain = write(tmp_path / "plain.jsonl", *items)
    noisy = tmp_path / "noisy.jsonl"
    rng = random.Random(1)
    records: list[r.Record] = []
    for item in items:
        for engine in ("jev", "laya-local", "remote"):
            p = rng.random()
            records.append(
                r.AnswerRecord(item.item_key, engine, engine, "m", {"all_passed": {"kind": "noul", "p_true": p}}, 5)
            )
    write(noisy, *items[:30], *records, *items[30:])
    plain.with_name("v1.jsonl").write_text('{"ts": "t", "criterion": "C1", "p": 0.3}\n')
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    export.write_dataset(export.ground_truth_rows([plain, plain.with_name("v1.jsonl")]), out_a, seed=7)
    export.write_dataset(export.ground_truth_rows([noisy]), out_b, seed=7)
    for name in ("train.jsonl", "calib.jsonl", "test.jsonl", "manifest.json"):
        a, b = (out_a / name).read_bytes(), (out_b / name).read_bytes()
        if name == "manifest.json":  # the ingest counts legitimately differ by the v1 line that only `a` read
            import json

            ma, mb = json.loads(a), json.loads(b)
            ma["counts"]["ingest"].pop("legacy_v1")
            assert ma == mb
        else:
            assert a == b


def test_export_modules_never_import_score_or_report():
    forbidden = {"l4.s1.score", "l4.s1.report", "l4.s1.shadow", "l4.llm.system_one", "l4.llm"}
    for name in ("export", "canary", "labels", "questions", "records", "audit", "stats"):
        path = Path(export.__file__).with_name(f"{name}.py")
        if not path.exists():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names] if isinstance(node, ast.Import)
                else [node.module or "", *(f"{node.module}.{a.name}" for a in node.names)]
                if isinstance(node, ast.ImportFrom)
                else []
            )  # fmt: skip
            assert not forbidden & set(names), f"{name}.py imports {forbidden & set(names)}"
    # and the real import graph: importing the export must not load the scoring side
    import subprocess
    import sys

    bad = "('l4.s1.score', 'l4.s1.report', 'l4.llm.system_one')"
    for module in ("l4.s1.export", "l4.s1.audit"):  # audit writes human labels that feed the next export
        code = f"import sys, {module}; print(sorted(m for m in sys.modules if m in {bad}))"
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        assert done.stdout.strip() == "[]", module


@pytest.mark.parametrize("source", ["jev", "judge:claude", "s1:laya"])
def test_allow_list_has_no_engine(source: str):
    assert not export.source_allowed(source)
    assert all(s.startswith(("deterministic:", "human:")) for s in export.ALLOWED_SOURCES)
