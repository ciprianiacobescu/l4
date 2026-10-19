"""In the verifier a refused harness write is a blocker (L4-SEC-021 part c, SCN-SEC-47) and an audit test file under a
planted link is not removed through it (L4-SEC-020)."""

import shutil

from l4.implementer.discrimination import discriminate_extra, unit_base
from l4.implementer.tdd import run_green, run_red
from l4.specs.base import Task
from l4.verifier.aggregate import aggregate_unit
from l4.verifier.audit import _drop_file
from l4.verifier.ladder import _unsafe_findings
from l4.verifier.types import Severity, Verdict

from ..implementer.conftest import green_step, red_step
from ..implementer.test_planted_links import nothing_in, planted, swap_cmd

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)


def test_a_link_planted_during_the_verifiers_discrimination_run_is_a_blocker_and_the_verdict_is_fail(
    make_bench, tmp_path
):
    """SCN-SEC-47: `test-extra-zero` is the verifier's run of tests that people or a chore wrote"""
    outside = tmp_path / "outside"
    outside.mkdir()
    armed = tmp_path / "armed"
    bench = make_bench([red_step(), green_step()], test={"command": swap_cmd(outside, f"[ -f {armed} ]")})
    red = run_red(bench.wb, TASK, attempt=1)
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok"
    wb = bench.wb
    wb.unsafe.clear()
    base = unit_base(wb) or red.sha
    armed.write_text("")  # from here on the unit's test code plants the link
    discriminate_extra(wb, ["tests.test_discount::test_known_code"], base)  # nothing is raised
    assert nothing_in(outside)
    assert (wb.worktree / "src/pytdd").is_dir() and not (wb.worktree / "src/pytdd").is_symlink()
    assert planted(bench, "src/pytdd")
    findings = _unsafe_findings(wb)
    assert [f.title for f in findings] == ["a gate run planted a symbolic link in the worktree"]
    assert findings[0].severity is Severity.BLOCKER and "src/pytdd" in findings[0].detail
    assert aggregate_unit(findings, [], []) is Verdict.FAIL


def test_no_record_means_no_finding(make_bench):
    assert _unsafe_findings(make_bench([]).wb) == []


def test_an_audit_test_file_under_a_planted_link_is_not_removed_through_it(make_bench, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test_l4_audit_c_1_r1.py").write_text("outside\n")
    wb = make_bench([]).wb
    shutil.rmtree(wb.worktree / "tests", ignore_errors=True)
    (wb.worktree / "tests").symlink_to(outside)
    _drop_file(wb, "tests/test_l4_audit_c_1_r1.py")
    assert (outside / "test_l4_audit_c_1_r1.py").read_text() == "outside\n"
    assert [u.link for u in wb.planted_links()] == ["tests"]
    assert not (wb.worktree / "tests").is_symlink()


def test_a_generated_ui_test_file_under_a_planted_e2e_link_is_not_removed_through_it(make_bench, tmp_path):
    """The writer's file is removed after agent-controlled e2e runs (verifier/generate.py): never through a link"""
    from l4.verifier.generate import _drop_generated

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test_l4_gen.py").write_text("outside\n")
    wb = make_bench([]).wb
    (wb.worktree / "e2e").symlink_to(outside)
    _drop_generated(wb, wb.worktree, "e2e/test_l4_gen.py")
    assert (outside / "test_l4_gen.py").read_text() == "outside\n"
    assert [u.link for u in wb.planted_links()] == ["e2e"]
    assert not (wb.worktree / "e2e").is_symlink()
    assert [f.title for f in _unsafe_findings(wb)] == ["a gate run planted a symbolic link in the worktree"]
