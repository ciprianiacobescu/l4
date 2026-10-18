"""L4-QMD-009: a verdict answer is recorded with the real actor, never as a person's by default of the code."""

from pathlib import Path

from l4.clarifier.actor import Actor, answer_actor
from l4.redact import Redactor
from l4.specs.questions import Question, QuestionsFile, QuestionStatus
from l4.state.ledger import LedgerEvent
from l4.vcs.git import Git
from l4.verifier.verdicts import consume_verdicts, raise_verdict_questions

from ..clarifier.answer_world import sh
from ._integrity_helpers import STAMP, UNIT

HOLD = "the diff is longer than 120000 characters: the judge saw only the start"


class Sink:
    def __init__(self) -> None:
        self.events: list[LedgerEvent] = []

    def append(self, event_type: str, /, **data) -> None:
        self.events.append(LedgerEvent(STAMP, "r-1", UNIT, len(self.events) + 1, event_type, data))


def world(repo: Path, sink: Sink) -> QuestionsFile:
    sh(repo, "init", "-q", "-b", "unit")
    raise_verdict_questions(
        repo, "u", outcomes=[], criteria=[], trace=[], findings=[], existing=None, consumed=(), ledger=sink,
        round_no=1, redactor=Redactor({}), holds=[HOLD],
    )  # fmt: skip
    path = repo / "questions.md"
    file = QuestionsFile.load(path)
    assert file is not None
    file = file.set_answer("Q-001", "accept the test covers it").set_status("Q-001", QuestionStatus.ANSWERED)
    file.save(path)
    return file


def by_commit(repo: Path, marker: str) -> None:
    sh(repo, "add", "questions.md")
    who = "person" if marker == "person" else f"agent: {marker}"
    sh(repo, "commit", "-q", "-m", f"answer Q-001 (u): hold\n\nStatus: answered\nBy: t ({who})\nVia: l4 questions\n")


def verdicts(sink: Sink) -> list[dict]:
    return [dict(e.data) for e in sink.events if e.type == "human.verdict"]


def test_consume_verdicts_records_the_agent(tmp_path: Path):  # SCN-DLG-40
    sink = Sink()
    file = world(tmp_path, sink)
    by_commit(tmp_path, "CLAUDECODE")

    def actor_of(question: Question) -> Actor:
        return answer_actor(Git(tmp_path), tmp_path, question, sink.events)

    assert consume_verdicts(file, sink.events, sink, [], actor_of=actor_of) == ["Q-001"]
    (recorded,) = verdicts(sink)
    assert recorded["decision"] == "accept" and recorded["by"] == "agent" and recorded["marker"] == "CLAUDECODE"


def test_consume_verdicts_records_a_person_through_the_commit(tmp_path: Path):
    sink = Sink()
    file = world(tmp_path, sink)
    by_commit(tmp_path, "person")
    consume_verdicts(
        file, sink.events, sink, [], actor_of=lambda q: answer_actor(Git(tmp_path), tmp_path, q, sink.events)
    )
    (recorded,) = verdicts(sink)
    assert recorded["by"] == "human" and "marker" not in recorded


def test_consume_verdicts_records_the_delegate(tmp_path: Path):
    sink = Sink()
    file = world(tmp_path, sink)
    consume_verdicts(file, sink.events, sink, [], actor_of=lambda q: Actor("delegate", profile="p", model="gpt-6.1"))
    (recorded,) = verdicts(sink)
    assert (recorded["by"], recorded["profile"], recorded["model"]) == ("delegate", "p", "gpt-6.1")
    assert "marker" not in recorded


def test_a_verdict_without_by_folds_as_human(tmp_path: Path):
    """Old ledgers (and old callers, which pass no `actor_of`) hold `by: human` or no `by` at all."""
    from l4.verifier.verdicts import effective_verdicts

    sink = Sink()
    file = world(tmp_path, sink)
    consume_verdicts(file, sink.events, sink, [])
    (recorded,) = verdicts(sink)
    assert recorded["by"] == "human"
    old = LedgerEvent(
        STAMP, "r-1", UNIT, 1, "human.verdict",
        {"question": "Q-001", "target": "H-1", "decision": "accept", "reason": "", "text_sha256": "x"},
    )  # fmt: skip
    (verdict,) = effective_verdicts([old], {"H-1": "x"}).values()
    assert verdict.by == "human"
