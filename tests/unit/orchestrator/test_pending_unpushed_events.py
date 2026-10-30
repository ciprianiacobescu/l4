"""L4-RACE-002: the pending ledger of a run whose final push failed holds events that name work which never reached the
branch (a delegate's accept of a text the branch does not have). The fold and the readers of those events must not
assume the named work exists: they match digests against the file as it is now, never a commit."""

from datetime import UTC, datetime, timedelta

import pytest

from l4.clarifier.actor import answer_actor
from l4.delegate.limits import delegate_cost
from l4.implementer.guards import FreezeManifest, FrozenFile
from l4.implementer.unfreeze import unfrozen
from l4.redact import Redactor
from l4.specs.questions import (
    NewQuestion,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    answer_sha256,
    raise_questions,
)
from l4.state.fold import fold
from l4.state.ledger import LedgerEvent, LedgerRead
from l4.state.pending import live_run, merge_ledgers

UNIT = "openspec:add-x"
RUN = "r-20261030T0100Z-0001"
TEST = "tests/test_notices.py"
MANIFEST = FreezeManifest("r" * 40, {TEST: FrozenFile("a" * 64, "test")}, ())
SCOPE = frozenset({"1.1", "1"})
GONE = "f" * 40  # a commit the run made and never pushed


def questions(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    asked = NewQuestion(
        "The test freezes a wrong constant", QuestionKind.TECHNICAL, ("1.1",), f"`{TEST}` is bad.", "now"
    )
    raise_questions(
        tmp_path, "add-x",
        [asked],
        redactor=Redactor({}),
    )  # fmt: skip
    return QuestionsFile.load(tmp_path / "questions.md")


def delegate_text(tmp_path):
    """Q-001 as the run's delegate accepted it."""
    file = questions(tmp_path / "run")
    return file.set_suggestion(
        "Q-001", f"Change `{TEST}:8` to expect the 30-day wording.", redactor=Redactor({})
    ).set_status("Q-001", QuestionStatus.ACCEPTED)


def persons_text(tmp_path):
    """Q-001 as a person answered it on the forge, which the failed run never saw."""
    file = questions(tmp_path / "person")
    file = file.set_status("Q-001", QuestionStatus.ANSWERED)
    body = file.get("Q-001").answer.body  # type: ignore[union-attr]
    return QuestionsFile.parse(
        file.data[: body.end] + f"Edit `{TEST}` as you see fit.\n".encode() + file.data[body.end :]
    )


def events_of_the_failed_run(tmp_path) -> list[LedgerEvent]:
    start = datetime(2026, 10, 30, 1, 0, tzinfo=UTC)
    digest = answer_sha256(delegate_text(tmp_path).get("Q-001"))
    rows = [
        ("run.started", {}),
        ("task.red_ok", {"task": "1.1", "red_sha": GONE, "frozen": [TEST]}),
        ("task.done", {"task": "1.1", "commit": GONE}),
        ("question.raised", {"id": "Q-001", "kind": "technical", "task": "1.1"}),
        ("delegate.asked", {"question": "Q-001"}),
        ("budget.cost", {"role": "delegate", "usd": 0.5}),
        ("question.answered", {"id": "Q-001", "by": "delegate", "answer_sha256": digest, "model": "m", "profile": "p"}),
        ("delegate.result", {"id": "Q-001", "status": "answered", "answer_sha256": digest, "cost_usd": 0.5}),
        ("run.finished", {"exit_code": 1}),
    ]
    return [
        LedgerEvent(start + timedelta(seconds=i), RUN, UNIT, i + 1, kind, data) for i, (kind, data) in enumerate(rows)
    ]


def test_the_fold_and_the_cost_reader_read_the_events_without_the_commits(tmp_path):
    events = events_of_the_failed_run(tmp_path)
    state = fold(events, UNIT)
    assert state.cost_usd == 0.5 and "Q-001" in state.questions.answered and "1.1" in state.tasks.done
    assert delegate_cost(events) == 0.5
    assert live_run(events) is None  # `run.finished` is there: the run is over


def test_the_branch_copy_of_the_run_and_the_longer_pending_file_merge_to_one_run(tmp_path):
    events = events_of_the_failed_run(tmp_path)
    merged = merge_ledgers(LedgerRead(events[:3], []), LedgerRead(events, []))
    assert [(e.run_id, e.seq) for e in merged.events] == [(RUN, i) for i in range(1, 10)]
    assert live_run(merged.events) is None


def test_a_delegate_accept_of_a_text_the_branch_does_not_have_unfreezes_nothing(tmp_path):
    """The branch's Q-001 is a person's answer (another digest): the delegate's record does not carry it."""
    events = events_of_the_failed_run(tmp_path)
    person = persons_text(tmp_path)
    assert answer_sha256(person.get("Q-001")) != answer_sha256(delegate_text(tmp_path / "again").get("Q-001"))
    assert unfrozen(person.questions, events, SCOPE, MANIFEST, delegate_unfreeze=True).paths == ()


@pytest.mark.parametrize("branch_has", ["delegates", "persons"])
def test_the_actor_of_an_answer_is_found_by_its_digest_not_by_a_commit(tmp_path, git_for, branch_has):
    events = events_of_the_failed_run(tmp_path)
    file = delegate_text(tmp_path / "x") if branch_has == "delegates" else persons_text(tmp_path)
    folder = tmp_path / "unit"
    folder.mkdir()
    actor = answer_actor(git_for(folder), folder, file.get("Q-001"), events)
    # the ledger says the delegate accepted this text: believed only when the file still has exactly this text
    assert actor.by == ("delegate" if branch_has == "delegates" else "human")
