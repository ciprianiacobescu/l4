# ruff: noqa: F401, F811  (the fixtures are imported by name)
"""`l4:needs-person` follows the delegate's escalated questions (delegate-answers 12.1; L4-DLG-008, L4-CLR-004;
SCN-DLG-25, SCN-DLG-26, SCN-DLG-45): the first sync after an escalation sets the label and writes the section, a
person's answer removes both at the next run."""

from ..delegate.conftest import blocked as delegate_blocked
from ..delegate.conftest import (  # noqa: F401
    delegate_run,
    escalation,
    fake_clock,
    install_hooks,
    no_clarifier,
    no_hooks_but_the_delegate,
    no_verifier,
    openspec_stand_in,
    publish_base,
    reply,
    run_l4,
)
from ..implementer.conftest import green_step, red_step
from ..orchestrator.conftest import edit_questions_on_origin
from .conftest import forge_env, use_fake_gitlab

REASON = "no project document decides this"


def test_the_label_follows_escalated_questions(delegate_run, forge_env, use_fake_gitlab, tdd_repo, raw):  # SCN-DLG-45
    gitlab = use_fake_gitlab
    run = delegate_run([delegate_blocked("product"), escalation(why=REASON)])
    assert run.code == 11
    labels = gitlab.mrs[1]["labels"]
    assert "l4:needs-person" in labels and "l4:needs-answers" in labels and "l4:awaiting_human" in labels
    (note,) = gitlab.notes[1]
    assert "Needs a person (the delegate escalated)" in note["body"]
    assert f"Q-001 (product): Which error 1?: {REASON}" in note["body"]
    assert "l4:needs-person" in gitlab.labels  # created by the mirror, the label set that setup also makes
    # a person answers (SCN-DLG-26): the next run records the answer and the mirror drops the label and the section
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="Block login until verified")
    resumed = delegate_run([red_step(), green_step()])
    assert resumed.events("question.answered")[-1]["by"] == "human"
    assert "l4:needs-person" not in gitlab.mrs[1]["labels"]
    assert "Needs a person" not in gitlab.notes[1][0]["body"]


def test_an_answered_question_has_no_label(delegate_run, forge_env, use_fake_gitlab):
    gitlab = use_fake_gitlab
    run = delegate_run([delegate_blocked("technical"), reply()])
    assert run.code == 11
    assert "l4:needs-person" not in gitlab.mrs[1]["labels"]
    (note,) = gitlab.notes[1]
    assert "Answered by the delegate" in note["body"] and "Q-001" in note["body"]
    assert "delegate-model-1 via fake" in note["body"]
