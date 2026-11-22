"""A support file that a task's reviewed text names and its red step changed stays at head for the run of the base's
tests (L4-VER-079). L4-VER-079 is slippable: its code is `base_tests._named_red_change`, and these are its tests."""

import pytest

from l4.verifier.base_tests import MAX_NAMED_SUPPORT, check_base_tests, kept_files

from ._integrity_helpers import UNIT, event, new_repo
from ._integrity_helpers import task as make_task
from .test_base_tests import ScriptedWb, passing_report

MODULES = "test/arch/modules.ts"
GRAPH = "export const edges = [\n  ['src/a', 'src/c'],\n];\n"
GRAPH_RED = "export const edges = [\n  ['src/a', 'src/c'],\n  ['src/a', 'src/b'],\n];\n"
REPO_TEST = "test('graph', () => {\n  expect(violations(edges)).toEqual([]);\n});\n"
EXTRA = "test/arch/extra.test.ts"  # a test module red changed: it is reverted, so the run happens
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
    assert kept_files(ctx, [MODULES]) == {MODULES: reason}
    wb = ScriptedWb(repo, git_environ, [passing_report("test.arch.repo__graph")], tmp_path / "unit")
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
    out = check_base_tests(wb, ctx_of(repo, base, red, tasks), prior=[], round_no=1)
    assert out.findings == [] and seen["base-tests"] == GRAPH_RED


def test_scn_ver_313_a_file_another_tasks_commit_also_changed_is_reverted(tmp_path, git_environ):  # SCN-VER-313
    repo, base, red, tasks = named_repo(tmp_path, git_environ, tasks=("1.1", "1.2"))
    repo.events.append(named(red))
    repo.write({MODULES: GRAPH_RED + "// 1.2\n"})
    head = repo.commit("red 1.2", task="1.2", tdd="red")  # no event names this commit
    assert kept_files(ctx_of(repo, base, head, tasks), [MODULES]) == {}


@pytest.mark.parametrize("tdd", ["green", "exempt"])
def test_scn_ver_313_a_green_commit_of_the_task_puts_it_back(tmp_path, git_environ, tdd):  # SCN-VER-313
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.events.append(named(red))
    repo.write({MODULES: GRAPH_RED + "// green\n"})
    head = repo.commit("green 1.1", task="1.1", tdd=tdd)
    assert kept_files(ctx_of(repo, base, head, tasks), [MODULES]) == {}


def test_scn_ver_313_a_fix_units_commit_is_not_covered(tmp_path, git_environ):  # SCN-VER-313
    repo, base, _, _ = named_repo(tmp_path, git_environ)
    repo.git("reset", "-q", "--hard", base)
    repo.write({MODULES: GRAPH_RED})
    fix = repo.commit("red fix", task="1.1", tdd="red", unit="openspec:fix-thing")
    repo.events.append(named(fix))  # an event of the unit's task 1.1: the fix unit's commit is another unit
    assert kept_files(ctx_of(repo, base, fix, [(UNIT, make_task("1.1"))]), [MODULES]) == {}


def test_scn_ver_313_a_commit_without_a_task_trailer_is_not_covered(tmp_path, git_environ):  # SCN-VER-313
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.events.append(named(red))
    repo.write({MODULES: GRAPH_RED + "// x\n"})
    head = repo.commit_as_harness("lessons", phase="lessons")
    assert kept_files(ctx_of(repo, base, head, tasks), [MODULES]) == {}


def test_scn_ver_314_an_older_reds_event_covers_nothing(tmp_path, git_environ):  # SCN-VER-314
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.events.append(named("0" * 40))  # the event of an earlier red commit of a reopened task
    assert kept_files(ctx_of(repo, base, red, tasks), [MODULES]) == {}


def test_scn_ver_314_an_event_without_a_source_covers_nothing(tmp_path, git_environ):  # SCN-VER-314
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.events.append(named(red, source=""))
    assert kept_files(ctx_of(repo, base, red, tasks), [MODULES]) == {}


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
    assert kept_files(ctx_of(repo, base, red, tasks), [MODULES]) == {}


def test_scn_ver_314_an_event_for_another_path_covers_nothing(tmp_path, git_environ):  # SCN-VER-314
    repo, base, red, tasks = named_repo(tmp_path, git_environ)
    repo.events.append(named(red, path="test/arch/other.ts"))
    assert kept_files(ctx_of(repo, base, red, tasks), [MODULES]) == {}


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
    assert kept_files(ctx, [".gitignore", "test/arch/repo.test.ts", "test/arch/new.ts"]) == {}


def test_scn_ver_314_a_rewrite_over_the_line_bound_is_reverted(tmp_path, git_environ):  # SCN-VER-314
    big = "".join(f"export const e{i} = {i};\n" for i in range(60))
    repo, base, red, tasks = named_repo(
        tmp_path, git_environ, base={"test/arch/big.ts": "x\n"}, red={"test/arch/big.ts": big}
    )
    repo.events.append(named(red, path="test/arch/big.ts"))
    assert kept_files(ctx_of(repo, base, red, tasks), ["test/arch/big.ts"]) == {}


def test_scn_ver_314_a_binary_file_is_reverted(tmp_path, git_environ):  # SCN-VER-314
    repo, base, _, tasks = named_repo(tmp_path, git_environ, base={"test/arch/img.dat": "x\n"})
    (repo.path / "test/arch/img.dat").write_bytes(b"\x00\x01\x02\xff")
    red = repo.commit("binary", task="1.1", tdd="red")
    repo.events.append(named(red, path="test/arch/img.dat"))
    assert kept_files(ctx_of(repo, base, red, tasks), ["test/arch/img.dat"]) == {}


@pytest.mark.parametrize(("added", "stays"), [(40, True), (41, False)])
def test_scn_ver_314_forty_changed_lines_stay_and_forty_one_do_not(tmp_path, git_environ, added, stays):  # SCN-VER-314
    path = "test/arch/a.ts"
    appended = "export {};\n" + "".join(f"export const n{i} = {i};\n" for i in range(added))
    repo, base, red, tasks = named_repo(tmp_path, git_environ, base={path: "export {};\n"}, red={path: appended})
    repo.events.append(named(red, path=path))
    assert (path in kept_files(ctx_of(repo, base, red, tasks), [path])) is stays


def test_scn_ver_314_only_the_first_three_named_files_stay_and_the_note_counts_the_rest(
    tmp_path, git_environ
):  # SCN-VER-314
    extra = {f"test/arch/d{i}.ts": f"export const d{i} = 1;\n" for i in range(4)}
    repo, base, red, tasks = named_repo(tmp_path, git_environ, base={k: "x\n" for k in extra}, red=extra)
    paths = sorted(extra)
    for path in paths:
        repo.events.append(named(red, path=path))
    ctx = ctx_of(repo, base, red, tasks)
    kept = kept_files(ctx, paths)
    assert MAX_NAMED_SUPPORT == 3 and sorted(kept) == paths[:3]
    wb = ScriptedWb(repo, git_environ, [passing_report("test.arch.repo__graph")], tmp_path / "unit")
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
    assert kept_files(ctx_of(repo, base, red, tasks), [MODULES]) == {MODULES: REASON}
