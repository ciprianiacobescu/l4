"""`l4 questions` reading, showing and editing (unfreeze-and-answer 4.2 to 4.4; L4-QMD-007, L4-QMD-008)."""

import dataclasses
import json

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.specs.questions_cli import run_questions

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
