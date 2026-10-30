"""L4-RACE-001 / L4-RACE-002 through `l4 run`: a person's answers pushed while the run works are merged at its next push
(`push.merged`); a push that cannot be recovered still ends the run on the forge, with its ledger in the lock ref's
pending ledger (SCN-IMP-22, SCN-RACE-07, SCN-RACE-08)."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.redact import Redactor
from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, QuestionStatus, raise_questions
from l4.state.fold import fold
from l4.state.ledger import TS_FORMAT, LedgerEvent
from l4.state.pending import live_run
from l4.vcs.secretscan import SecretHit

from ..implementer.conftest import green_step, red_step
from .conftest import BRANCH, UNIT, UNIT_DIR

QUESTIONS = f"{UNIT_DIR}/questions.md"
ASKED = "2026-10-05T10:00:00Z by implementer `codex`, run r-1, task 9.9"


def answered_questions(folder: Path) -> bytes:
    """A questions.md whose one question (it blocks a task nobody runs) a person answered."""
    folder.mkdir(parents=True, exist_ok=True)
    raise_questions(
        folder, "add-discount-codes", [NewQuestion("Which colour?", QuestionKind.PRODUCT, ("9.9",), "ctx", ASKED)],
        redactor=Redactor({}),
    )  # fmt: skip
    file = QuestionsFile.parse((folder / "questions.md").read_bytes()).set_status("Q-001", QuestionStatus.ANSWERED)
    body = file.get("Q-001").answer.body  # type: ignore[union-attr]
    return file.data[: body.end] + b"blue\n" + file.data[body.end :]


class Person:
    """A person's clone of the forge; `push(files)` commits to the unit branch and pushes, at the moment it is called
    (a step's `on_start` calls it, so it lands while the run works)."""

    def __init__(self, tdd, raw: Callable[..., str], where: Path) -> None:
        self.tdd, self.raw, self.where = tdd, raw, where
        self.sha = ""
        self.fired = 0

    def push(self, files: dict[str, bytes | str]) -> Callable[[object], None]:
        def fire(request: object) -> None:
            if self.fired:
                return
            self.fired += 1
            self.raw(self.where.parent, "clone", "-q", "--branch", BRANCH, str(self.tdd.origin), str(self.where))
            for rel, data in files.items():
                target = self.where / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data if isinstance(data, bytes) else data.encode())
            self.raw(self.where, "add", "-A")
            self.raw(self.where, "-c", "user.name=h", "-c", "user.email=h@x", "commit", "-q", "-m", "answers")
            self.raw(self.where, "push", "-q", "origin", BRANCH)
            self.sha = self.raw(self.where, "rev-parse", "HEAD").strip()

        return fire


@pytest.fixture
def person(tdd_repo, raw, tmp_path) -> Person:
    return Person(tdd_repo, raw, tmp_path / "person")


def test_answers_pushed_during_a_run_are_merged_and_the_run_ends_clean(run_l4, person, tmp_path):
    """SCN-IMP-22: the red checkpoint is pushed, a person answers while the green step runs, the next push merges."""
    answers = answered_questions(tmp_path / "q")
    run = run_l4([red_step(), green_step(on_start=person.push({QUESTIONS: answers}))])
    assert run.code == 0 and person.fired == 1
    [merged] = run.events("push.merged")
    assert merged["remote"] == person.sha and merged["commits"] == 1 and merged["paths"] == [QUESTIONS]
    assert run.raw(run.tdd.origin, "rev-list", "--merges", "--count", f"main..{BRANCH}").strip() == "1"
    parents = run.raw(run.tdd.origin, "rev-list", "--parents", "-n1", "--merges", f"main..{BRANCH}").split()
    assert person.sha in parents[2:]
    assert "merge 1 answer commit from the forge" in "\n".join(run.subjects())
    assert b"blue" in run.pushed(QUESTIONS).encode()  # the branch holds the answer next to the run's commits
    assert run.branch_ledger()[-1]["type"] == "run.finished"
    assert run.local_events("guard.secret") == []


def test_a_secret_found_by_the_scan_after_the_merge_stops_the_push(run_l4, person, tmp_path, monkeypatch):
    """SCN-RACE-07: the second scan (after the merge, before the push) is the one that fires; nothing is pushed after
    the merge, the run's commits are discarded and the unit halts as for a secret found before any merge."""
    import l4.orchestrator as orchestrator

    real = orchestrator.outgoing_secrets

    def scan(git, redactor, **kwargs):
        if git.run("rev-parse", "--verify", "--quiet", "HEAD^2", check=False).returncode == 0:  # HEAD is a merge
            return [SecretHit("src/pytdd/pricing.py", "anthropic-key")]
        return real(git, redactor, **kwargs)

    monkeypatch.setattr(orchestrator, "outgoing_secrets", scan)
    answers = answered_questions(tmp_path / "q")
    run = run_l4([red_step(), green_step(on_start=person.push({QUESTIONS: answers}))])
    assert run.code == 13
    [event] = run.local_events("guard.secret")
    assert (event["path"], event["kind"]) == ("src/pytdd/pricing.py", "anthropic-key")
    assert run.raw(run.tdd.origin, "rev-list", "--merges", "--count", f"main..{BRANCH}").strip() == "0"
    assert run.raw(run.tdd.origin, "merge-base", "--is-ancestor", person.sha, BRANCH) == ""  # the answers are there
    assert "feat" not in " ".join(run.subjects())  # the run's green commit never left


def other_files_of_a_person() -> dict[str, str]:
    return {"README.md": "a person edited this during the run\n"}


def test_a_failed_final_push_still_ends_the_run_in_the_lock_refs_pending_ledger(run_l4, person, capsys):
    """SCN-RACE-08: a person pushes a file that is no answer; the run's next push is refused and cannot be merged. The
    run exits 1, its commits stay on the runner, and its ledger, with `run.finished`, reaches the pending ledger."""
    run = run_l4([red_step(), green_step(on_start=person.push(other_files_of_a_person()))])
    err = capsys.readouterr().err
    assert run.code == 1 and "README.md" in err and "l4 restart" not in err and "Traceback" not in err
    files = run.pending_files()
    assert len(files) == 1  # this run's file
    [name] = files
    events = [json.loads(line) for line in files[name].splitlines()]
    assert events[0]["type"] == "run.started" and events[-1]["type"] == "run.finished"
    assert run.raw(run.tdd.origin, "rev-parse", BRANCH).strip() == person.sha  # nothing of the run's is on the branch
    folded = [
        LedgerEvent(
            datetime.strptime(e["ts"], TS_FORMAT).replace(tzinfo=UTC), e["run_id"], e["unit"], e["seq"], e["type"],
            {k: v for k, v in e.items() if k not in ("ts", "run_id", "unit", "seq", "type")},
        )
        for e in events
    ]  # fmt: skip
    assert live_run(folded) is None  # the next run's status shows no open run
    assert fold(folded, UNIT).phase is not None
