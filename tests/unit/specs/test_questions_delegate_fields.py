"""delegate-answers 4.1: `Answered by:` and `Escalated by:` are fields of a question (L4-QMD-001, L4-QMD-003)."""

import pytest

from l4.redact import Redactor
from l4.specs.questions import QuestionsFile, QuestionStatus
from l4.specs.questions_cli import check_text, edit_answer, round_trip

from .questions_world import questions_md

ANSWERED = "the delegate (claude-opus-5-5 via claude-code)"
ESCALATED = "the delegate (gpt-6.1-sol via codex): the design does not settle it"


def parsed(*specs: dict, eol: str = "\n", bom: bool = False) -> QuestionsFile:
    text = questions_md("a", *specs, eol=eol)
    return QuestionsFile.parse(("﻿" + text).encode() if bom else text.encode())


def test_the_two_lines_are_fields():
    text = questions_md("a", {"title": "Which?"}).replace(
        "- **Status:** open\n",
        f"- **Status:** open\n- **Answered by:** {ANSWERED}\n- **Escalated by:** {ESCALATED}\n",
    )
    question = QuestionsFile.parse(text).get("Q-001")
    assert question is not None
    assert question.answered_by == ANSWERED and question.escalated_by == ESCALATED
    plain = QuestionsFile.parse(questions_md("a", {"title": "Which?"})).get("Q-001")
    assert plain is not None and plain.answered_by == "" and plain.escalated_by == ""


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
@pytest.mark.parametrize("bom", [False, True])
def test_set_field_inserts_after_status(eol, bom):
    file = parsed({"title": "Which?"}, {"title": "Other?", "tasks": ("1.2",)}, eol=eol, bom=bom)
    out = file.set_field("Q-001", "Answered by", ANSWERED)
    line = f"- **Answered by:** {ANSWERED}".encode()
    assert out.get("Q-001").answered_by == ANSWERED
    assert out.get("Q-002").answered_by == ""
    status_line = b"- **Status:** open" + eol.encode()
    assert out.data.count(status_line + line + eol.encode()) == 2 - 1  # only Q-001 has it, right after its Status
    assert out.data.replace(line + eol.encode(), b"", 1) == file.data  # nothing else differs
    assert out.data.startswith(b"\xef\xbb\xbf") is bom
    assert out.data.count(b"\r\n") == (out.data.count(b"\n") if eol == "\r\n" else 0)
    # replacing keeps one line only
    again = out.set_field("Q-001", "Answered by", "the delegate (x via y)")
    assert again.data.count(b"**Answered by:**") == 1 and again.get("Q-001").answered_by == "the delegate (x via y)"
    assert again.data.replace(b"(x via y)", b"(claude-opus-5-5 via claude-code)") == out.data
    # an edit plus the line passes the round trip
    edited = edit_answer(file, "Q-001", "Use bcrypt.").set_field("Q-001", "Answered by", ANSWERED)
    assert round_trip(file, edited, "Q-001", QuestionStatus.ANSWERED, "Use bcrypt.") is None


def test_set_field_escalated_and_one_line():
    file = parsed({"title": "Which?"})
    out = file.set_field("Q-001", "Escalated by", "the delegate (m via c): a\nb")
    assert out.get("Q-001").escalated_by == "the delegate (m via c): a b"
    with pytest.raises(Exception, match="Answered by|Escalated by|field"):
        file.set_field("Q-001", "Kind", "x")


def test_an_answer_with_the_line_is_structure():  # SCN-DLG-39
    for name in ("Answered by", "Escalated by"):
        found = check_text(f"- **{name}:** the delegate (x via y)", Redactor({}))
        assert found is not None
        assert found.message.startswith("line 1 would be read as structure of the file")
