"""The reply checks that follow the rules of 0.4.21 (L4-DLG-023 to L4-DLG-025, L4-DLG-014; SCN-DLG-77 to 79, 81 to 84,
86 to 88, 106 to 110)."""

import tempfile
from pathlib import Path

from l4.delegate.reply import Discarded, Kept, check_reply, named_paths
from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, raise_questions
from l4.verifier.verdicts import WHEN_THEN

from .test_reply import FROZEN, HEAD, NAMES_STORE, REDACTOR, STORE_SUGGESTION, TEST_IDS, UNIT_REL, cite, reply

NO_CRITERION = (
    "The judge raised a major finding in round 1, and no deterministic check confirms it.\n\n"
    "Title: The empty cart returns 500\nDetail: nothing handles it."
)
WITH_CRITERION = NO_CRITERION.replace("round 1,", "round 1 (criterion C-2.1),")
GAP = " It reports behaviour that no scenario pins down."
TEST_LINES = [cite("tests/test_store.py:1", "def test_add(): ...")]


def ask(tmp_path, body, *, title, kind, context, tasks=(), suggestion="", **over):
    folder = Path(tempfile.mkdtemp(dir=tmp_path))
    new = NewQuestion(title, kind, tasks, context, "now", ("a", "b"))
    raise_questions(folder, "add-login", [new], redactor=REDACTOR)
    file = QuestionsFile.load(folder / "questions.md")
    if suggestion:
        file = file.set_suggestion("Q-001", suggestion, redactor=REDACTOR)
    return check_reply(
        body, file.get("Q-001"), file, head=over.pop("head", HEAD), test_ids=TEST_IDS, frozen=over.pop("frozen", {}),
        unit="add-login", branch="unit/add-login", redactor=REDACTOR, **over,
    )  # fmt: skip


def finding(tmp_path, body, context=NO_CRITERION, **over):
    return ask(tmp_path, body, title="Finding F-2: the empty cart", kind=QuestionKind.VERDICT, context=context, **over)


def criterion(tmp_path, body, **over):
    context = (
        "Criterion C-2.1 (totals) is uncovered after round 1.\n\nWhy: uncovered: the judge passed it, only the cap"
    )
    return ask(tmp_path, body, title="Criterion C-2.1: totals", kind=QuestionKind.VERDICT, context=context, **over)


def hold(tmp_path, body, kind="judge_view", **over):
    return ask(
        tmp_path, body, title="Hold H-12345678: the judge could not see the diff", kind=QuestionKind.VERDICT,
        context="The judge could not see all of the diff.", hold_kind=kind, **over,
    )  # fmt: skip


def chore(tmp_path, body, **over):
    context = "This is a fix task. It cannot unfreeze a test or test-support file."
    return ask(
        tmp_path, body, title="Which fixture?", kind=QuestionKind.TECHNICAL, context=context, tasks=("3.1",),
        chore=True, fix_task=True, **over,
    )  # fmt: skip


# -- L4-DLG-023: a reject sets the check as 0.4.21 reads it -----------------------------------------------------------


def test_a_reject_of_a_finding_with_no_criterion_needs_its_scenario(tmp_path):  # SCN-DLG-77
    got = finding(tmp_path, reply(decision="reject", text="the empty cart returns 500"))
    assert isinstance(got, Discarded) and got.status == "discarded" and got.decision == "reject"
    assert got.reason == "a reject of this finding needs a sentence WHEN ... THEN ...: it cites no criterion"
    ok = finding(tmp_path, reply(decision="reject", text="WHEN the cart is empty THEN the total is 0."))
    assert isinstance(ok, Kept) and ok.text.startswith("reject WHEN")


def test_the_last_scenario_counts(tmp_path):  # SCN-DLG-78
    text = (
        "The criterion says WHEN a user adds an item THEN the total updates. "
        "WHEN the cart is empty THEN the total is 0."
    )
    got = finding(tmp_path, reply(decision="reject", text=text))
    assert isinstance(got, Kept)
    match = WHEN_THEN.search(got.text.removeprefix("reject "))  # the parser the fix unit uses: the last one
    assert (
        match
        and match.group("when").strip() == "the cart is empty"
        and match.group("then").strip() == "the total is 0."
    )


def test_a_spec_gap_reject_with_a_reason_is_kept_when_it_cites_a_criterion(tmp_path):  # SCN-DLG-79
    context = WITH_CRITERION.replace("confirms it.", f"confirms it.{GAP}")
    got = finding(tmp_path, reply(decision="reject", text="The total ignores the tax line."), context=context)
    assert isinstance(got, Kept) and got.text == "reject The total ignores the tax line."


def test_a_reject_of_an_other_hold_still_needs_its_scenario(tmp_path):
    got = hold(tmp_path, reply(decision="reject", text="not measured"), kind="other")
    assert isinstance(got, Discarded) and "needs a sentence WHEN ... THEN ..." in got.reason
    assert isinstance(hold(tmp_path, reply(decision="reject", text="not measured"), kind="scope"), Kept)


# -- L4-DLG-024: cap-only, split and judge-view questions -------------------------------------------------------------


def test_a_cap_only_accept_cites_the_tests_lines(tmp_path):  # SCN-DLG-81, SCN-DLG-82
    options = {"cap_only": True, "cap_only_file": "tests/test_store.py"}
    ok = criterion(
        tmp_path, reply(decision="accept", text="the assert checks the totals", checked=TEST_LINES), **options
    )
    assert isinstance(ok, Kept) and ok.text == "accept the assert checks the totals"
    only_id = [cite("test:tests/test_store.py::test_add", "")]
    got = criterion(tmp_path, reply(decision="accept", text="it exists", checked=only_id), **options)
    assert isinstance(got, Discarded)
    assert got.reason == "an accept of a cap-only criterion cites the lines of tests/test_store.py"
    other = [cite("src/pkg/store.py:42", "return hash_password(raw, cost=12)")]
    assert isinstance(criterion(tmp_path, reply(decision="accept", text="x", checked=other), **options), Discarded)
    reject = criterion(tmp_path, reply(decision="reject", text="no test pins it", checked=only_id), **options)
    assert isinstance(reject, Kept)  # only an accept has to show the lines


def test_an_accept_of_a_criterion_that_is_not_cap_only_needs_no_lines(tmp_path):
    got = criterion(tmp_path, reply(decision="accept", text="the design settles it"))
    assert isinstance(got, Kept)


def test_a_judge_view_reject_is_discarded(tmp_path):  # SCN-DLG-84
    body = reply(decision="reject", text="WHEN the diff is long THEN the unit splits.")
    got = hold(tmp_path, body, judge_view_files=("src/pkg/store.py",))
    assert isinstance(got, Discarded) and got.decision == "reject"
    assert got.reason == "a reject of the judge's view escalates the unit: only a person decides it"


def test_a_judge_view_accept_cites_a_file_the_hold_names(tmp_path):
    named = [cite("src/pkg/store.py:42", "return hash_password(raw, cost=12)")]
    ok = hold(tmp_path, reply(decision="accept", text="I read the file", checked=named),
              judge_view_files=("src/pkg/store.py",))  # fmt: skip
    assert isinstance(ok, Kept)
    elsewhere = [cite("tests/test_store.py:1", "def test_add(): ...")]
    got = hold(tmp_path, reply(decision="accept", text="I read it", checked=elsewhere),
               judge_view_files=("src/pkg/store.py",))  # fmt: skip
    assert isinstance(got, Discarded) and got.reason == "an accept of a judge-view hold cites a file the hold names"
    none = hold(tmp_path, reply(decision="accept", text="I read it", checked=named), judge_view_files=())
    assert isinstance(none, Discarded)  # a hold that names no file is never accepted (the pass does not even call)
    spec = [cite("spec:design.md#D3")]
    assert isinstance(
        hold(
            tmp_path,
            reply(decision="accept", text="the spec", checked=spec),
            judge_view_files=(f"{UNIT_REL}/design.md",),
        ),
        Kept,
    )


# -- L4-DLG-025 and L4-DLG-014: a fix task and a test-support file stay a person's -------------------------------------


def test_a_chore_answer_naming_a_test_or_support_path_escalates(tmp_path):  # SCN-DLG-86
    text = "Change tests/conftest.py to add the fixture, then use it."
    got = chore(tmp_path, reply(text=text))
    assert isinstance(got, Discarded) and got.status == "escalated"
    assert got.reason == (
        "a fix task cannot change tests/conftest.py: a person commits that change on the unit branch, then answers"
    )
    by_test = chore(tmp_path, reply(text="Add a case to tests/test_store.py."))
    assert isinstance(by_test, Discarded) and "tests/test_store.py" in by_test.reason


def test_a_chore_answer_about_production_code_is_kept(tmp_path):  # SCN-DLG-87
    got = chore(tmp_path, reply(text="Change src/pkg/store.py to hash with cost 12."))
    assert isinstance(got, Kept)


def test_a_chore_answer_names_a_path_by_names_path(tmp_path):  # SCN-DLG-110
    text = "The conftest needs a fixture; change src/pkg/store.py to hash with cost 12."
    assert isinstance(chore(tmp_path, reply(text=text)), Kept)
    assert named_paths(text, ("**/conftest.py", "**/tests/**")) == []
    assert named_paths("see ./tests/conftest.py:12, then tests/conftest.pyc", ("**/conftest.py",)) == [
        "tests/conftest.py"
    ]
    assert named_paths("src/pkg/store.py", ("**/tests/**",)) == []


def test_a_question_that_is_no_chore_may_name_a_test_path(tmp_path):
    got = ask(
        tmp_path, reply(text="Add a case to tests/test_store.py."), title="Which case?", kind=QuestionKind.TECHNICAL,
        context="The design is silent.", tasks=("3.1",),
    )  # fmt: skip
    assert isinstance(got, Kept)


def test_unfreeze_true_never_opens_a_support_file(tmp_path):  # SCN-DLG-88
    context = "The red step froze tests/conftest.py and the green step needs a fixture there."
    got = ask(
        tmp_path, reply(decision="accept", text=""), title="Which fixture?", kind=QuestionKind.TECHNICAL,
        context=context, tasks=("3.1",), suggestion="Edit `tests/conftest.py`: add the fixture.", frozen=FROZEN,
        unfreeze=True,
    )  # fmt: skip
    assert isinstance(got, Discarded) and got.status == "escalated"
    assert got.reason == (
        "the answer would unfreeze tests/conftest.py of task 3.1, a test-support file: a person's change "
        "(delegate.unfreeze opens test files only)"
    )


def test_unfreeze_true_opens_nothing_in_a_fix_task(tmp_path):  # SCN-DLG-106
    got = ask(
        tmp_path, reply(decision="accept", text=""), title="Which case?", kind=QuestionKind.TECHNICAL,
        context=NAMES_STORE, tasks=("3.1",), suggestion=STORE_SUGGESTION, frozen=FROZEN, unfreeze=True, fix_task=True,
    )  # fmt: skip
    assert isinstance(got, Discarded) and got.status == "escalated" and "fix task" in got.reason
    same_outside = ask(
        tmp_path, reply(decision="accept", text=""), title="Which case?", kind=QuestionKind.TECHNICAL,
        context=NAMES_STORE, tasks=("3.1",), suggestion=STORE_SUGGESTION, frozen=FROZEN, unfreeze=True,
    )  # fmt: skip
    assert isinstance(same_outside, Kept) and [e.path for e in same_outside.unfreezes] == ["tests/test_store.py"]
