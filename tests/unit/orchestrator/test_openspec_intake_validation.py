"""L4-ADO-007: a single OpenSpec unit is validated strictly before any agent runs (SCN-ADO-20, -21, -22)."""

from l4.agents.fake import Step
from l4.specs.openspec import ARCHIVE_REFUSAL, intake_hint

from ..implementer.conftest import green_step, red_step
from ..specs.fixcli import patch_openspec
from .conftest import UNIT_DIR, new_origin_main

SPEC = f"{UNIT_DIR}/specs/pricing/spec.md"
MISSING = f"{ARCHIVE_REFUSAL} dreaming: target spec does not exist; only ADDED requirements are allowed."
NO_PURPOSE = (
    "## ADDED Requirements\n\n### Requirement: Discount codes\nSAVE10 is a known code.\n\n"
    '#### Scenario: Known code\n- **WHEN** `apply_discount(50.0, "SAVE10")` is called\n- **THEN** it returns `45.0`\n'
)


def test_a_strict_validation_error_rejects_the_unit_with_the_hint_before_any_agent(run_l4, monkeypatch):  # SCN-ADO-20
    patch_openspec(monkeypatch, valid=False, message=MISSING)
    run = run_l4([red_step(), green_step()])
    assert run.code == 14 and run.adapter.requests == []
    (event,) = run.local_events("unit.rejected")
    reasons = "\n".join(event["reasons"])
    assert MISSING in reasons and intake_hint(MISSING, "main") in reasons
    assert run.local_events("task.started") == []


def test_every_reason_is_recorded_and_the_purpose_is_one_of_them(run_l4, monkeypatch, tdd_repo, raw):
    patch_openspec(monkeypatch, valid=False, message="MODIFIED omits scenario(s): one. Copy the omitted scenarios")
    new_origin_main(tdd_repo, raw, {SPEC: NO_PURPOSE})
    run = run_l4([Step()])
    assert run.code == 14 and run.adapter.requests == []
    (event,) = run.local_events("unit.rejected")
    assert len(event["reasons"]) == 2
    assert "Copy the omitted scenarios" in event["reasons"][0] and "Purpose" in event["reasons"][1]


def test_a_new_capability_without_a_purpose_is_rejected(run_l4, monkeypatch, tdd_repo, raw):  # SCN-ADO-21
    patch_openspec(monkeypatch)
    new_origin_main(tdd_repo, raw, {SPEC: NO_PURPOSE})
    run = run_l4([red_step(), green_step()])
    assert run.code == 14 and run.adapter.requests == []
    (event,) = run.local_events("unit.rejected")
    assert len(event["reasons"]) == 1 and "Purpose" in event["reasons"][0] and "pricing" in event["reasons"][0]


def test_a_valid_change_starts_as_before(run_l4, monkeypatch):  # SCN-ADO-22
    patch_openspec(monkeypatch)
    run = run_l4([red_step(), green_step()])
    assert run.code == 0 and run.local_events("unit.rejected") == []
    assert run.local_events("task.started")
