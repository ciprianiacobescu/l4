"""L4-YOLO-105, -106: which findings a person can overrule, when an overrule holds, what a subject is once its overruled
findings are taken out, and how the plan fold keeps them. SCN-YOLO-296, -298, -300, -301, -303 (the pure parts)."""

import json
from pathlib import Path

from l4.yolo import accept as accepting
from l4.yolo.findings import finding_id
from l4.yolo.model import PlanEvent
from l4.yolo.state import fold_plan

BATCH = "batch:b1"
F_BLOCK = {"criterion": "missing_dependency", "severity": "blocking", "text": "two units list themselves"}
F_BLOCK2 = {"criterion": "contradiction", "severity": "blocking", "text": "A contradicts B"}
F_MAJOR = {"criterion": "testability", "severity": "major", "text": "no scenario gives an output"}
F_MINOR = {"criterion": "outcome", "severity": "minor", "text": "the outcome could be clearer"}
SCHEMA = Path(accepting.__file__).parent / "schemas" / "readiness.schema.json"


def entry(verdict, findings, material="m-batch"):
    return {"verdict": verdict, "digest": None, "material": material, "findings": [dict(f) for f in findings]}


def review(batch=None, **units):
    rows = {"openspec:a": entry("READY", [], "m-a"), **units}
    return {"units": rows, "batches": {"b1": batch or entry("NEEDS_REVISION", [F_BLOCK])}}


def overrule_event(finding, subject=BATCH, material="m-batch", actor="person", at="2026-11-01T10:00:00Z"):
    return PlanEvent(
        "plan.finding_overruled", at,
        {"finding": finding, "subject": subject, "criterion": "x", "severity": "blocking", "text": "t",
         "material": material, "reason": "checked", "by": "alex", "actor": actor, "marker": None},
    )  # fmt: skip


def state_of(*events):
    return fold_plan(
        "p1", [PlanEvent("plan.admitted", "2026-11-01T09:00:00Z", {"plan_digest": "d", "order": []}), *events]
    )


# --- which findings (D2) ------------------------------------------------------------------------------------------


def test_the_judge_criteria_are_the_enum_of_the_response_schema():
    enum = json.loads(SCHEMA.read_text(encoding="utf-8"))["properties"]["findings"]["items"]["properties"]["criterion"]
    assert frozenset(enum["enum"]) == accepting.JUDGE_CRITERIA


def test_scn_yolo_296_a_judges_blocking_finding_gives_its_subject_and_entry():
    fid = finding_id(BATCH, F_BLOCK)
    subject, found, held_entry = accepting.overrule_check("p1", review(), fid)
    assert subject == BATCH and found == F_BLOCK and held_entry["material"] == "m-batch"


def refusal_for(rev, fid):
    result = accepting.overrule_check("p1", rev, fid)
    assert isinstance(result, accepting.Refusal), result
    return result


def test_scn_yolo_298_a_harness_finding_is_refused_with_its_cause():
    for criterion in ("schema", "unit_missing", "completeness", "material", "verdict", "parts"):
        harness = {"criterion": criterion, "severity": "blocking", "text": "x"}
        rev = review(batch=entry("BLOCKED", [harness]))
        refusal = refusal_for(rev, finding_id(BATCH, harness))
        assert f"is a harness finding ({criterion})" in refusal.message and "nothing to overrule" in refusal.message
        assert refusal.fix == "l4 yolo findings p1"


def test_scn_yolo_298_a_finding_that_is_not_blocking_is_accepted_not_overruled():
    rev = review(batch=entry("NEEDS_REVISION", [F_MAJOR, F_MINOR]))
    for found in (F_MAJOR, F_MINOR):
        refusal = refusal_for(rev, finding_id(BATCH, found))
        assert f"is {found['severity']}: only a blocking finding is overruled" in refusal.message
        assert refusal.fix == f'l4 yolo accept p1 {BATCH} --reason "..."'


def test_scn_yolo_298_an_id_of_another_review_lists_the_blocking_ids_of_this_one():
    refusal = refusal_for(review(), "F-000000")
    assert "is not a finding of the latest review of p1" in refusal.message
    assert finding_id(BATCH, F_BLOCK) in refusal.message and refusal.fix == "l4 yolo findings p1"
    none = refusal_for(review(batch=entry("READY", [])), "F-000000")
    assert "blocking findings: none)" in none.message


def test_scn_yolo_298_an_entry_with_no_material_key_cannot_be_bound():
    rev = review(batch={"verdict": "NEEDS_REVISION", "digest": None, "findings": [F_BLOCK]})
    refusal = refusal_for(rev, finding_id(BATCH, F_BLOCK))
    assert "predates material keys" in refusal.message and refusal.fix == "l4 yolo review p1"


# --- when it holds (D3) -------------------------------------------------------------------------------------------


def test_an_overrule_holds_on_the_same_material_and_finding_only():
    fid = finding_id(BATCH, F_BLOCK)
    state = state_of(overrule_event(fid))
    assert accepting.overrule_holds(state, review()) == {fid: True}
    assert accepting.overrule_holds(state, review(batch=entry("NEEDS_REVISION", [F_BLOCK], "m-other"))) == {fid: False}
    assert accepting.overrule_holds(state, review(batch=entry("NEEDS_REVISION", [F_MAJOR]))) == {fid: False}
    assert accepting.overrule_holds(state, {"units": {}, "batches": {}}) == {fid: False}
    withdrawn = state_of(
        overrule_event(fid), PlanEvent("plan.overrule_withdrawn", "2026-11-01T11:00:00Z", {"finding": fid})
    )
    assert accepting.overrule_holds(withdrawn, review()) == {}


# --- what is left (D4) ---------------------------------------------------------------------------------------------


def test_scn_yolo_300_the_subject_after_its_overruled_findings():
    f1 = finding_id(BATCH, F_BLOCK)
    assert accepting.effective(BATCH, entry("BLOCKED", [F_BLOCK, F_MAJOR]), {f1}) == ("NEEDS_REVISION", [F_MAJOR])
    assert accepting.effective(BATCH, entry("NEEDS_REVISION", [F_BLOCK, F_MINOR]), {f1}) == ("READY", [F_MINOR])
    assert accepting.effective(BATCH, entry("NEEDS_REVISION", [F_BLOCK, F_BLOCK2]), {f1}) == (
        "NEEDS_REVISION", [F_BLOCK2],
    )  # fmt: skip
    assert accepting.effective(BATCH, entry("BLOCKED", [F_BLOCK, F_BLOCK2]), {f1}) == ("BLOCKED", [F_BLOCK2])


def test_a_harness_finding_left_keeps_the_entrys_verdict_and_nothing_held_changes_nothing():
    harness = {"criterion": "schema", "severity": "blocking", "text": "x"}
    f1 = finding_id(BATCH, F_BLOCK)
    assert accepting.effective(BATCH, entry("BLOCKED", [F_BLOCK, harness]), {f1}) == ("BLOCKED", [harness])
    assert accepting.effective(BATCH, entry("NEEDS_REVISION", [F_BLOCK]), set()) == ("NEEDS_REVISION", [F_BLOCK])
    assert accepting.effective(BATCH, entry("BLOCKED", []), {f1}) == ("BLOCKED", [])  # nothing to overrule


# --- the fold (D8) -------------------------------------------------------------------------------------------------


def test_scn_yolo_303_the_fold_keeps_a_persons_overrule_and_ignores_another_actor():
    fid = finding_id(BATCH, F_BLOCK)
    assert fid in state_of(overrule_event(fid)).overruled
    assert state_of(overrule_event(fid, actor="agent")).overruled == {}
    assert state_of(overrule_event(fid, actor=None)).overruled == {}


def test_a_later_overrule_replaces_the_earlier_and_a_withdrawal_removes_it():
    fid = finding_id(BATCH, F_BLOCK)
    state = state_of(
        overrule_event(fid, material="m-1"), overrule_event(fid, material="m-2", at="2026-11-02T00:00:00Z")
    )
    assert state.overruled[fid]["material"] == "m-2" and state.overruled[fid]["at"] == "2026-11-02T00:00:00Z"
    gone = state_of(overrule_event(fid), PlanEvent("plan.overrule_withdrawn", "2026-11-03T00:00:00Z", {"finding": fid}))
    assert gone.overruled == {}


def test_an_overrule_after_the_plan_is_final_is_ignored_and_the_activation_keeps_its_own_list():
    fid = finding_id(BATCH, F_BLOCK)
    cancelled = PlanEvent("plan.cancelled", "2026-11-01T09:30:00Z", {"by": "alex", "reason": "r"})
    assert state_of(cancelled, overrule_event(fid)).overruled == {}
    row = {"subject": BATCH, "criterion": "missing_dependency", "severity": "blocking", "text": "t", "reason": "r",
           "by": "alex", "actor": "person", "at": "2026-11-01T10:00:00Z"}  # fmt: skip
    activated = PlanEvent(
        "plan.activated", "2026-11-01T12:00:00Z", {"plan_digest": "d", "by": "alex", "overruled": {fid: row}}
    )
    assert state_of(activated).activated_overruled == {fid: row}
