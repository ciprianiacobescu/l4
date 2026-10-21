"""The step 6 row says what diff coverage did not measure (SPEC L4-VER-002 step 6, SCN-VER-55, SCN-VER-56)."""

from types import SimpleNamespace

import pytest

from l4.config.schema import L4Config
from l4.evidence.diffcov import DiffCoverage, check_diff_coverage
from l4.verifier import ladder

REASON = "diff coverage measures python only; changed code outside it: web/app.tsx"


def _row(dc: DiffCoverage, mode: str, monkeypatch):
    cfg = L4Config.model_validate({"verifier": {"evidence": {"diff_coverage": {"mode": mode}}}})
    ev = SimpleNamespace(coverage=dc, coverage_check=check_diff_coverage(dc, cfg), later_holds=[])
    run = SimpleNamespace(evidence=ev, records={}, result=SimpleNamespace(findings=[], holds=[], subject_sha="s"))
    monkeypatch.setattr(ladder, "_emit_step", lambda *a, **k: None)
    ladder._quality_step(SimpleNamespace(wb=SimpleNamespace(cfg=cfg)), run)
    return run.records["6"], run.result


@pytest.mark.parametrize("mode", ["warn", "fail"])
def test_not_applicable_row_says_not_measured_and_adds_no_hold_or_finding(monkeypatch, mode):
    dc = DiffCoverage(0.0, status="not_applicable", reason=REASON, other_files=("web/app.tsx",))
    row, result = _row(dc, mode, monkeypatch)
    assert row.status == "ok" and row.note == f"not measured: {REASON}"
    assert result.findings == [] and result.holds == []


def test_mixed_row_keeps_the_percentage_and_names_the_rest(monkeypatch):
    row, _ = _row(DiffCoverage(100.0, other_files=("web/app.tsx",)), "fail", monkeypatch)
    assert row.note == f"100.0% of the changed executable lines ran; not measured: {REASON}"
