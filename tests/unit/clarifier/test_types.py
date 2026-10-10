from pathlib import Path

import pytest

from l4.clarifier.answer import Citation
from l4.clarifier.ports import ClarifyOutcome, SpecQuestionsPort
from l4.redact import Redactor
from l4.specs.questions import (
    NewQuestion,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    answer_sha256,
    effective_answer,
    raise_questions,
)

REDACTOR = Redactor({})


def test_clarify_outcome_phase_and_exit_code_fields():
    assert ClarifyOutcome("implementing", 0).sticky_section is None
    held = ClarifyOutcome("awaiting_human", 11, clarifier_available=False, sticky_section="- Q-001")
    assert (held.exit_code, held.clarifier_available, held.results) == (11, False, {})
    for phase, code in (("implementing", 11), ("awaiting_human", 0)):
        with pytest.raises(ValueError):
            ClarifyOutcome(phase, code)  # type: ignore[arg-type]


def port(tmp_path: Path) -> SpecQuestionsPort:
    raise_questions(
        tmp_path, "add-x",
        [
            NewQuestion("Which hash?", QuestionKind.TECHNICAL, ("1.1",), "Passwords need a hash.\n## not a heading",
                        "2026-10-04 by implementer", options=("bcrypt", "argon2id")),
            NewQuestion("Which VAT rate?", QuestionKind.PRODUCT, ("1.2",), "ctx", "2026-10-04 by implementer"),
        ],
        redactor=REDACTOR,
    )  # fmt: skip
    path = tmp_path / "questions.md"
    return SpecQuestionsPort(path, QuestionsFile.parse(path.read_bytes()), redactor=REDACTOR)


def test_view_carries_context_options_and_kind(tmp_path: Path):
    first, second = port(tmp_path).load()
    assert (first.id, first.title, first.kind) == ("Q-001", "Which hash?", QuestionKind.TECHNICAL)
    assert first.blocking == ("1.1",)
    assert first.context == "Passwords need a hash.\n## not a heading"  # the neutralising backslash is not shown
    assert first.options == ("bcrypt", "argon2id") and second.options == ()
    assert (first.status, first.by, first.answer_text) == (QuestionStatus.OPEN, None, "")


def test_answer_and_suggestion_are_the_only_things_written(tmp_path: Path):
    p = port(tmp_path)
    before = (tmp_path / "questions.md").read_bytes()
    citations = [Citation(ref="design.md#L3", quote="hash with\n  bcrypt", claim="c")]
    p.set_clarifier_answer("Q-001", "Use bcrypt.", citations)
    p.set_clarifier_suggestion("Q-002", "Ask the owner.", "_confidence: low · kind: product_")
    saved = QuestionsFile.parse((tmp_path / "questions.md").read_bytes())  # saved at once, not at the end
    one, two = saved.get("Q-001"), saved.get("Q-002")
    assert one.status is QuestionStatus.ANSWERED_BY_CLARIFIER and two.status is QuestionStatus.OPEN
    assert effective_answer(one) == 'Use bcrypt.\n\nCitations:\n- `design.md#L3`: "hash with bcrypt" (shows: c)'
    assert two.suggestion_text == "_confidence: low · kind: product_\n\nAsk the owner."
    assert effective_answer(two) is None
    assert saved.data.count(b"### Clarifier suggestion") == 2
    assert b"| Q-001 | answered-by-clarifier |" in saved.data and b"| Q-002 | open |" in saved.data
    head = b"<!-- l4:index:start -->"
    assert before.split(head)[0] == saved.data.split(head)[0]  # the header above the index is untouched
    assert one.context_text == QuestionsFile.parse(before).get("Q-001").context_text
    view = p.load()[0]
    assert view.by == "clarifier" and view.answer_text == effective_answer(one)
    assert answer_sha256(one) is not None and p.file.data == saved.data


def test_an_answer_with_structure_in_it_round_trips(tmp_path: Path):
    p = port(tmp_path)
    text = "Use this:\n```py\n## x\n```\n<!-- note -->"
    p.set_clarifier_answer("Q-001", text, [])
    assert effective_answer(QuestionsFile.parse((tmp_path / "questions.md").read_bytes()).get("Q-001")) == text
