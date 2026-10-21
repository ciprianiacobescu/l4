"""detect-test-tamper 4.3 (L4-VER-036): verification.md says how each audit test ran and lists the allowed changes."""

from l4.verifier.evidence import restore_round
from l4.verifier.report import render_verification_md, verdict_json
from l4.verifier.types import AuditRecord, IntegrityCheck, IntegrityReport

from .test_report import result

REJECTION = (
    "it does not run with the unit's support files at the base (E   fixture 'codes' not found), and a run with them "
    "needs step 1's content scan to have read them: step 1's content scan did not read them: not checked: python only"
)


def audits():
    return [
        AuditRecord("C-5a1b2c3d", "accepted", "tests/test_l4_audit_c_5a1b2c3d_r1.py", ("t1",), "", "base",
                    ("tests/conftest.py",)),
        AuditRecord("C-1a1b2c3d", "accepted", "tests/test_l4_audit_c_1a1b2c3d_r1.py", ("t2",), "", "head",
                    ("tests/conftest.py",)),
        AuditRecord("C-2a1b2c3d", "accepted", "tests/test_l4_audit_c_2a1b2c3d_r1.py", ("t3",), "", "unchanged"),
        AuditRecord("C-3a1b2c3d", "skipped", "", (), "cap"),
    ]  # fmt: skip


def test_the_audit_table_has_a_support_column_and_the_allowed_changes_have_a_section():  # SCN-VER-120
    integrity = IntegrityReport(
        [IntegrityCheck("pre-existing tests", "ok", "1 test file(s) compared with the base (+1 allowed, listed)")],
        allowed_tests=["tests/test_pricing.py::test_total_adds_prices changed (task 2.1: [test-infra])"],
        mocked_support=["tests/conftest.py: patches pytdd.pricing.apply_discount in a fixture a test requests"],
    )
    text = render_verification_md(result(audit=audits(), integrity=integrity))
    assert "| Criterion | Status | Test | Support | Reason |" in text
    audit_lines = text.split("## Audit\n")[1].split("\n## ")[0].splitlines()
    rows = {line.split("|")[1].strip(): line.split("|")[4].strip() for line in audit_lines if line.startswith("| C-")}
    assert rows == {"C-5a1b2c3d": "base", "C-1a1b2c3d": "head", "C-2a1b2c3d": "-", "C-3a1b2c3d": "-"}
    assert "## Pre-existing tests changed with an allowance (L4-VER-031)" in text
    assert "- tests/test_pricing.py::test_total_adds_prices changed (task 2.1: [test-infra])" in text
    assert text.index("## Pre-existing tests changed with an allowance") < text.index("## Audit")
    assert "- tests/conftest.py: patches pytdd.pricing.apply_discount in a fixture a test requests" in text


def test_the_new_fields_survive_a_reload_and_an_old_round_without_them_loads():  # SCN-VER-120
    integrity = IntegrityReport([IntegrityCheck("pre-existing tests", "ok", "")], allowed_tests=["x::y changed (z)"])
    body = verdict_json(result(audit=audits(), integrity=integrity))
    again = restore_round(body, "openspec:x", 2)
    assert [(a.support, a.support_files) for a in again.audit[:2]] == [
        ("base", ("tests/conftest.py",)),
        ("head", ("tests/conftest.py",)),
    ]
    assert again.integrity is not None and again.integrity.allowed_tests == ["x::y changed (z)"]
    for row in body["audit"]:
        del row["support"], row["support_files"]
    del body["integrity"]["allowed_tests"], body["integrity"]["mocked_support"]
    old = restore_round(body, "openspec:x", 2)
    assert [a.support for a in old.audit] == ["", "", "", ""] and old.integrity.allowed_tests == []


def test_a_rejected_audit_test_says_why_it_did_not_run_at_the_base():  # SCN-VER-123
    rejected = AuditRecord("C-4a1b2c3d", "rejected", "tests/test_l4_audit_c_4a1b2c3d_r1.py", (), REJECTION)
    text = render_verification_md(result(audit=[rejected]))
    section = text.split("## Rejected audit tests")[1]
    assert "C-4a1b2c3d: it does not run with the unit's support files at the base" in section
    assert "step 1's content scan did not read them" in section
