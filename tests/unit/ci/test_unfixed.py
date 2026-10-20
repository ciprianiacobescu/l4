"""A CI failure that no fix touched (ci-evidence D12; L4-OPS-023): the project files a branch changed since a head,
and the history of a red job across the unit's hand-offs. A real git repository, ledger events built here."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from l4.ci.unfixed import CiHistory, ci_history, project_changes
from l4.config.schema import L4Config
from l4.state.ledger import LedgerEvent
from l4.vcs.git import Git

UNIT_DIR = "openspec/changes/a"
CFG = L4Config()


class Repo:
    def __init__(self, path: Path, raw) -> None:
        self.path, self.raw = path, raw
        self.git = Git(path)

    def commit(self, files: dict[str, str], message: str = "c") -> str:
        for name, text in files.items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.raw(self.path, "add", "-A", "-f")
        self.raw(self.path, "commit", "-q", "-m", message)
        return self.head()

    def head(self) -> str:
        return self.raw(self.path, "rev-parse", "HEAD").strip()

    def merge_of_base(self, files: dict[str, str]) -> str:
        """A merge commit that brings a commit of the base (`files`) in, as `bring_in_base` does."""
        here = self.raw(self.path, "rev-parse", "--abbrev-ref", "HEAD").strip()
        self.raw(self.path, "checkout", "-q", "-b", "side", self.head())
        self.commit(files, "base moved")
        self.raw(self.path, "checkout", "-q", here)
        self.raw(self.path, "merge", "-q", "--no-ff", "-m", "merge the base", "side")
        return self.head()


@pytest.fixture
def repo(make_repo, raw) -> Repo:
    path = make_repo("work")
    r = Repo(path, raw)
    r.commit({"src/app/cli.py": "v1\n", f"{UNIT_DIR}/tasks.md": "- [ ] 1.1\n", "tests/test_cli.py": "t1\n"}, "unit")
    return r


_SEQ = [0]


def event(type_: str, /, **data) -> LedgerEvent:
    _SEQ[0] += 1
    return LedgerEvent(
        ts=datetime(2026, 10, 20, 10, 0, tzinfo=UTC) + timedelta(seconds=_SEQ[0]), run_id="r-20261020T1000Z-aaaa",
        unit="openspec:a", seq=_SEQ[0], type=type_, data=data,
    )  # fmt: skip


def edge(head: str, *jobs: str) -> LedgerEvent:
    entries = [
        {"name": j, "stage": "", "url": "", "tail": "FAILED t::x\n1 failed", "failed_step": "tests"} for j in jobs
    ]
    return event(
        "phase.changed", trigger="repository_ci_failed", head=head, pipeline=1, jobs=entries, preexisting=[],
        **{"from": "in_review", "to": "verifying"},
    )  # fmt: skip


JOB = "ci.yml / tests"


def test_project_changes_leave_out_spec_harness_and_merges(repo):
    h = repo.head()
    repo.commit({f"{UNIT_DIR}/tasks.md": "- [x] 1.1\n", "openspec/changes/a-fix-1/tasks.md": "x\n"}, "spec")
    repo.commit({f"{UNIT_DIR}/.l4/ledger/r.jsonl": "{}\n", ".l4-out/x": "y\n", f"{UNIT_DIR}/questions.md": "q\n"}, "h")
    repo.merge_of_base({"src/app/other.py": "base\n"})
    assert project_changes(repo.git, h, repo.head(), UNIT_DIR, CFG) == ()
    repo.commit({"src/app/cli.py": "v2\n"}, "fix")
    assert project_changes(repo.git, h, repo.head(), UNIT_DIR, CFG) == ("src/app/cli.py",)


def test_project_changes_is_none_when_the_since_commit_is_no_ancestor(repo):
    h = repo.head()
    repo.raw(repo.path, "checkout", "-q", "-b", "other", h)
    other = repo.commit({"src/app/x.py": "x\n"}, "other line")
    repo.raw(repo.path, "checkout", "-q", "main")
    repo.commit({"src/app/cli.py": "v2\n"}, "main line")
    assert project_changes(repo.git, other, repo.head(), UNIT_DIR, CFG) is None
    assert project_changes(repo.git, "f" * 40, repo.head(), UNIT_DIR, CFG) is None


def test_the_same_job_again_on_an_unchanged_head_is_unfixed(repo):
    """SCN-OPS-40, SCN-OPS-41: a fix that touched only its own `tasks.md`, then the job red again."""
    h1 = repo.head()
    repo.commit({"openspec/changes/a-fix-1/tasks.md": "- [x] 1.1\n", f"{UNIT_DIR}/.l4/ledger/r.jsonl": "{}\n"}, "fix")
    h2 = repo.head()
    events = [edge(h1, JOB), event("verify.verdict", round=1, verdict="FAIL"), edge(h2, JOB)]
    (history,) = ci_history(events, repo.git, UNIT_DIR, CFG).values()
    assert (history.job, history.head, history.again_head, history.again_changed) == (JOB, h2, h1, 0)
    assert history.unfixed is True
    # a retry between the two edges, and the same head again, change nothing
    retried = [edge(h1, JOB), event("unit.retried", reason="x"), edge(h2, JOB)]
    assert ci_history(retried, repo.git, UNIT_DIR, CFG)[JOB].unfixed is True
    assert ci_history([edge(h1, JOB), edge(h1, JOB)], repo.git, UNIT_DIR, CFG)[JOB].unfixed is True


def test_the_first_failure_has_no_history(repo):
    (history,) = ci_history([edge(repo.head(), JOB)], repo.git, UNIT_DIR, CFG).values()
    assert (history.again_head, history.again_changed, history.unfixed) == (None, None, False)


def test_again_with_changes(repo):
    """SCN-OPS-42: a project file changed, or a person's commit, between the two edges."""
    h1 = repo.head()
    repo.commit({"src/app/cli.py": "v2\n"}, "fix")
    h2 = repo.head()
    history = ci_history([edge(h1, JOB), edge(h2, JOB)], repo.git, UNIT_DIR, CFG)[JOB]
    assert (history.again_head, history.again_changed, history.unfixed) == (h1, 1, False)
    repo.commit({"tests/test_cli.py": "t2\n"}, "a person edits the test")
    h3 = repo.head()
    assert ci_history([edge(h2, JOB), edge(h3, JOB)], repo.git, UNIT_DIR, CFG)[JOB].again_changed == 1


def test_a_job_that_failed_before_only_in_another_job_is_not_again(repo):
    h1 = repo.head()
    h2 = repo.commit({"openspec/changes/a-fix-1/tasks.md": "x\n"}, "fix")
    history = ci_history([edge(h1, "ci.yml / lint"), edge(h2, JOB)], repo.git, UNIT_DIR, CFG)
    assert history[JOB].again_head is None and history[JOB].unfixed is False


def test_put_back_and_notes(repo):
    """SCN-OPS-40: the test and support files the fix steps put back between the edges, and the chore's notes."""
    from l4.verifier.types import finding_id

    h1 = repo.head()
    h2 = repo.commit({"openspec/changes/a-fix-1/tasks.md": "x\n"}, "fix")
    fid = finding_id(f"repository CI failed: {JOB}")
    events = [
        event("guard.test_tamper", path="tests/early.py", phase="single", action="restored"),
        edge(h1, JOB),
        event(
            "guard.test_tamper", path="tests/test_cli.py", phase="single", action="restored", rule="test path freeze"
        ),
        event("guard.violation", path="tests/conftest.py", phase="single", rule="test support file", action="restored"),
        event("guard.violation", path="tests/conftest.py", phase="single"),
        event("guard.test_tamper", path="tests/green.py", phase="green", action="restored"),
        event("task.tdd_exempt", task="1.1", sha="s", kind="harness", finding=fid, findings=[fid]),
        event("task.done", task="1.1", sha="s", notes="the gates do not show it: " + "x" * 400, tdd="exempt"),
        edge(h2, JOB),
    ]
    history = ci_history(events, repo.git, UNIT_DIR, CFG)[JOB]
    assert history.put_back == ("tests/conftest.py", "tests/test_cli.py")
    assert (
        history.notes is not None and history.notes.startswith("the gates do not show it") and len(history.notes) <= 300
    )
    assert history.failed_step == "tests" and "FAILED t::x" in history.failing


def test_a_base_merge_is_not_a_fix(repo):
    """SCN-OPS-44."""
    h1 = repo.head()
    h2 = repo.merge_of_base({"src/app/other.py": "base\n"})
    history = ci_history([edge(h1, JOB), edge(h2, JOB)], repo.git, UNIT_DIR, CFG)[JOB]
    assert (history.again_changed, history.unfixed) == (0, True)


def test_a_rewritten_history_is_not_judged(repo):
    """SCN-OPS-44: H1 is no ancestor of H2: no count, not unfixed."""
    h1 = repo.head()
    repo.raw(repo.path, "reset", "-q", "--hard", "HEAD~1")
    h2 = repo.commit({"src/app/cli.py": "other\n"}, "rewritten")
    history = ci_history([edge(h1, JOB), edge(h2, JOB)], repo.git, UNIT_DIR, CFG)[JOB]
    assert (history.again_head, history.again_changed, history.unfixed) == (h1, None, False)


def test_a_history_is_a_frozen_value():
    assert CiHistory("j", "h", None, None, False, (), None, None, "").job == "j"
