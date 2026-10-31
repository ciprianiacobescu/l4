"""`l4 questions` and agents (unfreeze-and-answer 4.7; L4-QMD-009): the actor rule of `l4 yolo accept`, and the two
`clarifier` keys read from the base branch."""

import dataclasses

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.specs.questions import QuestionsFile, QuestionStatus
from l4.specs.questions_cli import run_questions

from .questions_world import FOLDER, A, QWorld, ledger_file, questions_md

CONFIG = ".l4/config.yaml"
KEY = "a person runs the command, or set clarifier.answer_by_agents: true in .l4/config.yaml on main"


class Tty:
    @staticmethod
    def isatty() -> bool:
        return True


def agent_app(world: QWorld, **env: str):
    return dataclasses.replace(world.app, environ={**world.app.environ, "CLAUDECODE": "1", **env})


def run(world: QWorld, app, *words: str, text: str | None = None, no_push: bool = False):
    return run_questions(app, words=words, unit=A, text=text, as_json=False, no_push=no_push)


def world_with(qworld: QWorld) -> QWorld:
    """Q-003 technical, its suggestion names the frozen `conftest.py` of task 2.1; Q-005 technical, names nothing;
    Q-002 product; Q-004 verdict."""
    qworld.unit_branch(
        "a",
        questions_md(
            "a",
            {"title": "Which hash?", "tasks": ("1.1",), "suggestion": "Use argon2id."},
            {"title": "Allow it?", "kind": "product", "tasks": ("3.1",)},
            {"title": "Edit the fixtures?", "tasks": ("2.1",), "suggestion": "Add the fixture to `conftest.py`."},
            {"title": "Verdict?", "kind": "verdict", "tasks": ()},
            {"title": "Which port?", "tasks": ("2.1",)},
        ),
        ledger=ledger_file(A, ("task.red_ok", {"task": "2.1", "frozen": ["conftest.py"], "fix_unit": None})),
    )
    return qworld


def base_config(world: QWorld, text: str) -> None:
    world.sim.human_commit({CONFIG: text}, "clarifier keys")


def pushed_status(world: QWorld, qid: str) -> QuestionStatus:
    data = world.remote.run_bytes("show", f"{world.origin_head('a')}:{FOLDER}/a/questions.md")
    return QuestionsFile.parse(data).get(qid).status


def refused(world: QWorld, app, *words: str, text: str | None = None) -> str:
    head = world.origin_head("a")
    with pytest.raises(L4Exit) as caught:
        run(world, app, *words, text=text)
    assert caught.value.code is ExitCode.USAGE_ERROR
    assert world.origin_head("a") == head  # nothing was pushed
    return str(caught.value)


def test_scn_qmd_23_an_agent_answers_a_technical_question_that_names_no_frozen_path(qworld, capsys):
    world_with(qworld)
    assert run(qworld, agent_app(qworld), "answer", "Q-005", text="Use argon2id.") is ExitCode.OK
    assert "pushed" in capsys.readouterr().out
    assert pushed_status(qworld, "Q-005") is QuestionStatus.ANSWERED
    body = qworld.remote.run("log", "-1", "--format=%b", "l4/openspec/a").stdout
    assert "By: alex (agent: CLAUDECODE)" in body and "Via: l4 questions" in body


def test_an_agent_accepts_a_suggestion_that_names_no_frozen_path(qworld, capsys):
    world_with(qworld)
    assert run(qworld, agent_app(qworld), "accept", "Q-001") is ExitCode.OK
    assert pushed_status(qworld, "Q-001") is QuestionStatus.ACCEPTED


def test_scn_qmd_24_an_agent_cannot_unfreeze_a_test_path_on_its_own(qworld, capsys):
    world_with(qworld)
    message = refused(qworld, agent_app(qworld), "accept", "Q-003")
    assert message.startswith("questions: an agent may not accept Q-003: the suggestion names the frozen path")
    assert "conftest.py of task 2.1" in message and f"\nFix: {KEY} " in message  # "(a pushed change a person can see)"
    text = "Add the fixture to conftest.py."
    assert "the text names the frozen path" in refused(qworld, agent_app(qworld), "answer", "Q-003", text=text)


def test_scn_qmd_24_the_key_on_the_base_branch_lets_the_accept_through(qworld, capsys):
    world_with(qworld)
    base_config(qworld, "clarifier:\n  answer_by_agents: true\n")
    assert run(qworld, agent_app(qworld), "accept", "Q-003") is ExitCode.OK
    assert pushed_status(qworld, "Q-003") is QuestionStatus.ACCEPTED


def test_scn_qmd_24_the_key_only_on_the_unit_branch_does_not(qworld):
    world_with(qworld)
    qworld.branch("a", {CONFIG: "clarifier:\n  answer_by_agents: true\n"}, "an agent sets the key on its branch")
    assert "an agent may not accept Q-003" in refused(qworld, agent_app(qworld), "accept", "Q-003")


def test_scn_qmd_25_an_agent_cannot_answer_a_product_question(qworld):
    world_with(qworld)
    message = refused(qworld, agent_app(qworld), "answer", "Q-002", text="Allow it.")
    assert message.startswith("questions: an agent may not answer Q-002: its kind is product")
    assert f"\nFix: {KEY}" in message


def test_a_verdict_question_is_a_persons_unless_the_key_is_set(qworld, capsys):
    world_with(qworld)
    message = refused(qworld, agent_app(qworld), "answer", "Q-004", text="accept: fine")
    assert "a verdict answer is a person's decision" in message
    base_config(qworld, "clarifier:\n  answer_by_agents: true\n")
    assert run(qworld, agent_app(qworld), "answer", "Q-004", text="accept: fine") is ExitCode.OK


def test_auto_accept_kinds_of_the_base_branch_widen_what_an_agent_may_do(qworld, capsys):
    world_with(qworld)
    base_config(qworld, "clarifier:\n  auto_accept_kinds: [technical, product]\n")
    assert run(qworld, agent_app(qworld), "answer", "Q-002", text="Allow it.") is ExitCode.OK
    assert pushed_status(qworld, "Q-002") is QuestionStatus.ANSWERED


def test_a_dry_run_by_an_agent_is_refused_the_same_way(qworld):
    world_with(qworld)
    app = agent_app(qworld)
    with pytest.raises(L4Exit, match="an agent may not answer Q-002"):
        run(qworld, app, "answer", "Q-002", text="Allow it.", no_push=True)


def test_a_caller_with_no_terminal_on_stdin_is_an_agent_and_a_terminal_is_a_person(qworld, capsys, monkeypatch):
    world_with(qworld)
    assert not any(qworld.app.environ.get(m) for m in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT"))
    message = refused(qworld, qworld.app, "answer", "Q-002", text="Allow it.")  # pytest's stdin is not a terminal
    assert "an agent may not answer Q-002" in message
    monkeypatch.setattr("sys.stdin", Tty())
    assert run(qworld, qworld.app, "answer", "Q-002", text="Allow it.") is ExitCode.OK
    assert "By: alex (person)" in qworld.remote.run("log", "-1", "--format=%b", "l4/openspec/a").stdout


def test_a_person_with_a_marker_in_the_environment_is_an_agent(qworld, monkeypatch):
    world_with(qworld)
    monkeypatch.setattr("sys.stdin", Tty())
    assert "an agent may not answer Q-002" in refused(qworld, agent_app(qworld), "answer", "Q-002", text="x")


def test_an_invalid_base_config_gives_the_default_rules(qworld, caplog):
    world_with(qworld)
    base_config(qworld, "clarifier:\n  answer_by_agents: maybe\n")
    assert "an agent may not answer Q-002" in refused(qworld, agent_app(qworld), "answer", "Q-002", text="x")


def harness_world(qworld: QWorld) -> QWorld:
    qworld.unit_branch(
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
    return qworld


def test_scn_imp_317_an_agent_cannot_answer_a_harness_question_without_consent(qworld, capsys):
    harness_world(qworld)
    app = dataclasses.replace(qworld.app, environ={**qworld.app.environ, "AI_AGENT": "l4-mcp"})
    message = refused(qworld, app, "answer", "Q-001", text="accept: the run broke")
    assert "a harness override is a person's decision" in message
    base_config(qworld, "clarifier:\n  answer_by_agents: true\n")
    assert run(qworld, app, "answer", "Q-001", text="accept: the run broke") is ExitCode.OK
    assert pushed_status(qworld, "Q-001") is QuestionStatus.ANSWERED
    body = qworld.remote.run("log", "-1", "--format=%b", "l4/openspec/a").stdout
    assert "agent: AI_AGENT" in body


# --- own-test-repair: a repair of a test is a person's (L4-IMP-091, design D4) ---------------------------------------

REPAIR_MESSAGE = "an agent may not answer Q-001: a repair of a test is a person's decision"


def repair_world(qworld: QWorld, check: str, **raise_data: object) -> QWorld:
    """Q-001 is a harness question that the ledger says was raised by `check`."""
    raised = {"id": "Q-001", "kind": "harness", "task": "1.1", "check": check, "fix_unit": None, **raise_data}
    qworld.unit_branch(
        "a",
        questions_md("a", {"title": "Task 1.1: a repair waits", "kind": "harness", "tasks": ("1.1",)}),
        ledger=ledger_file(A, ("question.raised", raised)),
    )
    return qworld


def test_scn_imp_473_an_agent_cannot_answer_a_repair_question(qworld):
    repair_world(qworld, "repair")
    message = refused(qworld, agent_app(qworld), "answer", "Q-001", text="accept: apply this edit")
    assert message.startswith(f"questions: {REPAIR_MESSAGE}")
    assert "\nFix: a person runs the command" in message and "answer_by_agents" not in message


def test_scn_imp_473_the_key_on_the_base_branch_does_not_let_an_agent_answer_a_repair(qworld):
    repair_world(qworld, "repair")
    base_config(qworld, "clarifier:\n  answer_by_agents: true\n")
    assert REPAIR_MESSAGE in refused(qworld, agent_app(qworld), "answer", "Q-001", text="accept: apply this edit")


def test_a_person_answers_a_repair_question(qworld, capsys, monkeypatch):
    repair_world(qworld, "repair")
    monkeypatch.setattr("sys.stdin", Tty())
    assert run(qworld, qworld.app, "answer", "Q-001", text="accept: apply this edit") is ExitCode.OK
    assert pushed_status(qworld, "Q-001") is QuestionStatus.ANSWERED


def fix_unit_world(qworld: QWorld, unit_check: str, fix_check: str) -> QWorld:
    """Both the unit's own `questions.md` and its fix unit's `a-fix-1` hold a harness Q-001: the ledger raised each
    with its own check (the fix unit's raise names `fix_unit`)."""
    own = {"id": "Q-001", "kind": "harness", "task": "1.1", "check": unit_check}
    fixed = {"id": "Q-001", "kind": "harness", "task": "1.1", "check": fix_check, "fix_unit": "a-fix-1"}
    spec = {"title": "Task 1.1: a repair waits", "kind": "harness", "tasks": ("1.1",)}
    qworld.unit_branch(
        "a",
        questions_md("a", spec),
        ledger=ledger_file(A, ("question.raised", own), ("question.raised", fixed)),
        extra={
            f"{FOLDER}/a-fix-1/tasks.md": "## 1. Fix\n\n- [ ] 1.1 Fix it\n",
            f"{FOLDER}/a-fix-1/questions.md": questions_md("a-fix-1", spec),
        },
    )
    return qworld


def test_a_fix_units_repair_question_is_read_from_the_fix_units_raise(qworld):  # SCN-IMP-473
    fix_unit_world(qworld, "tests", "repair")  # the unit's own Q-001 is another check: it must not hide the fix unit's
    base_config(qworld, "clarifier:\n  answer_by_agents: true\n")
    with pytest.raises(L4Exit, match="a repair of a test is a person's decision"):
        run_questions(
            agent_app(qworld), words=("answer", "Q-001"), unit="openspec:a-fix-1", text="accept: ok", as_json=False,
            no_push=True,
        )  # fmt: skip
    assert run(qworld, agent_app(qworld), "answer", "Q-001", text="accept: ok", no_push=True) is ExitCode.OK


def test_a_repair_question_of_the_unit_is_not_the_fix_units_question(qworld):
    fix_unit_world(qworld, "repair", "tests")
    base_config(qworld, "clarifier:\n  answer_by_agents: true\n")
    code = run_questions(
        agent_app(qworld), words=("answer", "Q-001"), unit="openspec:a-fix-1", text="accept: ok", as_json=False,
        no_push=True,
    )  # fmt: skip
    assert code is ExitCode.OK


def test_the_other_harness_checks_keep_their_rule_for_an_agent(qworld):
    repair_world(qworld, "tests")
    assert "a harness override is a person's decision" in refused(
        qworld, agent_app(qworld), "answer", "Q-001", text="accept: ok"
    )
    base_config(qworld, "clarifier:\n  answer_by_agents: true\n")
    assert run(qworld, agent_app(qworld), "answer", "Q-001", text="accept: ok") is ExitCode.OK
    assert pushed_status(qworld, "Q-001") is QuestionStatus.ANSWERED


def test_a_repair_question_with_no_readable_raise_keeps_todays_rule(qworld):
    qworld.unit_branch(
        "a",
        questions_md("a", {"title": "Task 1.1: a repair waits", "kind": "harness", "tasks": ("1.1",)}),
        ledger=None,
    )
    base_config(qworld, "clarifier:\n  answer_by_agents: true\n")
    assert run(qworld, agent_app(qworld), "answer", "Q-001", text="accept: ok") is ExitCode.OK
