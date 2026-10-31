"""`l4 questions` reading, showing and editing (unfreeze-and-answer 4.2 to 4.4; L4-QMD-007, L4-QMD-008)."""

import dataclasses
import io
import json
from datetime import UTC, datetime, timedelta

import pytest

from l4.config.redaction import load_app_config
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.local import LocalForge
from l4.redact import Redactor
from l4.specs.questions import QuestionsFile, QuestionStatus, answer_sha256, effective_answer
from l4.specs.questions_cli import (
    ClarifierRules,
    Refusal,
    agent_reason,
    build_edit,
    check_agent,
    check_question,
    check_text,
    edit_accept,
    edit_answer,
    load_folders,
    round_trip,
    run_questions,
)

from .questions_world import (
    FOLDER,
    RUN,
    A,
    B,
    QWorld,
    ledger_file,
    questions_md,
    unit_files,
)


def listed(world: QWorld, capsys, **options) -> tuple[ExitCode, str]:
    code = run_questions(
        world.app, **{"words": (), "unit": None, "text": None, "as_json": False, "no_push": False, **options}
    )
    return code, capsys.readouterr().out


def two_units(world: QWorld) -> None:
    world.unit_branch(
        "a",
        questions_md(
            "a",
            {
                "title": "Which hash?",
                "kind": "technical",
                "tasks": ("2.1",),
                "status": "answered",
                "answer": "argon2id",
            },
            {"title": "Allow unverified?", "kind": "product", "tasks": ("3.1",)},
        ),
    )
    world.unit_branch(
        "b", questions_md("b", {"title": "Which port?", "kind": "technical", "tasks": ("1.1",), "answer": "8080"})
    )


def test_scn_qmd_12_lists_the_open_questions_of_every_unit_branch(qworld, capsys):
    two_units(qworld)
    assert not (qworld.app.repo / FOLDER / "a" / "questions.md").exists()  # the checkout has none: the branch is read
    code, out = listed(qworld, capsys)
    assert code is ExitCode.OK
    assert f"{A} Q-002 product 3.1 Allow unverified?" in out
    assert f"{B} Q-001 draft 1.1 Which port?" in out
    assert f"{A} Q-001" not in out
    assert out.splitlines()[-1] == f"Next: l4 questions show Q-002 --unit {A}"


def test_list_alias_unit_filter_and_json(qworld, capsys):
    two_units(qworld)
    code, out = listed(qworld, capsys, words=("list",), unit=B, as_json=True)
    doc = json.loads(out)
    assert code is ExitCode.OK and doc["schema"] == "l4/questions@1"
    assert [(q["unit"], q["id"], q["kind"], q["draft"], q["blocking"]) for q in doc["questions"]] == [
        (B, "Q-001", "technical", True, ["1.1"])
    ]
    assert doc["next"] == f"l4 questions show Q-001 --unit {B}"


def test_no_open_question_and_a_unit_without_a_branch(qworld, capsys):
    code, out = listed(qworld, capsys)
    assert code is ExitCode.OK and out.strip() == "no open question"
    code, out = listed(qworld, capsys, unit=A)
    assert code is ExitCode.OK and f"{A} has no branch on origin" in out and "no open question" in out


def test_an_unknown_unit_is_refused(qworld, capsys):
    with pytest.raises(L4Exit) as caught:
        listed(qworld, capsys, unit="openspec:nope")
    assert caught.value.code is ExitCode.USAGE_ERROR
    assert str(caught.value).startswith("questions: no unit openspec:nope")
    assert "Fix: l4 status lists the units" in str(caught.value)


def test_scn_qmd_14_a_fix_unit_is_listed_under_its_parent(qworld, capsys):
    qworld.unit_branch(
        "a",
        extra={
            f"{FOLDER}/a-fix-1/tasks.md": "## 1. Fix\n\n- [ ] 1.1 Fix it\n",
            f"{FOLDER}/a-fix-1/questions.md": questions_md("a-fix-1", {"title": "Fix which?", "tasks": ("1.1",)}),
        },
    )
    code, out = listed(qworld, capsys, unit=A)
    assert code is ExitCode.OK
    assert "openspec:a-fix-1 Q-001 technical 1.1 Fix which?" in out
    assert out.splitlines()[-1] == "Next: l4 questions show Q-001 --unit openspec:a-fix-1"
    code, out = listed(qworld, capsys, unit="openspec:a-fix-1")  # the fix unit's own id reads the same folder
    assert "openspec:a-fix-1 Q-001" in out
    code, out = listed(qworld, capsys)  # no --unit: every unit with a branch, fix units included
    assert "openspec:a-fix-1 Q-001" in out


def test_a_failed_fetch_reads_the_refs_that_exist_and_warns(qworld, capsys):
    two_units(qworld)
    listed(qworld, capsys)  # the first run fetches
    qworld.unit_branch("a", questions_md("a", {"title": "Pushed later?", "tasks": ("2.1",)}))
    qworld.break_origin()
    code, out = listed(qworld, capsys)
    assert code is ExitCode.OK
    assert "warning: not fetched (" in out and "the questions may be old" in out
    assert f"{A} Q-002 product 3.1 Allow unverified?" in out  # the tracking ref the first run fetched
    assert "Pushed later?" not in out


def test_a_symlinked_questions_file_is_not_read(qworld, capsys):
    qworld.symlinked_questions("a")
    code, out = listed(qworld, capsys)
    assert code is ExitCode.OK
    assert f"warning: {A}: questions.md is a symlink on l4/openspec/a" in out


def test_an_oversized_questions_file_is_not_read(qworld, capsys):
    big = questions_md("a", {"title": "Big?"}) + "x" * (2 * 1024 * 1024)
    qworld.unit_branch("a", big)
    code, out = listed(qworld, capsys)
    assert code is ExitCode.OK
    assert f"warning: {A}: questions.md is larger than 2 MiB on l4/openspec/a" in out
    assert "Big?" not in out


def test_an_unreadable_section_gives_one_warning_line(qworld, capsys):
    text = questions_md("a", {"title": "Fenced?"}, {"title": "Hidden?"})
    text = text.replace("### Context\n", "### Context\n```\n", 1).replace("---\n\n## Q-002", "## Q-002", 1)
    qworld.unit_branch("a", text)
    code, out = listed(qworld, capsys)
    assert code is ExitCode.OK
    assert [line for line in out.splitlines() if line.startswith("warning:")] == [
        f"warning: {A} Q-002: the section cannot be read: it holds every pending task"
    ]


# --- show (unfreeze-and-answer 4.3) ------------------------------------------------------------------------------


class Tty:
    @staticmethod
    def isatty() -> bool:
        return True


@pytest.fixture
def person(monkeypatch):
    monkeypatch.setattr("sys.stdin", Tty())


def shown(world: QWorld, capsys, question: str, unit: str | None = A, **options) -> tuple[ExitCode, str]:
    options = {"words": ("show", question), "unit": unit, "text": None, "as_json": False, "no_push": False, **options}
    code = run_questions(world.app, **options)
    return code, capsys.readouterr().out


RED = (
    "task.red_ok",
    {
        "task": "2.1",
        "base": "abc",
        "tests": ["tests/test_x.py::t"],
        "frozen": ["conftest.py", ".gitignore", "tests/test_x.py"],
    },
)


def q003(**over) -> dict:
    spec = {
        "title": "Edit the conftest?",
        "kind": "technical",
        "tasks": ("2.1",),
        "context": "The fixture lives in `conftest.py`.",
        "options": ("Edit `conftest.py`: add the line", "Leave it"),
        "suggestion": "Edit `conftest.py`: add the line",
    }
    return {**spec, **over}


def with_q003(world: QWorld, *extra: dict, ledger: str | None = None) -> None:
    filler = [{"title": "One?", "tasks": ("1.1",)}, {"title": "Two?", "tasks": ("1.1",)}]
    world.unit_branch(
        "a", questions_md("a", *filler, q003(), *extra), ledger=ledger_file(A, RED) if ledger is None else ledger
    )


def test_scn_qmd_13_show_says_what_an_accept_would_unfreeze(qworld, capsys, person):
    with_q003(qworld)
    code, out = shown(qworld, capsys, "Q-003")
    assert code is ExitCode.OK
    assert "## Q-003: Edit the conftest?" in out and "- **Status:** open" in out and "### Clarifier suggestion" in out
    assert "accept takes: Edit `conftest.py`: add the line" in out
    assert "an accepted suggestion unfreezes conftest.py for the next green of 2.1" in out
    assert "tests/test_x.py" not in out.split("accept takes:")[1]  # the suggestion does not name it
    assert "caller: person: may accept and answer" in out
    assert out.splitlines()[-2:] == [
        f"Next: l4 questions accept Q-003 --unit {A}",
        f"Next: l4 questions answer Q-003 --unit {A} --text TEXT",
    ]


def test_show_keeps_an_ignore_file_and_an_unasked_file_frozen(qworld, capsys, person):
    suggestion = "Edit `conftest.py`, `.gitignore` and `tests/test_x.py`."
    with_q003(qworld)
    qworld.unit_branch(
        "a",
        questions_md(
            "a",
            {"title": "One?"},
            {"title": "Two?"},
            q003(suggestion=suggestion, options=("Edit `conftest.py`", "Leave it"), context="Fixture in `.gitignore`."),
        ),
        ledger=ledger_file(A, RED),
    )
    _, out = shown(qworld, capsys, "Q-003")
    assert "an accepted suggestion unfreezes conftest.py for the next green of 2.1" in out
    assert "an accepted suggestion leaves .gitignore frozen for 2.1 (an ignore file)" in out
    assert "an accepted suggestion leaves tests/test_x.py frozen for 2.1 (the question does not name it)" in out


def test_show_says_an_accept_would_unfreeze_a_pre_existing_test(qworld, capsys, person):
    old = "packages/api/tests/test_health.py"
    qworld.unit_branch(
        "a",
        questions_md(
            "a",
            {"title": "One?"},
            {"title": "Two?"},
            q003(
                suggestion=f"Edit `{old}`: assert on `_inner`.",
                options=(f"Edit `{old}`: assert", "Leave it"),
                context=f"`{old}` asserts the old type.",
            ),
        ),
        ledger=ledger_file(A, RED),
        extra={old: "def test_health():\n    assert 1\n"},
    )
    _, out = shown(qworld, capsys, "Q-003")
    assert f"an accepted suggestion unfreezes the pre-existing test {old} for the next green of 2.1" in out
    unasked = f"Edit `{old}`: assert on `_inner`."
    qworld.unit_branch(
        "a",
        questions_md("a", {"title": "One?"}, {"title": "Two?"}, q003(suggestion=unasked, context="It is wrong.")),
        ledger=ledger_file(A, RED),
        extra={old: "def test_health():\n    assert 1\n"},
    )
    _, out = shown(qworld, capsys, "Q-003")
    assert f"leaves {old} frozen for 2.1 (the question does not name it)" in out


def test_show_reads_the_latest_red_of_a_task_and_no_ledger_is_no_frozen_path(qworld, capsys, person):
    later = ("task.red_ok", {"task": "2.1", "base": "def", "frozen": ["other.py"]})
    with_q003(qworld, ledger=ledger_file(A, RED, later))
    _, out = shown(qworld, capsys, "Q-003")
    assert "accept takes:" in out and "unfreezes" not in out and "leaves" not in out  # other.py is not named
    with_q003(qworld, ledger="")
    _, out = shown(qworld, capsys, "Q-003")
    assert "accept takes: Edit `conftest.py`: add the line" in out and "unfreezes" not in out


def test_show_without_a_suggestion_names_the_answer_form(qworld, capsys, person):
    with_q003(qworld)
    qworld.unit_branch("a", questions_md("a", {"title": "Bare?", "tasks": ("1.1",)}))
    _, out = shown(qworld, capsys, "Q-001")
    assert "accept takes: no clarifier suggestion: answer it with --text" in out
    assert out.splitlines()[-1] == f"Next: l4 questions answer Q-001 --unit {A} --text TEXT"
    assert "Next: l4 questions accept" not in out


def test_show_of_a_verdict_question_gives_the_accept_or_reject_hint(qworld, capsys, person):
    qworld.unit_branch("a", questions_md("a", {"title": "Verdict?", "kind": "verdict", "tasks": (), "suggestion": "x"}))
    _, out = shown(qworld, capsys, "Q-001")
    assert f'answer with: l4 questions answer Q-001 --unit {A} --text "accept <reason>" (or "reject <reason>")' in out
    assert "Next: l4 questions accept" not in out and "accept takes" not in out


def test_show_json(qworld, capsys, person):
    with_q003(qworld)
    code, out = shown(qworld, capsys, "Q-003", as_json=True)
    doc = json.loads(out)
    assert code is ExitCode.OK and doc["schema"] == "l4/questions@1"
    assert (doc["unit"], doc["id"], doc["status"], doc["kind"], doc["blocking"]) == (
        A,
        "Q-003",
        "open",
        "technical",
        ["2.1"],
    )
    assert doc["accept"] == {"takes": "Edit `conftest.py`: add the line"}
    assert {"task": "2.1", "path": "conftest.py", "unfreezes": True, "why": ""} in doc["frozen"]
    assert doc["caller"]["actor"] == "person" and doc["caller"]["accept"] is None
    assert doc["next"][0] == f"l4 questions accept Q-003 --unit {A}" and "## Q-003:" in doc["section"]


def test_show_tells_an_agent_what_it_may_write(qworld, capsys, monkeypatch):
    with_q003(qworld)
    qworld.app = dataclasses.replace(qworld.app, environ={**qworld.app.environ, "CLAUDECODE": "1"})
    _, out = shown(qworld, capsys, "Q-003")
    assert "caller: agent (CLAUDECODE)" in out
    assert "accept: refused: the suggestion names the frozen path conftest.py of task 2.1" in out
    assert "answer: may, when its text names no frozen path" in out


def test_show_refusals_unknown_question_no_file_and_no_branch(qworld, capsys, person):
    with_q003(qworld)
    with pytest.raises(L4Exit) as caught:
        shown(qworld, capsys, "Q-077")
    assert (
        caught.value.code is ExitCode.USAGE_ERROR
        and "questions: no Q-077 in openspec/changes/a/questions.md" in str(caught.value)
    )
    assert f"Fix: l4 questions --unit {A}" in str(caught.value)
    with pytest.raises(L4Exit, match="has no branch on origin"):
        shown(qworld, capsys, "Q-001", unit=B)
    qworld.unit_branch("b", extra={"openspec/changes/b/.keep": "x\n"})
    with pytest.raises(L4Exit, match="b has no questions.md on l4/openspec/b"):
        shown(qworld, capsys, "Q-001", unit=B)
    with pytest.raises(L4Exit, match="show needs --unit"):
        shown(qworld, capsys, "Q-001", unit=None)
    with pytest.raises(L4Exit, match="not a question id"):
        shown(qworld, capsys, "banana")


def test_show_of_a_question_that_is_not_open_says_so(qworld, capsys, person):
    qworld.unit_branch("a", questions_md("a", {"title": "Done?", "status": "answered", "answer": "yes"}))
    code, out = shown(qworld, capsys, "Q-001")
    assert code is ExitCode.OK
    assert "Q-001 is answered: it takes no accept or answer" in out and "Next: l4 questions accept" not in out


def test_scn_qmd_14_show_reads_a_fix_unit_question_and_its_frozen_paths_from_the_parent_ledger(qworld, capsys, person):
    fix_red = ("task.red_ok", {"task": "1.1", "fix_unit": "a-fix-1", "frozen": ["conftest.py"]})
    parent_red = ("task.red_ok", {"task": "1.1", "frozen": ["other.py"]})
    qworld.unit_branch(
        "a",
        ledger=ledger_file(A, parent_red, fix_red),
        extra={
            f"{FOLDER}/a-fix-1/tasks.md": "## 1. Fix\n\n- [ ] 1.1 Fix it\n",
            f"{FOLDER}/a-fix-1/questions.md": questions_md("a-fix-1", q003(tasks=("1.1",))),
        },
    )
    code, out = shown(qworld, capsys, "Q-001", unit="openspec:a-fix-1")
    assert code is ExitCode.OK and "## Q-001: Edit the conftest?" in out
    assert "an accepted suggestion unfreezes conftest.py for the next green of 1.1" in out
    assert "other.py" not in out
    assert out.splitlines()[-2] == "Next: l4 questions accept Q-001 --unit openspec:a-fix-1"


# --- the edit and its checks (unfreeze-and-answer 4.4) -----------------------------------------------------------

PLAIN = Redactor({})


def parsed(*specs: dict, eol: str = "\n") -> QuestionsFile:
    return QuestionsFile.parse(questions_md("a", *specs, eol=eol))


def refusal(found: Refusal | None) -> str:
    assert found is not None
    return f"{found.message} | {found.fix}"


def test_edit_accept_sets_only_the_status_and_its_row():
    file = parsed({"title": "Which?", "tasks": ("1.1",), "suggestion": "Use argon2id."})
    out = edit_accept(file, "Q-001")
    assert out.get("Q-001").status is QuestionStatus.ACCEPTED and effective_answer(out.get("Q-001")) == "Use argon2id."
    assert b"| Q-001 | accepted |" in out.data and out.get("Q-001").answer_text == ""
    restored = out.data.replace(b"- **Status:** accepted", b"- **Status:** open").replace(b"| accepted |", b"| open |")
    assert restored == file.data  # nothing else differs


def test_edit_answer_sets_the_answer_body_the_status_and_the_row_and_nothing_else():
    file = parsed({"title": "Which?", "tasks": ("1.1",)}, {"title": "Other?", "tasks": ("1.2",)})
    out = edit_answer(file, "Q-001", "Use argon2id.\nCost 3.")
    q = out.get("Q-001")
    assert q.status is QuestionStatus.ANSWERED and effective_answer(q) == "Use argon2id.\nCost 3."
    assert out.get("Q-002").status is QuestionStatus.OPEN and out.get("Q-002").answer_text == ""
    assert round_trip(file, out, "Q-001", QuestionStatus.ANSWERED, "Use argon2id.\nCost 3.") is None


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_the_edits_keep_the_line_endings(eol):
    file = parsed({"title": "Which?", "tasks": ("1.1",), "suggestion": "Yes."}, eol=eol)
    for out in (edit_answer(file, "Q-001", "a\nb"), edit_accept(file, "Q-001")):
        assert out.data.count(b"\r\n") == (out.data.count(b"\n") if eol == "\r\n" else 0)
    text = "one\ntwo"
    assert round_trip(file, edit_answer(file, "Q-001", text), "Q-001", QuestionStatus.ANSWERED, text) is None


def test_round_trip_names_the_difference():
    file = parsed({"title": "A?", "tasks": ("1.1",)}, {"title": "B?", "tasks": ("1.2",)})
    good = edit_answer(file, "Q-001", "yes")
    assert round_trip(file, good, "Q-001", QuestionStatus.ANSWERED, "yes") is None
    assert "Status" in round_trip(file, good, "Q-001", QuestionStatus.ACCEPTED, None)
    assert "answer" in round_trip(file, good, "Q-001", QuestionStatus.ANSWERED, "no")
    other = good.set_status("Q-002", QuestionStatus.DISMISSED)
    assert "Q-002" in round_trip(file, other, "Q-001", QuestionStatus.ANSWERED, "yes")
    gone = QuestionsFile.parse(good.data.replace(b"## Q-002:", b"## Q-002 :"))
    assert "Q-002" in round_trip(file, gone, "Q-001", QuestionStatus.ANSWERED, "yes")
    bogus = QuestionsFile.parse(good.data.replace(b"- **Status:** open", b"- **Status:** bogus", 1))
    assert "parse issue" in round_trip(file, bogus, "Q-001", QuestionStatus.ANSWERED, "yes")


def test_scn_qmd_22_text_checks_name_the_line_or_the_kind():
    assert check_text("Block login.\n#hashtag is fine", PLAIN) is None
    assert "line 2" in check_text("Block login.\n  ## indented too", PLAIN).message
    assert check_text("a\n## Notes", PLAIN).fix == "remove or reword line 2"
    assert "line 2" in check_text("a\n## Notes", PLAIN).message
    assert "line 1" in check_text("- **Status:** dismissed", PLAIN).message
    for line in ("---", "| a | b |", "```", "~~~", "### Answer", "- **Kind:** x", "* **Asked:** y", "  ```py"):
        assert check_text(f"fine\n{line}", PLAIN) is not None, line
    assert "line 3" in check_text("a\r\nb\r\n---", PLAIN).message  # CRLF counts lines too
    assert "secret-like value (gitlab-pat)" in refusal(check_text("token glpat-abcdefghij0123456789", PLAIN))
    assert "rotate it" in refusal(check_text("token glpat-abcdefghij0123456789", PLAIN))
    assert "HTML comment" in refusal(check_text("x <!-- hide --> y", PLAIN))
    assert "empty" in refusal(check_text("  \n ", PLAIN))
    assert "20000" in refusal(check_text("x" * 20001, PLAIN)) and check_text("x" * 20000, PLAIN) is None
    named = Redactor({"TOKEN": "hunter2hunter2"})
    assert "value:TOKEN" in refusal(check_text("pw hunter2hunter2", named))


def test_scn_qmd_18_an_answered_question_is_refused_with_the_hand_edit_fix():
    file = parsed({"title": "Done?", "tasks": ("1.1",), "status": "answered", "answer": "yes"})
    for form in ("accept", "answer"):
        found = check_question(file, "Q-001", form, "no", unit=A, branch="l4/openspec/a")
        assert found.message == "Q-001 is answered"
        assert "edit its section on l4/openspec/a by hand" in found.fix and "L4-QMD-006" in found.fix
    dismissed = parsed({"title": "Done?", "status": "dismissed"})
    assert check_question(dismissed, "Q-001", "answer", "x", unit=A, branch="b").message == "Q-001 is dismissed"


def test_r4b_a_superseded_question_names_its_successor():
    file = parsed({"title": "Old?"}, {"title": "New?"})
    file = QuestionsFile.parse(file.data.replace(b"- **Status:** open", b"- **Status:** superseded by Q-002", 1))
    found = check_question(file, "Q-001", "answer", "x", unit=A, branch="b")
    assert found.message == "Q-001 is superseded by Q-002"
    assert found.fix == f"answer Q-002: l4 questions show Q-002 --unit {A}"


def test_r5_a_draft_answer_under_open_is_refused():
    file = parsed({"title": "Draft?", "answer": "half written"})
    found = check_question(file, "Q-001", "answer", "x", unit=A, branch="l4/openspec/a")
    assert found.message == "Q-001 has a draft answer under Status open"
    assert "submit it on l4/openspec/a" in found.fix
    assert check_question(file, "Q-001", "accept", None, unit=A, branch="b").message == found.message


def test_r7_accept_needs_a_suggestion_and_r3_the_question_must_exist():
    file = parsed({"title": "Bare?"})
    found = check_question(file, "Q-001", "accept", None, unit=A, branch="b")
    assert found.message == "Q-001 has no clarifier suggestion to accept"
    assert found.fix == f"l4 questions answer Q-001 --unit {A} --text TEXT"
    assert check_question(file, "Q-009", "answer", "x", unit=A, branch="b").message == "no Q-009 in questions.md"
    assert check_question(file, "Q-001", "answer", "fine", unit=A, branch="b") is None


def test_scn_qmd_21_the_verdict_rules_hold():
    file = parsed({"title": "Verdict?", "kind": "verdict", "tasks": (), "suggestion": "x"})
    found = check_question(file, "Q-001", "accept", None, unit=A, branch="b")
    assert found.message == "Q-001 is a verdict question: accept is not an answer to it"
    assert found.fix == f'l4 questions answer Q-001 --unit {A} --text "accept <reason>" (or "reject <reason>")'
    found = check_question(file, "Q-001", "answer", "looks fine", unit=A, branch="b")
    assert found.message == "a verdict answer starts with accept or reject"
    for text in ("reject: WHEN a THEN b", "accept the finding", "Accept - ok", "`reject` no", "  *accept*: yes"):
        assert check_question(file, "Q-001", "answer", text, unit=A, branch="b") is None, text
    assert check_question(file, "Q-001", "answer", "acceptable", unit=A, branch="b") is not None
    assert "structure" in check_question(file, "Q-001", "answer", "accept\n## x", unit=A, branch="b").message


RULES = ClarifierRules(("technical",), False)


def test_the_agent_rule_as_a_pure_function():
    technical = parsed({"title": "T?", "tasks": ("2.1",), "suggestion": "Edit `conftest.py`: add"}).get("Q-001")
    product = parsed({"title": "P?", "kind": "product", "tasks": ("2.1",)}).get("Q-001")
    verdict = parsed({"title": "V?", "kind": "verdict", "tasks": ()}).get("Q-001")
    frozen = {"2.1": ("conftest.py",)}
    assert agent_reason(technical, "Use argon2id.", frozen, RULES) is None
    assert agent_reason(technical, "Edit conftest.py", frozen, RULES) == (
        "the text names the frozen path conftest.py of task 2.1"
    )
    assert "suggestion names" in agent_reason(technical, "Edit `conftest.py`: add", frozen, RULES)
    assert agent_reason(technical, "Edit other.py", {"9.9": ("conftest.py",)}, RULES) is None  # a task it does not hold
    assert "kind is product" in agent_reason(product, "x", {}, RULES)
    assert "verdict" in agent_reason(verdict, "accept", {}, RULES)
    opened = ClarifierRules(("technical",), True)
    assert all(agent_reason(q, "Edit conftest.py", frozen, opened) is None for q in (technical, product, verdict))
    wide = ClarifierRules(("technical", "product"), False)
    assert agent_reason(product, "x", {}, wide) is None
    found = check_agent("accept", technical, "Edit conftest.py", frozen, RULES, "main")
    assert found.message.startswith("an agent may not accept Q-001: ")
    assert found.fix.startswith("a person runs the command, or set clarifier.answer_by_agents: true in .l4/config.yaml")
    assert "on main" in found.fix and check_agent("answer", technical, "ok", frozen, RULES, "main") is None


def run_form(
    world: QWorld,
    *words: str,
    unit: str | None = A,
    text: str | None = None,
    no_push: bool = False,
    no_run: bool = False,
    replace: bool = False,
):
    return run_questions(
        world.app, words=words, unit=unit, text=text, as_json=False, no_push=no_push, no_run=no_run, replace=replace
    )


@pytest.fixture(autouse=True)
def forge(monkeypatch):
    """The forge the command asks to start a run on the base branch (L4-OPS-002)."""
    local = LocalForge()
    monkeypatch.setattr("l4.state.retry.make_forge", lambda *a, **k: local)
    return local


def two_open(world: QWorld) -> None:
    world.unit_branch(
        "a",
        questions_md(
            "a",
            {"title": "Which hash?", "tasks": ("2.1",), "suggestion": "Use argon2id."},
            {"title": "Allow it?", "kind": "product", "tasks": ("3.1",)},
            {"title": "Verdict?", "kind": "verdict", "tasks": ()},
            {"title": "Done?", "status": "answered", "answer": "yes"},
        ),
    )


@pytest.mark.parametrize(
    ("words", "text", "cause", "fix"),
    [
        (("answer", "Q-004"), "no", "questions: Q-004 is answered", "L4-QMD-006"),
        (("accept", "Q-004"), None, "questions: Q-004 is answered", "by hand"),
        (("accept", "Q-003"), None, "accept is not an answer to it", 'answer Q-003 --unit openspec:a --text "accept'),
        (("answer", "Q-003"), "looks fine", "a verdict answer starts with accept or reject", "first word"),
        (("answer", "Q-002"), "see\n## Notes", "line 2 would be read as structure", "remove or reword line 2"),
        (("answer", "Q-002"), "- **Status:** dismissed", "line 1", "remove or reword line 1"),
        (("answer", "Q-002"), "key glpat-abcdefghij0123456789", "secret-like value (gitlab-pat)", "rotate it"),
        (("answer", "Q-002"), "  ", "the text is empty", "--text"),
        (("accept", "Q-002"), None, "Q-002 has no clarifier suggestion", "l4 questions answer Q-002"),
        (("answer", "Q-009"), "x", "no Q-009 in openspec/changes/a/questions.md", "l4 questions --unit openspec:a"),
        (("answer", "Q-002"), None, "answer needs --text", "--text TEXT"),
    ],
)
def test_the_writing_forms_refuse_with_exit_2_and_touch_nothing(qworld, words, text, cause, fix):
    two_open(qworld)
    head, tracking = qworld.origin_head("a"), qworld.tracking("a")
    with pytest.raises(L4Exit) as caught:
        run_form(qworld, *words, text=text)
    message = str(caught.value)
    assert caught.value.code is ExitCode.USAGE_ERROR
    assert message.startswith("questions: ") and cause in message
    assert "\nFix: " in message and fix in message.split("\nFix: ", 1)[1]
    assert qworld.origin_head("a") == head and qworld.tracking("a") in (tracking, head)


def written(world: QWorld, capsys, *words: str, text: str | None = None, **options) -> str:
    assert run_form(world, *words, text=text, **options) is ExitCode.OK
    return capsys.readouterr().out


def origin_commit(world: QWorld, name: str = "a") -> dict[str, str]:
    fields = ("an", "ae", "cn", "ce", "P", "s", "b")
    out = world.remote.run(
        "log", "-1", f"--format={'%x01'.join('%' + f for f in fields)}", f"l4/openspec/{name}"
    ).stdout
    return dict(zip(fields, out.rstrip("\n").split("\x01"), strict=True))


def diff_lines(world: QWorld, old: str, new: str) -> list[str]:
    out = world.remote.run("diff", "--unified=0", old, new).stdout
    return [ln for ln in out.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]


def test_scn_qmd_15_an_answer_is_committed_and_pushed_without_force(qworld, capsys, person):
    two_open(qworld)
    before = qworld.origin_head("a")
    out = written(qworld, capsys, "answer", "Q-002", text="Block login until the address is verified.")
    after = qworld.origin_head("a")
    assert after != before and qworld.tracking("a") == after
    commit = origin_commit(qworld)
    assert commit["P"] == before  # one commit on the fetched head: a fast-forward
    assert commit["s"] == "answer Q-002 (a): Allow it?"
    assert (commit["an"], commit["ae"]) == ("alex", "alex@example.com") == (commit["cn"], commit["ce"])
    assert commit["b"].strip().splitlines() == [
        "Status: answered", "By: alex (person)", "Via: l4 questions", "[skip ci]",
    ]  # fmt: skip
    assert "L4-" not in commit["b"] + commit["s"] and "[skip ci]" in commit["b"]
    changed = diff_lines(qworld, before, after)
    assert sorted(ln for ln in changed if ln.startswith("+")) == sorted(
        [
            "+- **Status:** answered",
            "+Block login until the address is verified.",
            next(ln for ln in changed if ln.startswith("+|") and "Q-002" in ln),
        ]
    )
    assert len([ln for ln in changed if ln.startswith("-")]) <= 3  # the Status line, the row, the old Answer body
    pushed = QuestionsFile.parse(qworld.remote.run_bytes("show", f"{after}:{FOLDER}/a/questions.md"))
    assert pushed.get("Q-002").status is QuestionStatus.ANSWERED
    assert pushed.get("Q-001").status is QuestionStatus.OPEN
    assert f"pushed {after[:10]} to l4/openspec/a: the push starts no run ([skip ci])" in out
    assert out.splitlines()[-1] == f"Next: l4 status --unit {A}"


def test_the_push_is_followed_by_a_run_on_the_base_branch(qworld, capsys, person, forge):
    two_open(qworld)
    forge.script_start_run("started")
    out = written(qworld, capsys, "answer", "Q-002", text="yes")
    assert [c.args for c in forge.called("start_run")] == [("main",)]
    assert "run started on main" in out
    assert out.index("pushed ") < out.index("run started on main") < out.index("Next: l4 status")


@pytest.mark.parametrize("form", ["accept", "answer"])
def test_a_refused_start_prints_how_to_start_a_run_by_hand(qworld, capsys, person, forge, form):
    two_open(qworld)
    forge.script_start_run("refused")
    code = run_form(qworld, form, "Q-001" if form == "accept" else "Q-002", text="yes" if form == "answer" else None)
    out = capsys.readouterr().out
    assert code is ExitCode.OK
    assert "pushed " in out and "start a run with: " in out and "main" in out and "run started" not in out


def test_no_run_starts_nothing(qworld, capsys, person, forge):
    two_open(qworld)
    out = written(qworld, capsys, "answer", "Q-002", text="yes", no_run=True)
    assert forge.called("start_run") == []
    assert "pushed " in out and "no run started (--no-run)" in out and "run started on" not in out


def test_no_push_starts_no_run(qworld, capsys, person, forge):
    two_open(qworld)
    out = written(qworld, capsys, "answer", "Q-002", text="yes", no_push=True)
    assert forge.called("start_run") == [] and "[skip ci]" in out and "run started" not in out


def test_scn_qmd_16_accept_takes_the_clarifier_suggestion(qworld, capsys, person):
    two_open(qworld)
    before = qworld.origin_head("a")
    written(qworld, capsys, "accept", "Q-001")
    commit = origin_commit(qworld)
    assert commit["s"] == "accept Q-001 (a): Which hash?" and "Status: accepted" in commit["b"]
    pushed = QuestionsFile.parse(qworld.remote.run_bytes("show", f"{qworld.origin_head('a')}:{FOLDER}/a/questions.md"))
    q = pushed.get("Q-001")
    assert q.status is QuestionStatus.ACCEPTED and q.answer_text == "" and effective_answer(q) == "Use argon2id."
    assert commit["P"] == before and "| Q-001 | accepted |" in pushed.data.decode()


def test_scn_qmd_17_a_dry_run_writes_nothing(qworld, capsys, person):
    two_open(qworld)
    head = qworld.origin_head("a")
    qworld.clone.run("fetch", "--quiet", "origin")
    local = qworld.clone.run("for-each-ref", "--format=%(refname) %(objectname)").stdout
    objects = qworld.clone.run("count-objects", "-v").stdout
    out = written(qworld, capsys, "answer", "Q-002", text="yes", no_push=True)
    assert "+yes" in out and "answer Q-002 (a): Allow it?" in out and "Status: answered" in out
    assert out.rstrip().endswith("nothing written (--no-push)")
    assert qworld.origin_head("a") == head and qworld.tracking("a") == head  # the fetch set it; the command did not
    assert qworld.clone.run("for-each-ref", "--format=%(refname) %(objectname)").stdout == local
    assert qworld.clone.run("count-objects", "-v").stdout == objects
    assert qworld.clone.run("status", "--porcelain").stdout == ""


def test_the_message_title_is_cut_at_60_characters(qworld, capsys, person):
    long = "T" * 90
    qworld.unit_branch("a", questions_md("a", {"title": long, "tasks": ("2.1",), "suggestion": "Yes."}))
    written(qworld, capsys, "accept", "Q-001")
    assert origin_commit(qworld)["s"] == f"accept Q-001 (a): {'T' * 60}"


def test_the_text_dash_reads_standard_input(qworld, capsys, person, monkeypatch):
    two_open(qworld)

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("sys.stdin", Terminal("from stdin\n"))
    written(qworld, capsys, "answer", "Q-002", text="-")
    pushed = qworld.remote.run_bytes("show", f"{qworld.origin_head('a')}:{FOLDER}/a/questions.md")
    assert QuestionsFile.parse(pushed).get("Q-002").answer_text == "from stdin"


def move_branch_after_fetch(world: QWorld, monkeypatch) -> str:
    """A person pushes to the unit branch after the command fetched it and before it pushed (SCN-QMD-19)."""
    import l4.specs.questions_cli as module

    real = module.fetch_unit_refs
    moved: list[str] = []

    def fetch_then_move(*args, **kwargs):
        real(*args, **kwargs)
        moved.append(world.branch("a", {f"{FOLDER}/a/notes.txt": "a person was here\n"}, "a person's commit"))

    monkeypatch.setattr(module, "fetch_unit_refs", fetch_then_move)
    return moved  # type: ignore[return-value]


def test_scn_qmd_19_a_branch_that_moved_after_the_fetch_is_refused(qworld, person, monkeypatch):
    two_open(qworld)
    moved = move_branch_after_fetch(qworld, monkeypatch)
    with pytest.raises(L4Exit) as caught:
        run_form(qworld, "answer", "Q-002", text="Block login.")
    assert caught.value.code is ExitCode.USAGE_ERROR
    assert str(caught.value).startswith("questions: l4/openspec/a moved since the fetch (now ")
    assert "\nFix: run the command again: it fetches first" in str(caught.value)
    assert qworld.origin_head("a") == moved[0]  # the person's commit is the head, nothing of ours is on origin


def test_a_push_rejected_as_not_a_fast_forward_is_the_same_refusal(qworld, person, monkeypatch):
    import l4.specs.questions_cli as module

    two_open(qworld)
    monkeypatch.setattr(module, "remote_head", lambda *a, **k: qworld.origin_head("a"))  # the check sees no move
    moved = move_branch_after_fetch(qworld, monkeypatch)
    with pytest.raises(L4Exit) as caught:
        run_form(qworld, "answer", "Q-002", text="Block login.")
    assert caught.value.code is ExitCode.USAGE_ERROR and "moved since the fetch" in str(caught.value)
    assert qworld.origin_head("a") == moved[0]


def test_any_other_push_failure_exits_1_with_the_explained_text(qworld, person, monkeypatch):
    import l4.specs.questions_cli as module

    two_open(qworld)
    real = module.fetch_unit_refs

    def fetch_then_break_the_push_url(*args, **kwargs):
        real(*args, **kwargs)
        qworld.clone.run("remote", "set-url", "--push", "origin", str(qworld.root / "nowhere.git"))

    monkeypatch.setattr(module, "fetch_unit_refs", fetch_then_break_the_push_url)
    head = qworld.origin_head("a")
    with pytest.raises(L4Exit) as caught:
        run_form(qworld, "answer", "Q-002", text="Block login.")
    assert caught.value.code is ExitCode.INTERNAL_ERROR
    assert "push of l4/openspec/a to origin failed" in str(caught.value)
    assert qworld.origin_head("a") == head


def test_a_checked_out_unit_branch_is_told_to_pull(qworld, capsys, person):
    two_open(qworld)
    qworld.clone.run("fetch", "--quiet", "origin")
    qworld.clone.run("checkout", "--quiet", "-b", "l4/openspec/a", "origin/l4/openspec/a")
    out = written(qworld, capsys, "answer", "Q-002", text="Block login.")
    assert "your checkout of l4/openspec/a is behind: git pull" in out
    assert qworld.clone.run("status", "--porcelain").stdout == ""  # the work tree was not touched


def test_scn_qmd_21_a_reject_reason_is_accepted_for_a_verdict_question(qworld, capsys, person):
    two_open(qworld)
    written(qworld, capsys, "answer", "Q-003", text="reject: WHEN a THEN b")
    pushed = qworld.remote.run_bytes("show", f"{qworld.origin_head('a')}:{FOLDER}/a/questions.md")
    assert QuestionsFile.parse(pushed).get("Q-003").status is QuestionStatus.ANSWERED


def test_build_edit_changes_only_the_status_the_answer_and_the_row(qworld):
    two_open(qworld)
    app, cfg = load_app_config(qworld.app)
    folders, _ = load_folders(app, cfg, qworld.clone, A)
    edit = build_edit("answer", folders[0], "Q-002", "Block login.\r\nUntil verified.", redactor=app.redactor)
    old, new = edit.old, edit.new
    q = old.get("Q-002")
    assert edit.status is QuestionStatus.ANSWERED and edit.question.id == "Q-002"
    cuts = [
        (q.status_value.start, q.status_value.end),
        (q.answer.body.start, q.answer.body.end),
        (old.index.start, old.index.end),
    ]
    pos, kept = 0, []
    for start, end in sorted(cuts):
        kept.append(old.data[pos:start])
        pos = end
    kept.append(old.data[pos:])
    rest = new.data
    for chunk in kept:
        at = rest.find(chunk)
        assert at >= 0
        rest = rest[at + len(chunk) :]
    assert new.get("Q-002").status is QuestionStatus.ANSWERED
    assert [(x.id, x.status) for x in new.questions if x.id != "Q-002"] == [
        (x.id, x.status) for x in old.questions if x.id != "Q-002"
    ]
    assert new.get("Q-002").answer_text == "Block login.\nUntil verified."


# --- R1, R2, R6: the unit must exist, have a branch, and be waiting for an answer (unfreeze-and-answer 4.6) --------

LIVE = "r-20261016T1100Z-bbbb"


def publish_pending(world: QWorld, tmp_path, *events: tuple[str, dict]) -> None:
    """A run on another machine: its ledger lines are on the lock ref of unit A (`ledger-pending/<run>.jsonl`)."""
    from l4.state.pending import PendingLedger
    from l4.vcs.names import lock_ref

    lines = [
        json.dumps(
            {
                "ts": f"2026-10-16T11:{n:02d}:00.000000Z",
                "run_id": LIVE,
                "unit": A,
                "seq": n,
                "type": kind,
                **data,
            }  # fmt: skip
        )
        for n, (kind, data) in enumerate(events, 1)
    ]
    path = tmp_path / f"{LIVE}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    PendingLedger(world.clone, lock_ref=lock_ref(A), unit=A, run_id=LIVE).publish(path)


@pytest.mark.parametrize("phase", ["merged", "abandoned"])
def test_a_finished_unit_does_not_wait_for_an_answer(qworld, person, phase):
    two_open(qworld)
    qworld.unit_branch(
        "a",
        ledger=ledger_file(A, ("phase.changed", {"from": "in_review", "to": phase, "trigger": "test"})),
    )
    head = qworld.origin_head("a")
    for words, text in ((("accept", "Q-001"), None), (("answer", "Q-002"), "Block login.")):
        with pytest.raises(L4Exit) as caught:
            run_form(qworld, *words, text=text)
        assert caught.value.code is ExitCode.USAGE_ERROR
        assert (
            str(caught.value)
            == f"questions: {A} does not wait for an answer: it is {phase}\nFix: an answer changes nothing"
        )
    assert qworld.origin_head("a") == head


def test_scn_qmd_20_a_live_run_refuses_the_write(qworld, person, tmp_path):
    two_open(qworld)
    publish_pending(qworld, tmp_path, ("run.started", {}))
    head = qworld.origin_head("a")
    with pytest.raises(L4Exit) as caught:
        run_form(qworld, "accept", "Q-001")
    assert caught.value.code is ExitCode.USAGE_ERROR
    assert (
        str(caught.value)
        == f"questions: a run is working on {A} (run {LIVE})\nFix: try again when it ends: l4 ci watch"
    )
    assert qworld.origin_head("a") == head


def test_a_finished_run_does_not_block_the_write(qworld, capsys, person, tmp_path):
    two_open(qworld)
    publish_pending(qworld, tmp_path, ("run.started", {}), ("run.finished", {}))
    assert "pushed" in written(qworld, capsys, "accept", "Q-001")


def test_r1_and_r2_an_unknown_unit_and_a_unit_without_a_branch(qworld, person):
    two_open(qworld)
    with pytest.raises(L4Exit) as caught:
        run_form(qworld, "accept", "Q-001", unit="openspec:nope")
    assert str(caught.value) == "questions: no unit openspec:nope\nFix: l4 status lists the units"
    with pytest.raises(L4Exit) as caught:
        run_form(qworld, "answer", "Q-001", unit=B, text="x")
    assert (
        str(caught.value)
        == f"questions: {B} has no branch on origin: no question was asked yet\nFix: the next run creates it"
    )


def test_the_command_line_reaches_the_handler(qworld, capsys, person):
    from l4.cli import main

    two_open(qworld)
    common = ["--repo", str(qworld.app.repo), "--config", str(qworld.app.config_path)]
    environ = dict(qworld.app.environ)
    assert main(["questions", *common], environ=environ) == 0
    assert f"{A} Q-001" in capsys.readouterr().out
    argv = ["questions", "answer", "Q-002", "--unit", A, "--text", "Block login.", "--no-push", *common]
    assert main(argv, environ=environ) == 0
    assert capsys.readouterr().out.rstrip().endswith("nothing written (--no-push)")


# --- l4 questions answer --replace (L4-QMD-010; SCN-QMD-26, SCN-QMD-27) -----------------------------------------

REJECTED = {
    "title": "Hold H-1234abcd?",
    "kind": "verdict",
    "tasks": (),
    "status": "answered",
    "answer": "reject too long",
}


def replacing(file: QuestionsFile, text: str, qid: str = "Q-001") -> str | None:
    found = check_question(file, qid, "answer", text, unit=A, branch="l4/openspec/a", replace=True)
    return None if found is None else refusal(found)


def test_scn_qmd_27_an_answered_verdict_is_refused_without_the_flag_and_the_fix_names_it():
    file = parsed(REJECTED)
    found = check_question(file, "Q-001", "answer", "accept it", unit=A, branch="l4/openspec/a")
    assert found.message == "Q-001 is answered" and "--replace" in found.fix
    assert f'l4 questions answer Q-001 --unit {A} --text "accept <reason>" --replace' in found.fix
    assert "L4-QMD-006" not in found.fix
    accept = check_question(file, "Q-001", "accept", None, unit=A, branch="b")
    assert accept.message == "Q-001 is answered" and "--replace" in accept.fix
    assert replacing(file, "accept the fix is in") is None


def test_scn_qmd_27_replace_is_refused_for_anything_but_an_answered_verdict_question():
    clarification = parsed({"title": "Done?", "tasks": ("1.1",), "status": "answered", "answer": "yes"})
    assert "a clarification answer is changed by hand" in refusal(check_question(
        clarification, "Q-001", "answer", "no", unit=A, branch="b", replace=True
    ))  # fmt: skip
    assert "L4-QMD-006" in refusal(
        check_question(clarification, "Q-001", "answer", "no", unit=A, branch="b", replace=True)
    )
    open_verdict = parsed({"title": "Verdict?", "kind": "verdict", "tasks": ()})
    assert "answer it without --replace" in replacing(open_verdict, "accept it")
    assert "is not different" in replacing(parsed(REJECTED), "reject too long")
    assert "starts with accept or reject" in replacing(parsed(REJECTED), "looks fine")
    assert "empty" in replacing(parsed(REJECTED), "  ")


def test_replace_also_takes_a_verdict_answered_with_accept():
    """L4-QMD-010: `l4 questions accept` answers a verdict question with the clarifier's suggestion (status
    accepted); that answer is replaced like a written one."""
    accepted = parsed({**REJECTED, "status": "accepted", "answer": "accept as suggested"})
    assert replacing(accepted, "reject the fix is missing") is None


def test_replace_answer_keeps_the_previous_answers_in_comments_the_parser_does_not_read():
    file = parsed({**REJECTED, "answer": "reject too long -->\nsee <!-- x"})
    once = file.replace_answer("Q-001", "accept the fix is in", who="Ana", on="2026-10-16")
    q = once.get("Q-001")
    assert q.status is QuestionStatus.ANSWERED and effective_answer(q) == "accept the fix is in"
    assert q.answer_text == "accept the fix is in" and answer_sha256(q) != answer_sha256(file.get("Q-001"))
    body = once.data.decode()
    assert "l4 questions --replace by Ana on 2026-10-16; previous answer:" in body
    assert "> reject too long --&gt;" in body and "> see &lt;!-- x" in body
    twice = once.replace_answer("Q-001", "reject again", who="Bo", on="2026-10-17")
    again = twice.data.decode()
    assert effective_answer(twice.get("Q-001")) == "reject again"
    assert again.index("by Ana on 2026-10-16") < again.index("by Bo on 2026-10-17")
    assert "> accept the fix is in" in again and "> reject too long" in again
    assert twice.issues == file.issues


def test_replace_answer_keeps_every_other_byte_of_the_file():
    file = parsed(REJECTED, {"title": "Other?", "tasks": ("1.2",)})
    out = file.replace_answer("Q-001", "accept fine", who="Ana", on="2026-10-16")
    assert out.get("Q-002").answer_text == "" and out.get("Q-002").status is QuestionStatus.OPEN
    assert b"| Q-001 | answered |" in out.data and out.data.count(b"## Q-") == file.data.count(b"## Q-")


def verdict_world(world: QWorld) -> None:
    world.unit_branch("a", questions_md("a", REJECTED, {"title": "Done?", "status": "answered", "answer": "yes"}))


def test_scn_qmd_26_a_replaced_answer_is_committed_with_the_old_one_kept(qworld, capsys, person):
    verdict_world(qworld)
    before = qworld.origin_head("a")
    out = written(qworld, capsys, "answer", "Q-001", text="accept the fix is in", replace=True)
    after = qworld.origin_head("a")
    assert after != before and origin_commit(qworld)["P"] == before
    commit = origin_commit(qworld)
    assert commit["s"] == "answer Q-001 (a): Hold H-1234abcd? (answer replaced)"
    assert "Replaced: yes" in commit["b"] and "Status: answered" in commit["b"] and "[skip ci]" in commit["b"]
    pushed = QuestionsFile.parse(qworld.remote.run_bytes("show", f"{after}:{FOLDER}/a/questions.md"))
    q = pushed.get("Q-001")
    assert q.status is QuestionStatus.ANSWERED and effective_answer(q) == "accept the fix is in"
    assert "> reject too long" in pushed.data.decode() and "by alex on " in pushed.data.decode()
    assert pushed.get("Q-002").status is QuestionStatus.ANSWERED
    assert f"pushed {after[:10]} to l4/openspec/a" in out


def test_replace_through_the_command_refuses_the_other_cases_and_touches_nothing(qworld):
    two_open(qworld)  # Q-003 is an open verdict question, Q-004 an answered clarification
    head = qworld.origin_head("a")
    for qid, text, cause in (
        ("Q-004", "no", "a clarification answer is changed by hand"),
        ("Q-003", "accept", "without"),
    ):
        with pytest.raises(L4Exit) as caught:
            run_form(qworld, "answer", qid, text=text, replace=True)
        assert caught.value.code is ExitCode.USAGE_ERROR and cause in str(caught.value)
    assert qworld.origin_head("a") == head
    verdict_world(qworld)
    head = qworld.origin_head("a")
    with pytest.raises(L4Exit) as caught:
        run_form(qworld, "answer", "Q-001", text="accept it")
    assert "--replace" in str(caught.value).split("\nFix: ", 1)[1] and qworld.origin_head("a") == head


def harness_world(world: QWorld) -> None:
    world.unit_branch(
        "a",
        questions_md(
            "a",
            {
                "title": "Task 3.1: the pre-satisfied check could not decide",
                "kind": "harness",
                "tasks": ("3.1",),
                "options": ("accept: count these on the evidence of the real run", "retry: run the check again"),
            },
        ),
    )


def test_scn_imp_316_a_harness_answer_must_start_with_accept_or_retry(qworld, capsys, person):
    harness_world(qworld)
    head = qworld.origin_head("a")
    with pytest.raises(L4Exit) as caught:
        run_questions(qworld.app, words=("answer", "Q-001"), unit=A, text="looks fine", as_json=False, no_push=False)
    assert caught.value.code is ExitCode.USAGE_ERROR
    message = str(caught.value)
    assert "accept" in message and "retry" in message and "\nFix:" in message
    with pytest.raises(L4Exit) as accepted:
        run_questions(qworld.app, words=("accept", "Q-001"), unit=A, text=None, as_json=False, no_push=False)
    assert accepted.value.code is ExitCode.USAGE_ERROR and "retry" in str(accepted.value)
    assert qworld.origin_head("a") == head
    done = run_questions(
        qworld.app, words=("answer", "Q-001"), unit=A, text="accept: the run broke", as_json=False, no_push=False
    )
    assert done is ExitCode.OK
    data = qworld.remote.run_bytes("show", f"{qworld.origin_head('a')}:{FOLDER}/a/questions.md")
    assert QuestionsFile.parse(data).get("Q-001").status is QuestionStatus.ANSWERED


def test_show_names_the_two_answers_of_a_harness_question(qworld, capsys, person):
    harness_world(qworld)
    run_questions(qworld.app, words=("show", "Q-001"), unit=A, text=None, as_json=False, no_push=False)
    out = capsys.readouterr().out
    assert 'l4 questions answer Q-001 --unit openspec:a --text "accept: <why>"' in out
    assert 'l4 questions answer Q-001 --unit openspec:a --text "retry: <note>"' in out


def test_show_offers_only_retry_for_a_harness_question_whose_step_was_not_saved(qworld, capsys, person):
    raised = {"id": "Q-001", "task": "3.1", "kind": "harness", "check": "pre_satisfied", "saved": False}
    qworld.unit_branch(
        "a",
        questions_md(
            "a",
            {
                "title": "Task 3.1: the pre-satisfied check could not decide",
                "kind": "harness",
                "tasks": ("3.1",),
                "options": ("retry: run the check again",),
            },
        ),
        ledger=ledger_file(A, ("question.raised", raised)),
    )
    run_questions(qworld.app, words=("show", "Q-001"), unit=A, text=None, as_json=False, no_push=False)
    out = capsys.readouterr().out
    assert 'l4 questions answer Q-001 --unit openspec:a --text "retry: <note>"' in out
    assert "accept: <why>" not in out


# --- reject-reason (L4-VER-060, SCN-VER-206): a spec gap's reject needs a reason -------------------------------


def gap_question(spec_gap: bool = True, **over) -> dict:
    from l4.verifier.types import Finding, Severity
    from l4.verifier.verdicts import _finding_question

    f = Finding(
        Severity.MAJOR, "Unknown id exits 2", "the code exits 2", "judge", "C-00000001", spec_gap=spec_gap,
        suggested_fix="WHEN the id is unknown THEN the command exits 2" if spec_gap else "",
    )  # fmt: skip
    q = _finding_question(f, 1)
    return {"title": q.title, "kind": "verdict", "tasks": (), "context": q.context, **over}


@pytest.mark.parametrize("text", ["reject", "reject:", "Reject.", "`reject`  ", "reject -"])
def test_a_bare_reject_of_a_spec_gap_question_is_refused(text):
    found = check_question(parsed(gap_question()), "Q-001", "answer", text, unit=A, branch="b")
    assert found.message == "a spec gap's reject needs a reason or a WHEN ... THEN ..."
    assert found.fix == f'l4 questions answer Q-001 --unit {A} --text "reject: <reason>[, then WHEN ... THEN ...]"'
    assert found.exit().code == 2


@pytest.mark.parametrize("text", ["reject: the criterion requires exit 1", "reject WHEN a THEN b", "accept"])
def test_a_reject_with_a_reason_of_a_spec_gap_question_is_accepted(text):
    assert check_question(parsed(gap_question()), "Q-001", "answer", text, unit=A, branch="b") is None


def test_a_bare_reject_of_other_verdict_questions_is_accepted():
    for spec in (
        gap_question(spec_gap=False),
        {"title": "Criterion C-00000001 (x): accept as satisfied?", "kind": "verdict", "tasks": ()},
        {"title": "Hold H-00000001: re-verify?", "kind": "verdict", "tasks": ()},
    ):
        assert check_question(parsed(spec), "Q-001", "answer", "reject", unit=A, branch="b") is None, spec["title"]


def test_the_replace_of_a_spec_gap_answer_by_a_bare_reject_is_refused():
    file = parsed(gap_question(status="answered", answer="reject WHEN a THEN b"))
    found = check_question(file, "Q-001", "answer", "reject", unit=A, branch="b", replace=True)
    assert found is not None and found.message.startswith("a spec gap's reject needs a reason")


def test_a_non_gap_finding_whose_detail_quotes_the_gap_sentence_is_not_refused():
    from l4.verifier.types import Finding, Severity
    from l4.verifier.verdicts import SPEC_GAP_NOTE, _finding_question

    f = Finding(Severity.MAJOR, "Unknown id", f"the judge wrote:{SPEC_GAP_NOTE}", "judge", "C-00000001", spec_gap=False)
    q = _finding_question(f, 1)
    file = parsed({"title": q.title, "kind": "verdict", "tasks": (), "context": q.context})
    assert check_question(file, "Q-001", "answer", "reject", unit=A, branch="b") is None
    gap = parsed(gap_question())
    assert check_question(gap, "Q-001", "answer", "reject", unit=A, branch="b") is not None


def test_a_bare_reject_of_a_spec_gap_with_no_criterion_asks_for_a_scenario():
    from l4.verifier.types import Finding, Severity
    from l4.verifier.verdicts import _finding_question

    f = Finding(Severity.MAJOR, "Unknown id exits 2", "d", "judge", None, spec_gap=True)
    q = _finding_question(f, 1)
    file = parsed({"title": q.title, "kind": "verdict", "tasks": (), "context": q.context})
    found = check_question(file, "Q-001", "answer", "reject", unit=A, branch="b")
    assert found.message == "a spec gap that cites no criterion needs a WHEN ... THEN ..."
    assert "reason or" not in found.message
    assert found.fix == f'l4 questions answer Q-001 --unit {A} --text "reject: <reason>, then WHEN ... THEN ..."'


def test_scn_ver_206_the_answer_command_refuses_a_bare_reject_of_a_spec_gap_and_leaves_the_file(qworld, capsys, person):
    qworld.unit_branch("a", questions_md("a", gap_question()))
    head = qworld.origin_head("a")
    with pytest.raises(L4Exit) as caught:
        run_questions(qworld.app, words=("answer", "Q-001"), unit=A, text="reject", as_json=False, no_push=False)
    assert caught.value.code is ExitCode.USAGE_ERROR and caught.value.code.value == 2
    assert "a spec gap's reject needs a reason or a WHEN ... THEN ..." in str(caught.value)
    assert qworld.origin_head("a") == head
    data = qworld.remote.run_bytes("show", f"{head}:{FOLDER}/a/questions.md")
    assert data.decode() == questions_md("a", gap_question())
    assert QuestionsFile.parse(data).get("Q-001").status is QuestionStatus.OPEN


# --- a fix unit that discover lists as a unit of its own (ci-evidence D13; L4-IMP-081, SCN-IMP-399) ---

FIX = "openspec:a-fix-1"


def listed_fix_unit(world: QWorld) -> None:
    """The fix unit's questions are on the parent's branch, and the fix unit is also a unit of the working tree."""
    world.unit_branch(
        "a",
        extra={
            f"{FOLDER}/a-fix-1/tasks.md": "## 1. Fix\n\n- [ ] 1.1 Fix it\n",
            f"{FOLDER}/a-fix-1/questions.md": questions_md(
                "a-fix-1", {"title": "Fix which?", "tasks": ("1.1",), "suggestion": "Use argon2id."}
            ),
        },
    )
    world.sim.human_commit(unit_files("a-fix-1"), "the fix unit is a change of the base too")
    world.clone.run("pull", "--quiet", "--ff-only", "origin", "main")


def test_show_and_accept_find_a_fix_units_question(qworld, capsys, person):
    listed_fix_unit(qworld)
    code, out = shown(qworld, capsys, "Q-001", unit=FIX)
    assert code is ExitCode.OK and "## Q-001: Fix which?" in out and "has no branch" not in out
    code = run_questions(qworld.app, words=("accept", "Q-001"), unit=FIX, text=None, as_json=False, no_push=False)
    assert code is ExitCode.OK
    pushed = qworld.remote.run_bytes("show", f"{qworld.origin_head('a')}:{FOLDER}/a-fix-1/questions.md")
    assert QuestionsFile.parse(pushed).get("Q-001").status is QuestionStatus.ACCEPTED


def test_the_parent_unit_shows_its_own_questions_not_the_fix_units(qworld, capsys):
    listed_fix_unit(qworld)
    with pytest.raises(L4Exit) as caught:
        shown(qworld, capsys, "Q-001", unit=A)
    assert "no Q-001" in str(caught.value) or "has no questions.md" in str(caught.value)


def test_a_fix_unit_without_a_folder_on_the_parent_branch_is_no_unit(qworld, capsys):
    qworld.unit_branch("a", questions_md("a", {"title": "Own?", "tasks": ("1.1",)}))
    with pytest.raises(L4Exit) as caught:
        shown(qworld, capsys, "Q-001", unit="openspec:a-fix-9")
    assert "no unit openspec:a-fix-9" in str(caught.value)


def test_a_unit_named_like_a_fix_unit_without_a_branch_keeps_the_no_branch_warning(qworld, capsys):
    """review: `a-fix-1` is a unit of the base here, `a` has a branch without that folder: the old warning, not
    "no unit"."""
    qworld.unit_branch("a", questions_md("a", {"title": "Own?", "tasks": ("1.1",)}))  # cut before the base got a-fix-1
    qworld.sim.human_commit(unit_files("a-fix-1"), "a change that is named like a fix unit")
    qworld.clone.run("pull", "--quiet", "--ff-only", "origin", "main")
    code, out = listed(qworld, capsys, unit=FIX)
    assert code is ExitCode.OK
    assert f"{FIX} has no branch on origin" in out and "no open question" in out


class KiroQWorld(QWorld):
    """The `kiro-basic` repository: the unit `kiro:user-greeting` whose specs are `.kiro/specs/<name>/`."""

    def __init__(self, tmp_path) -> None:
        from pathlib import Path

        import yaml

        from l4.sim.builtin.manifest import scenario_text
        from l4.sim.remote import SimRepo
        from l4.sim.runner import CONFIG_FILE, sim_app, sim_config
        from l4.sim.scenarios import load_scenario
        from l4.vcs.git import Git

        self.sim = SimRepo.create("kiro-basic", root=Path(tmp_path) / "world")
        root = self.sim.root.resolve()
        config = sim_config(load_scenario(scenario_text("happy-kiro"), source="happy-kiro.yaml"))
        (root / CONFIG_FILE).write_text(yaml.safe_dump(config), encoding="utf-8")
        self.root, self.app = root, sim_app(root)
        self.clone = Git(self.app.repo, environ=self.app.environ)
        self.clone.run("config", "user.name", "alex")
        self.clone.run("config", "user.email", "alex@example.com")
        self.remote = Git(self.sim.remote, environ=self.app.environ)

    def kiro_branch(self, files: dict[str, str]) -> str:
        return self.sim.human_commit(files, "branch of user-greeting", branch="l4/kiro/user-greeting")


def test_a_kiro_fix_units_questions_resolve_to_its_parents_branch(tmp_path, capsys):
    """review (D13 on the Kiro layout): the fix unit's folder `.kiro/specs/user-greeting-fix-1/` is on the parent's
    branch, and the fix unit is also a unit of the base."""
    world = KiroQWorld(tmp_path)
    fix = "kiro:user-greeting-fix-1"
    folder = ".kiro/specs/user-greeting-fix-1"
    questions = questions_md("user-greeting-fix-1", {"title": "Fix which?", "tasks": ("1.1",)})
    world.kiro_branch({f"{folder}/tasks.md": "## 1. Fix\n\n- [ ] 1.1 Fix it\n", f"{folder}/questions.md": questions})
    world.sim.human_commit(
        {f"{folder}/requirements.md": "# fix\n", f"{folder}/design.md": "# d\n", f"{folder}/tasks.md": "- [ ] 1.1 x\n"},
        "the fix unit is a spec of the base too",
    )
    world.clone.run("pull", "--quiet", "--ff-only", "origin", "main")
    code, out = shown(world, capsys, "Q-001", unit=fix)
    assert code is ExitCode.OK and "## Q-001: Fix which?" in out and "has no branch" not in out
    code, out = listed(world, capsys, unit="kiro:user-greeting")
    assert "kiro:user-greeting-fix-1 Q-001" in out


# --- L4-QMD-011: an answer while a run works says which run takes it (SCN-QMD-31) -----------------------------------

LINK = "<forge>/group/project/-/jobs/9"
STARTED = datetime(2026, 10, 16, 10, 1, tzinfo=UTC)  # `ledger_file`'s first line


class CiForge:
    def __init__(self, state: tuple[str, str] = ("running", ""), fail: bool = False) -> None:
        self.state, self.fail, self.calls = state, fail, []

    def ci_run_state(self, ci_url: str) -> tuple[str, str]:
        assert not self.fail, "the forge must not be asked"
        self.calls.append(ci_url)
        return self.state


def open_run_world(world: QWorld, monkeypatch, *, minutes: int = 7, forge=None, **started) -> CiForge:
    """Unit A's branch ledger has the `run.started` of `l4 run` of RUN and no end; the clock is `minutes` later."""
    fake = forge or CiForge()
    data = {"command": "run", "ci_url": LINK, "job_timeout_s": 10800, **started}
    two_open(world)
    world.unit_branch("a", ledger=ledger_file(A, ("run.started", data)))
    monkeypatch.setattr("l4.specs.questions_cli._now", lambda: STARTED + timedelta(minutes=minutes))
    monkeypatch.setattr("l4.specs.questions_cli.make_forge", lambda cfg, environ, **kwargs: fake)
    return fake


def info_line(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("[l4] questions:")]


def test_scn_qmd_31_an_answer_during_a_run_names_the_run(qworld, capsys, person, monkeypatch):
    fake = open_run_world(qworld, monkeypatch)
    before = qworld.origin_head("a")
    out = written(qworld, capsys, "answer", "Q-002", text="Block login until the address is verified.")
    assert qworld.origin_head("a") != before and "pushed" in out  # the write is what it was
    assert info_line(out) == [
        f"[l4] questions: run {RUN} works on {A} (started 7 min ago): "
        "it takes this answer at its next push, or the next run does"
    ]
    assert out.splitlines().index(info_line(out)[0]) == 1  # after the command's own line
    assert fake.calls == [LINK]


def test_an_accept_says_it_too(qworld, capsys, person, monkeypatch):
    open_run_world(qworld, monkeypatch, minutes=1)
    out = written(qworld, capsys, "accept", "Q-001")
    assert info_line(out) == [
        f"[l4] questions: run {RUN} works on {A} (started 1 min ago): "
        "it takes this answer at its next push, or the next run does"
    ]


def test_no_open_run_no_line(qworld, capsys, person, monkeypatch):
    two_open(qworld)
    assert info_line(written(qworld, capsys, "accept", "Q-001")) == []
    open_run_world(qworld, monkeypatch)
    qworld.unit_branch(
        "a", ledger=ledger_file(A, ("run.started", {"command": "run", "ci_url": LINK}), ("run.finished", {}))
    )
    assert info_line(written(qworld, capsys, "answer", "Q-002", text="Block login.")) == []


def test_a_run_older_than_its_job_timeout_is_not_named_and_the_forge_is_not_asked(qworld, capsys, person, monkeypatch):
    fake = open_run_world(qworld, monkeypatch, minutes=180 + 6, forge=CiForge(fail=True))
    assert info_line(written(qworld, capsys, "accept", "Q-001")) == []
    assert fake.calls == []


def test_when_the_forge_cannot_be_asked_the_age_decides(qworld, capsys, person, monkeypatch):
    from l4.forge.base import ForgeUnavailable

    open_run_world(qworld, monkeypatch)

    def no_token(cfg, environ, **kwargs):
        raise ForgeUnavailable("L4_FORGE_TOKEN is not set")

    monkeypatch.setattr("l4.specs.questions_cli.make_forge", no_token)
    assert len(info_line(written(qworld, capsys, "accept", "Q-001"))) == 1  # young: still working


def test_a_run_whose_ci_run_the_forge_calls_completed_is_not_named(qworld, capsys, person, monkeypatch):
    open_run_world(qworld, monkeypatch, forge=CiForge(("completed", "cancelled")))
    assert info_line(written(qworld, capsys, "accept", "Q-001")) == []


def test_a_forge_that_fails_while_asked_leaves_the_age_to_decide_and_never_fails_the_command(
    qworld, capsys, person, monkeypatch
):
    class Broken(CiForge):
        def ci_run_state(self, ci_url):
            raise RuntimeError("boom")

    open_run_world(qworld, monkeypatch, forge=Broken())
    assert len(info_line(written(qworld, capsys, "accept", "Q-001"))) == 1


def test_a_dry_run_writes_nothing_and_says_nothing_about_a_run(qworld, capsys, person, monkeypatch):
    open_run_world(qworld, monkeypatch)
    out = written(qworld, capsys, "accept", "Q-001", no_push=True)
    assert info_line(out) == [] and out.rstrip().endswith("nothing written (--no-push)")


def test_the_info_line_does_not_replace_the_pending_ledger_refusal_of_scn_qmd_20(qworld, person, tmp_path, monkeypatch):
    open_run_world(qworld, monkeypatch)
    publish_pending(qworld, tmp_path, ("run.started", {}))
    with pytest.raises(L4Exit) as caught:
        run_form(qworld, "accept", "Q-001")
    assert str(caught.value).startswith(f"questions: a run is working on {A} (run {LIVE})")


def test_a_run_without_a_ci_link_is_named_while_young_and_not_after_the_default_job_timeout(
    qworld, capsys, person, monkeypatch
):
    """Review fix 8: a local run that died has no CI run to ask about; only for this line, the age against the default
    job timeout plus the grace ends it (`l4 yolo status` keeps its rule)."""
    fake = open_run_world(qworld, monkeypatch, ci_url=None, job_timeout_s=None, forge=CiForge(fail=True))
    assert len(info_line(written(qworld, capsys, "accept", "Q-001"))) == 1
    assert fake.calls == []  # no link, nothing to ask
    monkeypatch.setattr("l4.specs.questions_cli._now", lambda: STARTED + timedelta(minutes=180 + 6))
    assert info_line(written(qworld, capsys, "answer", "Q-002", text="Block login.")) == []


# --- a verdict question that no round of this attempt raised is stale (L4-VER-070, SCN-VER-259) ---------------------

STALE = "stale: raised by an earlier attempt; the next round asks again"
VERDICT_ANSWERED = {
    "title": "Criterion C-aaaaaaaa (x): accept as satisfied?", "kind": "verdict", "tasks": (),
    "status": "answered", "answer": "accept: fine",
}  # fmt: skip


def stale_world(world: QWorld, *, raised: tuple[str, ...] = ()) -> None:
    """Q-001: an answered verdict question; Q-002: an open verdict question; Q-003: an open technical one. The ledger
    holds a `question.raised{kind: verdict}` for each id in `raised` only."""
    verdict = {**VERDICT_ANSWERED, "status": "open", "answer": ""}
    events = [("question.raised", {"id": q, "kind": "verdict", "round": 1}) for q in raised]
    world.unit_branch(
        "a",
        questions_md("a", VERDICT_ANSWERED, verdict, {"title": "Which port?", "kind": "technical", "tasks": ("1.1",)}),
        ledger=ledger_file(A, *events, ("question.raised", {"id": "Q-003", "kind": "technical"})),
    )


def test_list_marks_a_stale_verdict_question_answered_or_open_and_points_at_a_live_one(qworld, capsys):
    stale_world(qworld)
    code, out = listed(qworld, capsys)
    lines = out.splitlines()
    assert code is ExitCode.OK
    at = lines.index(f"{A} Q-001 stale none {VERDICT_ANSWERED['title']}")  # answered, yet listed: it is stale
    assert lines[at + 1].strip() == STALE
    assert f"{A} Q-002 stale none {VERDICT_ANSWERED['title']}" in lines
    assert any(line.startswith(f"{A} Q-003 technical 1.1 ") for line in lines)
    assert lines[-1] == f"Next: l4 questions show Q-003 --unit {A}"  # a stale one is not what to answer next


def test_list_shows_a_verdict_question_that_this_attempt_raised_as_it_always_did(qworld, capsys):
    stale_world(qworld, raised=("Q-001", "Q-002"))
    _, out = listed(qworld, capsys)
    assert STALE not in out and f"{A} Q-001" not in out  # answered: not listed
    assert f"{A} Q-002 verdict none {VERDICT_ANSWERED['title']}" in out.splitlines()


def test_list_json_has_a_stale_field(qworld, capsys):
    stale_world(qworld)
    _, out = listed(qworld, capsys, as_json=True)
    rows = {q["id"]: q for q in json.loads(out)["questions"]}
    assert {i: (q["stale"], q["status"]) for i, q in rows.items()} == {
        "Q-001": (True, "answered"), "Q-002": (True, "open"), "Q-003": (False, "open"),
    }  # fmt: skip
    assert rows["Q-001"]["note"] == STALE and "note" not in rows["Q-003"]
    assert json.loads(out)["next"] == f"l4 questions show Q-003 --unit {A}"


def test_list_does_not_call_a_verdict_question_stale_when_the_ledger_cannot_be_read(qworld, capsys):
    stale_world(qworld)
    qworld.unit_branch("a", ledger="{bad\n" + ledger_file(A, ("question.raised", {"id": "Q-003", "kind": "technical"})))
    _, out = listed(qworld, capsys)
    [warning] = [line for line in out.splitlines() if "the ledger cannot be read" in line]
    assert warning.startswith(f"warning: {A}: the ledger cannot be read (") and warning.count(f"{A}:") == 1
    assert warning.endswith("no question is marked stale") and "frozen" not in warning and STALE not in out


def test_show_marks_a_stale_verdict_question(qworld, capsys, person):
    stale_world(qworld, raised=("Q-002",))
    _, out = shown(qworld, capsys, "Q-001")
    assert STALE in out
    _, out = shown(qworld, capsys, "Q-002")
    assert STALE not in out
    _, out = shown(qworld, capsys, "Q-001", as_json=True)
    doc = json.loads(out)
    assert doc["stale"] is True and doc["note"] == STALE
    assert json.loads(shown(qworld, capsys, "Q-002", as_json=True)[1])["stale"] is False
    assert json.loads(shown(qworld, capsys, "Q-003", as_json=True)[1])["stale"] is False


def test_answering_a_stale_question_prints_one_info_line(qworld, capsys, person):
    stale_world(qworld, raised=("Q-001",))  # Q-002 is the open verdict question no ledger event names
    out = written(qworld, capsys, "answer", "Q-002", text="accept: fine", no_push=True)
    line = "Q-002 is stale: raised by an earlier attempt; the next round asks its criterion again"
    assert out.splitlines().count(line) == 1
    out = written(qworld, capsys, "answer", "Q-003", text="8080", no_push=True)  # a live question: no such line
    assert "is stale" not in out


def test_show_with_an_unreadable_ledger_names_what_is_not_shown(qworld, capsys, person):
    stale_world(qworld)
    qworld.unit_branch("a", ledger="{bad\n" + ledger_file(A, ("question.raised", {"id": "Q-003", "kind": "technical"})))
    _, out = shown(qworld, capsys, "Q-002")
    [warning] = [line for line in out.splitlines() if "the ledger cannot be read" in line]
    assert warning.count(f"{A}:") == 1 and warning.endswith("no frozen path or stale mark is shown")


def test_list_does_not_show_a_stale_verdict_question_that_a_new_one_superseded(qworld, capsys):
    """The round that asked the target again set Q-001 to `superseded by Q-002` (L4-VER-070): not listed, not stale."""
    text = questions_md("a", {**VERDICT_ANSWERED, "status": "superseded"}, {**VERDICT_ANSWERED, "status": "open"})
    qworld.unit_branch(
        "a",
        text.replace("- **Status:** superseded\n", "- **Status:** superseded by Q-002\n", 1),
        ledger=ledger_file(A, ("question.raised", {"id": "Q-002", "kind": "verdict", "round": 2})),
    )
    _, out = listed(qworld, capsys, as_json=True)
    assert [(q["id"], q["stale"]) for q in json.loads(out)["questions"]] == [("Q-002", False)]
    _, text = listed(qworld, capsys)
    assert STALE not in text and f"{A} Q-001" not in text


REPAIR_REASON = "a repair of a test is a person's decision"


def test_the_agent_rule_refuses_a_repair_question_whatever_the_key_says():  # SCN-IMP-473
    harness = parsed({"title": "H?", "kind": "harness", "tasks": ("1.1",)}).get("Q-001")
    opened = ClarifierRules(("technical",), True)
    for rules in (RULES, opened):
        assert agent_reason(harness, None, {}, rules, raise_check="repair") == REPAIR_REASON
        assert agent_reason(harness, "accept: x", {}, rules, raise_check="repair") == REPAIR_REASON
    found = check_agent("accept", harness, "accept: x", {}, opened, "main", raise_check="repair")
    assert found.message == f"an agent may not accept Q-001: {REPAIR_REASON}"
    assert "answer_by_agents" not in found.fix and "a person runs the command" in found.fix  # no key helps


def test_the_other_harness_checks_keep_the_agent_rule():
    harness = parsed({"title": "H?", "kind": "harness", "tasks": ("1.1",)}).get("Q-001")
    opened = ClarifierRules(("technical",), True)
    for check in (None, "pre_satisfied", "vacuity", "at_red", "tests"):
        assert agent_reason(harness, None, {}, opened, raise_check=check) is None, check
        assert agent_reason(harness, None, {}, RULES, raise_check=check) == "a harness override is a person's decision"
    technical = parsed({"title": "T?", "tasks": ("1.1",)}).get("Q-001")
    assert agent_reason(technical, "x", {}, RULES, raise_check="repair") is None  # only a harness question
