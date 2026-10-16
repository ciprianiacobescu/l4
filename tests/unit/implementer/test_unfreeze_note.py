"""M1.13 lines 21-23 (W-C3, SPEC L4-QMD-005/006, L4-IMP-002): the question of a blocked green step tells the human how
a frozen test is unfrozen. Damage line: the note must never widen what an `accepted` suggestion unfreezes, so it names
only the frozen files the agent's own question already names."""

from l4.agents.fake import Step
from l4.implementer.loop import run_task
from l4.implementer.unfreeze import unfreeze_note, unfrozen
from l4.specs.base import Task
from l4.specs.questions import QuestionsFile, QuestionStatus

from .conftest import red_step, result
from .test_suggested_edit import EDIT, QUESTION
from .test_unfreeze import MANIFEST, SCOPE, TEST, ask, recorded, with_status

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
FROZEN = ["tests/test_discount.py", "tests/test_other.py", "tests/test_third.py"]


def raised(make_bench, question: dict):
    blocked = Step(structured=result("green", status="blocked", questions=[question]))
    bench = make_bench([red_step(), blocked])
    assert run_task(bench.wb, TASK).status == "blocked"
    [asked] = QuestionsFile.load(bench.wb.ref.path / "questions.md").questions
    return asked


def test_the_note_names_the_frozen_files_the_question_names_and_the_rule():
    text = f"line 6 of tests/test_discount.py is wrong. {EDIT}"
    note = unfreeze_note(text, FROZEN, suggested=True)
    assert "`tests/test_discount.py`" in note and "test_other" not in note and "test_third" not in note
    assert "Status" in note and "`accepted`" in note and "option 1" in note
    assert "names its path" in note
    assert "override" in note and "unfreezes nothing" in note


def test_without_an_edit_option_the_note_does_not_offer_accepted():
    note = unfreeze_note("tests/test_discount.py line 6 is wrong", FROZEN, suggested=False)
    assert "`tests/test_discount.py`" in note and "`accepted`" not in note and "names its path" in note


def test_a_question_that_names_no_frozen_file_gets_the_general_sentence_without_any_path():
    note = unfreeze_note("the spec and the design disagree about rounding", FROZEN, suggested=False)
    assert "names no frozen test" in note and "cannot unfreeze anything" in note
    assert not any(path in note for path in FROZEN)


def test_at_most_three_files_are_named():
    many = [f"tests/test_{n}.py" for n in "abcde"]
    note = unfreeze_note(" ".join(many), many, suggested=False)
    assert note.count("`tests/test_") == 3


def test_a_support_file_the_option_names_gets_the_accept_note_and_the_command():
    """SCN-IMP-170: the live defect offered `accepted` for `conftest.py` while the code refused it."""
    text = "the fixture is in conftest.py. Edit `conftest.py`: add the line"
    note = unfreeze_note(text, ["conftest.py", *FROZEN], suggested=True, unit="my-unit")
    assert "`conftest.py`" in note and "`accepted`" in note and "option 1" in note
    assert "l4 questions accept Q-NNN --unit my-unit" in note
    assert "ignore file" in note and "never" in note


def test_the_command_has_a_placeholder_without_a_unit_and_is_left_out_without_the_hint():
    text = "Edit `conftest.py`: add the line"
    assert "--unit <unit>" in unfreeze_note(text, ["conftest.py"], suggested=True)
    assert "l4 questions accept" not in unfreeze_note(text, ["conftest.py"], suggested=True, qid_hint=False)


def test_a_question_that_names_an_ignore_file_never_offers_to_unfreeze_it():
    text = "Edit `.gitignore`: add the line"
    note = unfreeze_note(text, FROZEN, ignore=[".gitignore"], suggested=True, unit="u")
    assert "`.gitignore`" in note and "never" in note
    assert "`accepted`" not in note and "option 1" not in note and "l4 questions accept" not in note


def test_an_ignore_file_beside_a_support_file_is_listed_apart_and_not_offered():
    text = "Edit `conftest.py`: add the line; also .gitignore"
    note = unfreeze_note(text, ["conftest.py"], ignore=[".gitignore"], suggested=True, unit="u")
    head, _, tail = note.partition("never")
    assert "`conftest.py`" in head and "`.gitignore`" in note and "`accepted`" in note


def test_a_question_that_names_nothing_still_says_nothing_unfreezes():
    note = unfreeze_note("rounding is unclear", FROZEN, ignore=[".gitignore"], suggested=False)
    assert "names no frozen" in note and "cannot unfreeze anything" in note and "l4 questions accept" not in note


def test_a_path_that_only_contains_a_frozen_one_is_not_named():
    note = unfreeze_note("see tests/test_discount.py.bak and tests/sub/tests/test_discount.py", FROZEN, suggested=False)
    assert "names no frozen test" in note


def test_the_question_of_a_blocked_green_carries_the_note_after_the_agents_context(make_bench):
    asked = raised(make_bench, QUESTION)
    context = asked.context_text
    assert context.startswith("The frozen test `tests/test_discount.py:6` reads body['sub_areas']")
    assert "Harness note:" in context and context.index("Harness note:") > context.index("subareas")
    assert "`accepted`" in context and "tests/test_other.py" not in context


def test_a_blocked_red_gets_no_note(make_bench):
    from .conftest import blocked_step

    bench = make_bench([blocked_step()])
    assert run_task(bench.wb, TASK).status == "blocked"
    [asked] = QuestionsFile.load(bench.wb.ref.path / "questions.md").questions
    assert "Harness note" not in asked.context_text


def test_a_green_question_that_is_not_technical_gets_no_note(make_bench):
    asked = raised(make_bench, {**QUESTION, "kind": "product"})
    assert "Harness note" not in asked.context_text


def test_the_note_does_not_change_what_an_accepted_suggestion_unfreezes(tmp_path):
    """Pin of M1.10 C2 (passes at once): the files `unfrozen` reads are the agent's, the note adds none."""
    suggestion = f"Edit `{TEST}`: change the key on line 8."
    file = with_status(ask(tmp_path), QuestionStatus.ACCEPTED, suggestion=suggestion)
    assert unfrozen(file.questions, recorded(file), SCOPE, MANIFEST).paths == (TEST,)


def test_the_spec_describes_the_note():
    from pathlib import Path

    spec = (Path(__file__).resolve().parents[3] / "docs" / "SPEC.md").read_text(encoding="utf-8")
    assert "`Harness note: ...`" in spec and "never names a file the agent did not" in spec
