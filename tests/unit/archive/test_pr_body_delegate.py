"""The PR body names the delegate's answers at the hand-off (delegate-answers 27.1; L4-DLG-027; SCN-DLG-92)."""

from l4.archive import render_pr_body
from l4.state.lifecycle import Trigger

from .conftest import green_step, red_step

ARGS = ("openspec:x", "l4/openspec/x", "openspec/changes/x/verification.md", "https://h.test/g/p")


def test_the_body_names_the_delegates_answers_at_the_hand_off():  # SCN-DLG-92
    body = render_pr_body(
        *ARGS, delegate=[("Q-003", "claude-opus-5-5", "claude-code"), ("Q-007", "gpt-6.1-sol", "codex")]
    )
    assert (
        "- Answered by the delegate: Q-003 (claude-opus-5-5 via claude-code), Q-007 (gpt-6.1-sol via codex); "
        "its verdict accepts are labelled delegate_override in verification.md."
    ) in body
    assert body.count("Answered by the delegate") == 1


def test_no_line_without_a_delegate_answer():
    assert render_pr_body(*ARGS, delegate=()) == render_pr_body(*ARGS)
    assert "delegate" not in render_pr_body(*ARGS)


def test_a_line_is_one_line_whatever_the_model_says():
    body = render_pr_body(*ARGS, delegate=[("Q-001", "m\n- injected [x](http://e)", "cli")])
    assert "\n- injected" not in body and "](http" not in body.split("Answered by the delegate")[1].split("\n")[0]


def test_the_handoff_body_has_the_line_and_the_draft_body_is_refreshed(
    run_l4, install_hooks, forge_env, use_fake_gitlab, gitlab
):
    def verify(ctx):
        ledger = ctx.services.ledger
        ledger.append("question.raised", id="Q-003", kind="technical")
        ledger.append(
            "delegate.result",
            question="Q-003",
            id="Q-003",
            status="answered",
            model="claude-opus-5-5",
            cli="claude-code",
        )
        return Trigger.VERIFY_PASS

    install_hooks(verify=verify)
    assert run_l4([red_step(), green_step()]).code == 0
    (mr,) = gitlab.mrs.values()
    assert "- Answered by the delegate: Q-003 (claude-opus-5-5 via claude-code);" in mr["description"]


def test_a_handoff_without_a_delegate_answer_has_no_line(run_l4, install_hooks, forge_env, use_fake_gitlab, gitlab):
    install_hooks(verify=lambda ctx: Trigger.VERIFY_PASS)
    assert run_l4([red_step(), green_step()]).code == 0
    (mr,) = gitlab.mrs.values()
    assert "Answered by the delegate" not in mr["description"]
