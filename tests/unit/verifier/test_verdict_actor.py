"""L4-QMD-009: a verdict answer is recorded with the real actor, never as a person's by default of the code."""

from pathlib import Path

import pytest

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
        repo, "u", outcomes=[], criteria=[], trace=[], findings=[], existing=None, consumed=(), raised=(), ledger=sink,
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


# ---- a skipped-test hold is a person's: a model-authored answer is not in force (L4-VER-094, SCN-VER-388) ------------

SKIPPED = (
    "skipped: existing tests in `tests/test_live.py` are skipped, and this unit did not add or change a skip that "
    "can affect them (2 tests)"
)
SKIPPED_VIEW = {"sha": "b" * 64, "paths": ["tests.test_live::test_a", "tests.test_live::test_b"]}


def _events(*answers: tuple[str, str, str]) -> list[LedgerEvent]:
    """(question, by, decision) -> the ledger a round reads: each question raised, then answered."""
    from l4.verifier.verdicts import hold_id

    out: list[LedgerEvent] = []
    for question, by, decision in answers:
        data = {"id": question, "kind": "verdict", "target": hold_id(SKIPPED), "text_sha256": SKIPPED_VIEW["sha"]}
        out.append(LedgerEvent(STAMP, "r-1", UNIT, len(out) + 1, "question.raised", data))
        out.append(
            LedgerEvent(
                STAMP,
                "r-1",
                UNIT,
                len(out) + 1,
                "human.verdict",
                {
                    "question": question,
                    "target": hold_id(SKIPPED),
                    "decision": decision,
                    "by": by,
                    "reason": "ran them",
                    "text_sha256": SKIPPED_VIEW["sha"],
                },
            )  # fmt: skip
        )
    return out


def _finalize(tmp_path: Path, monkeypatch, events: list[LedgerEvent]):
    from types import SimpleNamespace

    from l4.config.schema import L4Config
    from l4.verifier import ladder
    from l4.verifier.types import Verdict, VerifyResult

    monkeypatch.setattr(ladder, "_hold_unjudged", lambda vc, result: None)
    emitted: list[tuple[str, dict]] = []
    wb = SimpleNamespace(
        ref=SimpleNamespace(id=UNIT, path=tmp_path), cfg=L4Config.model_validate({}),
        emit=lambda kind, **data: emitted.append((kind, data)),
    )  # fmt: skip
    result = VerifyResult(UNIT, 2, Verdict.FAIL, "b", "h")
    result.holds = [SKIPPED]
    result.hold_views = {SKIPPED: dict(SKIPPED_VIEW)}
    ladder._finalize(SimpleNamespace(wb=wb, round=2), ladder._Run(result), [], events)
    return result, emitted


@pytest.mark.parametrize("by", ["agent", "delegate", "clarifier"])
def test_scn_ver_388_a_model_authored_answer_is_dropped_with_one_void(tmp_path, monkeypatch, by):
    from l4.verifier.types import Verdict

    result, emitted = _finalize(tmp_path, monkeypatch, _events(("Q-001", by, "accept")))
    assert result.holds == [SKIPPED] and result.human == [] and result.verdict is Verdict.NEEDS_HUMAN
    ((kind, data),) = emitted
    assert kind == "human.void" and data["question"] == "Q-001" and "person" in data["reason"]
    assert data["target"].startswith("H-")


def test_scn_ver_388_a_model_authored_reject_is_dropped_too(tmp_path, monkeypatch):
    from l4.verifier.types import Verdict

    result, emitted = _finalize(tmp_path, monkeypatch, _events(("Q-001", "agent", "reject")))
    assert result.findings == [] and result.verdict is Verdict.NEEDS_HUMAN and [k for k, _ in emitted] == ["human.void"]


def test_scn_ver_388_an_answer_by_a_person_is_applied(tmp_path, monkeypatch):
    from l4.verifier.types import Verdict

    result, emitted = _finalize(tmp_path, monkeypatch, _events(("Q-001", "human", "accept")))
    assert result.holds == [] and result.verdict is Verdict.PASS and emitted == []


def test_a_second_round_does_not_record_a_second_void_for_the_same_question(tmp_path, monkeypatch):
    events = _events(("Q-001", "agent", "reject"))
    _, first = _finalize(tmp_path, monkeypatch, events)
    voids = [LedgerEvent(STAMP, "r-1", UNIT, 99, "human.void", dict(data)) for kind, data in first]
    _, second = _finalize(tmp_path, monkeypatch, [*events, *voids])
    assert len(first) == 1 and second == []


def test_the_hold_is_asked_again_after_the_void(tmp_path, monkeypatch):
    """A model's answer consumed Q-001; with the hold unresolved, the next round raises it anew."""
    from l4.redact import Redactor
    from l4.verifier.verdicts import raise_verdict_questions

    sink = Sink()
    asked = {"holds": [SKIPPED], "hold_views": {SKIPPED: SKIPPED_VIEW}, "redactor": Redactor({}), "ledger": sink}
    kw = {"outcomes": [], "criteria": [], "trace": [], "findings": []}
    first = raise_verdict_questions(tmp_path, "u", existing=None, consumed=(), raised=(), round_no=1, **kw, **asked)
    assert first == ["Q-001"]
    file = QuestionsFile.load(tmp_path / "questions.md")
    again = raise_verdict_questions(
        tmp_path, "u", existing=file, consumed=["Q-001"], raised=["Q-001"], round_no=2, **kw, **asked
    )
    assert again == ["Q-002"]  # Q-001 is consumed: nothing waits on the hold, so it is asked again
    still = QuestionsFile.load(tmp_path / "questions.md")
    assert (
        raise_verdict_questions(
            tmp_path, "u", existing=still, consumed=["Q-001"], raised=["Q-001", "Q-002"], round_no=3, **kw, **asked
        )
        == []
    )
    result, _ = _finalize(tmp_path, monkeypatch, _events(("Q-001", "agent", "accept"), ("Q-002", "human", "accept")))
    assert result.holds == [] and result.verdict.value == "PASS"
