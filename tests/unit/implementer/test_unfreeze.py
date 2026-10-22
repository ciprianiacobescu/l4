"""What a human answer unfreezes for a task's green (M1.10 decision 6; L4-IMP-002, L4-QMD-005, L4-QMD-006)."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from l4.implementer.guards import FreezeManifest, FrozenFile
from l4.implementer.unfreeze import Grant, named_by_task, names_path, unfrozen
from l4.redact import Redactor
from l4.specs.questions import (
    NewQuestion,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    answer_sha256,
    answered_by,
    raise_questions,
)
from l4.state.ledger import LedgerEvent

TEST = "tests/test_notices.py"
SUGGESTION = (
    "Change `tests/test_notices.py:8` to expect the 30-day wording, and update the notice in `src/pricing/notices.py`."
)
MANIFEST = FreezeManifest(
    "r" * 40,
    {
        TEST: FrozenFile("a" * 64, "test"),
        "tests/test_other.py": FrozenFile("b" * 64, "test"),
        "tests/conftest.py": FrozenFile("c" * 64, "support"),
    },
    ("**/conftest.py",),
)
SCOPE = frozenset({"1.1", "1"})


def sub(tmp_path: Path, name: str) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    return folder


CONTEXT = f"`{TEST}` calls `RETURN_POLICY()`. The criteria require a `str`."  # the live Q-002 names its test


def ask(
    tmp_path: Path, *, kind=QuestionKind.TECHNICAL, tasks=("1.1",), title="The test freezes a wrong constant",
    context: str = CONTEXT,
):  # fmt: skip
    raise_questions(
        tmp_path, "add-x", [NewQuestion(title, kind, tasks, context, "now", ("a", "b"))], redactor=Redactor({})
    )
    return QuestionsFile.load(tmp_path / "questions.md")


def with_status(file, status: QuestionStatus, *, suggestion: str = SUGGESTION, answer: str | None = None):
    if suggestion:
        file = file.set_suggestion("Q-001", suggestion, redactor=Redactor({}))
    file = file.set_status("Q-001", status)
    if answer is not None:
        body = file.get("Q-001").answer.body
        file = QuestionsFile.parse(file.data[: body.end] + answer.encode() + b"\n" + file.data[body.end :])
    return file


def recorded(file, qid: str = "Q-001", by: str | None = None, digest: str | None = None) -> list[LedgerEvent]:
    question = file.get(qid)
    data = {"id": qid, "by": by or answered_by(question), "answer_sha256": digest or answer_sha256(question)}
    return [LedgerEvent(datetime(2026, 10, 6, tzinfo=UTC), "r-20261006T0000Z-0001", "openspec:add-x", 1,
                        "question.answered", data)]  # fmt: skip


def test_the_live_q002_accepted_suggestion_unfreezes_its_test(tmp_path):
    file = with_status(ask(tmp_path), QuestionStatus.ACCEPTED)
    got = unfrozen(file.questions, recorded(file), SCOPE, MANIFEST)
    assert got.paths == (TEST,) and got.question == "Q-001" and got.answer_sha256 == answer_sha256(file.get("Q-001"))
    assert got.kept == ()  # the other frozen files are not named
    answered = with_status(ask(sub(tmp_path, "b")), QuestionStatus.ANSWERED,
                           suggestion="", answer=f"Yes: edit {TEST}, line 8.")  # fmt: skip
    assert unfrozen(answered.questions, recorded(answered), SCOPE, MANIFEST).paths == (TEST,)


def test_answered_by_clarifier_never_unfreezes(tmp_path):
    file = with_status(ask(tmp_path), QuestionStatus.ANSWERED_BY_CLARIFIER)
    assert unfrozen(file.questions, recorded(file), SCOPE, MANIFEST).paths == ()
    open_ = with_status(ask(sub(tmp_path, "x")), QuestionStatus.OPEN)
    assert unfrozen(open_.questions, recorded(open_), SCOPE, MANIFEST).paths == ()
    forged = with_status(ask(sub(tmp_path, "y")), QuestionStatus.ACCEPTED)
    assert unfrozen(forged.questions, recorded(forged, by="clarifier"), SCOPE, MANIFEST).paths == ()


def test_an_answer_edited_after_it_was_recorded_does_not_count(tmp_path):
    file = with_status(ask(tmp_path), QuestionStatus.ACCEPTED)
    events = recorded(file)
    edited = file.set_suggestion("Q-001", SUGGESTION + " Also tests/test_other.py.", redactor=Redactor({}))
    assert unfrozen(edited.questions, events, SCOPE, MANIFEST).paths == ()  # the digest no longer matches
    assert unfrozen(file.questions, [], SCOPE, MANIFEST).paths == ()  # never recorded at a re-entry


def test_a_named_support_file_of_a_human_answer_is_unfrozen_and_an_ignore_file_is_not(tmp_path):
    """SCN-IMP-168 and SCN-IMP-169 at function level (L4-IMP-015)"""
    manifest = FreezeManifest(
        "r" * 40, {**MANIFEST.files, ".gitignore": FrozenFile("d" * 64, "support")}, MANIFEST.support_globs
    )
    text = "Update `tests/conftest.py` and tests/test_notices.py and .gitignore, plus tests/test_unknown.py."
    asked = ask(tmp_path, context=f"{CONTEXT} `tests/conftest.py` and .gitignore are involved.")
    file = with_status(asked, QuestionStatus.ACCEPTED, suggestion=text)
    got = unfrozen(file.questions, recorded(file), SCOPE, manifest)
    assert got.paths == ("tests/conftest.py", TEST)
    assert got.kept == ((".gitignore", "an ignore file"),)
    assert [g.reason for g in got.grants] == ["human_answer"] and got.grants[0].source is None


def test_an_accepted_suggestion_that_the_question_does_not_name_keeps_a_support_file_frozen(tmp_path):
    text = "Edit `tests/conftest.py`: add the setdefault line."
    file = with_status(ask(tmp_path), QuestionStatus.ACCEPTED, suggestion=text)
    got = unfrozen(file.questions, recorded(file), SCOPE, MANIFEST)
    assert got.paths == () and [p for p, _ in got.kept] == ["tests/conftest.py"]
    named = ask(sub(tmp_path, "n"), context="`tests/conftest.py` lacks the line.")
    named = with_status(named, QuestionStatus.ACCEPTED, suggestion=text)
    assert unfrozen(named.questions, recorded(named), SCOPE, MANIFEST).paths == ("tests/conftest.py",)


def test_an_old_task_unfrozen_event_without_a_reason_folds_as_before():
    """0.1: the integrity fold reads only `paths`, `task`, `red_sha` and `question` (SCN-VER-63 has no `reason`)"""
    grant = Grant("Q-001", "a" * 64, ("tests/conftest.py",))
    assert grant.reason == "human_answer" and grant.source is None


def test_a_question_of_another_task_or_a_verdict_does_not_count(tmp_path):
    other = with_status(ask(tmp_path, tasks=("2.1",)), QuestionStatus.ACCEPTED)
    assert unfrozen(other.questions, recorded(other), SCOPE, MANIFEST).paths == ()
    parent = with_status(ask(sub(tmp_path, "p"), tasks=("1",)),
                         QuestionStatus.ACCEPTED)  # fmt: skip
    assert unfrozen(parent.questions, recorded(parent), SCOPE, MANIFEST).paths == (TEST,)  # a parent holds its children
    verdict = with_status(
        ask(sub(tmp_path, "v"), kind=QuestionKind.VERDICT),
        QuestionStatus.ACCEPTED,
    )
    assert unfrozen(verdict.questions, recorded(verdict), SCOPE, MANIFEST).paths == ()


def test_path_tokens_with_line_and_punctuation(tmp_path):
    cases = {
        "see tests/test_notices.py.": True,
        "(tests/test_notices.py:8)": True,
        "tests/test_notices.py:8-12, then": True,
        '"tests/test_notices.py"': True,
        "tests/test_notices.pyc": False,
        "mytests/test_notices.py": False,
        "tests/test_notices.py.bak": False,
        "tests/test_notices": False,
        "the test_notices.py file": False,
    }
    for index, (text, expected) in enumerate(cases.items()):
        folder = tmp_path / str(index)
        folder.mkdir()
        file = with_status(ask(folder), QuestionStatus.ACCEPTED, suggestion=text)
        got = unfrozen(file.questions, recorded(file), SCOPE, MANIFEST).paths
        assert (got == (TEST,)) is expected, text
    many = " ".join(f"tests/test_{n}.py" for n in "abcde")
    wide = FreezeManifest("r" * 40, {f"tests/test_{n}.py": FrozenFile("a" * 64, "test") for n in "abcde"}, ())
    folder = tmp_path / "many"
    folder.mkdir()
    file = with_status(ask(folder, context=many), QuestionStatus.ACCEPTED, suggestion=many)
    got = unfrozen(file.questions, recorded(file), SCOPE, wide)
    assert len(got.paths) == 3 and len(got.kept) == 2  # at most 3 per question


def test_an_accepted_suggestion_unfreezes_only_tests_the_question_names(tmp_path):
    """An accepted answer is the clarifier's text, not the human's: it unfreezes only a test the question itself names
    (title, Context, Options), never one it adds (review of M1.10 line 10). A human's own answer may name any test."""
    file = with_status(ask(tmp_path), QuestionStatus.ACCEPTED, suggestion=f"Change {TEST}:8 and tests/test_other.py.")
    got = unfrozen(file.questions, recorded(file), SCOPE, MANIFEST)
    assert got.paths == (TEST,)
    assert [p for p, _ in got.kept] == ["tests/test_other.py"] and "question" in got.kept[0][1]
    unnamed = with_status(ask(sub(tmp_path, "u"), context="The constant is wrong."), QuestionStatus.ACCEPTED)
    assert unfrozen(unnamed.questions, recorded(unnamed), SCOPE, MANIFEST).paths == ()
    titled = with_status(ask(sub(tmp_path, "t"), title=f"{TEST} is wrong", context="ctx"), QuestionStatus.ACCEPTED)
    assert unfrozen(titled.questions, recorded(titled), SCOPE, MANIFEST).paths == (TEST,)
    human = with_status(ask(sub(tmp_path, "h"), context="The constant is wrong."), QuestionStatus.ANSWERED,
                        suggestion="", answer=f"Edit {TEST} and tests/test_other.py.")  # fmt: skip
    assert unfrozen(human.questions, recorded(human), SCOPE, MANIFEST).paths == (TEST, "tests/test_other.py")


# --- L4-IMP-014: the task text names a support file -----------------------------------------------------------------


def test_names_path_dot_slash_allows_only_a_leading_dot_slash():
    """SCN-IMP-164 at function level"""
    for text, path, plain, dotted in [
        ("the conftest", "conftest.py", False, False),
        ("`**/conftest.py`", "conftest.py", False, False),
        ("`../conftest.py`", "conftest.py", False, False),
        ("`./conftest.py`", "conftest.py", False, True),
        ("see ./conftest.py.", "conftest.py", False, True),
        ("tests/conftest.py", "conftest.py", False, False),
        ("tests/conftest.py", "tests/conftest.py", True, True),
        ("./tests/conftest.py", "tests/conftest.py", False, True),
        ("conftest.py:12", "conftest.py", True, True),
        ("conftest.py.bak", "conftest.py", False, False),
    ]:
        assert names_path(text, path) is plain, (text, path)
        assert names_path(text, path, dot_slash=True) is dotted, (text, path)


def bench_manifest(**extra: FrozenFile) -> FreezeManifest:
    files = {
        "tests/test_otel.py": FrozenFile("a" * 64, "test"),
        "conftest.py": FrozenFile("b" * 64, "support"),
        "tests/conftest.py": FrozenFile("c" * 64, "support"),
        **extra,
    }
    return FreezeManifest("r" * 40, files, ("**/conftest.py",))


def test_named_by_task_opens_a_named_support_file_and_nothing_else():
    got = named_by_task("Set APP_OTEL_ENABLED in `./conftest.py`.", bench_manifest(), source="plan:p1@abc")
    assert got.paths == ("conftest.py",) and got.kept == ()
    [grant] = got.grants
    assert (grant.question, grant.reason, grant.source) == (None, "named_by_task", "plan:p1@abc")
    assert got.question is None and got.answer_sha256 is None
    none = named_by_task("the conftest, `**/conftest.py`, `../conftest.py`", bench_manifest(), source="s")
    assert none.grants == () and none.kept == ()


def test_named_by_task_lists_each_kept_reason():
    """SCN-IMP-162, SCN-IMP-163, SCN-IMP-165"""
    manifest = bench_manifest(
        **{
            ".gitignore": FrozenFile("d" * 64, "support"),
            "tests/fixtures/expected.json": FrozenFile("e" * 64, "support"),
            "tests/link_conftest.py": FrozenFile(None, "support"),
            "tests/changed_conftest.py": FrozenFile("f" * 64, "support", in_red=True),
        }
    )
    text = (
        "tests/test_otel.py .gitignore tests/fixtures/expected.json tests/link_conftest.py "
        "tests/changed_conftest.py tests/conftest.py"
    )
    got = named_by_task(text, manifest, source="s")
    assert got.paths == ("tests/conftest.py",)
    assert dict(got.kept) == {
        "tests/test_otel.py": "a red test of this task",
        ".gitignore": "an ignore file",
        "tests/fixtures/expected.json": "not a Python file: a person decides",
        "tests/link_conftest.py": "a symlink at the red commit",
        "tests/changed_conftest.py": "the red step of this task changed it",
    }


def test_named_by_task_opens_at_most_three_in_sorted_order():
    files = {f"tests/c{n}/conftest.py": FrozenFile("a" * 64, "support") for n in (4, 3, 2, 1)}
    manifest = FreezeManifest("r" * 40, files, ("**/conftest.py",))
    got = named_by_task(" ".join(sorted(files, reverse=True)), manifest, source="s")
    assert got.paths == ("tests/c1/conftest.py", "tests/c2/conftest.py", "tests/c3/conftest.py")
    assert got.kept == (("tests/c4/conftest.py", "more than 3 paths named"),)


def test_a_test_file_outside_the_manifest_is_neither_opened_nor_listed():
    got = named_by_task("fix tests/test_old.py and conftest.py", bench_manifest(), source="s")
    assert got.paths == ("conftest.py",) and got.kept == ()


# --- a pre-existing tracked test file (0.4.5) ---

OLD = "packages/api/tests/test_health.py"
WITH_OLD = FreezeManifest("r" * 40, MANIFEST.files, MANIFEST.support_globs, (OLD, "packages/api/tests/test_more.py"))
OLD_SUGGESTION = f"Edit `{OLD}`: assert on `captured[-1]._inner`."


def test_an_accepted_answer_that_names_a_pre_existing_test_and_the_question_names_too_opens_it(tmp_path):
    file = with_status(ask(tmp_path, context=f"`{OLD}` asserts the old type."), QuestionStatus.ACCEPTED,
                       suggestion=OLD_SUGGESTION)  # fmt: skip
    got = unfrozen(file.questions, recorded(file), SCOPE, WITH_OLD)
    assert got.paths == (OLD,) and got.question == "Q-001" and got.grants[0].reason == "human_answer"
    assert got.answer_sha256 == answer_sha256(file.get("Q-001"))


def test_a_pre_existing_test_the_question_does_not_name_or_a_stale_answer_opens_nothing(tmp_path):
    unasked = with_status(ask(tmp_path), QuestionStatus.ACCEPTED, suggestion=OLD_SUGGESTION)
    got = unfrozen(unasked.questions, recorded(unasked), SCOPE, WITH_OLD)
    assert got.paths == () and [p for p, _ in got.kept] == [OLD]  # recorded as kept, with the reason
    named = with_status(ask(sub(tmp_path, "n"), context=f"`{OLD}` is wrong."), QuestionStatus.ACCEPTED,
                        suggestion=OLD_SUGGESTION)  # fmt: skip
    events = recorded(named)
    edited = named.set_suggestion("Q-001", OLD_SUGGESTION + " Again.", redactor=Redactor({}))
    assert unfrozen(edited.questions, events, SCOPE, WITH_OLD).paths == ()  # edited after it was recorded
    assert (
        unfrozen(named.questions, events, SCOPE, replace(WITH_OLD, preexisting=())).paths == ()
    )  # not in the manifest
    assert unfrozen(named.questions, [], SCOPE, WITH_OLD).paths == ()  # never recorded


def test_a_person_s_own_answer_opens_a_pre_existing_test_it_names_and_a_red_test_is_not_one(tmp_path):
    answered = with_status(ask(tmp_path), QuestionStatus.ANSWERED, suggestion="", answer=f"Yes, edit {OLD}.")
    assert unfrozen(answered.questions, recorded(answered), SCOPE, WITH_OLD).paths == (OLD,)
    both = with_status(ask(sub(tmp_path, "b")), QuestionStatus.ANSWERED, suggestion="", answer=f"Edit {OLD}.")
    other = replace(WITH_OLD, preexisting=(TEST, OLD))  # a red test listed twice would still be one grant
    assert unfrozen(both.questions, recorded(both), SCOPE, other).paths == (OLD,)


def test_a_harness_answer_never_unfreezes(tmp_path):
    """L4-IMP-063: `accept: tests/test_notices.py` answers a check L4 could not decide; it opens no frozen file."""
    file = with_status(
        ask(tmp_path, kind=QuestionKind.HARNESS), QuestionStatus.ANSWERED, suggestion="", answer=f"accept: {TEST}"
    )
    assert unfrozen(file.questions, recorded(file), SCOPE, MANIFEST).paths == ()


# --- named-tests 2.1: a helper red added and the task line names (L4-IMP-083) ---

HELPER = "tests/fakes_store.py"
HELPER_STUB = "def make_store():\n    raise NotImplementedError\n"
HELPER_TEXTS = {
    HELPER: HELPER_STUB,
    "tests/test_new.py": "def test_new():\n    assert 1\n",
    "tests/helpers.py": "def helper():\n    return 1\n",
    "tests/broken.py": "def broken(:\n",
    "tests/real.py": "def real():\n    return 1\n",
}


def helper_manifest(**extra: FrozenFile) -> FreezeManifest:
    files = {
        HELPER: FrozenFile("a" * 64, "test", in_red=True, added=True),
        "tests/test_new.py": FrozenFile("b" * 64, "test", in_red=True, added=True),
        "tests/helpers.py": FrozenFile("c" * 64, "test", in_red=True),
        "tests/broken.py": FrozenFile("d" * 64, "test", in_red=True, added=True),
        "tests/link.py": FrozenFile(None, "test", in_red=True, added=True),
        **extra,
    }
    return FreezeManifest("r" * 40, files, ())


def read_red(path: str) -> str | None:
    return HELPER_TEXTS.get(path)


def test_a_helper_red_added_and_the_task_names_is_opened_as_a_helper():  # SCN-IMP-405
    got = named_by_task(f"Fill in `{HELPER}`", helper_manifest(), source="plan:p1@abc", red_text=read_red)
    assert got.paths == (HELPER,) and got.kept == ()
    [grant] = got.grants
    assert (grant.reason, grant.source, grant.helper) == ("named_by_task", "plan:p1@abc", True)


def test_without_a_reader_nothing_is_a_helper():
    got = named_by_task(f"Fill in `{HELPER}`", helper_manifest(), source="s")
    assert got.paths == () and dict(got.kept) == {HELPER: "a red test of this task"}


def test_a_red_file_with_tests_a_changed_file_and_odd_files_stay_frozen():  # SCN-IMP-407
    text = f"tests/test_new.py tests/helpers.py tests/broken.py tests/link.py {HELPER}"
    got = named_by_task(text, helper_manifest(), source="s", red_text=read_red)
    assert got.paths == (HELPER,)
    assert dict(got.kept) == {
        "tests/test_new.py": "a red test of this task",
        "tests/helpers.py": "a red test of this task",
        "tests/broken.py": "a red test of this task",
        "tests/link.py": "a red test of this task",
    }


def test_a_helper_counts_against_the_cap_with_the_other_opened_paths():
    files = {f"tests/h{n}.py": FrozenFile("a" * 64, "test", in_red=True, added=True) for n in (4, 3, 2, 1)}
    texts = {p: "def f():\n    return 1\n" for p in files}
    got = named_by_task(" ".join(files), FreezeManifest("r" * 40, files, ()), source="s", red_text=texts.get)
    assert got.paths == ("tests/h1.py", "tests/h2.py", "tests/h3.py")
    assert got.kept == (("tests/h4.py", "more than 3 paths named"),)
