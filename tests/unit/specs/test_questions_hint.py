"""`l4 questions` names the delegate while it is off (delegate-answers 26.1; L4-DLG-021; SCN-DLG-71/72/73/111)."""

import json

import yaml

from l4.delegate.hint import hint_text
from l4.exitcodes import ExitCode
from l4.specs.questions_cli import run_questions

from .questions_world import A, QWorld, ledger_file, questions_md

HINT = hint_text("main")


def waiting_unit(world: QWorld, kind: str = "technical", phase: str = "awaiting_human") -> None:
    world.unit_branch(
        "a",
        questions_md("a", {"title": "Which hash?", "kind": kind, "tasks": ("1.1",)}),
        ledger=ledger_file(A, ("phase.changed", {"from": "implementing", "to": phase, "trigger": "test"})),
    )


def waiting_unit_escalated(world: QWorld) -> None:
    world.unit_branch(
        "a",
        questions_md("a", {"title": "Which hash?", "kind": "technical", "tasks": ("1.1",)}),
        ledger=ledger_file(
            A,
            ("question.raised", {"id": "Q-001", "kind": "technical"}),
            ("phase.changed", {"from": "implementing", "to": "awaiting_human", "trigger": "test"}),
            ("delegate.result", {"question": "Q-001", "id": "Q-001", "status": "escalated", "kind": "technical"}),
        ),
    )


def publish_base(world: QWorld, delegate: dict | None, *, text: str | None = None) -> None:
    config = yaml.safe_load((world.root / "sim-config.yaml").read_text())
    if delegate is not None:
        config["delegate"] = delegate
    world.sim.human_commit({".l4/config.yaml": text if text is not None else yaml.safe_dump(config)}, "base config")
    world.clone.run("fetch", "--quiet", "origin")


def listed(world: QWorld, capsys, *, as_json=False) -> tuple[ExitCode, str]:
    code = run_questions(world.app, words=(), unit=None, text=None, as_json=as_json, no_push=False)
    return code, capsys.readouterr().out


def test_the_hint_follows_next(qworld, capsys):  # SCN-DLG-71
    waiting_unit(qworld)
    publish_base(qworld, {"scope": "all"})
    code, out = listed(qworld, capsys)
    lines = out.splitlines()
    assert code is ExitCode.OK
    assert lines[-2].startswith("Next: l4 questions show Q-001") and lines[-1] == HINT
    assert out.count("Hint:") == 1
    _, raw = listed(qworld, capsys, as_json=True)
    assert json.loads(raw)["delegate_hint"] == HINT


def test_no_hint_while_the_delegate_is_on(qworld, capsys):  # SCN-DLG-72
    waiting_unit(qworld)
    publish_base(qworld, {"scope": "all", "enabled": True})
    _, out = listed(qworld, capsys)
    assert "Hint:" not in out
    _, raw = listed(qworld, capsys, as_json=True)
    assert json.loads(raw)["delegate_hint"] is None


def test_no_hint_out_of_scope(qworld, capsys):  # SCN-DLG-73
    waiting_unit(qworld)
    publish_base(qworld, None)  # scope: yolo, the unit is in no plan
    _, out = listed(qworld, capsys)
    assert "Hint:" not in out


def test_no_hint_for_a_unit_that_does_not_wait_or_a_kind_it_does_not_answer(qworld, capsys):
    waiting_unit(qworld, phase="implementing")
    publish_base(qworld, {"scope": "all"})
    assert "Hint:" not in listed(qworld, capsys)[1]
    waiting_unit(qworld, kind="product")
    publish_base(qworld, {"scope": "all", "kinds": ["technical"]})
    assert "Hint:" not in listed(qworld, capsys)[1]


def test_no_hint_when_the_base_config_cannot_be_read(qworld, capsys):  # SCN-DLG-111
    waiting_unit(qworld)
    publish_base(qworld, None, text="delegate: [this is not a mapping\n")
    _, out = listed(qworld, capsys)
    assert "Hint:" not in out
    _, raw = listed(qworld, capsys, as_json=True)
    assert json.loads(raw)["delegate_hint"] is None


def test_no_hint_for_a_question_the_delegate_already_escalated(qworld, capsys):  # SCN-DLG-115
    waiting_unit_escalated(qworld)
    publish_base(qworld, {"scope": "all"})
    _, out = listed(qworld, capsys)
    assert "Hint:" not in out
    _, raw = listed(qworld, capsys, as_json=True)
    assert json.loads(raw)["delegate_hint"] is None
