from dataclasses import replace

from l4.clarifier.notify import UNAVAILABLE_SENTENCE, build_sticky_section
from l4.clarifier.ports import QuestionView
from l4.specs.questions import QuestionKind, QuestionStatus


def view(qid: str, title: str, kind: QuestionKind | None = QuestionKind.PRODUCT) -> QuestionView:
    return QuestionView(qid, title, QuestionStatus.OPEN, kind, ("1.1",), "ctx", (), "", "", None)


WHERE = {"path": "openspec/changes/add-vat/questions.md", "branch": "l4/openspec/add-vat"}


def test_sticky_section_lists_open_questions_and_unavailable_sentence():
    section = build_sticky_section(
        [view("Q-001", "Which VAT rate?"), view("Q-002", "Which hash?", QuestionKind.TECHNICAL)],
        **WHERE, link="https://git.example/p/-/blob/l4/openspec/add-vat/openspec/changes/add-vat/questions.md",
        clarifier_unavailable=True,
    )  # fmt: skip
    assert "- Q-001 (product): Which VAT rate?" in section and "- Q-002 (technical): Which hash?" in section
    assert "[`openspec/changes/add-vat/questions.md`](https://git.example/p/-/blob/" in section
    assert "`l4/openspec/add-vat`" in section
    assert UNAVAILABLE_SENTENCE == "The clarifier was unavailable; no suggestions were written."
    assert UNAVAILABLE_SENTENCE in section


def test_invalid_output_and_draft_sentences_and_no_link():
    section = build_sticky_section([view("Q-001", "t")], **WHERE, link=None, invalid=["Q-001"], drafts=["Q-002"])
    assert "The clarifier produced invalid output for Q-001; no suggestion was written." in section
    assert "Q-002 has an answer but its Status is still `open`" in section
    assert "`openspec/changes/add-vat/questions.md` on branch `l4/openspec/add-vat`" in section
    assert section.count(UNAVAILABLE_SENTENCE) == 1  # L4-CLR-005: invalid twice also says "unavailable"


def test_titles_are_one_line_and_cannot_mention_or_markup():
    nasty = "Which?\n@all <!-- l4:sticky --> [x](http://evil) `tick`"
    section = build_sticky_section([view("Q-001", nasty, None)], **WHERE, link=None)
    line = next(line for line in section.splitlines() if line.startswith("- Q-001"))
    assert line.startswith("- Q-001 (unlabelled): Which?")
    assert "@all" not in section and "<!--" not in section and "](http" not in section


def test_an_unreadable_harness_answer_is_named_in_the_sticky_note():
    unread = replace(
        view("Q-007", "Task 3.1: the check could not decide", QuestionKind.HARNESS),
        status=QuestionStatus.ANSWERED, answer_text="looks fine",
    )  # fmt: skip
    section = build_sticky_section([unread], **WHERE, link=None)
    assert (
        "Q-007 has an answer that does not start with `accept` or `retry`: it was not read. Please answer again."
        in section
    )
