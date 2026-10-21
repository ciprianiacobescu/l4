"""delegate-answers 4.2: the edit core of `l4 questions` works on the run's worktree (L4-DLG-006, SCN-DLG-38)."""

from pathlib import Path

import pytest

from l4.config.redaction import load_app_config
from l4.exitcodes import ExitCode, L4Exit
from l4.redact import Redactor
from l4.specs.questions_cli import (
    DelegateMark,
    Folder,
    _dry_run,
    build_edit,
    commit_message,
    folder_from_worktree,
    load_folders,
)

from .questions_world import FOLDER, A, QWorld, questions_md
from .test_questions_cli import person, run_form, written  # noqa: F401  (the fixtures and helpers of the CLI tests)

BRANCH = "l4/openspec/a"
MARK = DelegateMark(model="claude-opus-5-5", cli="claude-code", profile="delegate-opus")


def open_one(world: QWorld, **over: object) -> None:
    world.unit_branch("a", questions_md("a", {"title": "Which hash?", "tasks": ("2.1",), **over}))


def worktree(world: QWorld, tmp_path: Path) -> Path:
    world.clone.run("fetch", "--quiet", "origin")
    where = tmp_path / "run-worktree"
    world.clone.run("worktree", "add", "--quiet", "--detach", str(where), f"refs/remotes/origin/{BRANCH}")
    return where


def folder_of(world: QWorld, where: Path) -> Folder:
    return folder_from_worktree(world.clone, where, A, f"{FOLDER}/a", f"{FOLDER}/a", BRANCH, "implementing", None)


def test_a_folder_from_the_worktree(qworld, tmp_path):
    open_one(qworld)
    where = worktree(qworld, tmp_path)
    folder = folder_of(qworld, where)
    head = qworld.tracking("a")
    assert folder.head == head and folder.unit == A and folder.parent == A and folder.fix is None
    assert folder.rel == f"{FOLDER}/a" and folder.ledger_rel == f"{FOLDER}/a" and folder.branch == BRANCH
    assert folder.file is not None and folder.file.get("Q-001") is not None and folder.problem is None
    loaded, _ = load_folders(qworld.app, _cfg(qworld), qworld.clone, A, fetch=False)
    assert loaded[0].file is not None and loaded[0].file.data == folder.file.data
    # HEAD moves: the folder reads the commit the worktree stands on, not the branch
    (where / FOLDER / "a" / "questions.md").write_text("changed\n")
    qworld.clone.at(where).run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qam", "edit")
    assert folder_of(qworld, where).head == qworld.clone.at(where).rev_parse("HEAD") != head


def test_a_fix_unit_folder_names_its_parent(qworld, tmp_path):
    open_one(qworld)
    where = worktree(qworld, tmp_path)
    folder = folder_from_worktree(
        qworld.clone, where, "openspec:a-fix-1", f"{FOLDER}/a-fix-1", f"{FOLDER}/a", BRANCH, "implementing", "a-fix-1"
    )
    assert folder.parent == A and folder.fix == "a-fix-1" and folder.ledger_rel == f"{FOLDER}/a"
    assert folder.file is None and folder.problem is None


def _cfg(world: QWorld):
    return load_app_config(world.app)[1]


def test_the_delegate_edit_equals_the_cli_edit(qworld, tmp_path, capsys, person):  # noqa: F811
    open_one(qworld, suggestion="Use argon2id.")
    where = worktree(qworld, tmp_path)
    folder = folder_of(qworld, where)
    edit = build_edit("answer", folder, "Q-001", "Use bcrypt with cost 12.", redactor=Redactor({}))
    out = written(qworld, capsys, "answer", "Q-001", text="Use bcrypt with cost 12.", no_push=True)
    expected = _dry_run(edit, commit_message(edit, "alex", "person", None))
    assert out.strip() == expected.strip()


def test_commit_message_names_the_delegate(qworld, tmp_path):
    open_one(qworld)
    folder = folder_of(qworld, worktree(qworld, tmp_path))
    edit = build_edit("answer", folder, "Q-001", "Use bcrypt.", redactor=Redactor({}))
    message = commit_message(edit, "alex", "delegate", None, mark=MARK)
    assert message == (
        "answer Q-001 (a): Which hash?\n\nStatus: answered\n"
        "By: delegate (claude-opus-5-5 via claude-code; profile delegate-opus)\nVia: l4 delegate\n[skip ci]\n"
    )
    assert commit_message(edit, "alex", "person", None) == (
        "answer Q-001 (a): Which hash?\n\nStatus: answered\nBy: alex (person)\nVia: l4 questions\n[skip ci]\n"
    )
    assert commit_message(edit, "alex", "agent", "CLAUDECODE") == (
        "answer Q-001 (a): Which hash?\n\nStatus: answered\n"
        "By: alex (agent: CLAUDECODE)\nVia: l4 questions\n[skip ci]\n"
    )


def test_a_draft_refuses_the_delegate(qworld, tmp_path):  # SCN-DLG-38
    qworld.unit_branch("a", questions_md("a", {"title": "Which hash?", "tasks": ("2.1",), "answer": "my draft"}))
    folder = folder_of(qworld, worktree(qworld, tmp_path))
    with pytest.raises(L4Exit) as caught:
        build_edit("answer", folder, "Q-001", "Use bcrypt.", redactor=Redactor({}))
    assert caught.value.code is ExitCode.USAGE_ERROR
    assert "Q-001 has a draft answer under Status open" in str(caught.value)
