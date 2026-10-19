"""`_judge_step` on a unit with many criteria: a judge `fail` and its never-executed counterexample."""

from l4.verifier.gates import run_build_gates
from l4.verifier.ladder import VerifyContext, _finalize, _judge_step, _Run
from l4.verifier.types import Verdict, VerifyResult

from .conftest import judge_reply
from .test_judge_run import Scripted, invalid, ok

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


def test_scn_ver_143_channel_file_names_outside_the_familys_folders_stay_in_the_diff(make_bench, monkeypatch):
    from l4.verifier import ladder

    wb, base, head, unit = _diff_world(make_bench)
    monkeypatch.setattr(ladder, "_unit_dirs", lambda w: [unit])  # `<unit>-fix-1` is not a folder of this family
    diff, _ = ladder._git_diff(wb, base, head)
    assert f"CHANNEL-Q {unit}-fix-1" in diff and f"CHANNEL-F {unit}-fix-1" in diff and "PROJECT-QUESTIONS" in diff
    assert f"CHANNEL-Q {unit}\n" not in diff and f"CHANNEL-F {unit}\n" not in diff
    assert "CHANNEL-L" not in diff and "CHANNEL-A" not in diff  # `.l4/` is the harness's in every folder


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


# ---- a diff longer than one prompt is judged in parts (L4-VER-041 to L4-VER-043, L4-VER-045) -------------------


def _body(tag: str, lines: int) -> str:
    return "".join(f"{tag}_{n:03d} = {n}\n" for n in range(lines))


def parts_bench(make_bench, monkeypatch, files: dict[str, str], *results, cap: int = 2500, limit: int = 8):
    """A bench whose unit branch adds `files` and whose judge answers `results` in turn, with a lowered part size."""
    from l4.verifier import diffparts

    monkeypatch.setattr(diffparts, "MAX_PART_CHARS", cap)
    monkeypatch.setattr(diffparts, "MAX_JUDGE_PARTS", limit)
    wb = make_bench([]).wb
    assert run_build_gates(wb).ok
    base = wb.git.run("rev-parse", "origin/main").stdout.strip()
    for rel, text in files.items():
        (wb.worktree / rel).parent.mkdir(parents=True, exist_ok=True)
        (wb.worktree / rel).write_text(text)
    wb.git.run("add", "-A")
    head = wb.commit("feat: files", task="1.1", attempt=1, phase="green", tdd="green")
    result = VerifyResult(wb.ref.id, 1, Verdict.NEEDS_HUMAN, base, head)
    judge = Scripted(*results)
    vc = VerifyContext(wb, judge, "judge", ["impl"], 1, 60)  # type: ignore[arg-type]
    run = _Run(result)
    _judge_step(vc, run, base, [])
    return wb, result, run, judge


def replies(wb, count: int):
    ids = [c.id for c in wb.provider.criteria(wb.ref)]
    return [ok(judge_reply(ids)) for _ in range(count)]


def judge_events(wb):
    from l4.verifier.ladder import _events

    return [e for e in _events(wb) if e.type == "verify.judge"]


FOUR = {
    "src/app/export.py": _body("export", 50), "tests/test_export.py": _body("t_export", 50),
    "src/app/report.py": _body("report", 50), "tests/test_report.py": _body("t_report", 50),
}  # fmt: skip


def test_scn_ver_131_a_long_diff_is_judged_in_two_parts_with_no_hold(make_bench, monkeypatch):
    import hashlib

    from l4.verifier.report import render_verification_md

    probe = make_bench([]).wb  # the ids the replies must carry
    wb, result, run, judge = parts_bench(make_bench, monkeypatch, FOUR, *replies(probe, 2))
    assert len(judge.calls) == 2 and run.judged is not None
    first, second = (call[0].content for call in judge.calls)
    assert "part 1 of 2" in first and "part 2 of 2" in second
    for text in (first, second):  # every file is listed with its part in both prompts
        for rel in FOUR:
            assert rel in text
    assert "export" in first and "src/app/report.py b/src/app/report.py" not in first
    assert "diff --git a/src/app/report.py" in second and "diff --git a/src/app/export.py" not in second
    assert not [h for h in result.holds if h.startswith("judge view:") or "the diff is longer" in h]
    events = judge_events(wb)
    assert [(e.data["part"], e.data["parts"]) for e in events] == [(1, 2), (2, 2)]
    assert len(result.judge_parts) == 2 and [r["part"] for r in result.judge_parts] == [1, 2]
    hashes = [r["prompt_sha256"] for r in result.judge_parts]
    assert result.prompt_sha256 == hashlib.sha256("\n".join(hashes).encode()).hexdigest()
    assert result.prompt_template == "judge@11" and result.judge_calls == 2
    assert result.judge_reply == "valid"
    text = render_verification_md(result)
    assert "judged in 2 parts" in text and "  - part 1: 2 file(s)," in text and "  - part 2: 2 file(s)," in text


def test_scn_ver_131_the_same_diff_gives_the_same_parts_again(make_bench, monkeypatch):
    probe = make_bench([]).wb
    _, one, _, _ = parts_bench(make_bench, monkeypatch, FOUR, *replies(probe, 2))
    _, two, _, _ = parts_bench(make_bench, monkeypatch, FOUR, *replies(probe, 2))
    assert [r["files"] for r in one.judge_parts] == [r["files"] for r in two.judge_parts]
    assert [r["chars"] for r in one.judge_parts] == [r["chars"] for r in two.judge_parts]


def test_a_diff_within_the_cap_is_one_call_with_no_part_heading(make_bench, monkeypatch):
    probe = make_bench([]).wb
    wb, result, run, judge = parts_bench(make_bench, monkeypatch, FOUR, *replies(probe, 1), cap=120_000)
    assert len(judge.calls) == 1 and "part 1 of" not in judge.calls[0][0].content
    assert "## Diff (base...head)\n" in judge.calls[0][0].content
    assert result.judge_parts == [] and judge_events(wb)[0].data.get("part") is None
    assert not [h for h in result.holds if "diff" in h]


def test_scn_ver_135_eleven_files_need_more_than_eight_parts_and_the_hold_names_what_was_not_seen(
    make_bench, monkeypatch
):
    files = {f"src/app/f{n:02d}.py": _body(f"f{n:02d}", 150) for n in range(11)}
    probe = make_bench([]).wb
    wb, result, run, judge = parts_bench(make_bench, monkeypatch, files, *replies(probe, 8), cap=3000)
    assert len(judge.calls) == 8 and run.judged is not None
    (hold,) = [h for h in result.holds if h.startswith("judge view:")]
    assert hold == (
        "judge view: the diff needs more than 8 parts of 3000 characters: the judge did not see "
        "`src/app/f08.py`, `src/app/f09.py`, `src/app/f10.py`"
    )
    assert "src/app/f08.py" in judge.calls[0][0].content  # the file list names the files no part shows


def test_the_hold_for_unseen_files_names_five_paths_and_counts_the_rest(make_bench, monkeypatch):
    files = {f"src/app/f{n:02d}.py": _body(f"f{n:02d}", 150) for n in range(10)}
    probe = make_bench([]).wb
    _, result, _, _ = parts_bench(make_bench, monkeypatch, files, *replies(probe, 2), cap=3000, limit=2)
    (hold,) = [h for h in result.holds if h.startswith("judge view:")]
    assert hold.endswith(
        "`src/app/f02.py`, `src/app/f03.py`, `src/app/f04.py`, `src/app/f05.py`, `src/app/f06.py` (+3 more)"
    )
    assert "needs more than 2 parts of 3000 characters" in hold


def test_scn_ver_136_a_part_whose_reply_is_discarded_discards_the_judge_verdict(make_bench, monkeypatch):
    probe = make_bench([]).wb
    wb, result, run, judge = parts_bench(make_bench, monkeypatch, FOUR, *replies(probe, 1), invalid(), invalid())
    assert run.judged is None and result.judge_verdict is None
    (hold,) = [h for h in result.holds if "discarded" in h]
    assert hold.startswith("the judge's reply was discarded (part 2 of 2, schema_invalid:")
    assert result.criteria == [] and not any(e.type == "verify.counterexample" for e in _events_of(wb))


def _events_of(wb):
    from l4.verifier.ladder import _events

    return _events(wb)


def test_scn_ver_137_a_file_longer_than_one_part_holds_with_its_name(make_bench, monkeypatch):
    files = {"data/seed.json": _body("seed", 400), "src/app/a.py": _body("a", 5), "src/app/b.py": _body("b", 5)}
    probe = make_bench([]).wb
    wb, result, run, judge = parts_bench(make_bench, monkeypatch, files, *replies(probe, 3), cap=1000)
    expected = (
        "judge view: the diff of `data/seed.json` is longer than one part (1000 characters): "
        "the judge saw only its start"
    )
    assert expected in result.holds
    big = next(c[0].content for c in judge.calls if "data/seed.json b/data/seed.json" in c[0].content)
    assert "seed_399" not in big and "seed_000" in big  # only the start is shown
    assert not [h for h in result.holds if h.startswith("the diff is longer")]


def test_scn_ver_141_a_lock_file_beside_small_files_is_one_call_with_one_line_and_no_hold(make_bench, monkeypatch):
    files = {"uv.lock": _body("lock", 2000), "src/app/a.py": _body("a", 5), "src/app/b.py": _body("b", 5)}
    probe = make_bench([]).wb
    wb, result, run, judge = parts_bench(make_bench, monkeypatch, files, *replies(probe, 1), cap=3000)
    assert len(judge.calls) == 1 and "part 1 of" not in judge.calls[0][0].content
    text = judge.calls[0][0].content
    assert (
        "lock file uv.lock: 0 -> " in text
        and "+2000 -0 lines, 0 touch a source field" in text
        and "lock_1999" not in text
    )
    assert not [h for h in result.holds if "diff" in h]


def test_review_m1_the_step_records_the_binding_and_the_full_unseen_list(make_bench, monkeypatch):
    from l4.verifier.report import render_verification_md, verdict_json

    files = {f"src/app/f{n:02d}.py": _body(f"f{n:02d}", 150) for n in range(11)}
    probe = make_bench([]).wb
    wb, result, run, judge = parts_bench(make_bench, monkeypatch, files, *replies(probe, 8), cap=3000)
    (hold,) = [h for h in result.holds if h.startswith("judge view:")]
    view = result.hold_views[hold]
    assert len(view["sha"]) == 64 and view["paths"] == ["src/app/f08.py", "src/app/f09.py", "src/app/f10.py"]
    other = wb.git.run("rev-parse", f"{result.head_sha}:src/app/f08.py").stdout.strip()
    assert other and view["sha"] != hold  # bound to blobs, not to the text
    text = render_verification_md(result)
    assert "## Files by part" in text and "part 1: src/app/f00.py" in text
    assert "no part (not judged): src/app/f10.py" in text
    assert verdict_json(result)["hold_views"][hold]["paths"] == view["paths"]


def test_review_m3_the_listing_of_a_part_prompt_is_capped(make_bench, monkeypatch):
    from l4.verifier import diffparts

    monkeypatch.setattr(diffparts, "LISTING_MAX_LINES", 3)
    probe = make_bench([]).wb
    _, result, _, judge = parts_bench(make_bench, monkeypatch, FOUR, *replies(probe, 2))
    first = judge.calls[0][0].content
    import re

    block = re.search(r'<l4:data kind="diff parts">\n(.*?)\n</l4:data>', first, flags=re.S)
    assert block is not None and "+1 more files: see verification.md" in block.group(1)
    assert "tests/test_report.py" not in block.group(1)
    assert len(result.judge_files) == 4  # the full list is kept for verification.md
