"""L4-YOLO-099, L4-YOLO-096 (the ledger part): `plan.review_incomplete` as the findings readers see it. Pure functions
over hand-built events."""

from dataclasses import replace

from l4.yolo import findings as fnd
from l4.yolo.state import fold_plan

from .yolo_ledger_world import ev

GAP = {"criterion": "testability", "severity": "major", "text": "no inputs"}


def reviewed(at, units=None, batches=None, version=4):
    return replace(
        ev("plan.reviewed", plan_digest="p", prompt_version=version, units=units or {}, batches=batches or {}), at=at
    )


def incomplete(at, answered=None, failures=(), version=4, source="ci", reason="no_judge", left=()):
    return replace(
        ev(
            "plan.review_incomplete",
            plan_digest="p",
            prompt_version=version,
            source=source,
            reason=reason,
            answered=answered or {},
            left=list(left),
            failures=list(failures),
            cost_usd=0.0,
        ),
        at=at,
    )


def entry(verdict="READY", material="m1", digest="d1", findings=(), **more):
    return {"verdict": verdict, "digest": digest, "material": material, "findings": [dict(f) for f in findings], **more}


def failure(profile="j1", subject="a", kind="error", material="m1"):
    row = {"profile": profile, "subject": subject, "kind": kind, "detail": "boom"}
    return {**row, "material": material} if material else row


def test_prior_entries_reads_the_answered_entries_of_an_incomplete_review_at_its_time():
    events = [incomplete("2026-11-19T10:00:00Z", {"a": entry(material="ma"), "batch:b1/summary": entry(material="mp")})]
    found = fnd.prior_entries(events, 4)
    assert found["ma"]["at"] == "2026-11-19T10:00:00Z" and found["mp"]["verdict"] == "READY"


def test_prior_entries_reads_the_part_rows_of_a_recorded_batch():
    rows = [
        {
            "part": "batch:b1/a",
            "material": "p1",
            "verdict": "READY",
            "findings": [],
            "reused_from": "2026-11-18T00:00:00Z",
        },
        {"part": "batch:b1/summary", "material": "p2", "verdict": "READY", "findings": []},
    ]
    batch = {"verdict": "READY", "material": "mb", "findings": [], "parts": rows}
    found = fnd.prior_entries([reviewed("2026-11-19T11:00:00Z", batches={"b1": batch})], 4)
    assert found["mb"]["at"] == "2026-11-19T11:00:00Z"
    assert found["p1"]["at"] == "2026-11-18T00:00:00Z"  # a reuse keeps the time of the judgement
    assert found["p2"]["at"] == "2026-11-19T11:00:00Z"


def test_prior_entries_skips_a_harness_finding_and_another_prompt_version():
    schema = {"criterion": "schema", "severity": "blocking", "text": "schema_invalid: x"}
    events = [
        incomplete("2026-11-19T10:00:00Z", {"a": entry("BLOCKED", "ma", findings=[schema]), "b": entry(material="mb")}),
        incomplete("2026-11-19T10:05:00Z", {"c": entry(material="mc")}, version=3),
    ]
    assert set(fnd.prior_entries(events, 4)) == {"mb"}


def test_history_yields_an_incomplete_entry_with_its_source_and_never_a_part():
    events = [
        reviewed("2026-11-19T09:00:00Z", units={"a": entry("NEEDS_REVISION", "m0", findings=[GAP])}),
        incomplete(
            "2026-11-19T10:00:00Z", {"a": entry(material="m1"), "batch:b1/a": entry(material="mp")}, source="local"
        ),
    ]
    hist = fnd.history(events, "a", 4)
    assert [(h["at"], h["source"], h["material"]) for h in hist] == [
        ("2026-11-19T09:00:00Z", "ci", "m0"),
        ("2026-11-19T10:00:00Z", "local", "m1"),
    ]
    assert fnd.history(events, "batch:b1/a", 4) == []  # a part is no subject
    assert [h["material"] for h in fnd.judged(hist)] == ["m0", "m1"]


def test_failed_before_sees_only_the_events_after_the_latest_review_and_accumulates():
    events = [
        incomplete("2026-11-19T08:00:00Z", failures=[failure("j9", "a", "timeout", "old")]),
        reviewed("2026-11-19T09:00:00Z"),
        incomplete("2026-11-19T10:00:00Z", failures=[failure("j1", "a", "timeout", "m1")]),
        incomplete(
            "2026-11-19T11:00:00Z",
            failures=[
                failure("j2", "a", "timeout", "m1"),
                failure("j1", "a", "timeout", "m1"),
                failure("j1", "", "unusable", None),
                failure("j1", "b", "sandbox", "m2"),
                failure("j1", "b", "limit", "m2"),
                failure("j3", "c", "length", "m3"),
                failure("j3", "d", "schema_invalid", "m4"),
            ],
        ),
        incomplete("2026-11-19T12:00:00Z", failures=[failure("j5", "e", "error", "m5")], version=3),
    ]
    assert fnd.failed_before(events, 4) == {"m1": ["j1", "j2"], "m3": ["j3"], "m4": ["j3"]}
    assert fnd.failed_before([*events, reviewed("2026-11-19T13:00:00Z")], 4) == {}


def test_latest_incomplete_is_the_newest_after_the_latest_review_of_the_prompt_version():
    first = incomplete("2026-11-19T10:00:00Z", reason="no_judge")
    second = incomplete("2026-11-19T11:00:00Z", reason="timeout")
    assert fnd.latest_incomplete([reviewed("2026-11-19T09:00:00Z"), first, second], 4) == second
    assert fnd.latest_incomplete([first, second, reviewed("2026-11-19T12:00:00Z")], 4) is None
    assert fnd.latest_incomplete([incomplete("2026-11-19T10:00:00Z", version=3)], 4) is None
    assert fnd.latest_incomplete([], 4) is None


def test_the_state_fold_and_rounds_not_ready_ignore_the_event():
    base = [
        ev("plan.admitted", plan_digest="p", order=["a"], merge="human"),
        reviewed("2026-11-19T09:00:00Z", units={"a": entry("NEEDS_REVISION", "m0", "d0", [GAP])}),
    ]
    extra = incomplete("2026-11-19T10:00:00Z", {"a": entry("NEEDS_REVISION", "m1", "d1", [GAP])}, [failure()])
    assert fold_plan("p1", [*base, extra]) == fold_plan("p1", base)
    assert fnd.rounds_not_ready([*base, extra], "a") == fnd.rounds_not_ready(base, "a") == 1
