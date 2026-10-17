"""detect-test-tamper 4.2 (L4-VER-033, L4-VER-034): which way each audit test ran, and the fallback."""

from l4.verifier.audit import BASE_RUN_ENV, AuditOutcome, _judge_written
from l4.verifier.support_base import SupportPlan

from ..implementer.conftest import KNOWN, UNKNOWN_TEST, green_step, red_step
from .test_ladder_depth import JUDGE, audited_criterion, writer_step

BUILDERS = "CODE = 'SAVE10'\n"
USES_BUILDERS = (
    "import pytest\n\nfrom helpers.builders import CODE\nfrom pytdd.pricing import apply_discount\n\n\n"
    f'@pytest.mark.l4("{KNOWN}")\ndef test_known_code():\n    assert apply_discount(50.0, CODE) == 45.0\n\n\n'
    + UNKNOWN_TEST
)
CONFTEST_CODES = "import pytest\n\n\n@pytest.fixture\ndef codes():\n    return ['SAVE10']\n"
AUDIT_NEEDS_CODES = (
    'import pytest\nfrom pytdd.pricing import apply_discount\n\n\n@pytest.mark.l4("{cid}")\n'
    "def test_audit_known_code(codes):\n    assert apply_discount(100.0, codes[0]) == 90.0\n"
)
UNIT_DIR = "openspec/changes/add-discount-codes"


def run_with(run_l4, with_verifier, red_writes, audit_code):
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    red = red_step()
    red.writes = {**red.writes, **red_writes}
    return cid, run_l4([red, green_step(), writer_step(cid, audit_code), JUDGE], **config)


def test_a_unit_test_that_needs_the_units_helper_does_not_stop_the_audit_run(
    run_l4, valid_spec, with_verifier
):  # SCN-VER-115
    from .test_ladder_depth import AUDIT_KNOWN

    writes = {"tests/helpers/builders.py": BUILDERS, "tests/test_discount.py": USES_BUILDERS}
    cid, run = run_with(run_l4, with_verifier, writes, AUDIT_KNOWN)
    [audit] = run.events("verify.audit")
    assert (audit["criterion"], audit["status"], audit["support"]) == (cid, "accepted", "base")
    assert audit["support_files"] == ["tests/helpers/builders.py"]


def test_an_audit_test_that_needs_the_units_fixture_falls_back_after_a_clean_scan(
    run_l4, valid_spec, with_verifier
):  # SCN-VER-116
    cid, run = run_with(run_l4, with_verifier, {"tests/conftest.py": CONFTEST_CODES}, AUDIT_NEEDS_CODES)
    [audit] = run.events("verify.audit")
    assert (audit["status"], audit["support"], audit["support_files"]) == ("accepted", "head", ["tests/conftest.py"])
    assert run.outcome["units"][0]["verdict"] == "PASS"


def test_no_fallback_when_step_1_could_not_read_the_support_files(run_l4, valid_spec, with_verifier):  # SCN-VER-117
    writes = {"tests/conftest.py": CONFTEST_CODES, "tests/helpers/setup.ts": "export const x = 1;\n"}
    cid, run = run_with(run_l4, with_verifier, writes, AUDIT_NEEDS_CODES)
    [audit] = run.events("verify.audit")
    assert audit["status"] == "rejected" and audit["support"] == ""
    assert audit["reason"].startswith("it does not run with the unit's support files at the base")
    assert "step 1's content scan did not read them" in audit["reason"]
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert "an audit test was rejected" in text or "## Rejected audit tests" in text


def test_the_zero_value_run_uses_the_same_support_files_as_the_head_run(make_bench, monkeypatch):  # SCN-VER-118
    bench = make_bench([])
    wb = bench.wb
    base = wb.head()
    (wb.worktree / "tests").mkdir(exist_ok=True)
    (wb.worktree / "tests/conftest.py").write_text("import pytest\n")
    wb.git.run("add", "tests/conftest.py")
    wb.git.run("-c", "user.name=a", "-c", "user.email=a@b.invalid", "commit", "-q", "-m", "unit conftest")
    cid = "C-0a1b2c3d"
    rel = f"tests/test_l4_audit_c_{cid.removeprefix('C-')}_r1.py"
    (wb.worktree / rel).write_text(
        f'import pytest\nfrom pytdd.pricing import total\n\n\n@pytest.mark.l4("{cid}")\n'
        "def test_audit_total():\n    assert total([1.0]) == 1.0\n"
    )
    seen = []
    gates = []

    def gate(name, command, *, reports=(), extra_env=None, **kw):
        from types import SimpleNamespace

        from l4.gates.junit import TestCase, TestReport

        gates.append((name, (wb.worktree / "tests/conftest.py").exists(), dict(extra_env or {})))
        stem = f"test_l4_audit_c_{cid.removeprefix('C-')}_r1"
        report = TestReport({f"tests.{stem}::test_audit_total": TestCase(f"tests.{stem}::test_audit_total", "passed")})
        return SimpleNamespace(report=report, log_path=wb.worktree / "none.log", reason="")

    monkeypatch.setattr(wb, "run_gate", gate)

    def recorder(wb_, candidates, *, extra_env=None):
        from l4.implementer.discrimination import PreSatisfied

        seen.append(((wb_.worktree / "tests/conftest.py").exists(), dict(extra_env or {})))
        return PreSatisfied({c: tuple(t) for c, t in candidates.items()}, {})

    monkeypatch.setattr("l4.verifier.audit.confirm_pre_satisfied", recorder)
    out = AuditOutcome()
    plan = SupportPlan((("tests/conftest.py", "A"),), True, "", base)
    _judge_written(wb, {cid: rel}, 1, out, support=plan)
    assert [(r.status, r.support, r.reason) for r in out.records] == [("accepted", "base", "")]
    assert gates == [("audit-base-support", False, BASE_RUN_ENV)]  # the head run: the conftest is set aside
    assert seen == [(False, BASE_RUN_ENV)]  # and so is the zero-value run's
    assert (wb.worktree / "tests/conftest.py").read_text() == "import pytest\n"  # back after the run
