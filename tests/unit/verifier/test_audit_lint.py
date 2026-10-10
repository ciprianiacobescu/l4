"""M1.12 lines 8-14 (L4-VER-002 step 4a): an audit test is linted inside the audit step, and a lint failure never
reaches a hand-off head. The lint gate itself stays at step 2: moving it after 4a would fail the ladder on a test the
verifier wrote."""

import shlex
import sys

from l4.agents.base import RunResult  # noqa: F401  (keeps the helper imports below in one place)

from ..implementer.conftest import green_step, red_step
from ..orchestrator.conftest import BRANCH, UNIT_DIR
from .test_ladder_depth import (  # noqa: F401  (the fixtures and scripted steps of the audit end-to-end tests)
    AUDIT_KNOWN,
    JUDGE,
    audited_criterion,
    steps_of,
    writer_step,
)

# a stand-in for `ruff check`: it flags `import os` in an audit test, and reads no other file
FLAG = "import os"
LINT_SCRIPT = (
    "import glob, sys\n"
    "bad = [f for f in sorted(glob.glob('tests/test_l4_audit_*.py')) if 'import os' in open(f).read()]\n"
    "print(*[f + ':1:8: F401 `os` imported but unused' for f in bad], sep='\\n')\n"
    "sys.exit(1 if bad else 0)\n"
)
LINT = f"{sys.executable} -c {shlex.quote(LINT_SCRIPT)}"
UNUSED_IMPORT = f"{FLAG}\n" + AUDIT_KNOWN
CLEAN = AUDIT_KNOWN.replace("import pytest\n", "import pytest\n\n", 1)  # the fixture project sorts imports


def audit_path(cid: str, round_no: int = 1) -> str:
    return f"tests/test_l4_audit_c_{cid.removeprefix('C-')}_r{round_no}.py"


def run_with(run_l4, with_verifier, replies):
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    steps = [red_step(), green_step(), *[writer_step(cid, code) for code in replies], JUDGE]
    return cid, run_l4(steps, lint=[LINT], **config)


def test_an_audit_test_with_a_lint_failure_is_rejected_not_committed_and_never_judged(
    run_l4, valid_spec, with_verifier
):
    cid, run = run_with(run_l4, with_verifier, [UNUSED_IMPORT, UNUSED_IMPORT])
    [audit] = run.events("verify.audit")
    assert audit["criterion"] == cid and audit["status"] == "rejected"
    assert audit["reason"].startswith("lint:") and "F401" in audit["reason"]
    assert "verifier round 1" not in " ".join(run.subjects())  # nothing of the round was committed
    assert audit_path(cid) not in run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", BRANCH).split()
    assert steps_of(run)["2"] == "ok" and steps_of(run)["4a"] == "ok"  # step 2 did not fail: the gate stayed there
    judge_prompt = run.adapter.requests[-1].prompt
    assert "## Written by the harness this round" not in judge_prompt and "test_audit_known_code" not in judge_prompt


def test_the_writer_gets_the_lint_output_once_and_a_fixed_test_is_accepted(run_l4, valid_spec, with_verifier):
    cid, run = run_with(run_l4, with_verifier, [UNUSED_IMPORT, CLEAN])
    assert run.code == 0
    retry = run.adapter.requests[3].prompt  # red, green, writer, writer again
    assert "## Your previous attempt was rejected" in retry and "F401" in retry and "import os" in retry
    assert run.adapter.requests[2].prompt.count("F401") == 0
    [audit] = run.events("verify.audit")
    assert audit["status"] == "accepted" and audit["path"] == audit_path(cid)
    committed = run.pushed(audit_path(cid))
    assert "import os" not in committed and "def test_audit_known_code" in committed
    assert [e["outcome"] for e in run.events("verify.audit_lint")] == ["failed", "fixed"]
    assert len(run.adapter.requests) == 5  # one extra writer call, never a third


def test_a_test_that_still_fails_lint_after_the_retry_never_reaches_the_head_and_does_not_block_a_supported_pass(
    run_l4, valid_spec, with_verifier
):
    """The damage line of M1.12: a lint failure must not reach a hand-off head, whatever else happens. The audit test is
    a sample on a criterion that real tests already trace, so a rejected one (like any rejected audit test) is a minor
    finding and does not hold the criterion: the judge's PASS on the unit's own evidence stands (review fix)."""
    cid, run = run_with(run_l4, with_verifier, [UNUSED_IMPORT, UNUSED_IMPORT])
    assert run.code == 0, "a lint-rejected audit test must not turn a supported PASS into needs_human"
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert "lint:" in text and cid in text and "Rejected audit tests" in text
    assert [e["verdict"] for e in run.events("verify.verdict")] == ["PASS"]
    tree = run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", BRANCH).split()
    assert not [p for p in tree if "test_l4_audit" in p]  # no audit test at the hand-off head
    for commit in run.raw(run.tdd.origin, "rev-list", BRANCH).split():
        files = run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", commit).split()
        assert not [p for p in files if "test_l4_audit" in p]  # nor in any commit of the branch


def test_a_fix_that_breaks_the_test_is_not_accepted_on_the_strength_of_its_lint(run_l4, valid_spec, with_verifier):
    """The retried test is checked like a new one: it must still pass at head and fail against zero values."""
    cid, run = run_with(run_l4, with_verifier, [UNUSED_IMPORT, AUDIT_KNOWN.replace("== 90.0", "== 91.0")])
    [audit] = run.events("verify.audit")
    assert audit["status"] == "failed"  # fails at head: held as an audit failure always was
    assert "verifier round 1" not in " ".join(run.subjects())
    assert run.code == 11


def test_without_a_lint_gate_nothing_changes(run_l4, valid_spec, with_verifier):
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    run = run_l4([red_step(), green_step(), writer_step(cid, UNUSED_IMPORT), JUDGE], **config)
    assert run.code == 0
    [audit] = run.events("verify.audit")
    assert audit["status"] == "accepted" and run.events("verify.audit_lint") == []
    assert not [e for e in run.events("gate.finished") if e["name"].endswith("-audit")]  # no lint gate was called


def test_the_lint_runs_on_the_audit_test_only_through_the_same_gate_runner(
    run_l4, valid_spec, with_verifier, monkeypatch
):
    from l4.implementer.workbench import Workbench

    calls: list[tuple[str, str, object]] = []
    original = Workbench.run_gate

    def spy(self, name, command, **kw):
        calls.append((name, command, self.worktree))
        return original(self, name, command, **kw)

    monkeypatch.setattr(Workbench, "run_gate", spy)
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    ruff = f"{sys.executable} -m ruff check ."
    run = run_l4([red_step(), green_step(), writer_step(cid, UNUSED_IMPORT), writer_step(cid, CLEAN), JUDGE],
                 lint=[ruff], **config)  # fmt: skip
    assert run.code == 0
    step2 = [c for c in calls if c[0] == "lint"]
    own = [c for c in calls if c[0] == "lint-audit"]
    assert step2 and {c[1] for c in step2} == {ruff}  # the lint gate keeps its place and its whole-repository form
    assert [c[1] for c in own] == [
        f"{sys.executable} -m ruff check {audit_path(cid)}"
    ] * 2  # the failing file, then its fix
    assert {c[2] for c in own} == {c[2] for c in step2}  # the same worktree, so the same sandbox and gate log folder
    assert [e["outcome"] for e in run.events("verify.audit_lint")] == ["failed", "fixed"]
    first = next(e for e in run.events("verify.audit_lint"))
    assert first["reason"].startswith(("F401", "I001"))  # the first line of ruff's own output


def test_a_command_that_cannot_be_narrowed_runs_as_configured_and_still_guards_the_hand_off(
    run_l4, valid_spec, with_verifier
):
    cid, run = run_with(run_l4, with_verifier, [UNUSED_IMPORT, UNUSED_IMPORT])  # LINT is a script, not `ruff check`
    assert run.events("verify.audit")[0]["status"] == "rejected"


def test_the_judge_lists_the_accepted_audit_test_with_the_other_per_test_outcomes(run_l4, valid_spec, with_verifier):
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    run = run_l4([red_step(), green_step(), writer_step(cid, AUDIT_KNOWN), JUDGE], **config)
    prompt = run.adapter.requests[-1].prompt
    listing = prompt.partition("Per-test outcome of the full test gate")[2].partition("Traceability")[0]
    stem = f"tests.test_l4_audit_c_{cid.removeprefix('C-')}_r1::test_audit_known_code"
    assert f"{stem}  passed  (audit" in listing  # in the list, labelled, not only in the matrix


def test_a_rejected_audit_test_is_not_listed_for_the_judge_and_has_its_own_section_with_the_reason(
    run_l4, valid_spec, with_verifier
):
    cid, run = run_with(run_l4, with_verifier, [UNUSED_IMPORT, UNUSED_IMPORT])
    listing = (
        run.adapter.requests[-1].prompt.partition("Per-test outcome of the full test gate")[2].partition("Trace")[0]
    )
    assert "test_l4_audit" not in listing and "(audit" not in listing
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    section = text.partition("## Rejected audit tests")[2].partition("\n## ")[0]
    assert cid in section and "lint:" in section and "F401" in section


def test_the_per_test_list_is_built_from_the_audit_records_not_the_gate_run():
    """Reproduction of the live finding (PR-2, MF-3): the matrix named an audit test the per-test list did not hold."""
    from l4.verifier.ladder import _gate_summary
    from l4.verifier.types import AuditRecord, CriterionEvidence, TracingTest, Verdict, VerifyResult

    stem = "tests.test_l4_audit_c_0a1b2c3d_r1::test_x"
    result = VerifyResult("openspec:u", 1, Verdict.NEEDS_HUMAN, "", "abc")
    result.tests = {"tests.test_a::test_a": "passed"}
    result.trace = [CriterionEvidence("C-0a1b2c3d", "a", "covered", (TracingTest(stem, "passed", "audit"),))]
    result.audit = [AuditRecord("C-0a1b2c3d", "accepted", "tests/test_l4_audit_c_0a1b2c3d_r1.py", (stem,))]
    text = _gate_summary(result)
    listing = text.partition("Per-test outcome of the full test gate")[2].partition("Traceability")[0]
    assert f"{stem}  passed  (audit" in listing and "tests.test_a::test_a  passed" in listing
    result.audit = [
        AuditRecord("C-0a1b2c3d", "rejected", "tests/test_l4_audit_c_0a1b2c3d_r1.py", (stem,), "lint: F401")
    ]
    assert stem not in _gate_summary(result).partition("Traceability")[0]
