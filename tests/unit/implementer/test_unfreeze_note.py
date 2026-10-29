"""M1.13 lines 21-23 (W-C3, SPEC L4-QMD-005/006, L4-IMP-002): the question of a blocked green step tells the human how
a frozen test is unfrozen. Damage line: the note must never widen what an `accepted` suggestion unfreezes, so it names
only the frozen files the agent's own question already names."""

from l4.agents.fake import Step
from l4.implementer.loop import run_task
from l4.implementer.unfreeze import forbidden_note, unfreeze_note, unfrozen
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


# --- a question after a forbidden-path removal, or naming such a path (forbidden-path-intake D5; L4-IMP-015) ---

MIGRATION = "app/migrations/0001_initial.py"
RULE = "**/migrations/**"
ASK = {
    "title": f"The task needs {MIGRATION}",
    "context": "The harness removes the file after every step.",
    "kind": "technical",
    "options": ["A person adds it", "Drop the migration from the task"],
}


def test_the_forbidden_note_names_the_path_the_glob_and_both_fixes():
    note = forbidden_note([(MIGRATION, RULE)], unit="my-unit")
    assert note.startswith("Harness note:")
    assert f"`{MIGRATION}` is forbidden by `odd.forbidden_paths` (`{RULE}`)" in note
    assert "No agent may write it and no answer changes that" in note
    assert "A person commits `app/migrations/0001_initial.py` on the unit branch" in note and "L4-SEC-004" in note
    assert (
        f"sets `odd.forbidden_paths` in `.l4/config.yaml` on the base branch to an explicit list without `{RULE}`"
        in note
    )
    assert 'l4 questions answer Q-NNN --unit my-unit --text "..."' in note
    assert "frozen" not in note and "unfreez" not in note and "`accepted`" not in note


def test_the_forbidden_note_has_a_placeholder_without_a_unit_and_names_several_paths():
    note = forbidden_note([(MIGRATION, RULE), ("infra/main.tf", "infra/**")])
    assert "--unit <unit>" in note
    assert f"`{MIGRATION}` (`{RULE}`)" in note and "`infra/main.tf` (`infra/**`)" in note
    assert "without `**/migrations/**`, `infra/**`" in note or "without `**/migrations/**` and `infra/**`" in note


def red_then(make_bench, step):
    bench = make_bench([red_step(), step])
    assert run_task(bench.wb, TASK).status == "blocked"
    [asked] = QuestionsFile.load(bench.wb.ref.path / "questions.md").questions
    return asked


def test_a_question_after_a_forbidden_removal_carries_the_forbidden_note(make_bench):  # SCN-IMP-424
    step = Step(
        writes={MIGRATION: "# migration\n"},
        structured=result("green", status="blocked", questions=[{**ASK, "title": "Blocked"}]),
    )
    context = red_then(make_bench, step).context_text
    assert f"`{MIGRATION}` is forbidden by `odd.forbidden_paths` (`{RULE}`)" in context
    assert "Harness note:" in context and context.index("Harness note:") > context.index("removes the file")
    assert "frozen" not in context and "unfreez" not in context and "tests/test_discount.py" not in context


def test_a_question_that_names_a_forbidden_path_carries_it_without_any_removal(make_bench):  # SCN-IMP-424
    context = red_then(make_bench, Step(structured=result("green", status="blocked", questions=[ASK]))).context_text
    assert f"`{MIGRATION}` is forbidden by `odd.forbidden_paths` (`{RULE}`)" in context
    assert "red tests" not in context


def test_a_blocked_red_that_names_a_forbidden_path_carries_the_note_too(make_bench):
    bench = make_bench([Step(structured=result("red", status="blocked", questions=[ASK]))])
    assert run_task(bench.wb, TASK).status == "blocked"
    [asked] = QuestionsFile.load(bench.wb.ref.path / "questions.md").questions
    assert "is forbidden by `odd.forbidden_paths`" in asked.context_text


def test_a_question_with_no_forbidden_path_keeps_the_unfreeze_note(make_bench):
    context = raised(make_bench, QUESTION).context_text
    assert "red tests and test-support files" in context and "odd.forbidden_paths" not in context


def test_a_non_technical_question_naming_a_forbidden_path_gets_no_note(make_bench):
    asked = raised(make_bench, {**ASK, "kind": "product"})
    assert "Harness note" not in asked.context_text


def test_the_forbidden_note_for_a_contract_path_offers_only_the_persons_commit():
    note = forbidden_note([(".github/workflows/new.yml", ".github/workflows/**")], unit="u")
    assert "A person commits `.github/workflows/new.yml` on the unit branch" in note
    assert "sets `odd.forbidden_paths`" not in note and 'l4 questions answer Q-NNN --unit u --text "..."' in note


def commit_migration(tdd_repo) -> None:
    """The migration exists in the unit's worktree: committed on main before the bench is built."""
    from l4.vcs.git import Git

    git = Git(tdd_repo.repo, environ=tdd_repo.environ)
    (tdd_repo.repo / "app" / "migrations").mkdir(parents=True)
    (tdd_repo.repo / MIGRATION).write_text("STATUS = 'open'\n")
    git.run("add", MIGRATION)
    git.run("commit", "-q", "-m", "an existing migration")
    git.push("origin", ["main"])


MENTIONS = {
    "title": "tests/test_discount.py expects 'new' but the migration sets 'open'",
    "context": f"tests/test_discount.py:6 expects 'new' but the existing migration {MIGRATION} sets 'open'.",
    "kind": "technical",
    "options": [EDIT, "Keep the test and change the code (contradicts the spec)"],
}


def test_a_question_that_only_mentions_an_existing_forbidden_file_keeps_the_unfreeze_note(make_bench, tdd_repo):
    commit_migration(tdd_repo)  # SCN-IMP-425
    context = raised(make_bench, MENTIONS).context_text
    assert "red tests and test-support files" in context and "`accepted`" in context
    assert "odd.forbidden_paths" not in context


def test_a_missing_forbidden_path_beside_an_option_that_edits_a_frozen_test_keeps_the_unfreeze_note(make_bench):
    asked = raised(make_bench, {**MENTIONS, "context": f"The task asks for {MIGRATION}, which does not exist."})
    assert "`accepted`" in asked.context_text and "odd.forbidden_paths" not in asked.context_text
