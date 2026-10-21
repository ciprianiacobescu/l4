"""Resume at aggregation (verifier 5.2, design D4): `subject_sha` and the conditions for reusing a round."""

import json

from l4.vcs.git import Git
from l4.verifier.evidence import restore_round, reusable, subject_sha
from l4.verifier.report import verdict_json
from l4.verifier.types import (
    CriterionEvidence,
    Finding,
    GateLine,
    IntegrityCheck,
    IntegrityReport,
    Severity,
    StepRecord,
    TracingTest,
    Verdict,
    VerifyResult,
)

from ._integrity_helpers import UNIT, UNIT_DIR, new_repo


def commit_phase(repo, files, phase, message="work"):
    repo.write(files)
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", message, f"--trailer=L4-Unit: {UNIT}", "--trailer=L4-Run: r-1",
             "--trailer=L4-Iteration: 1", f"--trailer=L4-Phase: {phase}")  # fmt: skip
    return repo.git("rev-parse", "HEAD").strip()


def test_subject_is_the_last_commit_that_is_neither_evidence_nor_an_answer(tmp_path, git_environ):
    repo, _ = new_repo(tmp_path, git_environ)
    code = commit_phase(repo, {"src/a.py": "X = 1\n", f"{UNIT_DIR}/tasks.md": "- [x] 1\n"}, "implementing")
    commit_phase(repo, {f"{UNIT_DIR}/.l4/ledger/r-1.jsonl": "{}\n"}, "awaiting_human", "chore: ledger")
    commit_phase(repo, {f"{UNIT_DIR}/verification.md": "v\n", f"{UNIT_DIR}/.l4/evidence/round-1/verdict.json": "{}"},
                 "verifying", "docs: verification round 1")  # fmt: skip
    commit_phase(repo, {f"{UNIT_DIR}/questions.md": "q\n"}, "awaiting_human", "docs: questions")
    commit_phase(repo, {"tests/test_l4_audit_c_aaaaaaaa_r1.py": "x\n"}, "verifying", "test: verifier round 1")
    commit_phase(repo, {".serena/memories/harness/lessons.md": "l\n"}, "lessons", "chore(memory)")
    head = commit_phase(repo, {f"{UNIT_DIR}/questions.md": "answered\n"}, "implementing", "answer Q-001")
    assert subject_sha(Git(repo.path, environ=git_environ), head, [UNIT_DIR]) == code


def test_human_push_restarts_at_step_0(tmp_path, git_environ):
    repo, _ = new_repo(tmp_path, git_environ)
    commit_phase(repo, {"src/a.py": "X = 1\n"}, "implementing")
    git = Git(repo.path, environ=git_environ)
    before = subject_sha(git, git.rev_parse("HEAD"), [UNIT_DIR])
    edit = commit_phase(repo, {"src/a.py": "X = 2\n"}, "implementing", "a human edits the code")
    spec = commit_phase(repo, {f"{UNIT_DIR}/specs/x/spec.md": "s\n"}, "implementing", "a human edits the spec")
    assert subject_sha(git, edit, [UNIT_DIR]) == edit != before
    assert subject_sha(git, spec, [UNIT_DIR]) == spec


def test_a_commit_with_no_trailer_that_touches_code_is_a_subject(tmp_path, git_environ):
    repo, _ = new_repo(tmp_path, git_environ)
    repo.write({"src/a.py": "X = 1\n"})
    human = repo.commit("a human, no trailer", unit=UNIT)  # carries trailers: the path decides
    git = Git(repo.path, environ=git_environ)
    assert subject_sha(git, human, [UNIT_DIR]) == human


def prev(**over):
    base = {"schema": "l4/verdict@1", "verdict": "NEEDS_HUMAN", "subject_sha": "abc", "family_criteria": ["C-a", "C-b"]}
    return {**base, **over}


def test_reuse_needs_the_same_subject_the_same_criteria_and_a_needs_human_round():
    ids = ["C-b", "C-a"]
    assert reusable(prev(), "abc", ids)
    assert not reusable(prev(), "def", ids)  # a commit arrived
    assert not reusable(prev(), "abc", ["C-a", "C-b", "C-c"])  # a fix unit added a criterion
    assert not reusable(prev(verdict="FAIL"), "abc", ids)
    assert not reusable(prev(subject_sha=""), "", ids)
    assert not reusable(None, "abc", ids)


def test_a_round_restores_from_its_verdict_json_with_steps_marked_reused():
    result = VerifyResult(
        UNIT, 1, Verdict.NEEDS_HUMAN, "b" * 40, "c" * 40, judge_profile="judge", subject_sha="abc",
        steps=[StepRecord("0", "preconditions", "ok"), StepRecord("4a", "audit sampling", "not_run", note="empty"),
               StepRecord("10", "aggregation", "ok")],
        gates=[GateLine("test", "pytest", "pass", "", "log")], tests={"t::a": "passed"}, red_green={"t::a": "1.1"},
        findings=[Finding(Severity.MINOR, "nit", "d", "judge", "C-a")], holds=["a hold"], judge_calls=2,
        trace=[CriterionEvidence("C-a", "alias", "covered", (TracingTest("t::a", "passed", "zero_value", False),),
                                 (("t::b", "why"),), "held")],
        integrity=IntegrityReport(
            [IntegrityCheck("scan", "ok", "n")], [Finding(Severity.MINOR, "m", "d", "deterministic")], ["decl"]
        ),
        judge_verdict={"criteria": []}, prompt_sha256="p" * 64,
    )  # fmt: skip
    data = json.loads(json.dumps(verdict_json(result)))
    back = restore_round(data, UNIT, 2)
    assert back.round == 2 and back.reused_from == 1 and back.subject_sha == "abc"
    assert [(s.step, s.status) for s in back.steps] == [("0", "reused"), ("4a", "not_run")]
    assert back.steps[0].note == "reused (round 1)"
    assert back.gates == result.gates and back.tests == result.tests and back.holds == ["a hold"]
    assert back.findings == result.findings and back.trace == result.trace
    assert back.integrity == result.integrity and back.judge_verdict == {"criteria": []}
    assert back.judge_calls == 2 and back.prompt_sha256 == "p" * 64


# --- the base merge commit (verifier 5.2 with M1.7: a merge that brings code is a new subject) -----------------------


def unit_behind_main(tmp_path, git_environ, main_files):
    """A unit branch with code (implementing) and a round's evidence (verifying); `main` then moves on by `main_files`.
    The checkout is left on the unit branch. Returns (repo, git, code commit, evidence commit)."""
    repo, _ = new_repo(tmp_path, git_environ)
    repo.git("checkout", "-q", "-b", "unit")
    code = commit_phase(repo, {"src/a.py": "X = 1\n"}, "implementing")
    evidence = commit_phase(repo, {f"{UNIT_DIR}/verification.md": "v\n"}, "verifying", "docs: verification round 1")
    repo.git("checkout", "-q", "main")
    commit_phase(repo, main_files, "implementing", "main moved")
    repo.git("checkout", "-q", "unit")
    return repo, Git(repo.path, environ=git_environ), code, evidence


def merge_main(repo, phase="verifying"):
    repo.git("merge", "--no-ff", "-q", "-m", f"chore: merge main\n\nL4-Unit: {UNIT}\nL4-Phase: {phase}", "main")
    return repo.git("rev-parse", "HEAD").strip()


def test_base_merge_commit_is_a_new_subject(tmp_path, git_environ):
    repo, git, code, evidence = unit_behind_main(tmp_path, git_environ, {"src/b.py": "Y = 1\n"})
    assert subject_sha(git, evidence, [UNIT_DIR]) == code
    merge = merge_main(repo)  # tagged `L4-Phase: verifying`, yet it brings code the last round never saw
    assert subject_sha(git, merge, [UNIT_DIR]) == merge != code
    # evidence committed on top of the merge does not hide it
    later = commit_phase(repo, {f"{UNIT_DIR}/verification.md": "v2\n"}, "verifying", "docs: verification round 2")
    assert subject_sha(git, later, [UNIT_DIR]) == merge


def test_merge_with_empty_first_parent_diff_is_not_a_subject(tmp_path, git_environ):
    # main made the very change the unit has: the merge adds nothing to the unit's tree
    repo, git, code, evidence = unit_behind_main(tmp_path, git_environ, {"src/a.py": "X = 1\n"})
    assert merge_main(repo)
    assert repo.git("diff", "--name-only", "HEAD^1", "HEAD").strip() == ""
    assert subject_sha(git, "HEAD", [UNIT_DIR]) == code
    # and a merge that brings only harness-owned files is not a subject either
    (tmp_path / "second").mkdir()
    repo2, git2, code2, _ = unit_behind_main(tmp_path / "second", git_environ, {f"{UNIT_DIR}/questions.md": "q\n"})
    merge2 = merge_main(repo2)
    assert repo2.git("diff", "--name-only", "HEAD^1", "HEAD").split() == [f"{UNIT_DIR}/questions.md"]
    assert subject_sha(git2, merge2, [UNIT_DIR]) == code2
