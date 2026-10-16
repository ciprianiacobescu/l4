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
