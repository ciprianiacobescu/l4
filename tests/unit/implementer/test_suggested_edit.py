"""M1.12 lines 27-29 (F2, L4-IMP-002, L4-QMD-005/006): a green step blocked on a frozen test that contradicts the spec
asks a question whose suggested answer is the exact edit, so one `accepted` unfreezes exactly that file."""

from l4.agents.fake import Step
from l4.implementer.loop import run_task
from l4.implementer.prompt import load_template, render_prompt
from l4.implementer.unfreeze import unfrozen
from l4.specs.questions import QuestionsFile, QuestionStatus

from .conftest import red_step, result
from .test_prompt import ctx
from .test_unfreeze import MANIFEST, SCOPE, TEST, ask, recorded, sub, with_status

EDIT = "Edit `tests/test_discount.py`: change the key `sub_areas` to `subareas` in the body on line 6."
QUESTION = {
    "title": "tests/test_discount.py line 6 asserts sub_areas, the spec says subareas",
    "context": "The frozen test `tests/test_discount.py:6` reads body['sub_areas']; the spec names `subareas`.",
    "kind": "technical",
    "options": [EDIT, "Keep the test and rename the key in the code (contradicts the spec)"],
}


def blocked_green() -> Step:
    return Step(structured=result("green", status="blocked", questions=[QUESTION]))


def test_a_blocked_green_raises_a_technical_question_carrying_the_suggested_edit(make_bench):
    from l4.specs.base import Task

    bench = make_bench([red_step(), blocked_green()])
    out = run_task(bench.wb, Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3))
    assert out.status == "blocked"
    file = QuestionsFile.load(bench.wb.ref.path / "questions.md")
    [question] = file.questions
    assert question.kind.value == "technical" and question.status is QuestionStatus.OPEN
    assert question.suggestion_text.startswith("Edit `tests/test_discount.py`: ")
    assert "tests/test_discount.py" in question.title and "sub_areas" in question.title


def test_an_edit_option_only_becomes_a_suggestion_for_a_technical_question(make_bench):
    from l4.specs.base import Task

    product = {**QUESTION, "kind": "product"}
    bench = make_bench([red_step(), Step(structured=result("green", status="blocked", questions=[product]))])
    run_task(bench.wb, Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3))
    [question] = QuestionsFile.load(bench.wb.ref.path / "questions.md").questions
    assert question.suggestion_text == ""


def test_one_accepted_unfreezes_exactly_the_named_file_and_nothing_else(tmp_path):
    """Pin of M1.10 C2 for the MF-7 shape (passes at once)."""
    suggestion = f"Edit `{TEST}`: change the key `sub_areas` to `subareas` on line 8."
    file = with_status(ask(tmp_path), QuestionStatus.ACCEPTED, suggestion=suggestion)
    got = unfrozen(file.questions, recorded(file), SCOPE, MANIFEST)
    assert got.paths == (TEST,) and got.question == "Q-001"
    assert "tests/test_other.py" not in got.paths  # a second test file the answer does not name stays frozen
    answered = with_status(
        ask(sub(tmp_path, "b")), QuestionStatus.ANSWERED, suggestion="", answer=f"Yes, edit {TEST} as suggested."
    )
    assert unfrozen(answered.questions, recorded(answered), SCOPE, MANIFEST).paths == (TEST,)
    elsewhere = with_status(
        ask(sub(tmp_path, "c")), QuestionStatus.ACCEPTED, suggestion="Edit `tests/test_other.py`: change line 1."
    )
    assert (
        unfrozen(elsewhere.questions, recorded(elsewhere), SCOPE, MANIFEST).paths == ()
    )  # the question names TEST only


def test_green_md_asks_for_the_test_the_line_the_contradiction_and_the_exact_edit():
    template = load_template("green")
    assert template.version == 5
    for needle in ("Edit `<path>`: <the exact change>", "the test file and the line", "the contradiction"):
        assert needle in template.body, needle
    prompt = render_prompt("green", ctx())
    assert "Edit `<path>`: <the exact change>" in prompt.text and prompt.template_version == "contract@11+green@5"
