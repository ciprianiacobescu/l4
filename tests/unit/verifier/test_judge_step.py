"""`_judge_step` on a unit with many criteria: a judge `fail` and its never-executed counterexample."""

from l4.verifier.gates import run_build_gates
from l4.verifier.ladder import VerifyContext, _finalize, _judge_step, _Run
from l4.verifier.types import Verdict, VerifyResult

from .conftest import judge_reply
from .test_judge_run import Scripted, ok

FAILS = "from pytdd.pricing import total\n\n\ndef test_cx():\n    assert total([]) == 1.0\n"
MORE = "".join(
    f"\n#### Scenario: Extra {n}\n- **WHEN** `total([])` is called\n- **THEN** it returns `0`\n" for n in range(7)
)


def judge_unit(make_bench, verdicts: dict[int, str]):
    wb = make_bench([]).wb
    spec = wb.ref.path / "specs" / "pricing" / "spec.md"
    spec.write_text(spec.read_text() + MORE)
    assert run_build_gates(wb).ok
    criteria = wb.provider.criteria(wb.ref)
    reply = judge_reply([c.id for c in criteria])
    for position, verdict in verdicts.items():
        reply["criteria"][position]["verdict"] = verdict
        reply["criteria"][position]["counterexample"] = {"call": FAILS, "expected": "1.0", "actual": "0"}
    base = wb.git.run("rev-parse", "origin/main").stdout.strip()
    result = VerifyResult(wb.ref.id, 1, Verdict.NEEDS_HUMAN, base, wb.head())
    vc = VerifyContext(wb, Scripted(ok(reply)), "judge", ["impl"], 1, 60)  # type: ignore[arg-type]
    run = _Run(result)
    _judge_step(vc, run, base, [])
    _finalize(vc, run, criteria, [])
    return result


def test_a_judge_fail_is_needs_human_and_its_counterexample_is_never_executed(make_bench):
    result = judge_unit(make_bench, dict.fromkeys(range(3), "fail"))
    runs = [c.counterexample for c in result.criteria if c.counterexample]
    assert [r.status for r in runs] == ["unexecuted"] * 3 and "M1" in runs[0].note
    assert all(c.result == "needs_human" for c in result.criteria[:3])


def test_a_planted_symlink_where_a_snippet_used_to_be_written_is_left_alone(make_bench, tmp_path):
    """Regression: the harness once wrote the counterexample through an agent-planted `.l4-out` symlink."""
    wb = make_bench([]).wb
    victim = tmp_path / "victim.txt"
    victim.write_text("ORIGINAL")
    planted = wb.worktree / ".l4-out" / "counterexample" / "test_cx_1.py"
    planted.parent.mkdir(parents=True)
    planted.symlink_to(victim)
    judge_unit(make_bench, {0: "fail"})
    assert victim.read_text() == "ORIGINAL"


def test_a_unit_without_scenarios_records_step_9_as_not_run_for_that_reason(make_bench):
    wb = make_bench([]).wb
    spec = wb.ref.path / "specs" / "pricing" / "spec.md"
    spec.write_text("## Requirements\n")
    base = wb.git.run("rev-parse", "origin/main").stdout.strip()
    result = VerifyResult(wb.ref.id, 1, Verdict.NEEDS_HUMAN, base, wb.head())
    run = _Run(result)
    _judge_step(VerifyContext(wb, Scripted(), "judge", ["impl"], 1, 60), run, base, [])  # type: ignore[arg-type]
    assert run.records["9"].status == "not_run" and "no criteria" in run.records["9"].note


def _diff_world(make_bench):
    bench = make_bench([])
    wb = bench.wb
    unit = wb.ref.path.relative_to(wb.worktree).as_posix()
    base = wb.git.run("rev-parse", "origin/main").stdout.strip()
    files = {
        f"{unit}/verification.md": "# Verification\nROUND-1\n",  # the harness's own report of the unit
        f"{unit}-fix-1/verification.md": "# Verification\nFIX-ROUND\n",  # a fix unit's
        "docs/verification.md": "# Our verification guide\nPROJECT-DOC\n",  # a project file of the same name
        "src/pytdd/extra.py": "X = 1\n",
        "src/app/report.py": "REPORT = 1\n",
        "tests/test_report.py": "def test_report():\n    assert True\n",
        "docs/questions.md": "# Our questions\nPROJECT-QUESTIONS\n",
    }
    for folder in (unit, f"{unit}-fix-1"):  # the channel files of both unit folders (L4-VER-040)
        files[f"{folder}/questions.md"] = f"# Questions\nCHANNEL-Q {folder}\n"
        files[f"{folder}/feedback.md"] = f"# Feedback\nCHANNEL-F {folder}\n"
        files[f"{folder}/.l4/ledger/r1.jsonl"] = f'{{"CHANNEL-L": "{folder}"}}\n'
        files[f"{folder}/.l4/review-accepted.json"] = f'{{"CHANNEL-A": "{folder}"}}\n'
    for rel, text in files.items():
        (wb.worktree / rel).parent.mkdir(parents=True, exist_ok=True)
        (wb.worktree / rel).write_text(text)
    wb.git.run("add", "-A")
    head = wb.commit("feat: files", task="1.1", attempt=1, phase="green", tdd="green")
    return wb, base, head, unit


def test_the_judge_diff_has_no_verification_md_of_the_family(make_bench, monkeypatch):
    from l4.verifier import ladder

    wb, base, head, unit = _diff_world(make_bench)
    monkeypatch.setattr(ladder, "_unit_dirs", lambda w: [unit, f"{unit}-fix-1"])
    diff, truncated = ladder._git_diff(wb, base, head)
    assert not truncated and "src/pytdd/extra.py" in diff
    assert "ROUND-1" not in diff and "FIX-ROUND" not in diff  # the harness's reports are not the unit's work


def test_scn_ver_130_the_judge_reads_the_units_work_not_the_familys_channel_files(make_bench, monkeypatch):
    from l4.verifier import ladder

    wb, base, head, unit = _diff_world(make_bench)
    monkeypatch.setattr(ladder, "_unit_dirs", lambda w: [unit, f"{unit}-fix-1"])
    diff, truncated = ladder._git_diff(wb, base, head)
    assert not truncated
    for kept in ("src/app/report.py", "tests/test_report.py", "docs/questions.md", "PROJECT-QUESTIONS"):
        assert kept in diff
    for dropped in ("CHANNEL-Q", "CHANNEL-F", "CHANNEL-L", "CHANNEL-A", "ROUND-1", "FIX-ROUND"):
        assert dropped not in diff
    monkeypatch.setattr(ladder, "MAX_DIFF_CHARS", len(diff) - 1)  # the flag is computed on the filtered text
    assert ladder._git_diff(wb, base, head)[1] is True
    monkeypatch.setattr(ladder, "MAX_DIFF_CHARS", len(diff))
    assert ladder._git_diff(wb, base, head)[1] is False


def test_a_project_verification_md_elsewhere_stays_in_the_diff(make_bench, monkeypatch):
    from l4.verifier import ladder

    wb, base, head, unit = _diff_world(make_bench)
    monkeypatch.setattr(ladder, "_unit_dirs", lambda w: [unit])
    diff, _ = ladder._git_diff(wb, base, head)
    assert "PROJECT-DOC" in diff and "docs/verification.md" in diff
    assert "FIX-ROUND" in diff  # a directory that is no unit of this family is project content


def test_files_only_people_changed_reach_the_judge_as_owner_changes(make_bench, raw):
    from l4.evidence.collect import scope_evidence

    bench = make_bench([])
    wb = bench.wb
    assert run_build_gates(wb).ok
    base = wb.git.run("rev-parse", "origin/main").stdout.strip()
    (wb.worktree / "src" / "pytdd" / "pricing.py").write_text("def total(prices):\n    return 0.0\n")
    raw(wb.worktree, "add", "-A")
    raw(wb.worktree, "-c", "user.name=Pat", "-c", "user.email=pat@example.invalid", "commit", "-q", "-m", "owner edit")
    human_sha = raw(wb.worktree, "rev-parse", "HEAD").strip()
    (wb.worktree / "src" / "pytdd" / "more.py").write_text("X = 1\n")
    wb.git.run("add", "-A")
    head = wb.commit("feat: more", task="1.1", attempt=1, phase="green", tdd="green")  # the harness's own file
    criteria = wb.provider.criteria(wb.ref)
    backend = Scripted(ok(judge_reply([c.id for c in criteria])))
    run = _Run(VerifyResult(wb.ref.id, 1, Verdict.NEEDS_HUMAN, base, head))
    run.scope = scope_evidence(wb, base, head, wb.ref)
    _judge_step(VerifyContext(wb, backend, "judge", ["impl"], 1, 60), run, base, [])  # type: ignore[arg-type]
    sent = backend.calls[0][0].content
    block = sent.split("## Owner changes")[1].split("\n## ")[0]
    assert f"src/pytdd/pricing.py (commit {human_sha[:10]})" in block
    assert "more.py" not in block  # a harness commit's file is the unit's work
    quiet = Scripted(ok(judge_reply([c.id for c in criteria])))
    other = _Run(VerifyResult(wb.ref.id, 1, Verdict.NEEDS_HUMAN, base, head))  # step 1 did not run: no scope
    _judge_step(VerifyContext(wb, quiet, "judge", ["impl"], 1, 60), other, base, [])  # type: ignore[arg-type]
    assert "## Owner changes" not in quiet.calls[0][0].content


def test_a_file_a_person_and_the_harness_both_changed_is_no_owner_change(make_bench, raw):
    """Review of M1.10 line 16: attribution is per commit (M1.9), so the implementer cannot hide its own edit of a file
    behind a person's commit to the same file."""
    from l4.evidence.collect import scope_evidence

    bench = make_bench([])
    wb = bench.wb
    base = wb.git.run("rev-parse", "origin/main").stdout.strip()
    pricing = wb.worktree / "src" / "pytdd" / "pricing.py"
    pricing.write_text("def total(prices):\n    return 0.0\n")
    raw(wb.worktree, "add", "--", "src/pytdd/pricing.py")  # the person's file only, not the run's ledger
    raw(wb.worktree, "-c", "user.name=Pat", "-c", "user.email=pat@example.invalid", "commit", "-q", "-m", "owner edit")
    pricing.write_text("def total(prices):\n    return 1.0\n")  # the implementer's later edit of the same file
    wb.git.run("add", "-A")
    head = wb.commit("feat: more", task="1.1", attempt=1, phase="green", tdd="green")
    scope = scope_evidence(wb, base, head, wb.ref)
    assert [f.human for f in scope.files if f.path == "src/pytdd/pricing.py"] == [None]
    criteria = wb.provider.criteria(wb.ref)
    backend = Scripted(ok(judge_reply([c.id for c in criteria])))
    run = _Run(VerifyResult(wb.ref.id, 1, Verdict.NEEDS_HUMAN, base, head))
    run.scope = scope
    _judge_step(VerifyContext(wb, backend, "judge", ["impl"], 1, 60), run, base, [])  # type: ignore[arg-type]
    assert "## Owner changes" not in backend.calls[0][0].content


def test_the_judge_sees_the_rounds_audit_tests_and_their_outcomes(make_bench):
    """W8: the accepted audit tests are in the worktree, not in the diff, and their outcomes come from the audit gate,
    not from the test gate the summary lists: the prompt carries them as the harness's own output of the round."""
    from l4.verifier.types import AuditRecord

    wb = make_bench([]).wb
    path = "tests/test_l4_audit_c_0a1b2c3d_r1.py"
    (wb.worktree / path).write_text("# generated\ndef test_known():\n    assert 1 == 1\n")
    base = wb.git.run("rev-parse", "origin/main").stdout.strip()
    result = VerifyResult(wb.ref.id, 1, Verdict.NEEDS_HUMAN, base, wb.head())
    result.audit = [
        AuditRecord("C-0a1b2c3d", "accepted", path, ("tests.test_l4_audit_c_0a1b2c3d_r1::test_known",)),
        AuditRecord("C-ffffffff", "rejected", "tests/test_l4_audit_c_ffffffff_r1.py", (), "passes on zero values"),
    ]
    criteria = wb.provider.criteria(wb.ref)
    backend = Scripted(ok(judge_reply([c.id for c in criteria])))
    vc = VerifyContext(wb, backend, "judge", ["impl"], 1, 60)  # type: ignore[arg-type]
    _judge_step(vc, _Run(result), base, [])
    prompt = backend.calls[0][0].content
    assert "## Written by the harness this round (committed after your review)" in prompt
    assert path in prompt and "tests.test_l4_audit_c_0a1b2c3d_r1::test_known  passed" in prompt
    assert "def test_known():" in prompt
    assert "test_l4_audit_c_ffffffff" not in prompt  # a rejected test is not evidence and was removed
