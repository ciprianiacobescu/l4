"""unfreeze-option-form 2.2 (L4-QMD-008, SCN-QMD-29, SCN-QMD-30): an open technical question with no clarifier
suggestion takes option 1 as what `accept` writes, shows and checks."""

import dataclasses
import hashlib
import json
from datetime import UTC, datetime

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.implementer.guards import FreezeManifest, FrozenFile
from l4.implementer.unfreeze import unfrozen
from l4.redact import Redactor
from l4.specs.questions import (
    QuestionsFile,
    QuestionStatus,
    accept_text,
    answer_sha256,
    effective_answer,
    is_answered,
)
from l4.specs.questions_cli import (
    PathEffect,
    build_edit,
    check_question,
    edit_accept,
    round_trip,
    run_questions,
    suggestion_effects,
)
from l4.state.ledger import LedgerEvent

from .questions_world import FOLDER, A, QWorld, ledger_file, questions_md
from .test_questions_cli import person, shown, written  # noqa: F401  (the fixtures and helpers of the CLI tests)
from .test_questions_edit_core import folder_of, open_one, worktree

TAKEN = "Edit `src/app.test.ts`: seed the issued secret"
SHAPE = {
    "title": "The frozen test seeds nothing?",
    "kind": "technical",
    "tasks": ("2.1",),
    "context": "The frozen test reads a secret nobody issued.\n\nHarness note: a frozen test opens through `accepted`.",
    "options": ("Edit src/app.test.ts: seed the issued secret", "Edit `src/other.test.ts`: read it from the config"),
}
RED = ("task.red_ok", {"task": "2.1", "base": "abc", "frozen": ["src/app.test.ts", "conftest.py"]})


def pushed(world: QWorld) -> QuestionsFile:
    return QuestionsFile.parse(world.remote.run_bytes("show", f"{world.origin_head('a')}:{FOLDER}/a/questions.md"))


def test_scn_qmd_29_build_edit_accept_writes_the_block_and_the_question_reads_back_answered(qworld, tmp_path):
    open_one(qworld, **{k: v for k, v in SHAPE.items() if k not in ("title", "tasks")})
    folder = folder_of(qworld, worktree(qworld, tmp_path))
    assert folder.file.get("Q-001").suggestion is None
    edit = build_edit("accept", folder, "Q-001", None, redactor=Redactor({}))
    read_back = edit.new.get("Q-001")
    assert edit.old.data == folder.file.data  # the bytes on the branch
    assert read_back.status is QuestionStatus.ACCEPTED and read_back.answer_text == ""
    assert read_back.suggestion_text == TAKEN
    assert effective_answer(read_back) == TAKEN and is_answered(read_back)
    assert answer_sha256(read_back) == hashlib.sha256(TAKEN.encode("utf-8")).hexdigest()
    data = edit.new.data.decode()
    assert data.index("### Clarifier suggestion") < data.index("### Answer", data.index("## Q-001"))
    assert "| Q-001 | accepted |" in data
    before = folder.file.data.decode()
    restored = data.replace(f"### Clarifier suggestion\n{TAKEN}\n\n", "")
    restored = restored.replace("- **Status:** accepted", "- **Status:** open").replace("| accepted |", "| open |")
    assert restored == before  # only the block, the Status value and the index row differ


def test_build_edit_accept_changes_no_other_question(qworld, tmp_path):
    qworld.unit_branch(
        "a",
        questions_md(
            "a", {"title": "One?", "tasks": ("1.1",), "options": ("Edit src/a.py: x",)}, {**SHAPE, "title": "Two?"}
        ),
    )
    folder = folder_of(qworld, worktree(qworld, tmp_path))
    edit = build_edit("accept", folder, "Q-002", None, redactor=Redactor({}))
    assert edit.new.get("Q-001").suggestion is None and edit.new.get("Q-001").status is QuestionStatus.OPEN
    assert edit.new.get("Q-002").status is QuestionStatus.ACCEPTED


def test_scn_qmd_30_a_written_suggestion_is_taken_as_it_is_and_never_replaced(qworld, tmp_path):
    open_one(qworld, **{k: v for k, v in SHAPE.items() if k not in ("title", "tasks")}, suggestion="Take option 2")
    folder = folder_of(qworld, worktree(qworld, tmp_path))
    assert accept_text(folder.file.get("Q-001")) == "Take option 2"
    edit = build_edit("accept", folder, "Q-001", None, redactor=Redactor({}))
    assert edit.new.get("Q-001").suggestion_text == "Take option 2"
    assert edit.new.data.decode().count("### Clarifier suggestion") == 1
    assert effective_answer(edit.new.get("Q-001")) == "Take option 2"


def test_an_empty_written_block_is_not_replaced_either(qworld, tmp_path):
    qworld.unit_branch("a", questions_md("a", {**SHAPE, "suggestion": "(empty)"}), ledger=ledger_file(A, RED))
    folder = folder_of(qworld, worktree(qworld, tmp_path))
    edit = build_edit("accept", folder, "Q-001", None, redactor=Redactor({}))
    assert effective_answer(edit.new.get("Q-001")) == "(empty)" and TAKEN not in edit.new.data.decode()


def test_answer_writes_no_block(qworld, tmp_path):
    open_one(qworld, **{k: v for k, v in SHAPE.items() if k not in ("title", "tasks")})
    folder = folder_of(qworld, worktree(qworld, tmp_path))
    edit = build_edit("answer", folder, "Q-001", "Use the config.", redactor=Redactor({}))
    assert b"### Clarifier suggestion" not in edit.new.data
    assert effective_answer(edit.new.get("Q-001")) == "Use the config."


def test_check_question_accepts_option_one_and_still_refuses_what_has_none():
    def file(**over) -> QuestionsFile:
        return QuestionsFile.parse(questions_md("a", {**SHAPE, **over}))

    assert check_question(file(), "Q-001", "accept", None, unit=A, branch="b") is None
    no_edit = file(options=("Keep the test", "Edit `src/other.test.ts`: x"))
    assert (
        "no clarifier suggestion to accept"
        in check_question(no_edit, "Q-001", "accept", None, unit=A, branch="b").message
    )
    product = file(kind="product")
    assert "no clarifier suggestion" in check_question(product, "Q-001", "accept", None, unit=A, branch="b").message
    assert (
        "no clarifier suggestion"
        in check_question(file(options=()), "Q-001", "accept", None, unit=A, branch="b").message
    )


def test_the_cli_accept_pushes_the_block_and_the_status(qworld, capsys, person):  # noqa: F811
    qworld.unit_branch("a", questions_md("a", SHAPE), ledger=ledger_file(A, RED))
    written(qworld, capsys, "accept", "Q-001")
    q = pushed(qworld).get("Q-001")
    assert q.status is QuestionStatus.ACCEPTED and q.suggestion_text == TAKEN
    assert effective_answer(q) == TAKEN and q.answer_text == ""
    assert "| Q-001 | accepted |" in pushed(qworld).data.decode()


def test_the_cli_answer_pushes_no_block(qworld, capsys, person):  # noqa: F811
    qworld.unit_branch("a", questions_md("a", SHAPE), ledger=ledger_file(A, RED))
    written(qworld, capsys, "answer", "Q-001", text="Use the config.")
    assert b"### Clarifier suggestion" not in pushed(qworld).data


def test_show_names_option_one_as_what_accept_takes(qworld, capsys, person):  # noqa: F811
    qworld.unit_branch("a", questions_md("a", SHAPE), ledger=ledger_file(A, RED))
    code, out = shown(qworld, capsys, "Q-001")
    assert code is ExitCode.OK
    assert f"accept takes: {TAKEN} (option 1: the question has no clarifier suggestion)" in out
    assert "an accepted suggestion unfreezes src/app.test.ts for the next green of 2.1" in out
    assert f"Next: l4 questions accept Q-001 --unit {A}" in out.splitlines()
    assert "### Clarifier suggestion" not in out  # show prints the section as the file has it


def test_show_json_names_where_the_text_comes_from(qworld, capsys, person):  # noqa: F811
    qworld.unit_branch("a", questions_md("a", SHAPE), ledger=ledger_file(A, RED))
    _, out = shown(qworld, capsys, "Q-001", as_json=True)
    doc = json.loads(out)
    assert doc["accept"] == {"takes": TAKEN, "from": "option 1"}
    assert {"task": "2.1", "path": "src/app.test.ts", "unfreezes": True, "why": ""} in doc["frozen"]
    assert doc["next"][0] == f"l4 questions accept Q-001 --unit {A}"


def test_scn_qmd_30_show_of_a_written_suggestion_has_no_from(qworld, capsys, person):  # noqa: F811
    qworld.unit_branch("a", questions_md("a", {**SHAPE, "suggestion": "Take option 2"}), ledger=ledger_file(A, RED))
    _, out = shown(qworld, capsys, "Q-001", as_json=True)
    assert json.loads(out)["accept"] == {"takes": "Take option 2"}
    _, text = shown(qworld, capsys, "Q-001")
    assert "accept takes: Take option 2" in text and "option 1: the question" not in text


def test_show_of_a_question_without_a_suggestion_or_an_edit_option_is_as_before(qworld, capsys, person):  # noqa: F811
    qworld.unit_branch("a", questions_md("a", {**SHAPE, "options": ("Keep the test",)}))
    _, out = shown(qworld, capsys, "Q-001")
    assert "accept takes: no clarifier suggestion: answer it with --text" in out
    _, js = shown(qworld, capsys, "Q-001", as_json=True)
    assert json.loads(js)["accept"] == {"takes": None}


def agent(world: QWorld):
    return dataclasses.replace(world.app, environ={**world.app.environ, "CLAUDECODE": "1"})


def test_the_agent_rule_reads_the_text_option_one_would_write(qworld):
    """An agent may not accept an option 1 that names a frozen path, as for a written suggestion."""
    named = {**SHAPE, "options": ("Edit conftest.py: add the fixture", "Leave it"), "context": "See `conftest.py`."}
    qworld.unit_branch("a", questions_md("a", named), ledger=ledger_file(A, RED))
    head = qworld.origin_head("a")
    with pytest.raises(L4Exit) as caught:
        run_questions(agent(qworld), words=("accept", "Q-001"), unit=A, text=None, as_json=False, no_push=False)
    assert "an agent may not accept Q-001: the suggestion names the frozen path conftest.py of task 2.1" in str(
        caught.value
    )
    assert qworld.origin_head("a") == head


def test_an_agent_accepts_an_option_one_that_names_no_frozen_path(qworld, capsys):
    free = {**SHAPE, "options": ("Edit src/free.py: add the case", "Leave it"), "context": "See `src/free.py`."}
    qworld.unit_branch("a", questions_md("a", free), ledger=ledger_file(A, RED))
    code = run_questions(agent(qworld), words=("accept", "Q-001"), unit=A, text=None, as_json=False, no_push=False)
    assert code is ExitCode.OK
    assert pushed(qworld).get("Q-001").status is QuestionStatus.ACCEPTED


def test_suggestion_effects_names_the_frozen_path_of_option_one():
    question = QuestionsFile.parse(questions_md("a", SHAPE)).get("Q-001")
    frozen = {"2.1": ("src/app.test.ts", "conftest.py")}
    assert suggestion_effects(question, frozen) == [PathEffect("2.1", "src/app.test.ts", True, "")]
    written_block = QuestionsFile.parse(questions_md("a", {**SHAPE, "suggestion": "Take option 2"})).get("Q-001")
    assert suggestion_effects(written_block, frozen) == []  # a written block is the text; it names no path
    product = QuestionsFile.parse(questions_md("a", {**SHAPE, "kind": "product"})).get("Q-001")
    assert suggestion_effects(product, frozen) == []


# --- L2 (review): show must not promise what accept refuses -------------------------------------------------------

HIDDEN = "plainvalue-8f3k2m9x1q7z"  # a value the test's redactor knows
SECRET_OPTION = f"Edit src/app.test.ts: seed {HIDDEN}"


def with_secret(**over) -> QuestionsFile:
    return QuestionsFile.parse(questions_md("a", {**SHAPE, "options": (SECRET_OPTION, "Leave it"), **over}))


def test_check_question_refuses_an_option_one_the_redactor_would_change():
    file = with_secret()
    found = check_question(file, "Q-001", "accept", None, unit=A, branch="b", redactor=Redactor({"token": HIDDEN}))
    assert found is not None
    assert found.message == ("option 1 of Q-001 holds a value the redactor hides, so accept cannot take it as written")
    assert found.fix == f"l4 questions answer Q-001 --unit {A} --text TEXT"
    assert check_question(file, "Q-001", "accept", None, unit=A, branch="b", redactor=Redactor({})) is None
    written_block = with_secret(suggestion="Take option 2")  # a written block is never the option
    assert (
        check_question(written_block, "Q-001", "accept", None, unit=A, branch="b", redactor=Redactor({"token": HIDDEN}))
        is None
    )


def test_build_edit_refuses_up_front_and_the_takes_check_agrees(qworld, tmp_path):
    qworld.unit_branch("a", questions_md("a", {**SHAPE, "options": (SECRET_OPTION, "Leave it")}))
    folder = folder_of(qworld, worktree(qworld, tmp_path))
    hiding = Redactor({"token": HIDDEN})
    with pytest.raises(L4Exit) as caught:
        build_edit("accept", folder, "Q-001", None, redactor=hiding)
    assert "holds a value the redactor hides" in str(caught.value)
    assert caught.value.code is ExitCode.USAGE_ERROR
    # the read-back check would have refused it as well: both checks say no to the same text
    base = folder.file.with_option_suggestion("Q-001", redactor=hiding)
    new = edit_accept(base, "Q-001")
    why = round_trip(folder.file, new, "Q-001", QuestionStatus.ACCEPTED, None, accept_text(folder.file.get("Q-001")))
    assert why == "the answer of Q-001 reads back differently from the suggestion it takes"
    ok = round_trip(
        folder.file,
        edit_accept(folder.file.with_option_suggestion("Q-001", redactor=Redactor({})), "Q-001"),
        "Q-001",
        QuestionStatus.ACCEPTED,
        None,
        accept_text(folder.file.get("Q-001")),
    )
    assert ok is None


def test_show_says_accept_cannot_take_an_option_one_the_redactor_hides(qworld, capsys, person):  # noqa: F811
    # the raising run did not know the value (it is a secret of the CLI's own config), so the file holds it as is
    qworld.app.redactor.adopt(Redactor({"token": HIDDEN}))
    qworld.unit_branch(
        "a", questions_md("a", {**SHAPE, "options": (SECRET_OPTION, "Leave it")}), ledger=ledger_file(A, RED)
    )
    code, out = shown(qworld, capsys, "Q-001")
    assert code is ExitCode.OK
    assert "accept takes:" not in out
    assert "accept: option 1 of Q-001 holds a value the redactor hides, so accept cannot take it as written" in out
    assert "an accepted suggestion" not in out  # nothing is promised
    assert f"Next: l4 questions answer Q-001 --unit {A} --text TEXT" in out.splitlines()
    assert not any(line.startswith("Next: l4 questions accept") for line in out.splitlines())
    _, js = shown(qworld, capsys, "Q-001", as_json=True)
    doc = json.loads(js)
    assert doc["accept"]["takes"] is None and "redactor hides" in doc["accept"]["refused"]
    assert doc["frozen"] == []


# --- L3 (review): the file `accept` wrote reaches the grant of `implementer.unfreeze.unfrozen` -----------------------

SUPPORT = "tests/conftest.py"
MANIFEST = FreezeManifest(
    "r" * 40,
    {"src/app.test.ts": FrozenFile("a" * 64, "test"), SUPPORT: FrozenFile("c" * 64, "support")},
    ("**/conftest.py",),
)
SCOPE = frozenset({"2.1", "2"})


def answered_event(qid: str, by: str, digest: str | None) -> LedgerEvent:
    data: dict[str, object] = {"id": qid, "by": by, "answer_sha256": digest}
    if by == "delegate":
        data.update(profile="delegate-opus", model="claude-opus-5-5")
    return LedgerEvent(
        datetime(2026, 10, 29, tzinfo=UTC), "r-20261029T0000Z-0001", "openspec:a", 1, "question.answered", data
    )


def accepted_file(qworld, tmp_path) -> QuestionsFile:
    """Q-001 names the red test `src/app.test.ts`, Q-002 the support file, both by a bare option 1 and no block; each is
    accepted by `build_edit`, the way the CLI and the delegate write it."""
    support = {
        **SHAPE,
        "title": "Which fixture?",
        "context": f"The red step froze {SUPPORT}.",
        "options": (f"Edit {SUPPORT}: add the fixture.", "Leave it"),
    }
    qworld.unit_branch("a", questions_md("a", SHAPE, support), ledger=ledger_file(A, RED))
    folder = folder_of(qworld, worktree(qworld, tmp_path))
    first = build_edit("accept", folder, "Q-001", None, redactor=Redactor({}))
    second = build_edit("accept", dataclasses.replace(folder, file=first.new), "Q-002", None, redactor=Redactor({}))
    return second.new


def events_of(file: QuestionsFile, by: str) -> list[LedgerEvent]:
    return [answered_event(q, by, answer_sha256(file.get(q))) for q in ("Q-001", "Q-002")]


def test_the_file_accept_wrote_is_granted_to_the_delegate_for_a_test_file_only(qworld, tmp_path):
    file = accepted_file(qworld, tmp_path)
    got = unfrozen(file.questions, events_of(file, "delegate"), SCOPE, MANIFEST, delegate_unfreeze=True)
    assert got.paths == ("src/app.test.ts",)
    [grant] = got.grants
    assert (grant.reason, grant.by, grant.question) == ("delegate_answer", "delegate", "Q-001")
    assert grant.answer_sha256 == answer_sha256(file.get("Q-001"))
    assert any(path == SUPPORT and "test-support file" in why for path, why in got.kept)  # a support file stays frozen


def test_the_same_file_opens_nothing_in_a_fix_task_or_without_the_switch(qworld, tmp_path):
    file = accepted_file(qworld, tmp_path)
    events = events_of(file, "delegate")
    fix = unfrozen(file.questions, events, SCOPE, MANIFEST, delegate_unfreeze=True, fix_task=True)
    assert fix.grants == () and any(path == "src/app.test.ts" for path, _ in fix.kept)
    off = unfrozen(file.questions, events, SCOPE, MANIFEST, delegate_unfreeze=False)
    assert off.grants == ()


def test_a_person_s_accept_of_the_same_file_grants_the_test_and_the_support_file(qworld, tmp_path):
    file = accepted_file(qworld, tmp_path)
    got = unfrozen(file.questions, events_of(file, "human"), SCOPE, MANIFEST, delegate_unfreeze=True)
    assert set(got.paths) == {"src/app.test.ts", SUPPORT} and {g.reason for g in got.grants} == {"human_answer"}


def test_without_the_block_the_digest_of_the_raised_file_grants_nothing(qworld, tmp_path):
    """The load never derives the block: a digest of the derived text, with the file as raised, matches nothing."""
    file = accepted_file(qworld, tmp_path)
    raised = QuestionsFile.parse(questions_md("a", SHAPE)).set_status("Q-001", QuestionStatus.ACCEPTED)
    got = unfrozen(raised.questions, events_of(file, "delegate"), SCOPE, MANIFEST, delegate_unfreeze=True)
    assert got.grants == ()
