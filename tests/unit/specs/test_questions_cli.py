"""`l4 questions` reading, showing and editing (unfreeze-and-answer 4.2 to 4.4; L4-QMD-007, L4-QMD-008)."""

import json

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.specs.questions_cli import run_questions

from .questions_world import (
    FOLDER,
    A,
    B,
    QWorld,
    questions_md,
    qworld,  # noqa: F401  (fixture)
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


def test_scn_qmd_12_lists_the_open_questions_of_every_unit_branch(qworld, capsys):  # noqa: F811
    two_units(qworld)
    assert not (qworld.app.repo / FOLDER / "a" / "questions.md").exists()  # the checkout has none: the branch is read
    code, out = listed(qworld, capsys)
    assert code is ExitCode.OK
    assert f"{A} Q-002 product 3.1 Allow unverified?" in out
    assert f"{B} Q-001 draft 1.1 Which port?" in out
    assert f"{A} Q-001" not in out
    assert out.splitlines()[-1] == f"Next: l4 questions show Q-002 --unit {A}"


def test_list_alias_unit_filter_and_json(qworld, capsys):  # noqa: F811
    two_units(qworld)
    code, out = listed(qworld, capsys, words=("list",), unit=B, as_json=True)
    doc = json.loads(out)
    assert code is ExitCode.OK and doc["schema"] == "l4/questions@1"
    assert [(q["unit"], q["id"], q["kind"], q["draft"], q["blocking"]) for q in doc["questions"]] == [
        (B, "Q-001", "technical", True, ["1.1"])
    ]
    assert doc["next"] == f"l4 questions show Q-001 --unit {B}"


def test_no_open_question_and_a_unit_without_a_branch(qworld, capsys):  # noqa: F811
    code, out = listed(qworld, capsys)
    assert code is ExitCode.OK and out.strip() == "no open question"
    code, out = listed(qworld, capsys, unit=A)
    assert code is ExitCode.OK and f"{A} has no branch on origin" in out and "no open question" in out


def test_an_unknown_unit_is_refused(qworld, capsys):  # noqa: F811
    with pytest.raises(L4Exit) as caught:
        listed(qworld, capsys, unit="openspec:nope")
    assert caught.value.code is ExitCode.USAGE_ERROR
    assert str(caught.value).startswith("questions: no unit openspec:nope")
    assert "Fix: l4 status lists the units" in str(caught.value)


def test_scn_qmd_14_a_fix_unit_is_listed_under_its_parent(qworld, capsys):  # noqa: F811
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


def test_a_failed_fetch_reads_the_refs_that_exist_and_warns(qworld, capsys):  # noqa: F811
    two_units(qworld)
    listed(qworld, capsys)  # the first run fetches
    qworld.unit_branch("a", questions_md("a", {"title": "Pushed later?", "tasks": ("2.1",)}))
    qworld.break_origin()
    code, out = listed(qworld, capsys)
    assert code is ExitCode.OK
    assert "warning: not fetched (" in out and "the questions may be old" in out
    assert f"{A} Q-002 product 3.1 Allow unverified?" in out  # the tracking ref the first run fetched
    assert "Pushed later?" not in out


def test_a_symlinked_questions_file_is_not_read(qworld, capsys):  # noqa: F811
    qworld.symlinked_questions("a")
    code, out = listed(qworld, capsys)
    assert code is ExitCode.OK
    assert f"warning: {A}: questions.md is a symlink on l4/openspec/a" in out


def test_an_oversized_questions_file_is_not_read(qworld, capsys):  # noqa: F811
    big = questions_md("a", {"title": "Big?"}) + "x" * (2 * 1024 * 1024)
    qworld.unit_branch("a", big)
    code, out = listed(qworld, capsys)
    assert code is ExitCode.OK
    assert f"warning: {A}: questions.md is larger than 2 MiB on l4/openspec/a" in out
    assert "Big?" not in out


def test_an_unreadable_section_gives_one_warning_line(qworld, capsys):  # noqa: F811
    text = questions_md("a", {"title": "Fenced?"}, {"title": "Hidden?"})
    text = text.replace("### Context\n", "### Context\n```\n", 1).replace("---\n\n## Q-002", "## Q-002", 1)
    qworld.unit_branch("a", text)
    code, out = listed(qworld, capsys)
    assert code is ExitCode.OK
    assert [line for line in out.splitlines() if line.startswith("warning:")] == [
        f"warning: {A} Q-002: the section cannot be read: it holds every pending task"
    ]
