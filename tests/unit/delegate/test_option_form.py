"""unfreeze-option-form 2.3 (L4-DLG-014, L4-QMD-008; SCN-DLG-122): the delegate's `accept` of an open technical
question with no suggestion block takes option 1, under the rules of any accepted suggestion."""

import hashlib
import tempfile
from pathlib import Path

import pytest

from l4.agents.fake import Step
from l4.delegate import run as pass_module
from l4.delegate.prompt import PROMPT_VERSION, SYSTEM
from l4.delegate.reply import Discarded, Kept, check_reply
from l4.redact import Redactor
from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, QuestionStatus, raise_questions

from ..implementer.conftest import result
from .conftest import UNIT_DIR, escalation, reply
from .test_reply import FROZEN, HEAD, NAMES_STORE, REDACTOR, TEST_IDS, cite

QUESTIONS = f"{UNIT_DIR}/questions.md"
STORE_OPTION = "Edit tests/test_store.py: add the case."
STORE_TAKEN = "Edit `tests/test_store.py`: add the case."
CONFTEST_OPTION = "Edit tests/conftest.py: add the fixture."
NAMES_CONFTEST = "The red step froze tests/conftest.py and the green step needs a fixture there."
ACCEPT = {
    "question": "Q-001", "decision": "accept", "text": "", "reason": "design D3 settles it", "checked": [cite()],
}  # fmt: skip


def raised(
    tmp_path: Path, options: tuple[str, ...], context: str, *, suggestion: str = "", kind=QuestionKind.TECHNICAL
):
    folder = Path(tempfile.mkdtemp(dir=tmp_path))
    ids = raise_questions(
        folder, "add-login", [NewQuestion("Which case?", kind, ("3.1",), context, "now", options)], redactor=REDACTOR
    )
    assert ids == ["Q-001"]
    file = QuestionsFile.load(folder / "questions.md")
    if suggestion:
        file = file.set_suggestion("Q-001", suggestion, redactor=REDACTOR)
    return file, file.get("Q-001")


def check(tmp_path: Path, body: dict, options: tuple[str, ...], context: str, *, suggestion: str = "", **over):
    file, question = raised(tmp_path, options, context, suggestion=suggestion)
    return check_reply(
        body, question, file, head=HEAD, test_ids=TEST_IDS, frozen=over.pop("frozen", FROZEN), unit="add-login",
        branch="unit/add-login", redactor=REDACTOR, **over,
    )  # fmt: skip


def test_scn_dlg_122_an_accept_of_a_bare_option_one_is_kept_and_unfreezes_the_test_file(tmp_path):
    got = check(tmp_path, ACCEPT, (STORE_OPTION, "Leave it"), NAMES_STORE, unfreeze=True)
    assert isinstance(got, Kept) and got.form == "accept" and got.text is None
    assert got.effective == STORE_TAKEN
    assert [(e.path, e.task, e.unfreezes) for e in got.unfreezes] == [("tests/test_store.py", "3.1", True)]


def test_the_unfreeze_rules_hold_for_an_option_one_accept(tmp_path):
    support = check(
        tmp_path, ACCEPT, (CONFTEST_OPTION, "Leave it"), NAMES_CONFTEST, unfreeze=True
    )  # the delegate opens test files only
    assert isinstance(support, Discarded) and support.status == "escalated" and "test-support file" in support.reason
    fix = check(tmp_path, ACCEPT, (STORE_OPTION, "Leave it"), NAMES_STORE, unfreeze=True, fix_task=True)
    assert isinstance(fix, Discarded) and fix.status == "escalated" and "fix task" in fix.reason
    off = check(tmp_path, ACCEPT, (STORE_OPTION, "Leave it"), NAMES_STORE)
    assert isinstance(off, Discarded) and off.status == "escalated"
    assert "delegate.unfreeze is false" in off.reason
    # the question names the file because its option 1 does: a context that does not is no obstacle
    unnamed = check(tmp_path, ACCEPT, (STORE_OPTION, "Leave it"), "The fixture is missing.", unfreeze=True)
    assert isinstance(unnamed, Kept) and [e.path for e in unnamed.unfreezes] == ["tests/test_store.py"]
    answer = {**ACCEPT, "decision": "answer", "text": "Add the case to tests/test_store.py."}
    free = check(tmp_path, answer, (STORE_OPTION, "Leave it"), NAMES_STORE, unfreeze=True)
    assert isinstance(free, Discarded) and "only the clarifier suggestion may unfreeze it" in free.reason


def test_a_written_suggestion_wins_over_option_one(tmp_path):
    got = check(tmp_path, ACCEPT, (STORE_OPTION, "Leave it"), NAMES_STORE, suggestion="Take option 2", unfreeze=True)
    assert isinstance(got, Kept) and got.effective == "Take option 2" and got.unfreezes == ()


@pytest.mark.parametrize("options", [("Keep the test", "Edit `tests/test_store.py`: x"), ()])
def test_an_option_one_that_is_no_edit_gives_accept_nothing_to_take(tmp_path, options):
    got = check(tmp_path, ACCEPT, options, NAMES_STORE, unfreeze=True)
    assert isinstance(got, Discarded) and "accept needs a clarifier suggestion" in got.reason


def test_a_product_question_has_no_option_one_suggestion(tmp_path):
    file, question = raised(tmp_path, (STORE_OPTION,), NAMES_STORE, kind=QuestionKind.PRODUCT)
    got = check_reply(
        ACCEPT, question, file, head=HEAD, test_ids=TEST_IDS, frozen=FROZEN, unit="add-login",
        branch="unit/add-login", redactor=Redactor({}), unfreeze=True,
    )  # fmt: skip
    assert isinstance(got, Discarded) and "accept needs a clarifier suggestion" in got.reason


# -- the pass: the block is written by the same edit, the prompt shows the text --------------------------------------


def blocked_with(*options: str) -> Step:
    question = {"title": "Which error 1?", "context": "what does an unknown code raise", "kind": "technical",
                "options": list(options)}  # fmt: skip
    return Step(structured=result("red", status="blocked", questions=[question]))


@pytest.fixture
def no_suggestion_written(monkeypatch):
    """A question raised before 0.4.39: the implementer wrote no suggestion block for it."""
    monkeypatch.setattr("l4.implementer.loop._suggest_edits", lambda *args, **kwargs: None)


def test_the_pass_writes_the_block_and_records_the_digest_of_the_read_back_question(
    delegate_run, no_suggestion_written, monkeypatch
):  # SCN-DLG-122
    shown: list[str] = []
    real = pass_module.build_prompt

    def spy(question, material, **kwargs):
        built = real(question, material, **kwargs)
        shown.append(built.text)
        return built

    monkeypatch.setattr(pass_module, "build_prompt", spy)
    run = delegate_run(
        [blocked_with("Edit src/pkg/codes.py: raise ValueError for an unknown code.", "Leave it"),
         reply(decision="accept", text="")]
    )  # fmt: skip
    taken = "Edit `src/pkg/codes.py`: raise ValueError for an unknown code."
    assert shown and f"Clarifier suggestion (`accept` takes it as it is):\n{taken}" in shown[0]
    file = QuestionsFile.parse(run.pushed(QUESTIONS).encode())
    q = file.get("Q-001")
    assert q.status is QuestionStatus.ACCEPTED and q.suggestion_text == taken
    (answered,) = run.events("question.answered")
    assert answered["by"] == "delegate"
    assert answered["answer_sha256"] == hashlib.sha256(taken.encode("utf-8")).hexdigest()
    (done,) = [e for e in run.events("delegate.result") if e.get("status") == "answered"]
    assert done["decision"] == "accept" and done["answer_sha256"] == answered["answer_sha256"]


def test_an_escalation_writes_no_block(delegate_run, no_suggestion_written):
    run = delegate_run([blocked_with("Edit src/pkg/codes.py: raise ValueError.", "Leave it"), escalation()])
    file = QuestionsFile.parse(run.pushed(QUESTIONS).encode())
    assert file.get("Q-001").status is QuestionStatus.OPEN and file.get("Q-001").suggestion is None
    assert b"### Clarifier suggestion" not in run.pushed(QUESTIONS).encode()


# -- the prompt's rules -------------------------------------------------------------------------------------------


def test_the_rules_say_a_frozen_test_file_opens_only_through_accept():
    flat = " ".join(SYSTEM.split())
    assert (
        "A frozen test file is opened only by `accept` of the clarifier suggestion: an `answer` whose text names a "
        "frozen path is refused, whatever it says." in flat
    )
    assert PROMPT_VERSION >= 6  # the rule came with delegate@6
