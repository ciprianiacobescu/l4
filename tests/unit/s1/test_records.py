from collections import Counter
from pathlib import Path

from l4.s1 import records as r


def item(**kw) -> r.ItemRecord:
    base = dict(
        item_key="k1", unit="openspec:x", unit_hash=r.unit_hash("p", "openspec:x"), project="p", run_id="R", round=1,
        origin="live", subject="src/a.py", state="STATE", state_sha256="s" * 64, question_set="l4/tests-ok@2",
        question_sha256="q" * 64, expected={"all_passed": True}, label_source="deterministic:tests-ran",
        tags=["origin:live"],
    )  # fmt: skip
    return r.ItemRecord(**{**base, **kw})


def test_item_answer_label_round_trip_and_item_without_any_answer(tmp_path: Path):
    a, b = tmp_path / "cache.jsonl", tmp_path / "run.jsonl"
    first = item()
    second = item(item_key="k2", expected={}, label_source=None)  # criterion item before m13: nothing labels it
    answer = r.AnswerRecord("k1", "jev", "jev", "jev-1.13.0", {"all_passed": {"kind": "noul", "p_true": 0.9}}, 273)
    failed = r.AnswerRecord("k1", "remote", "laya-mac", "", {}, 0, error="down")
    label = r.LabelRecord("k2", {"satisfied": True}, "satisfied", "human:verdict", "human", "2026-10-04T00:00:00Z")
    r.append_records([a, b], [first, second, answer, failed, label])
    for path in (a, b):
        got = r.read_records(path)
        assert got == [first, second, answer, failed, label]
    assert r.read_records(a, ("item",)) == [first, second]
    assert [x.item_key for x in r.read_records(a, ("item",)) if x.item_key not in {"k1"}] == ["k2"]
    # an item that no engine answered is still a complete item
    only_items = [x for x in r.read_records(a) if isinstance(x, r.AnswerRecord)]
    assert {x.item_key for x in only_items} == {"k1"}


def test_v1_lines_are_skipped_and_counted_and_answers_are_not_built_when_unwanted(tmp_path: Path):
    path = tmp_path / "c.jsonl"
    path.write_text(
        '{"ts": "t", "unit": "u", "criterion": "C1", "state_sha256": "x", "p": 0.5, "model": "m"}\n'
        "not json\n"
        '{"schema": "l4/s1-calibration@2", "kind": "answer", "item_key": "k", "bogus": 1}\n'
        '{"schema": "other@1", "kind": "item"}\n'
    )
    stats: Counter[str] = Counter()
    assert r.read_records(path, ("item", "label"), stats) == []
    assert stats == Counter(legacy_v1=1, unreadable=1, unknown_kind=1)


def test_keys_are_stable_and_distinguish_subjects():
    assert r.item_key("p", "u", "s", "a.py", "h") == r.item_key("p", "u", "s", "a.py", "h")
    assert r.item_key("p", "u", "s", "a.py", "h") != r.item_key("p", "u", "s", "b.py", "h")
    assert r.unit_hash("p", "u") != r.unit_hash("p2", "u")
