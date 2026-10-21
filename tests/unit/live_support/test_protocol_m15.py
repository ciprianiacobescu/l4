import json

from ...live.protocol_m15 import commits_above, s1_lines

# A `.l4-out/s1/<run>.jsonl` with M1.6's shadow on: the v1 calibration row of step 8 (M1.5, no `kind`) next to the
# l4/s1-calibration@2 `item` and `answer` records of the shadow half (they carry `kind` and no `criterion`).
V1 = {
    "ts": "2026-10-05T08:10:00Z", "unit": "openspec:show-item-count", "run_id": "r-1", "round": 1,
    "criterion": "C-de7f2d3f", "state_sha256": "a" * 64, "question": "criterion_met", "p": 0.93,
    "question_set": "step8@1", "evidence": [], "served_model": "jev-1.13.0", "engine": "jev", "model": "jev-1.13.0",
    "server_version": "", "state_tokens": 120, "server_truncated": False, "deterministic": "covered", "judge": "pass",
}  # fmt: skip
ITEM = {"kind": "item", "item_key": "k1", "unit": "openspec:show-item-count", "subject": "src/pricing/web/page.py"}
ANSWER_JEV = {"kind": "answer", "item_key": "k1", "engine": "jev", "profile": "jev", "model": "jev-1.13.0",
              "answers": {"in_scope": {"p": 0.8}}, "latency_ms": 300, "error": None}  # fmt: skip
ANSWER_LAYA = {**ANSWER_JEV, "engine": "laya-local", "profile": "laya", "model": "typed-decisions"}


def _text(*rows: dict) -> str:
    return "".join(json.dumps(r) + "\n" for r in rows)


def test_the_criterion_rows_are_the_v1_lines_only():
    lines = s1_lines({".l4-out/s1/r-1.jsonl": _text(V1, ITEM, ANSWER_JEV, ANSWER_LAYA)})
    assert lines.criteria == [V1]
    assert lines.items == [ITEM]
    assert lines.answers == [ANSWER_JEV, ANSWER_LAYA]


def test_answers_are_grouped_by_engine():
    lines = s1_lines({"a": _text(ITEM, ANSWER_JEV, ANSWER_LAYA, {**ANSWER_LAYA, "item_key": "k2", "error": "down"})})
    assert sorted(lines.by_engine()) == ["jev", "laya-local"]
    assert len(lines.by_engine()["laya-local"]) == 2


def test_without_shadow_the_file_is_all_criterion_rows():
    lines = s1_lines({"a": _text(V1), "b": "\n"})
    assert lines.criteria == [V1] and lines.items == [] and lines.answers == []


# The unit branch as GitLab lists it (newest first). After the human merge every one of its commits is on `main`
# too, so "the commits not on main" is empty then; the commits above the seed commit are the same before and after.
BRANCH_LOG = [{"id": "h"}, {"id": "m"}, {"id": "d"}, {"id": "t"}, {"id": "g"}, {"id": "r"}, {"id": "seed"}, {"id": "u"}]


def test_the_unit_commits_are_the_ones_above_the_seed_oldest_first():
    assert [c["id"] for c in commits_above(BRANCH_LOG, "seed")] == ["r", "g", "t", "d", "m", "h"]


def test_a_branch_that_does_not_reach_the_seed_gives_nothing():
    assert commits_above(BRANCH_LOG, "elsewhere") == []
