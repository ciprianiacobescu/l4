"""`l4 questions` reading, showing and editing (unfreeze-and-answer 4.2 to 4.4; L4-QMD-007, L4-QMD-008)."""

import dataclasses
import json

import pytest

from l4.config.redaction import load_app_config
from l4.exitcodes import ExitCode, L4Exit
from l4.redact import Redactor
from l4.specs.questions import QuestionsFile, QuestionStatus, effective_answer
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
    A,
    B,
    QWorld,
    ledger_file,
    questions_md,
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


def run_form(world: QWorld, *words: str, unit: str | None = A, text: str | None = None, no_push: bool = False):
    return run_questions(world.app, words=words, unit=unit, text=text, as_json=False, no_push=no_push)


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


def test_a_valid_edit_is_built_and_the_write_is_not_yet_there(qworld):
    two_open(qworld)
    with pytest.raises(NotImplementedError, match="4.5"):
        run_form(qworld, "answer", "Q-002", text="Block login until verified.")
    with pytest.raises(NotImplementedError, match="4.5"):
        run_form(qworld, "accept", "Q-001")


def test_scn_qmd_21_a_reject_reason_is_accepted_for_a_verdict_question(qworld):
    two_open(qworld)
    with pytest.raises(NotImplementedError):
        run_form(qworld, "answer", "Q-003", text="reject: WHEN a THEN b")


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
