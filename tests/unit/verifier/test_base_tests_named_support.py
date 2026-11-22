"""A support file that a task's reviewed text names and its red step changed stays at head for the run of the base's
tests (L4-VER-079). L4-VER-079 is slippable: its code is `base_tests._named_red_change`, and these are its tests."""

import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from l4.gates.junit import TestCase, TestReport
from l4.verifier.base_tests import FAILS_TITLE, GONE_TITLE, MAX_NAMED_SUPPORT, check_base_tests, kept_files

from ._integrity_helpers import UNIT, event, new_repo
from ._integrity_helpers import task as make_task
from .test_base_tests import ScriptedWb, passing_report

MODULES = "test/arch/modules.ts"
GRAPH = "export const edges = [\n  ['src/a', 'src/c'],\n];\n"
GRAPH_RED = "export const edges = [\n  ['src/a', 'src/c'],\n  ['src/a', 'src/b'],\n];\n"
REPO_TEST = "test('graph', () => {\n  expect(violations(edges)).toEqual([]);\n});\n"
EXTRA = "test/arch/extra.test.ts"  # a test module red changed: it is reverted, so the run happens
BASE = passing_report("test.arch.repo__graph")  # the base report: no test of it belongs to a data file
SOURCE = "plan:p@d"
REASON = f"task 1.1: changed by its red step, named by its reviewed text ({SOURCE})"


def named(red_sha, *, path=MODULES, via="kept", task="1.1", source=SOURCE, seq=1):
    """The ledger event: `task.unfrozen{named_by_task}` that `run_green` records for a green attempt."""
    where = {"paths": [path], "kept": []} if via == "paths" else {"paths": [], "kept": [{"path": path, "why": "x"}]}
    return event("task.unfrozen", seq, task=task, reason="named_by_task", source=source, red_sha=red_sha, **where)


def named_repo(tmp_path, git_environ, *, base=None, red=None, tasks=("1.1",)):
    """The evidence's history: `test/arch/modules.ts` and the unchanged base test at the base, then task 1.1's red
    commit that adds an edge to the graph file."""
    files = {MODULES: GRAPH, "test/arch/repo.test.ts": REPO_TEST, EXTRA: "test('x', () => {});\n", **(base or {})}
    repo, base_sha = new_repo(tmp_path, git_environ, files)
    repo.write({MODULES: GRAPH_RED, EXTRA: "test('x', () => { /* red */ });\n", **(red or {})})
    red_sha = repo.commit("red 1.1", task="1.1", tdd="red")
    return repo, base_sha, red_sha, [(UNIT, make_task(k)) for k in tasks]


def ctx_of(repo, base, head, tasks):
    return repo.context(base, head, tasks=tasks)


@pytest.mark.parametrize("via", ["kept", "paths"])
def test_scn_ver_312_a_named_data_file_stays_at_head_and_is_listed(tmp_path, git_environ, via):  # SCN-VER-312
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.events.append(named(red, via=via))
    ctx = ctx_of(repo, base, red, tasks)
    # a path in `paths` is already freed by `_allowance` (`unfrozen by <source>`): kept either way
    reason = REASON if via == "kept" else f"task 1.1: unfrozen by {SOURCE}"
    assert kept_files(ctx, [MODULES], BASE) == {MODULES: reason}
    wb = ScriptedWb(repo, git_environ, [passing_report("test.arch.repo__graph")], tmp_path / "unit")
    wb.baselines[base] = BASE
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    assert out.findings == []
    assert f"{MODULES} kept at head for the run ({reason})" in out.allowed_tests
    assert out.human_tests == []
    assert wb.events[0][1]["reverted"] == [EXTRA]


def test_scn_ver_312_the_base_test_runs_against_the_head_version(tmp_path, git_environ):  # SCN-VER-312
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.events.append(named(red))
    seen = {}

    class Reading(ScriptedWb):
        def run_gate(self, name, command, **kw):
            seen[name] = (self.worktree / MODULES).read_text()
            return super().run_gate(name, command, **kw)

    wb = Reading(repo, git_environ, [passing_report("test.arch.repo__graph")], tmp_path / "unit")
    wb.baselines[base] = BASE
    out = check_base_tests(wb, ctx_of(repo, base, red, tasks), prior=[], round_no=1)
    assert out.findings == [] and seen["base-tests"] == GRAPH_RED


def test_scn_ver_313_a_file_another_tasks_commit_also_changed_is_reverted(tmp_path, git_environ):  # SCN-VER-313
    repo, base, red, tasks = named_repo(tmp_path, git_environ, tasks=("1.1", "1.2"))
    repo.events.append(named(red))
    repo.write({MODULES: GRAPH_RED + "// 1.2\n"})
    head = repo.commit("red 1.2", task="1.2", tdd="red")  # no event names this commit
    assert kept_files(ctx_of(repo, base, head, tasks), [MODULES], BASE) == {}


@pytest.mark.parametrize("tdd", ["green", "exempt"])
def test_scn_ver_313_a_green_commit_of_the_task_puts_it_back(tmp_path, git_environ, tdd):  # SCN-VER-313
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.events.append(named(red))
    repo.write({MODULES: GRAPH_RED + "// green\n"})
    head = repo.commit("green 1.1", task="1.1", tdd=tdd)
    assert kept_files(ctx_of(repo, base, head, tasks), [MODULES], BASE) == {}


def test_scn_ver_313_a_fix_units_commit_is_not_covered(tmp_path, git_environ):  # SCN-VER-313
    repo, base, _, _ = named_repo(tmp_path, git_environ)
    repo.git("reset", "-q", "--hard", base)
    repo.write({MODULES: GRAPH_RED})
    fix = repo.commit("red fix", task="1.1", tdd="red", unit="openspec:fix-thing")
    repo.events.append(named(fix))  # an event of the unit's task 1.1: the fix unit's commit is another unit
    assert kept_files(ctx_of(repo, base, fix, [(UNIT, make_task("1.1"))]), [MODULES], BASE) == {}


def test_scn_ver_313_a_commit_without_a_task_trailer_is_not_covered(tmp_path, git_environ):  # SCN-VER-313
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.events.append(named(red))
    repo.write({MODULES: GRAPH_RED + "// x\n"})
    head = repo.commit_as_harness("lessons", phase="lessons")
    assert kept_files(ctx_of(repo, base, head, tasks), [MODULES], BASE) == {}


def test_scn_ver_314_an_older_reds_event_covers_nothing(tmp_path, git_environ):  # SCN-VER-314
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.events.append(named("0" * 40))  # the event of an earlier red commit of a reopened task
    assert kept_files(ctx_of(repo, base, red, tasks), [MODULES], BASE) == {}


def test_scn_ver_314_an_event_without_a_source_covers_nothing(tmp_path, git_environ):  # SCN-VER-314
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.events.append(named(red, source=""))
    assert kept_files(ctx_of(repo, base, red, tasks), [MODULES], BASE) == {}


def test_scn_ver_314_an_event_of_another_reason_or_task_covers_nothing(tmp_path, git_environ):  # SCN-VER-314
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.events.append(named(red, task="1.2"))
    repo.events.append(
        event(
            "task.unfrozen",
            2,
            task="1.1",
            reason="human_answer",
            paths=[],
            red_sha=red,
            kept=[{"path": MODULES, "why": "x"}],
        )
    )
    assert kept_files(ctx_of(repo, base, red, tasks), [MODULES], BASE) == {}


def test_scn_ver_314_an_event_for_another_path_covers_nothing(tmp_path, git_environ):  # SCN-VER-314
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.events.append(named(red, path="test/arch/other.ts"))
    assert kept_files(ctx_of(repo, base, red, tasks), [MODULES], BASE) == {}


def test_scn_ver_314_an_ignore_file_a_test_module_and_an_added_file_are_reverted(tmp_path, git_environ):  # SCN-VER-314
    repo, base, red, tasks = named_repo(
        tmp_path,
        git_environ,
        base={".gitignore": "dist\n"},
        red={
            ".gitignore": "dist\nbuild\n",
            "test/arch/repo.test.ts": REPO_TEST + "// red\n",
            "test/arch/new.ts": "x\n",
        },
    )
    for path in (".gitignore", "test/arch/repo.test.ts", "test/arch/new.ts"):
        repo.events.append(named(red, path=path))
    ctx = ctx_of(repo, base, red, tasks)
    assert kept_files(ctx, [".gitignore", "test/arch/repo.test.ts", "test/arch/new.ts"], BASE) == {}


def test_scn_ver_314_a_rewrite_over_the_line_bound_is_reverted(tmp_path, git_environ):  # SCN-VER-314
    big = "".join(f"export const e{i} = {i};\n" for i in range(60))
    repo, base, red, tasks = named_repo(
        tmp_path, git_environ, base={"test/arch/big.ts": "x\n"}, red={"test/arch/big.ts": big}
    )
    repo.events.append(named(red, path="test/arch/big.ts"))
    assert kept_files(ctx_of(repo, base, red, tasks), ["test/arch/big.ts"], BASE) == {}


def test_scn_ver_314_a_binary_file_is_reverted(tmp_path, git_environ):  # SCN-VER-314
    repo, base, _, tasks = named_repo(tmp_path, git_environ, base={"test/arch/img.dat": "x\n"})
    (repo.path / "test/arch/img.dat").write_bytes(b"\x00\x01\x02\xff")
    red = repo.commit("binary", task="1.1", tdd="red")
    repo.events.append(named(red, path="test/arch/img.dat"))
    assert kept_files(ctx_of(repo, base, red, tasks), ["test/arch/img.dat"], BASE) == {}


@pytest.mark.parametrize(("added", "stays"), [(40, True), (41, False)])
def test_scn_ver_314_forty_changed_lines_stay_and_forty_one_do_not(tmp_path, git_environ, added, stays):  # SCN-VER-314
    path = "test/arch/a.ts"
    appended = "export {};\n" + "".join(f"export const n{i} = {i};\n" for i in range(added))
    repo, base, red, tasks = named_repo(tmp_path, git_environ, base={path: "export {};\n"}, red={path: appended})
    repo.events.append(named(red, path=path))
    assert (path in kept_files(ctx_of(repo, base, red, tasks), [path], BASE)) is stays


def test_scn_ver_314_only_the_first_three_named_files_stay_and_the_note_counts_the_rest(
    tmp_path, git_environ
):  # SCN-VER-314
    extra = {f"test/arch/d{i}.ts": f"export const d{i} = 1;\n" for i in range(4)}
    repo, base, red, tasks = named_repo(tmp_path, git_environ, base={k: "x\n" for k in extra}, red=extra)
    paths = sorted(extra)
    for path in paths:
        repo.events.append(named(red, path=path))
    ctx = ctx_of(repo, base, red, tasks)
    kept = kept_files(ctx, paths, BASE)
    assert MAX_NAMED_SUPPORT == 3 and sorted(kept) == paths[:3]
    wb = ScriptedWb(repo, git_environ, [passing_report("test.arch.repo__graph")], tmp_path / "unit")
    wb.baselines[base] = BASE
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    assert out.findings == []
    assert paths[3] in wb.events[0][1]["reverted"] and paths[0] not in wb.events[0][1]["reverted"]
    assert "1 more support file(s) named by task 1.1 reverted (at most 3 kept)" in out.note


def test_scn_ver_315_the_comparison_of_pre_existing_tests_is_unchanged(tmp_path, git_environ):  # SCN-VER-315
    from l4.verifier import integrity

    helper = "tests/helpers/shared.py"
    base_text = "def test_shared():\n    assert 1\n"
    repo, base = new_repo(tmp_path, git_environ, {helper: base_text})
    repo.write({helper: "def test_shared():\n    assert 2\n"})
    red = repo.commit("red 1.1", task="1.1", tdd="red")
    repo.events.append(named(red, path=helper))
    ctx = ctx_of(repo, base, red, [(UNIT, make_task("1.1"))])
    out = integrity.check_tests(ctx)
    assert any("pre-existing test was changed" in f.title for f in out.findings)


def test_scn_ver_316_a_ledger_of_0_4_59_keeps_the_file_on_the_next_round(tmp_path, git_environ):  # SCN-VER-316
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    # the event as 0.4.59's `run_green` wrote it: no key this change adds
    repo.events.append(
        event(
            "task.unfrozen",
            1,
            task="1.1",
            paths=[],
            reason="named_by_task",
            source=SOURCE,
            red_sha=red,
            kept=[{"path": MODULES, "why": "a red test of this task"}],
        )
    )
    assert kept_files(ctx_of(repo, base, red, tasks), [MODULES], BASE) == {MODULES: REASON}


# the blocker's text and its records (L4-VER-080)

TOKEN = "glpat-" + "A1b2C3d4E5f6G7h8I9j0"
FAILING_ID = "test.arch.repo::graph"
BODY = "AssertionError: expected [ 'src/a -> src/b' ] to deeply equal []\n  at test/arch/repo.test.ts:3\n"


def failing_case(message="expected [ 'src/a -> src/b' ] to deeply equal []", body=BODY):
    return TestCase(FAILING_ID, "failed", message, failure_kind="assertion", detail=body)


def failing_run(tmp_path, git_environ, *, named_task=True, extra=None, report=None):
    """The unit of SCN-VER-313: `modules.ts` changed by task 1.1's named red commit and by 1.2's red commit, so step 1
    reverts it, and the base test (which passed at the base) fails."""
    repo, base, red, tasks = named_repo(tmp_path, git_environ, tasks=("1.1", "1.2"), **(extra or {}))
    if named_task:
        repo.events.append(named(red))
    repo.write({MODULES: GRAPH_RED + "// 1.2\n"})
    head = repo.commit("red 1.2", task="1.2", tdd="red")
    wb = ScriptedWb(repo, git_environ, [report or TestReport({FAILING_ID: failing_case()})], tmp_path / "unit")
    wb.baselines[base] = BASE
    wb.baselines[base] = passing_report(FAILING_ID.replace("::", "__"))
    return wb, ctx_of(repo, base, head, tasks), repo


def test_scn_ver_317_the_blocker_names_the_reverted_file_and_the_tasks_that_changed_it(tmp_path, git_environ):
    wb, ctx, _ = failing_run(tmp_path, git_environ)
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    reverted = wb.events[0][1]["reverted"]
    assert MODULES in reverted
    [finding] = out.findings
    lead = (
        f"with the unit's test and support files at their base version (support files reverted: {MODULES} "
        f"(task 1.1, 1.2); {len(reverted)} files in all), these base tests fail: "
    )
    assert finding.title == FAILS_TITLE and finding.detail == (
        lead + f"{FAILING_ID} (expected [ 'src/a -> src/b' ] to deeply equal [])"
    )
    assert wb.events[0][1]["support_reverted"] == [{"path": MODULES, "tasks": ["1.1", "1.2"], "people": False}]


def test_the_detail_of_a_base_test_that_no_longer_runs_leads_the_same_way(tmp_path, git_environ):
    wb, ctx, _ = failing_run(
        tmp_path, git_environ, report=TestReport({"other::t": TestCase("other::t", "failed", "x")})
    )
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    [finding] = out.findings
    assert finding.title == GONE_TITLE
    assert finding.detail.startswith("with the unit's test and support files at their base version (support files")
    assert f"; {len(wb.events[0][1]['reverted'])} files in all), these base tests no longer run: " in finding.detail
    assert finding.detail.endswith(FAILING_ID)


def test_at_most_five_files_are_named_and_the_rest_counted(tmp_path, git_environ):
    many = {f"test/arch/s{i}.ts": f"export const s{i} = 1;\n" for i in range(7)}
    wb, ctx, _ = failing_run(tmp_path, git_environ, extra={"base": {k: "x\n" for k in many}, "red": many})
    [finding] = check_base_tests(wb, ctx, prior=[], round_no=1).findings
    support = wb.events[0][1]["support_reverted"]
    assert len(support) == 8  # modules.ts and the seven others; the extra test module is no support file
    assert [e["path"] for e in support] == sorted(e["path"] for e in support)
    assert finding.detail.count(" (task 1.") == 5 and "(+3 more)" in finding.detail


def test_the_record_is_cut_at_twenty_entries(tmp_path, git_environ):
    many = {f"test/arch/s{i:02}.ts": f"export const s{i} = 1;\n" for i in range(25)}
    wb, ctx, _ = failing_run(tmp_path, git_environ, extra={"base": {k: "x\n" for k in many}, "red": many})
    [finding] = check_base_tests(wb, ctx, prior=[], round_no=1).findings
    assert len(wb.events[0][1]["support_reverted"]) == 20 and "(+21 more); 27 files in all)" in finding.detail


def test_a_reverted_file_a_person_and_a_taskless_harness_commit_changed_is_a_person_s(  # SCN-VER-327
    tmp_path, git_environ
):
    repo, base = new_repo(tmp_path, git_environ, {MODULES: GRAPH, "tests/test_a.py": "def test_a():\n    assert 1\n"})
    repo.write({MODULES: GRAPH_RED})
    repo.commit_as_human("a person edits")
    repo.write({MODULES: GRAPH_RED + "// h\n", "tests/test_a.py": "def test_a():\n    assert 2\n"})
    head = repo.commit_as_harness("a harness commit with no task", phase="implementing")
    wb = ScriptedWb(repo, git_environ, [TestReport({FAILING_ID: failing_case()})], tmp_path / "unit")
    wb.baselines[base] = BASE
    wb.baselines[base] = passing_report(FAILING_ID.replace("::", "__"))
    [finding] = check_base_tests(wb, ctx_of(repo, base, head, []), prior=[], round_no=1).findings
    assert wb.events[0][1]["support_reverted"] == [{"path": MODULES, "tasks": [], "people": True}]
    assert f"reverted: {MODULES} (a person); 2 files in all)" in finding.detail


def test_a_reverted_file_only_a_taskless_harness_commit_changed_is_a_harness_commit_s(  # SCN-VER-327
    tmp_path, git_environ
):
    repo, base = new_repo(tmp_path, git_environ, {MODULES: GRAPH, "tests/test_a.py": "def test_a():\n    assert 1\n"})
    repo.write({MODULES: GRAPH_RED, "tests/test_a.py": "def test_a():\n    assert 2\n"})
    head = repo.commit_as_harness("lessons", phase="lessons")  # no L4-Task trailer
    wb = ScriptedWb(repo, git_environ, [TestReport({FAILING_ID: failing_case()})], tmp_path / "unit")
    wb.baselines[base] = passing_report(FAILING_ID.replace("::", "__"))
    [finding] = check_base_tests(wb, ctx_of(repo, base, head, []), prior=[], round_no=1).findings
    assert wb.events[0][1]["support_reverted"] == [{"path": MODULES, "tasks": [], "people": False}]
    assert f"reverted: {MODULES} (a harness commit); 2 files in all)" in finding.detail
    assert "(a person)" not in finding.detail


def test_with_no_reverted_support_file_the_detail_is_as_before_and_the_key_is_empty(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_a.py": "def test_a():\n    assert 1\n"})
    repo.write({"tests/test_a.py": "def test_a():\n    assert 2\n"})
    head = repo.commit("red", task="1.1", tdd="red")
    failed = TestReport({"tests.test_a::test_a": TestCase("tests.test_a::test_a", "failed", "boom")})
    wb = ScriptedWb(repo, git_environ, [failed], tmp_path / "unit")
    wb.baselines[base] = BASE
    wb.baselines[base] = passing_report("tests.test_a__test_a")
    out = check_base_tests(wb, repo.context(base, head, tasks=[(UNIT, make_task("1.1"))]), prior=[], round_no=1)
    [finding] = out.findings
    assert finding.detail == "tests.test_a::test_a (boom)" and wb.events[0][1]["support_reverted"] == []


def test_each_failing_base_test_has_a_failures_record_with_its_excerpt(tmp_path, git_environ):  # SCN-VER-318
    wb, ctx, _ = failing_run(tmp_path, git_environ)
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    record = out.failures[FAILING_ID]
    assert record["gate"] == "base-tests" and record["kind"] == "assertion"
    assert record["message"] == "expected [ 'src/a -> src/b' ] to deeply equal []"
    assert "AssertionError: expected [ 'src/a -> src/b' ] to deeply equal []" in record["excerpt"]
    assert list(out.failures) == [FAILING_ID]  # a base test that no longer runs has no case, so no record


def test_scn_ver_319_a_secret_is_in_no_record_and_the_detail_stays_redacted_by_the_writer(tmp_path, git_environ):
    case = failing_case(message=f"token {TOKEN} rejected", body=f"E   token {TOKEN} rejected\n")
    wb, ctx, _ = failing_run(tmp_path, git_environ, report=TestReport({FAILING_ID: case}))
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    assert TOKEN not in str(out.failures) and "A1b2C3d4E5f6G7h8I9j0" not in str(out.failures)
    assert out.failures[FAILING_ID]["gate"] == "base-tests"


def test_a_ledger_of_0_4_59_without_the_key_changes_nothing_for_the_readers():  # L4-VER-080
    from l4.verifier.failures import BASE_FAILS_TITLE, shown_failure_ids

    assert FAILS_TITLE == BASE_FAILS_TITLE
    assert shown_failure_ids({"a::b": {"gate": "test", "kind": "assertion", "message": "x"}}, FAILS_TITLE, "") == []


def test_a_run_that_gave_no_report_still_records_the_reverted_support_files(tmp_path, git_environ):  # L4-VER-080
    wb, ctx, _ = failing_run(tmp_path, git_environ)
    wb._reports.clear()  # the gate gives no report
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    assert "gave no report" in out.findings[0].detail
    assert wb.events[0][1]["support_reverted"] == [{"path": MODULES, "tasks": ["1.1", "1.2"], "people": False}]


def test_an_event_that_names_a_commit_which_is_no_red_step_covers_nothing(tmp_path, git_environ):  # SCN-VER-313
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.git("reset", "-q", "--hard", base)
    repo.write({MODULES: GRAPH_RED + "// green\n"})
    green = repo.commit("green 1.1 alone", task="1.1", tdd="green")
    repo.events.append(named(green))  # the event names the commit, but it is a green commit
    assert kept_files(ctx_of(repo, base, green, tasks), [MODULES], BASE) == {}


def test_a_path_no_commit_changed_is_not_kept_and_does_not_fail(tmp_path, git_environ):  # SCN-VER-314
    repo, base, red, tasks = named_repo(tmp_path, git_environ, base={"test/arch/untouched.ts": "x\n"})
    repo.events.append(named(red, path="test/arch/untouched.ts"))
    assert kept_files(ctx_of(repo, base, red, tasks), ["test/arch/untouched.ts", "no/such/file.ts"], BASE) == {}


# a file the base's own tests live in is never kept (L4-VER-079, the base report decides)


def _no_base_run(monkeypatch, report=None):
    """FAKE merge-base run: the base reference of a unit with no cached baseline (`report` None: it gave none)."""
    monkeypatch.setattr("l4.verifier.base_tests.base_checkout", lambda wb, sha: _tree(wb))
    monkeypatch.setattr(
        "l4.verifier.base_tests.run_gate_at",
        lambda wb, tree, spec, network: SimpleNamespace(report=report, reason="FAKE: no report"),
    )


@contextmanager
def _tree(wb):
    yield wb.worktree


def _hosting_run(tmp_path, git_environ, path, ids, *, base_text="export const x = 1;\n"):
    """A unit whose task 1.1 names `path`, a file with no test-looking name that red changed, and whose base report
    holds `ids`. Returns the workbench, the context and the base report."""
    repo, base, red, tasks = named_repo(tmp_path, git_environ, base={path: base_text}, red={path: base_text + "// r\n"})
    repo.events.append(named(red, path=path))
    report = TestReport({i: TestCase(i, "passed") for i in ids}) if ids else None
    wb = ScriptedWb(repo, git_environ, [passing_report("test.arch.repo__graph")], tmp_path / "unit")
    if report is not None:
        wb.baselines[base] = report
    return wb, ctx_of(repo, base, red, tasks), report


@pytest.mark.parametrize(
    ("path", "ids"),
    [
        ("src/__tests__/render.ts", ["src/__tests__/render.ts::renders"]),
        ("test/arch/repo.ts", ["test/arch/repo.ts::graph"]),
        ("test/helpers/x.ts", ["./test/helpers/x.ts::a"]),
        ("src/test/java/com/acme/Shared.java", ["com.acme.Shared::works"]),
        ("tests/helpers.py", ["tests.helpers.TestIt::t"]),
    ],
)
def test_scn_ver_324_a_named_file_a_base_test_lives_in_is_reverted(tmp_path, git_environ, path, ids):  # SCN-VER-324
    wb, ctx, report = _hosting_run(tmp_path, git_environ, path, ids)
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    assert path in wb.events[0][1]["reverted"]
    assert not any(a.startswith(f"{path} kept") for a in out.allowed_tests)
    assert kept_files(ctx, [path], report) == {}


def test_scn_ver_324_a_data_file_no_base_test_id_maps_to_stays(tmp_path, git_environ):  # SCN-VER-324
    path = "src/__tests__/data.ts"
    wb, ctx, report = _hosting_run(tmp_path, git_environ, path, ["src/__tests__/render.ts::renders", "a.b::c"])
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    assert any(a.startswith(f"{path} kept at head") for a in out.allowed_tests)
    assert path not in wb.events[0][1]["reverted"]
    assert kept_files(ctx, [path], report) == {
        path: f"task 1.1: changed by its red step, named by its reviewed text ({SOURCE})"
    }


@pytest.mark.parametrize("via", ["kept", "paths"])
def test_scn_ver_326_a_plan_named_people_does_not_file_the_kept_file_as_a_persons(
    tmp_path, git_environ, via
):  # SCN-VER-326
    source = "plan:people-ops@d"  # the reason text embeds the source: routing must not read it
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.events.append(named(red, via=via, source=source))
    ctx = ctx_of(repo, base, red, tasks)
    wb = ScriptedWb(repo, git_environ, [passing_report("test.arch.repo__graph")], tmp_path / "unit")
    wb.baselines[base] = BASE
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    [line] = [a for a in out.allowed_tests if a.startswith(f"{MODULES} kept at head")]
    assert source in line and out.human_tests == []


def test_scn_ver_326_a_file_only_people_changed_is_still_a_persons_line(tmp_path, git_environ):  # SCN-VER-326
    repo, base = new_repo(tmp_path, git_environ, {MODULES: GRAPH, "test/arch/repo.test.ts": REPO_TEST})
    repo.write({MODULES: GRAPH_RED})
    head = repo.commit_as_human("a person edits the graph")
    wb = ScriptedWb(repo, git_environ, [passing_report("test.arch.repo__graph")], tmp_path / "unit")
    out = check_base_tests(wb, ctx_of(repo, base, head, []), prior=[], round_no=1)
    assert [h for h in out.human_tests if h.startswith(f"{MODULES} kept at head")] and out.allowed_tests == []


def test_scn_ver_325_with_no_base_report_nothing_is_kept_by_the_named_rule(tmp_path, git_environ, monkeypatch):
    path = "test/arch/data.ts"  # SCN-VER-325
    wb, ctx, _ = _hosting_run(tmp_path, git_environ, path, [])
    _no_base_run(monkeypatch)
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    assert path in wb.events[0][1]["reverted"]
    assert not any(a.startswith(f"{path} kept") for a in out.allowed_tests)
    assert kept_files(ctx, [path]) == {} and kept_files(ctx, [path], None) == {}


def test_scn_ver_325_the_base_reference_is_fetched_only_for_a_named_file(tmp_path, git_environ, monkeypatch):
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_a.py": "def test_a():\n    assert 1\n"})
    repo.write({"tests/test_a.py": "def test_a():\n    assert 2\n"})
    head = repo.commit("red", task="1.1", tdd="red")
    wb = ScriptedWb(repo, git_environ, [passing_report("tests.test_a__test_a")], tmp_path / "unit")
    _no_base_run(monkeypatch)
    monkeypatch.setattr(
        "l4.verifier.base_tests.run_gate_at", lambda *a, **k: pytest.fail("the base was run for no named file")
    )
    out = check_base_tests(wb, ctx_of(repo, base, head, [(UNIT, make_task("1.1"))]), prior=[], round_no=1)
    assert out.findings == []


# what the rule does not widen to (SCN-VER-328): each test below kills a mutant of `_names_red_change` or `_regular`


@pytest.mark.parametrize(
    ("changed", "text_names"),
    [
        ("test/arch/x.ts", "test/arch/x.tsx"),
        ("test/arch/x.tsx", "test/arch/x.ts"),
        ("test/arch/x.ts", "test/arch/x"),
        ("test/arch/sub/x.ts", "x.ts"),
        ("test/arch/x.ts", "test/arch"),
    ],
)
def test_scn_ver_328_a_path_the_text_does_not_name_exactly_is_reverted(tmp_path, git_environ, changed, text_names):
    repo, base, red, tasks = named_repo(tmp_path, git_environ, base={changed: "x\n"}, red={changed: "x\ny\n"})
    repo.events.append(named(red, path=text_names))
    ctx = ctx_of(repo, base, red, tasks)
    assert kept_files(ctx, [changed], BASE) == {}
    repo.events.append(named(red, path=changed, seq=2))  # the control: named exactly, the same file stays
    assert list(kept_files(ctx, [changed], BASE)) == [changed]


def _link(repo, path, target="../elsewhere.ts"):
    (repo.path / path).unlink()
    os.symlink(target, repo.path / path)


def test_scn_ver_328_a_named_file_that_is_a_link_at_head_is_reverted(tmp_path, git_environ):
    path = "test/arch/data.ts"
    repo, base, _, tasks = named_repo(tmp_path, git_environ, base={path: "export const a = 1;\n"})
    _link(repo, path)
    red = repo.commit("red 1.1 replaces the file by a link", task="1.1", tdd="red")
    repo.events.append(named(red, path=path))
    assert kept_files(ctx_of(repo, base, red, tasks), [path], BASE) == {}


def test_scn_ver_328_a_named_file_that_is_a_link_at_the_base_is_reverted(tmp_path, git_environ):
    path = "test/arch/data.ts"
    repo, base0, _, _ = named_repo(tmp_path, git_environ, base={path: "export const a = 1;\n"})
    repo.git("reset", "-q", "--hard", base0)
    _link(repo, path)
    base = repo.commit("the base holds a link")
    (repo.path / path).unlink()
    repo.write({path: "export const a = 1;\n"})
    red = repo.commit("red 1.1 makes it a file", task="1.1", tdd="red")
    repo.events.append(named(red, path=path))
    assert kept_files(ctx_of(repo, base, red, [(UNIT, make_task("1.1"))]), [path], BASE) == {}


def test_scn_ver_328_a_named_file_deleted_at_head_is_reverted(tmp_path, git_environ):
    path = "test/arch/data.ts"
    repo, base, _, tasks = named_repo(tmp_path, git_environ, base={path: "export const a = 1;\n"})
    repo.delete(path)
    red = repo.commit("red 1.1 deletes the file", task="1.1", tdd="red")
    repo.events.append(named(red, path=path))
    assert kept_files(ctx_of(repo, base, red, tasks), [path], BASE) == {}


@pytest.mark.parametrize("reason", ["human_answer", "delegate_answer", "", None])
def test_scn_ver_328_an_unfreeze_of_another_reason_keeps_nothing_by_this_rule(tmp_path, git_environ, reason):
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    data = {"task": "1.1", "paths": [], "red_sha": red, "source": SOURCE, "kept": [{"path": MODULES, "why": "x"}]}
    if reason is not None:
        data["reason"] = reason
    repo.events.append(event("task.unfrozen", 1, **data))  # a source and a kept entry, but not `named_by_task`
    assert kept_files(ctx_of(repo, base, red, tasks), [MODULES], BASE) == {}
