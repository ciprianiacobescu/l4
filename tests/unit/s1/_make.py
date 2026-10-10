"""Builders for S1 record tests."""

from l4.s1 import questions as q
from l4.s1 import records as r

SOURCES = {
    q.FILE_RELEVANT: "deterministic:scope",
    q.CHANGE_COVERED: "deterministic:diff-coverage",
    q.TESTS_OK: "deterministic:tests-ran",
    q.CRITERION: "deterministic:traceability",
}


def make_item(
    key: str, *, unit: str = "openspec:a", set_name: str = q.TESTS_OK, truth: dict | None = None, source=...,
    tags: tuple[str, ...] = ("origin:live",), state: str | None = None, expected: dict | None = None,
) -> r.ItemRecord:  # fmt: skip
    truth = {"tests_ok": True} if truth is None and set_name == q.TESTS_OK else truth
    exp = expected if expected is not None else (q.expected_for(set_name, truth) if truth is not None else {})
    state = state if state is not None else f"state of {key}"
    return r.ItemRecord(
        item_key=key, unit=unit, unit_hash=r.unit_hash("p", unit), project="p", run_id="R", round=1,
        origin="canary" if "origin:canary" in tags else "live", subject=key, state=state, state_sha256="h" * 64,
        question_set=set_name, question_sha256=q.get_set(set_name).sha256, expected=exp,
        label_source=SOURCES[set_name] if source is ... else source, tags=list(tags),
    )  # fmt: skip
