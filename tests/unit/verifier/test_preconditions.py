from pathlib import Path
from types import SimpleNamespace

import pytest

from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.redact import Redactor
from l4.specs.base import Marker, ValidationIssue
from l4.vcs.merge import BaseMergeConflict
from l4.vcs.trailers import CommitTrailers
from l4.verifier.basemerge import bring_in_base
from l4.verifier.preconditions import check_preconditions
from l4.verifier.types import Severity

from ..conftest import UNIT  # noqa: F401
from .conftest import FakeCli, with_validation


def tick_and_commit(wb) -> str:
    wb.provider.set_marker(wb.ref, "1.1", Marker.DONE)
    return wb.commit("feat: 1.1", task="1.1", attempt=1, phase="green", tdd="green")


def test_a_finished_unit_on_a_current_branch_has_no_findings(make_bench):
    wb = make_bench([]).wb
    with_validation(wb)
    head = tick_and_commit(wb)
    pre = check_preconditions(wb)
    assert pre.findings == [] and pre.head == head
    assert pre.base_sha == wb.git.run("rev-parse", "origin/main").stdout.strip()


def test_a_pending_task_is_a_blocker(make_bench):
    wb = make_bench([]).wb
    with_validation(wb)
    [finding] = check_preconditions(wb).findings
    assert finding.severity is Severity.BLOCKER and finding.source == "deterministic"
    assert "1.1" in finding.detail and "not done" in finding.title


def test_strict_invalid_unit_is_hard_failure(make_bench):
    wb = make_bench([]).wb
    cli = with_validation(wb, FakeCli(False, (ValidationIssue("ERROR", "specs/x.md", "Scenario has no WHEN"),)))
    tick_and_commit(wb)
    [finding] = check_preconditions(wb).findings
    assert finding.severity is Severity.BLOCKER and "Scenario has no WHEN" in finding.detail
    assert cli.calls == [("validate", "add-discount-codes", "--strict", "--json")]


def test_a_branch_that_lacks_the_base_head_is_an_error_not_a_verdict(make_bench, raw):
    bench = make_bench([])
    with_validation(bench.wb)
    tick_and_commit(bench.wb)
    repo = bench.tdd.repo
    (repo / "NEWS.md").write_text("new on main\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "main moved")
    raw(repo, "push", "-q", "origin", "main")
    bench.wb.git.fetch("origin")
    with pytest.raises(L4Exit) as exc:
        check_preconditions(bench.wb)
    assert exc.value.code is ExitCode.INTERNAL_ERROR
    assert "bug: the base merge of step 0 did not run" in str(exc.value)
    assert bench.wb.git.rev_parse("HEAD") == bench.wb.head()  # nothing was merged


def test_a_dirty_worktree_is_refused_before_anything_runs(make_bench):
    wb = make_bench([]).wb
    with_validation(wb)
    tick_and_commit(wb)
    (wb.worktree / "stray.txt").write_text("x")
    with pytest.raises(L4Exit, match="uncommitted"):
        check_preconditions(wb)


def test_the_harness_own_output_does_not_make_the_worktree_dirty(make_bench):
    wb = make_bench([]).wb
    with_validation(wb)
    tick_and_commit(wb)
    (wb.worktree / ".l4-out").mkdir()
    (wb.worktree / ".l4-out" / "junit.xml").write_text("<testsuites/>")
    assert check_preconditions(wb).findings == []


# --- the base merge of step 0 (state-vcs-locks 1.27, verifier 1.6) -------------------------------------------------


def hook_ctx(bench) -> SimpleNamespace:
    """The parts of a `HookContext` that `bring_in_base` reads, around the bench's own worktree and ledger."""
    wb = bench.wb
    app = AppContext(bench.tdd.repo, None, "human", 0, wb.run_id, bench.tdd.environ, Redactor({}))
    names = SimpleNamespace(unit_cache=wb.unit_cache)  # the keyed unit directory (L4-SEC-034), where `excludes` lives
    services = SimpleNamespace(git=wb.git, worktree=wb.worktree, ref=wb.ref, ledger=wb.ledger, app=app, names=names)
    return SimpleNamespace(cfg=wb.cfg, services=services, push=wb.push, shared={})


def main_commits(bench, raw, files: dict[str, str], message: str = "main moved") -> str:
    repo = bench.tdd.repo
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", message)
    raw(repo, "push", "-q", "origin", "main")
    bench.wb.git.fetch("origin")
    return raw(repo, "rev-parse", "HEAD").strip()


def events_of(bench, event_type: str) -> list[dict]:
    return bench.events(event_type)


def test_base_merged_before_gates_and_conflict_is_error_in_m1(make_bench, raw):
    bench = make_bench([])
    wb = bench.wb
    with_validation(wb)
    tick_and_commit(wb)
    own = (wb.worktree / "src" / "pytdd" / "pricing.py").read_text()
    (wb.worktree / "src" / "pytdd" / "pricing.py").write_text("# unit\n" + own)
    wb.git.run("add", "-A")
    unit_head = wb.git.commit(
        "feat: unit edit", CommitTrailers(unit=wb.ref.id, run_id=wb.run_id, iteration=1, phase="implementing")
    )
    pushes_before = list(bench.pushes)
    ctx = hook_ctx(bench)

    # a conflict with the base: nothing is merged or pushed, the ledger says why, and the exit is 1 (M1)
    conflicting = main_commits(bench, raw, {"src/pytdd/pricing.py": "# main\n" + own, "NEWS.md": "news\n"})
    with pytest.raises(BaseMergeConflict) as exc:
        bring_in_base(ctx)
    assert exc.value.code is ExitCode.INTERNAL_ERROR and exc.value.files == ("src/pytdd/pricing.py",)
    assert wb.head() == unit_head and bench.pushes == pushes_before
    assert wb.is_clean() and wb.git.run("rev-parse", "-q", "--verify", "MERGE_HEAD", check=False).returncode != 0
    [conflict] = events_of(bench, "base.conflict")
    assert conflict["files"] == ["src/pytdd/pricing.py"] and conflict["resolved"] == []
    assert conflict["base"] == "main" and conflict["base_sha"] == conflicting
    [step] = events_of(bench, "verify.step")
    assert (step["step"], step["status"], step["reason"], step["round"]) == ("0", "error", "base-merge-conflict", 1)
    assert events_of(bench, "verify.verdict") == []
    with pytest.raises(L4Exit, match="did not run"):
        check_preconditions(wb)  # the guard: step 0's own check still refuses a branch that lacks the base head

    # main reverts the conflicting edit: the next run merges, pushes the merge, and clears the conflict note
    cleared = main_commits(bench, raw, {"src/pytdd/pricing.py": own}, "revert the conflicting edit")
    merged = bring_in_base(ctx)
    assert merged.kind == "merged" and merged.base_sha == cleared and merged.behind == 2
    assert wb.head() == merged.merge_sha and bench.pushes[-1] == merged.merge_sha
    parents = raw(wb.worktree, "rev-list", "--parents", "-n1", "HEAD").split()
    assert parents[1:] == [unit_head, cleared]
    body = raw(wb.worktree, "log", "-1", "--format=%B")
    assert (
        body.splitlines()[0] == f"chore(add-discount-codes): merge main@{cleared[:10]} into the unit branch [skip ci]"
    )
    assert "L4-Phase: verifying" in body and "L4-Iteration: 1" in body and f"L4-Run: {wb.run_id}" in body
    assert "L4-Task" not in body and "L4-TDD" not in body and "L4-Step" not in body
    [done] = events_of(bench, "base.merged")
    assert done["merge_sha"] == merged.merge_sha and done["behind"] == 2 and done["frozen_touched"] == []
    assert ctx.shared["notes"] == ()
    assert check_preconditions(wb).findings == []  # step 0 now passes
    again = bring_in_base(ctx)  # the branch contains the base: nothing to do
    assert again.kind == "noop" and len(events_of(bench, "base.merged")) == 1 and bench.pushes[-1] == merged.merge_sha


def test_frozen_file_changed_by_merge_is_recorded_not_a_finding(make_bench, raw):
    bench = make_bench([])
    wb = bench.wb
    with_validation(wb)
    tick_and_commit(wb)
    wb.emit("task.red_ok", task="1.1", base="x", tests=[], frozen=["tests/test_pricing.py"], notes=[])
    main_commits(
        bench, raw, {"tests/test_pricing.py": "from pytdd import total\n\n\ndef test_x():\n    assert total([]) == 0\n"}
    )
    merged = bring_in_base(hook_ctx(bench))
    assert merged.frozen_touched == ("tests/test_pricing.py",)
    [done] = events_of(bench, "base.merged")
    assert done["frozen_touched"] == ["tests/test_pricing.py"]
    assert check_preconditions(wb).findings == []
    assert "tests/test_pricing.py" in merged.note


def _ci_edge(writer, *, jobs=None, **extra) -> None:
    jobs = jobs if jobs is not None else [
        {"name": "test", "stage": "test", "url": "https://forge.example/j/9",
         "tail": "E assert 1 == 2\nFAILED t.py::x"},
        {"name": "lint", "stage": "lint", "url": "https://forge.example/j/10", "tail": ""},
    ]  # fmt: skip
    writer.append("phase.changed", **{"from": "in_review", "to": "verifying"}, trigger="repository_ci_failed",
                  head="a" * 40, pipeline=5, jobs=jobs, preexisting=[], **extra)  # fmt: skip


def test_ci_failure_of_the_reentry_is_a_step_0_blocker_once(make_bench):
    """The project's own CI red on H (SCN-ARC-14): one deterministic blocker per red job, in the round that follows the
    edge only. A round after its verdict has none."""
    bench = make_bench([])
    wb = bench.wb
    with_validation(wb)
    tick_and_commit(wb)
    assert check_preconditions(wb).findings == []
    _ci_edge(bench.writer)
    found = check_preconditions(wb).findings
    assert [(f.severity, f.source, f.title) for f in found] == [
        (Severity.BLOCKER, "deterministic", "repository CI failed: test"),
        (Severity.BLOCKER, "deterministic", "repository CI failed: lint"),
    ]
    assert "stage test" in found[0].detail and "a" * 10 in found[0].detail
    assert "https://forge.example/j/9" in found[0].detail and "E assert 1 == 2" in found[0].detail
    assert found[0].id == check_preconditions(wb).findings[0].id  # stable ids: the same job, the same finding
    bench.writer.append("verify.verdict", round=1, verdict="FAIL", findings=2)
    assert check_preconditions(wb).findings == []
    _ci_edge(
        bench.writer, jobs=[{"name": "build", "stage": "build", "url": "", "tail": ""}]
    )  # a later edge starts over
    assert [f.title for f in check_preconditions(wb).findings] == ["repository CI failed: build"]


# --- the failing step of a red job (M1.10 line 5; L4-VER-002 step 0, SCN-ARC-14) ---

STEP = "uv run ruff check --select E501 --line-length 92 src"
CI_FILE = f"test:\n  script:\n    - uv sync\n    - {STEP}\n"
STEP_TAIL = f"Executing step_script\n$ {STEP}\nE501 Line too long (108 > 92)\nFound 1 error.\n"


def person_commit(wb, raw, files: dict[str, str]) -> str:
    for name, text in files.items():
        (wb.worktree / name).write_text(text)
    raw(wb.worktree, "add", "-A")
    raw(wb.worktree, "-c", "user.name=Pat", "-c", "user.email=pat@example.invalid", "commit", "-q", "-m", "ci: edit")
    return raw(wb.worktree, "rev-parse", "HEAD").strip()


def edge_at(bench, head: str, *, step: str | None = STEP, tail: str = STEP_TAIL, job: str = "test") -> None:
    bench.writer.append(
        "phase.changed", **{"from": "in_review", "to": "verifying"}, trigger="repository_ci_failed", head=head,
        pipeline=5, preexisting=[], jobs=[{"name": job, "stage": "test", "url": "", "tail": tail, "step": step}],
    )  # fmt: skip


def ci_step_events(bench) -> list[dict]:
    return bench.events("ci.step")


def test_ci_blocker_names_the_failing_step_and_records_ci_step(make_bench, raw):
    from l4.verifier.preconditions import record_ci_steps

    bench = make_bench([])
    wb = bench.wb
    with_validation(wb)
    tick_and_commit(wb)
    head = person_commit(wb, raw, {".gitlab-ci.yml": CI_FILE})
    edge_at(bench, head)
    pre = check_preconditions(wb)
    (finding,) = pre.findings
    assert finding.title == "repository CI failed: test"
    assert finding.detail.startswith(f"failing step: `{STEP}` (job `test` at {head[:10]})")
    assert "Log ends" in " ".join(finding.detail.split())[:600]  # what a fix task keeps
    assert [(s.job, s.command, s.reason) for s in pre.ci_steps] == [("test", STEP, None)]
    record_ci_steps(wb, pre)
    (event,) = ci_step_events(bench)
    assert (event["job"], event["head"], event["status"], event["command"]) == ("test", head, "derived", STEP)
    assert event["step"] == STEP and event["source"] == f".gitlab-ci.yml@{head[:10]}" and event["reason"] is None


def test_a_ci_file_a_harness_commit_changed_is_refused(make_bench):
    from l4.verifier.preconditions import record_ci_steps

    bench = make_bench([])
    wb = bench.wb
    with_validation(wb)
    (wb.worktree / ".gitlab-ci.yml").write_text(CI_FILE)  # an agent's edit of the CI file, committed by the harness
    head = tick_and_commit(wb)
    edge_at(bench, head)
    pre = check_preconditions(wb)
    (finding,) = pre.findings
    assert not finding.detail.startswith("failing step")  # nothing to name: the step is skipped
    record_ci_steps(wb, pre)
    (event,) = ci_step_events(bench)
    assert event["status"] == "skipped" and event["command"] is None and "harness commit" in event["reason"]


def test_a_ci_file_a_person_changed_on_the_branch_is_read_at_h(make_bench, raw):
    bench = make_bench([])
    wb = bench.wb
    with_validation(wb)
    tick_and_commit(wb)
    head = person_commit(wb, raw, {".gitlab-ci.yml": CI_FILE})
    (wb.worktree / ".gitlab-ci.yml").write_text("test:\n  script:\n    - make something-else\n")
    wb.commit("chore: later edit", task="1.1", attempt=2, phase="green", tdd="green")  # after H: not what H ran
    edge_at(bench, head)
    pre = check_preconditions(wb)
    assert [(s.command, s.reason) for s in pre.ci_steps] == [(STEP, None)]
    assert pre.findings[0].detail.startswith(f"failing step: `{STEP}`")


def test_ci_step_is_recorded_once_per_head_and_job(make_bench, raw):
    from l4.verifier.preconditions import record_ci_steps

    bench = make_bench([])
    wb = bench.wb
    with_validation(wb)
    tick_and_commit(wb)
    head = person_commit(wb, raw, {".gitlab-ci.yml": CI_FILE})
    edge_at(bench, head)
    record_ci_steps(wb, check_preconditions(wb))
    again = check_preconditions(wb)
    assert again.ci_steps == () and again.findings  # still a blocker, but nothing new to record
    record_ci_steps(wb, again)
    assert len(ci_step_events(bench)) == 1
    bench.writer.append("verify.verdict", round=1, verdict="FAIL", findings=1)
    head2 = person_commit(wb, raw, {".gitlab-ci.yml": CI_FILE + "# more\n"})
    edge_at(bench, head2)
    record_ci_steps(wb, check_preconditions(wb))
    assert [e["head"] for e in ci_step_events(bench)] == [head, head2]


def test_a_long_step_and_a_long_log_both_fit_the_600_characters_a_fix_task_keeps():
    from l4.verifier.preconditions import ci_detail

    command = "python scripts/check.py " + "x" * 270
    detail = ci_detail("test", "test", "a" * 40, "https://gitlab.example.test/g/p/-/jobs/12345", "boom " * 200, command)
    summary = detail.split("\n\n")[0]
    assert summary.startswith(f"failing step: `{command}`") and "Log ends" in summary and len(summary) <= 600
    assert summary.endswith("boom.")  # the end of the log is kept, not cut by the task's 600 characters


def test_a_local_include_a_harness_commit_changed_is_refused(make_bench, raw):
    """Review of M1.10 line 5: an included CI file outside the protected `.gitlab/` (here `ci/jobs.yml`) is no
    forbidden path, so an agent can edit it; the edit is a harness commit, and the step is skipped, never run."""
    from l4.verifier.preconditions import record_ci_steps

    bench = make_bench([])
    wb = bench.wb
    with_validation(wb)
    (wb.worktree / "ci").mkdir()
    person_commit(wb, raw, {".gitlab-ci.yml": "include:\n  - local: /ci/jobs.yml\n", "ci/jobs.yml": CI_FILE})
    (wb.worktree / "ci" / "jobs.yml").write_text(CI_FILE.replace("- uv sync", "- rm -rf build"))  # the agent's
    head = tick_and_commit(wb)
    edge_at(bench, head)
    pre = check_preconditions(wb)
    record_ci_steps(wb, pre)
    (event,) = ci_step_events(bench)
    assert event["status"] == "skipped" and event["command"] is None
    assert "ci/jobs.yml" in event["reason"] and "harness commit" in event["reason"]


# --- the failing step of a red GitHub job (ci-evidence D5; L4-VER-064, SCN-VER-227 to SCN-VER-230) ---

GITHUB_URL = "https://github.test/acme/widgets/actions/runs/123/job/456"
COVERAGE = [f"src/app/mod{i}.py   120   4   97%" for i in range(25)]
GITHUB_TAIL = "\n".join(
    [
        "Run uv run pytest -q",
        "FAILED tests/test_cli.py::test_help - AssertionError: assert 'run' in 'Usage: app'",
        "1 failed, 2277 passed in 312.40s (0:05:12)",
        "...",
        *COVERAGE,
        "TOTAL   9000  300  97%",
        "Error: Process completed with exit code 1.",
    ]
)


def github_edge(bench, head: str, *, tail: str = GITHUB_TAIL, **job) -> None:
    entry = {
        "name": "ci.yml / tests", "stage": "", "url": GITHUB_URL, "tail": tail, "step": None,
        "workflow": "ci.yml", "event": "push", "failed_step": "tests",
    } | job  # fmt: skip
    bench.writer.append(
        "phase.changed", **{"from": "in_review", "to": "verifying"}, trigger="repository_ci_failed", head=head,
        pipeline=5, preexisting=[], jobs=[entry],
    )  # fmt: skip


def test_the_blocker_names_the_github_step_and_leads_with_the_failure(make_bench):
    """SCN-VER-227: the failing test and the count come before `Log ends:` when a coverage report follows them."""
    bench = make_bench([])
    wb = bench.wb
    with_validation(wb)
    head = tick_and_commit(wb)
    github_edge(bench, head)
    (finding,) = check_preconditions(wb).findings
    detail = finding.detail
    assert detail.startswith(f"job `ci.yml / tests` failed in step `tests` on the hand-off commit {head[:10]}")
    first = detail[:600]
    assert "Failed: FAILED tests/test_cli.py::test_help - AssertionError" in first
    assert first.index("1 failed, 2277 passed") < first.index("Log ends:")
    assert "Error: Process completed with exit code 1." in first
    assert detail.split("\n\n", 1)[1] == GITHUB_TAIL


def test_an_error_line_in_the_end_needs_no_failed_part_and_e_lines_come_after_the_failing_test(make_bench):
    from l4.verifier.preconditions import ci_detail

    short = "Run pytest\nFAILED t.py::t - boom\n1 failed in 1s\nError: Process completed with exit code 1."
    detail = ci_detail("ci.yml / tests", "", "a" * 40, GITHUB_URL, short, None, "tests")
    assert "Failed:" not in detail and "FAILED t.py::t - boom" in detail[:600]  # already in the end of the log
    tail = "\n".join(
        ["E       assert x"] * 3 + ["E       assert y", "FAILED t.py::t - boom", "1 failed in 1s", *COVERAGE]
    )
    first = ci_detail("ci.yml / tests", "", "a" * 40, GITHUB_URL, tail, None, "tests")[:600]
    assert first.index("FAILED t.py::t - boom") < first.index("1 failed in 1s") < first.index("E       assert x")


def test_a_detail_whose_failures_are_in_the_end_is_todays():
    """SCN-VER-228: the 0.4.20 text, pasted as a literal, for a GitLab tail whose failures are already at its end."""
    from l4.verifier.preconditions import ci_detail

    tail = (
        "Executing step_script\n$ uv run ruff check src\nE501 Line too long (108 > 92)\n --> src/a.py:2:93\n"
        "Found 1 error."
    )
    expected = (
        "failing step: `uv run ruff check src` (job `test` at aaaaaaaaaa). job `test` (stage test) failed on the "
        "hand-off commit aaaaaaaaaa (https://gitlab.test/j/1). Log ends: Executing step_script $ uv run ruff check "
        "src E501 Line too long (108 > 92) --> src/a.py:2:93 Found 1 error..\n\n" + tail
    )
    assert ci_detail("test", "test", "a" * 40, "https://gitlab.test/j/1", tail, "uv run ruff check src") == expected
    plain = "E       assert 1 == 2\nFAILED t.py::x"  # the 0.4.20 text of a log whose failures are all in its end
    assert ci_detail("test", "test", "a" * 40, "", plain) == (
        "job `test` (stage test) failed on the hand-off commit aaaaaaaaaa. Log ends: E assert 1 == 2 FAILED t.py::x."
        "\n\n" + plain
    )


def test_an_older_edge_leads_with_its_failures(make_bench):
    """SCN-VER-229: a ledger of 0.4.20 (no `failed_step`): today's `where`, with the failures first."""
    bench = make_bench([])
    wb = bench.wb
    with_validation(wb)
    head = tick_and_commit(wb)
    tail = "\n".join(["FAILED tests/test_a.py::test_x - AssertionError", *[f"line {i}" for i in range(40)]])
    bench.writer.append(
        "phase.changed", **{"from": "in_review", "to": "verifying"}, trigger="repository_ci_failed", head=head,
        pipeline=5, preexisting=[], jobs=[{"name": "test", "stage": "test", "url": "", "tail": tail}],
    )  # fmt: skip
    (finding,) = check_preconditions(wb).findings
    assert finding.detail.startswith(f"job `test` (stage test) failed on the hand-off commit {head[:10]}")
    assert "FAILED tests/test_a.py::test_x - AssertionError" in finding.detail[:600]
    assert finding.detail.index("Failed:") < finding.detail.index("Log ends:")


def test_a_github_step_is_named_never_derived(make_bench, raw, monkeypatch):
    """SCN-VER-230: a `$ make deploy` line of a GitHub job's output selects nothing, and no CI file is read."""
    from l4.verifier import preconditions
    from l4.verifier.preconditions import record_ci_steps

    bench = make_bench([])
    wb = bench.wb
    with_validation(wb)
    tick_and_commit(wb)
    head = person_commit(wb, raw, {".gitlab-ci.yml": "tests:\n  script:\n    - make deploy\n"})
    github_edge(bench, head, tail="Run make\n$ make deploy\nFAILED t.py::t - boom")
    reads: list[str] = []
    real = preconditions.show_blob
    monkeypatch.setattr(preconditions, "show_blob", lambda git, rev, path: reads.append(path) or real(git, rev, path))
    pre = check_preconditions(wb)
    assert [(s.job, s.step, s.command, s.reason) for s in pre.ci_steps] == [
        ("ci.yml / tests", "tests", None, preconditions.GITHUB_STEP_REASON)
    ]
    assert pre.ci_steps[0].source == f"ci.yml@{head[:10]}" and pre.ci_steps[0].status == "skipped"
    assert ".gitlab-ci.yml" not in reads
    record_ci_steps(wb, pre)
    (event,) = ci_step_events(bench)
    assert event["status"] == "skipped" and event["command"] is None and event["step"] == "tests"


# --- the same job failing again (ci-evidence D12; L4-OPS-023, SCN-OPS-40, SCN-OPS-42, SCN-OPS-44) ---


def unit_commit(wb, raw, name: str = "notes.md") -> str:
    """A commit that changes the unit's own folder only: the fix unit's tick, as far as a project file goes."""
    return person_commit(wb, raw, {f"{wb.unit_rel}/{name}": "x\n"})


def test_a_repeated_ci_job_gets_the_again_prefix(make_bench, raw):
    """SCN-OPS-40: the fix changed no project file, its put-back files and notes follow the first part."""
    from l4.verifier.types import finding_id

    bench = make_bench([])
    wb = bench.wb
    with_validation(wb)
    tick_and_commit(wb)
    h1 = wb.head()
    github_edge(bench, h1)
    bench.writer.append("verify.verdict", round=1, verdict="FAIL", findings=1)
    fid = finding_id("repository CI failed: ci.yml / tests")
    bench.writer.append("guard.test_tamper", path="tests/test_cli.py", phase="single", action="restored")
    bench.writer.append("guard.violation", path="tests/conftest.py", phase="single", rule="test support file")
    bench.writer.append("task.tdd_exempt", task="1.1", sha="s", kind="harness", finding=fid, findings=[fid])
    bench.writer.append("task.done", task="1.1", sha="s", notes="the gates do not show it " + "n" * 400, tdd="exempt")
    h2 = unit_commit(wb, raw)
    github_edge(bench, h2)
    (finding,) = check_preconditions(wb).findings
    prefix = (
        f"again: job `ci.yml / tests` also failed on the hand-off commit {h1[:10]}; project files changed since: 0. "
        f"job `ci.yml / tests` failed in step `tests` on the hand-off commit {h2[:10]}"
    )
    assert finding.detail.startswith(prefix)
    first = finding.detail[:600]
    assert "Failed:" in first and "Log ends:" in first  # the prefix is counted: both still fit
    extra = finding.detail.split("\n\n")[1]
    assert "tests/conftest.py, tests/test_cli.py were put back" in extra and "a person must commit that change" in extra
    assert "The fix step said: the gates do not show it" in extra and len(extra.split("said: ")[1]) <= 300
    assert finding.detail.split("\n\n", 2)[2] == GITHUB_TAIL


def test_again_prefix_with_changes_and_after_a_rewrite(make_bench, raw):
    """SCN-OPS-42, SCN-OPS-44: a project change is counted; a rewritten history has no count."""
    bench = make_bench([])
    wb = bench.wb
    with_validation(wb)
    tick_and_commit(wb)
    h1 = wb.head()
    github_edge(bench, h1)
    bench.writer.append("verify.verdict", round=1, verdict="FAIL", findings=1)
    h2 = person_commit(wb, raw, {"src/pytdd/pricing.py": "# fixed\n"})
    github_edge(bench, h2)
    (finding,) = check_preconditions(wb).findings
    assert finding.detail.startswith(
        f"again: job `ci.yml / tests` also failed on the hand-off commit {h1[:10]}; project files changed since: 1. "
    )
    assert "were put back" not in finding.detail and "The fix step said" not in finding.detail
    bench.writer.append("verify.verdict", round=2, verdict="FAIL", findings=1)
    github_edge(bench, "e" * 40)  # a head that is not in the repository: no ancestor, no count
    (rewritten,) = check_preconditions(wb).findings
    assert rewritten.detail.startswith(
        f"again: job `ci.yml / tests` also failed on the hand-off commit {h2[:10]}. job `ci.yml / tests`"
    )


def test_a_first_failure_has_no_again_prefix(make_bench):
    bench = make_bench([])
    wb = bench.wb
    with_validation(wb)
    github_edge(bench, tick_and_commit(wb))
    (finding,) = check_preconditions(wb).findings
    assert finding.detail.startswith("job `ci.yml / tests` failed in step `tests`")


# --- the `Failed:` part is chosen against the window it leaves (review B1; SCN-VER-227's last clause) ---

AGAIN = "again: job `ci.yml / tests` also failed on the hand-off commit bbbbbbbbbb; project files changed since: 0. "


def _first(tail: str, prefix: str = "") -> str:
    from l4.verifier.preconditions import ci_detail

    return ci_detail("ci.yml / tests", "", "a" * 40, GITHUB_URL, tail, None, "tests", prefix=prefix)[:600]


def test_failed_lines_survive_the_window_the_failed_part_shrinks_with_an_again_prefix():
    tail = "\n".join(
        ["E       assert 'run' in 'Usage: app'", "E       assert x", "E       assert y", "E       assert z"]
        + [f"line {i} of the step's output" for i in range(6)]
        + ["FAILED tests/test_cli.py::test_help - AssertionError", "Error: Process completed with exit code 1."]
    )
    assert "FAILED tests/test_cli.py::test_help" in _first(tail, AGAIN)


def test_the_incident_fixture_with_an_again_prefix_keeps_the_failing_test():
    from l4.forge.logexcerpt import actions_excerpt

    log = (Path(__file__).resolve().parents[2] / "fixtures" / "ci_logs" / "github-pytest-failure.log").read_text(
        encoding="utf-8"
    )
    text = actions_excerpt(log, None).text
    assert "FAILED" in text
    assert "FAILED tests/" in _first(text, AGAIN)


def test_a_mid_step_annotation_does_not_push_the_failing_test_out():
    tail = "\n".join(
        ["FAILED tests/test_a.py::test_x - AssertionError: boom", "E       assert 1 == 2"]
        + ["Error: something mid-step"]
        + [f"output line number {i} that is not interesting" for i in range(30)]
    )
    assert "FAILED tests/test_a.py::test_x" in _first(tail)


def test_twenty_five_long_failed_lines_keep_the_first_test_id():
    tail = "\n".join(f"FAILED tests/test_{i}.py::test_t{i} - AssertionError: " + "x" * 200 for i in range(25))
    tail += "\n" + "\n".join(f"output line {i} padding padding padding" for i in range(20))
    first = _first(tail, AGAIN)
    assert "FAILED tests/test_0.py::test_t0" in first
    assert "Log ends:" in first


def test_no_failed_part_is_made_only_of_assertion_lines():
    """SCN-VER-227: the incident's own excerpt has its failing test in the end, so `Failed:` stays out."""
    tail = "\n".join(
        ["E       assert 1 == 2", "E       assert 3 == 4", "FAILED t.py::t - boom", "1 failed in 1s"]
        + [f"output line {i}" for i in range(2)]
    )
    detail = _first(tail)
    assert "Failed:" not in detail and "FAILED t.py::t" in detail
    only_e = "\n".join(["E       assert 1 == 2"] + [f"output line number {i} that is long enough" for i in range(40)])
    assert "Failed:" not in _first(only_e)
