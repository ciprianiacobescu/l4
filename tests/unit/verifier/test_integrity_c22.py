"""Contract C22 at the M1.3 merge: `task.red_ok` and `task.done` are written before their commits and carry the step
`base`, not a `sha`. Step 1 reads the red and green shas from `task.red_committed` / `task.green_committed`, or, when a
kill lost those lines, derives them from the commits (the unit's commit for the task whose first parent is `base`)."""

from l4.verifier.integrity import check_freeze, check_tdd_history, run_integrity

from ._integrity_helpers import event, new_repo

TEST = "def test_a():\n    assert 1\n"


def _red_green(tmp_path, git_environ, *, committed: bool = True, tamper: bool = False):
    """One task, red then green, with the ledger M1.4's `run_red` / `run_green` write."""
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({"tests/test_a.py": TEST})
    red = repo.commit("red", task="1.1", tdd="red")
    repo.write({"src/a.py": "X = 1\n"})
    if tamper:
        repo.write({"tests/test_a.py": TEST + "\n\ndef test_b():\n    pass\n"})
    green = repo.commit("green", task="1.1", tdd="green")
    repo.events = [event("task.red_ok", 1, task="1.1", base=base, tests=["t"], frozen=["tests/test_a.py"])]
    if committed:
        repo.events.append(event("task.red_committed", 2, task="1.1", base=base, sha=red))
    repo.events.append(event("task.done", 3, task="1.1", base=red, parents=[], notes=""))
    if committed:
        repo.events.append(event("task.green_committed", 4, task="1.1", base=red, sha=green))
    return repo, base, green


def test_a_happy_red_green_with_the_c22_ledger_passes_freeze_and_tdd_history(tmp_path, git_environ):
    repo, base, head = _red_green(tmp_path, git_environ)
    ctx = repo.context(base, head)
    freeze, history = check_freeze(ctx), check_tdd_history(ctx)
    assert not freeze.findings and not freeze.skipped, freeze.note
    assert not history.findings and not history.skipped, history.note
    report = run_integrity(ctx)
    statuses = {c.name: c.status for c in report.checks}
    assert statuses["red-green freeze"] == "ok" and statuses["tdd history"] == "ok", statuses


def test_shas_are_derived_from_the_commits_when_the_committed_lines_were_lost(tmp_path, git_environ):
    repo, base, head = _red_green(tmp_path, git_environ, committed=False)
    ctx = repo.context(base, head)
    freeze, history = check_freeze(ctx), check_tdd_history(ctx)
    assert not freeze.findings and not freeze.skipped, freeze.note
    assert not history.findings and not history.skipped, history.note


def test_a_frozen_test_changed_between_red_and_green_is_still_caught(tmp_path, git_environ):
    for committed in (True, False):
        (tmp_path / str(committed)).mkdir()
        repo, base, head = _red_green(tmp_path / str(committed), git_environ, committed=committed, tamper=True)
        [finding] = check_freeze(repo.context(base, head)).findings
        assert "frozen test" in finding.title and "tests/test_a.py" in finding.detail


def test_a_red_event_whose_base_matches_no_commit_is_a_mismatch(tmp_path, git_environ):
    repo, base, head = _red_green(tmp_path, git_environ, committed=False)
    repo.events[0] = event("task.red_ok", 1, task="1.1", base=head, tests=["t"], frozen=[])
    [finding] = check_tdd_history(repo.context(base, head)).findings
    assert "do not match the ledger" in finding.title


def test_already_satisfied_with_the_c22_ledger_matches(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({"tests/test_a.py": TEST})
    sha = repo.commit("sat", task="1.1", tdd="already-satisfied")
    before = [
        event("task.red_ok", 1, task="1.1", base=base, tests=["t"], frozen=[]),
        event("task.done", 2, task="1.1", base=base, parents=[], notes="", tdd="already-satisfied"),
    ]
    after = [
        event("task.red_committed", 3, task="1.1", base=base, sha=sha),
        event("task.green_committed", 4, task="1.1", base=base, sha=sha),
    ]
    for events in (before + after, before):
        repo.events = events
        history = check_tdd_history(repo.context(base, sha))
        assert not history.findings and not history.skipped, history.note


def test_a_parent_closed_without_a_step_has_no_tdd_history_to_check(tmp_path, git_environ):
    """M1.4's `_close_parents`: a parent whose descendants are all optional is ticked in a commit of its own, with
    `L4-Task` and no `L4-TDD`, and `task.done{closed}`; it never had a red or a green step."""
    repo, base, head = _red_green(tmp_path, git_environ)
    repo.write({".kiro/specs/x/tasks.md": "- [x] 2. parent\n"})
    closed = repo.commit("close 2", task="2")
    repo.events.append(event("task.done", 5, task="2", base=head, parents=[], notes="", closed="no open required task"))
    history = check_tdd_history(repo.context(base, closed))
    assert not history.findings, history.findings
