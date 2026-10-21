"""The sticky note's waiting section ends with the delegate hint while it is off (delegate-answers 26.1; L4-DLG-021;
SCN-DLG-74)."""

import pytest

from l4 import services
from l4.clarifier.notify import build_sticky_section
from l4.delegate.hint import hint_text

from .test_hook import CLARIFIER_CONFIG, blocked, clarifier_reply
from .test_notify import view  # the existing helper that builds a QuestionView

HINT = hint_text("main")


def test_the_section_ends_with_the_hint():
    section = build_sticky_section(
        [view("Q-001", "Which error?")], path="p/questions.md", branch="b", link=None, hint=HINT
    )
    assert section.splitlines()[-1] == HINT and section.count("Hint:") == 1


def test_no_hint_no_line():
    section = build_sticky_section([view("Q-001", "Which error?")], path="p/questions.md", branch="b", link=None)
    assert "Hint:" not in section


@pytest.fixture(autouse=True)
def hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(services.HOOKS, "verify", "l4_test_no_verifier:verify_hook")
    monkeypatch.setitem(services.HOOKS, "clarify", "l4.clarifier.clarifier:clarify_hook")


def publish_base(tdd_repo, raw, **config) -> None:
    tdd_repo.write_config(**config)
    raw(tdd_repo.repo, "add", ".l4/config.yaml")
    raw(tdd_repo.repo, "commit", "-q", "--allow-empty", "-m", "the base configuration")
    raw(tdd_repo.repo, "push", "-q", "origin", "main")
    raw(tdd_repo.repo, "fetch", "-q", "origin")


def waiting_note(run_l4, tdd_repo, raw, use_fake_gitlab, delegate):
    publish_base(tdd_repo, raw, delegate=delegate, **CLARIFIER_CONFIG)
    run = run_l4([blocked("product"), clarifier_reply(kind="product", confidence="medium")], **CLARIFIER_CONFIG)
    assert run.code == 11
    (note,) = use_fake_gitlab.notes[1]
    return note["body"]


def test_the_note_of_a_waiting_unit_ends_with_the_hint(run_l4, tdd_repo, raw, forge_env, use_fake_gitlab):  # SCN-DLG-74
    body = waiting_note(run_l4, tdd_repo, raw, use_fake_gitlab, {"scope": "all"})
    waiting = body.split("### Waiting for you: a human answer")[1]
    assert waiting.rstrip().splitlines()[-1] == HINT
    assert "Needs a person (the delegate escalated)" not in body


def test_no_hint_in_the_note_while_the_delegate_is_on(run_l4, tdd_repo, raw, forge_env, use_fake_gitlab):
    body = waiting_note(run_l4, tdd_repo, raw, use_fake_gitlab, {"scope": "all", "enabled": True})
    assert "Hint:" not in body


def test_no_hint_in_the_note_out_of_scope(run_l4, tdd_repo, raw, forge_env, use_fake_gitlab):
    body = waiting_note(run_l4, tdd_repo, raw, use_fake_gitlab, {"scope": "yolo"})
    assert "Hint:" not in body
