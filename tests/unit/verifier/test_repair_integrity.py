"""own-test-repair (L4-VER-070): the verifier accepts a repair of the repaired tests only, and the judge sees it."""

from l4.state.ledger import LedgerEvent
from l4.verifier.integrity import (
    check_freeze,
    check_tdd_history,
    check_test_paths,
    check_tests,
    run_integrity,
)
from l4.verifier.types import Severity

from ._integrity_helpers import STAMP, UNIT, UNIT_DIR, event, new_repo, task


def exempt(seq: int, **data: object) -> LedgerEvent:
    """`task.tdd_exempt` (its `kind` is a data key, which `event` cannot take)."""
    return LedgerEvent(STAMP, "r-20261004T0000Z-aaaa", UNIT, seq, "task.tdd_exempt", {"kind": "harness", **data})


FIX = "add-thing-fix-1"
FIX_UNIT = f"openspec:{FIX}"
A = "def test_x():\n    assert helper(1)\n"
A_REPAIRED = "def test_x():\n    assert helper()\n"
B = "def test_y():\n    assert True\n"
B_CHANGED = "def test_y():\n    assert 1\n"


def repair_history(tmp_path, git_environ, *, events=None, extra=None, tdd="exempt", unit=FIX_UNIT, task_key="1.1"):
    """Base; the unit's red commit adds `e2e/test_a.py` and `e2e/test_b.py`; its green commit; then a fix unit's step
    commit that repairs `e2e/test_a.py` (and `extra`). `events` default: what a repair step writes."""
    repo, base = new_repo(tmp_path, git_environ, {"README.md": "x\n"})
    repo.write({"e2e/test_a.py": A, "e2e/test_b.py": B})
    red = repo.commit("red", task="1.1", tdd="red")
    repo.write({"src/app.py": "x = 1\n"})
    green = repo.commit("green", task="1.1", tdd="green")
    repo.write({"e2e/test_a.py": A_REPAIRED, **(extra or {})})
    step = repo.commit("repair", task=task_key, tdd=tdd, unit=unit)
    repo.events = events or [
        event(
            "task.red_ok",
            1,
            task="1.1",
            sha=red,
            frozen=["e2e/test_a.py", "e2e/test_b.py"],
            tests=["e2e.test_a::test_x"],
        ),
        event("task.done", 2, task="1.1", sha=green, tdd="green"),
        event(
            "task.repaired", 3, task=task_key, fix_unit=FIX, files=["e2e/test_a.py"], tests=["e2e/test_a.py::test_x"]
        ),
        exempt(4, task=task_key, fix_unit=FIX, sha=step, finding="F-1", findings=["F-1"]),
        event("task.done", 5, task=task_key, fix_unit=FIX, sha=step, tdd="exempt"),
    ]
    return repo, base, step


def paths_of(out) -> str:
    return " ".join(f.detail for f in out.findings)


def test_an_exempt_commit_may_change_the_files_its_repaired_event_names_and_nothing_else(
    tmp_path, git_environ
):  # SCN-VER-257
    repo, base, step = repair_history(tmp_path, git_environ, extra={"e2e/test_b.py": B_CHANGED})
    ctx = repo.context(base, step, tasks=[(UNIT, task("1.1")), (FIX_UNIT, task("1.1"))])
    out = check_test_paths(ctx)
    [finding] = out.findings
    assert (
        finding.severity is Severity.BLOCKER
        and finding.title == "a test file changed in a step that may not change tests"
    )
    assert "e2e/test_b.py" in finding.detail and "e2e/test_a.py" not in finding.detail


def test_a_repair_commit_that_changes_only_the_repaired_file_is_accepted(tmp_path, git_environ):
    repo, base, step = repair_history(tmp_path, git_environ)
    assert check_test_paths(repo.context(base, step)).findings == []


def test_a_plain_exempt_commit_that_changes_the_same_file_is_still_a_blocker(
    tmp_path, git_environ
):  # SCN-IMP-458 (verifier)
    events = [
        exempt(1, task="1.1", fix_unit=FIX, finding="F-1", findings=["F-1"]),
        event("task.done", 2, task="1.1", fix_unit=FIX, tdd="exempt"),
    ]
    repo, base, step = repair_history(tmp_path, git_environ, events=events)
    assert "e2e/test_a.py" in paths_of(check_test_paths(repo.context(base, step)))


def test_a_repaired_event_of_another_task_unit_or_a_green_commit_does_not_allow_the_change(tmp_path, git_environ):
    named = lambda **over: [  # noqa: E731
        event("task.repaired", 1, **{"task": "1.1", "fix_unit": FIX, "files": ["e2e/test_a.py"], **over}),
        event("task.done", 2, task="1.1", fix_unit=FIX, tdd="exempt"),
    ]
    cases = [
        (named(task="2.1"), {}),  # another task
        (named(fix_unit="add-thing-fix-2"), {}),  # another fix unit
        (named(), {"tdd": "green"}),  # a green commit: only an exempt one has the exception
    ]
    for n, (events, over) in enumerate(cases):
        folder = tmp_path / str(n)
        folder.mkdir()
        repo, base, step = repair_history(folder, git_environ, events=events, **over)
        assert "e2e/test_a.py" in paths_of(check_test_paths(repo.context(base, step))), (n, events)


def test_the_other_checks_do_not_see_a_repair_commit_of_the_units_own_test(tmp_path, git_environ):
    """The red-freeze check compares red and green of one task; the pre-existing-test check compares the base's tests; a
    repair commit is neither, so only the test-path check needs the exception (SCN-VER-257 asks for both)."""
    repo, base, step = repair_history(tmp_path, git_environ)
    ctx = repo.context(base, step, tasks=[(UNIT, task("1.1")), (FIX_UNIT, task("1.1"))])
    for check in (check_freeze, check_tests, check_test_paths, check_tdd_history):
        assert check(ctx).findings == [], check.__name__
    report = run_integrity(ctx)
    assert not report.blocked, [(c.name, c.status) for c in report.checks]
    assert UNIT_DIR  # the unit directory of the helper
