# ruff: noqa: F811
import json

from l4 import services
from l4.agents.fake import Step
from l4.clarifier.ports import ClarifyOutcome
from l4.cli import main

from ..archive.conftest import forge_env, gitlab, use_fake_gitlab  # noqa: F401  (a fake GitLab for the hand-off)
from ..implementer.conftest import KNOWN, blocked_step, green_step, red_step, result
from ..verifier.conftest import valid_spec  # noqa: F401
from .conftest import BRANCH, UNIT_DIR, edit_questions_on_origin, new_origin_main

CLARIFIER_ROLE = {"clarifier": ["judge"]}
TWO_TASKS = "## 1. Pricing\n\n- [ ] 1.1 Add `apply_discount`\n- [ ] 1.2 Add `shout`\n"
SHOUT_TEST = (
    f'import pytest\nfrom pytdd.pricing import shout\n\n\n@pytest.mark.l4("{KNOWN}")\ndef test_shout():\n'
    '    assert shout("ada") == "ADA"\n'
)
QUESTION = (
    "# Questions\n\n<!-- l4:index:start -->\n| ID | Status | Blocking | Kind | Question |\n"
    "|----|--------|----------|------|----------|\n| Q-001 | open | 1.1 | product | Which rate? |\n"
    "<!-- l4:index:end -->\n\n"
    "---\n\n## Q-001: Which rate?\n\n- **Status:** open\n- **Blocking tasks:** 1.1\n- **Kind:** product\n"
    "- **Asked:** a human\n\n### Context\nx\n\n### Answer\n<!-- write below this line -->\n"
)


def test_a_committed_answer_resumes_the_unit_and_the_question_is_not_raised_again(run_l4, tdd_repo, raw):
    blocked = run_l4([blocked_step()])
    assert blocked.code == 11
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="Round half up.")
    resumed = run_l4([red_step(), green_step()])
    assert resumed.code == 0 and resumed.outcome["units"][0]["phase_after"] == "implemented"
    triggers = resumed.triggers()
    assert triggers[-2:] == ["answers_submitted", "all_leaves_done"]
    (answered,) = resumed.events("question.answered")
    assert (answered["id"], answered["by"]) == ("Q-001", "human") and len(answered["answer_sha256"]) == 64
    assert [e["id"] for e in resumed.events("question.raised")] == ["Q-001"]  # not raised again
    assert "- [x] 1.1" in resumed.pushed(f"{UNIT_DIR}/tasks.md")


def test_an_answer_with_status_still_open_is_a_draft_and_changes_nothing(run_l4, tdd_repo, raw):
    first = run_l4([blocked_step()])
    triggers, probes = first.triggers(), len(first.events("availability.selected"))  # the ledger is read lazily
    edit_questions_on_origin(tdd_repo, raw, status="open", answer="Round half up?")
    again = run_l4([red_step(), green_step()])
    assert again.code == 11 and again.adapter.requests == []
    assert again.outcome["units"][0]["phase_after"] == "awaiting_human"
    assert again.triggers() == triggers  # `--unit` does not push the unit through implementing and back
    assert len(again.events("availability.selected")) == probes
    assert [e["id"] for e in again.events("question.unsubmitted_answer")] == ["Q-001"]
    assert again.events("question.answered") == [] and len(again.events("question.raised")) == 1


def test_a_human_who_edits_the_section_only_gets_the_index_row_refreshed_and_committed(run_l4, tdd_repo, raw):
    run_l4([blocked_step()])
    clone = tdd_repo.repo.parent / "human-raw"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
    path = clone / UNIT_DIR / "questions.md"
    text = path.read_text().replace("- **Status:** open", "- **Status:** answered")
    path.write_text(text.replace("<!-- write below this line -->", "<!-- write below this line -->\nRound half up."))
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", "answer Q-001")
    raw(clone, "push", "-q", "origin", BRANCH)
    resumed = run_l4([red_step(), green_step()])
    assert resumed.code == 0
    pushed = resumed.pushed(f"{UNIT_DIR}/questions.md")
    assert "| Q-001 | answered |" in pushed and "| Q-001 | open |" not in pushed
    assert resumed.subjects().count("docs(add-discount-codes): questions index [skip ci]") == 1


def test_an_answer_that_is_dismissed_unblocks_too(run_l4, tdd_repo, raw):
    run_l4([blocked_step()])
    edit_questions_on_origin(tdd_repo, raw, status="dismissed")
    assert run_l4([red_step(), green_step()]).code == 0


def test_other_tasks_run_while_a_question_holds_one_and_the_unit_then_waits(run_l4, tdd_repo, raw):
    questions = QUESTION
    new_origin_main(tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": TWO_TASKS, f"{UNIT_DIR}/questions.md": questions})
    stub_second = Step(
        writes={"tests/test_shout.py": SHOUT_TEST, "src/pytdd/pricing.py": _with_shout("raise NotImplementedError")},
        structured=result("red", task_ids=["1.2"]),
    )
    green_second = Step(
        writes={"src/pytdd/pricing.py": _with_shout("return name.upper()")},
        structured=result("green", task_ids=["1.2"]),
    )
    run = run_l4([stub_second, green_second])
    assert run.code == 11
    tasks = run.pushed(f"{UNIT_DIR}/tasks.md")
    assert "- [ ] 1.1" in tasks and "- [x] 1.2" in tasks  # the independent task was done first
    assert run.triggers()[-1] == "questions_blocking"
    assert run.events("phase.changed")[-1]["questions"] == ["Q-001"]


def _with_shout(body: str) -> str:
    from ..implementer.conftest import IMPL

    return IMPL + f"\n\ndef shout(name):\n    {body}\n"


def test_a_clarify_hook_that_answers_everything_lets_the_run_go_on(run_l4, install_hooks):
    calls: list[str] = []

    def clarify(ctx):
        from l4.redact import Redactor
        from l4.specs.questions import QuestionsFile, QuestionStatus

        calls.append("clarify")
        path = ctx.services.ref.path / "questions.md"
        file = QuestionsFile.load(path)
        file = file.set_suggestion("Q-001", "Round half up.", redactor=Redactor({}))
        file.set_status("Q-001", QuestionStatus.ANSWERED_BY_CLARIFIER).save(path)
        ctx.services.ledger.append("clarifier.result", id="Q-001", status="answered")
        return ClarifyOutcome("implementing", 0)

    install_hooks(clarify=clarify)
    run = run_l4([blocked_step(), red_step(), green_step()], roles=CLARIFIER_ROLE)
    assert run.code == 0 and calls == ["clarify"]
    assert run.triggers() == [
        "unit_discovered_pending", "intake_all_pass", "lease_acquired", "questions_to_clarifier",
        "clarifier_answered_all", "all_leaves_done",
    ]  # fmt: skip
    assert [e["id"] for e in run.events("question.raised")] == ["Q-001"]


def test_a_clarify_hook_that_needs_a_human_ends_the_run_with_exit_11(run_l4, install_hooks):
    install_hooks(clarify=lambda ctx: ClarifyOutcome("awaiting_human", 11))
    run = run_l4([blocked_step()], roles=CLARIFIER_ROLE)
    assert run.code == 11
    assert run.triggers()[-2:] == ["questions_to_clarifier", "clarifier_needs_human"]
    assert run.outcome["units"][0]["phase_after"] == "awaiting_human"


def test_a_clarifier_role_that_is_unavailable_sends_the_unit_to_a_human_not_to_exit_12(run_l4, install_hooks):
    from l4.agents.factory import RoleUnavailable

    def unavailable(ctx):
        raise RoleUnavailable("clarifier", "logged out")

    install_hooks(clarify=unavailable)
    run = run_l4([blocked_step()], roles=CLARIFIER_ROLE)
    assert run.code == 11  # L4-CLR-005: the clarifier never raises exit 12
    assert run.triggers()[-2:] == ["questions_to_clarifier", "clarifier_needs_human"]
    assert run.events("phase.changed")[-1]["reason"].startswith("clarifier unavailable")
    assert run.outcome["units"][0]["phase_after"] == "awaiting_human"


def test_a_unit_with_no_clarifier_profile_goes_straight_to_a_human(run_l4, install_hooks):
    install_hooks(clarify=lambda ctx: (_ for _ in ()).throw(AssertionError("must not run")))
    run = run_l4([blocked_step()])  # roles.clarifier is empty: the role is absent, not unavailable
    assert run.code == 11 and run.triggers()[-1] == "questions_blocking"


def test_a_disabled_clarifier_is_not_called(run_l4, install_hooks):
    install_hooks(clarify=lambda ctx: (_ for _ in ()).throw(AssertionError("must not run")))
    run = run_l4([blocked_step()], clarifier={"enabled": False})
    assert run.code == 11 and run.triggers()[-1] == "questions_blocking"


def test_a_unit_left_in_clarifying_goes_to_a_human_when_no_clarifier_is_there(run_l4, install_hooks, monkeypatch):
    def crash(ctx):
        raise RuntimeError("clarifier crashed")

    install_hooks(clarify=crash)
    crashed = run_l4([blocked_step()], roles=CLARIFIER_ROLE)
    assert crashed.code == 1 and crashed.triggers()[-1] == "questions_to_clarifier"
    monkeypatch.setitem(services.HOOKS, "clarify", "l4_test_no_clarifier:clarify_hook")  # the hook is gone
    again = run_l4([red_step(), green_step()])
    assert again.code == 11 and again.adapter.requests == []
    assert again.triggers()[-1] == "clarifier_needs_human"


# --- the live loop without --unit (simulation-harness 1.13) ----------------------------------------------------


def plan_entry(tdd_repo, capsys) -> dict:
    capsys.readouterr()
    assert main(["plan", "--json", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 0
    (entry,) = json.loads(capsys.readouterr().out)["units"]
    return entry


def test_plan_says_implement_once_an_answer_is_committed_and_run_without_unit_resumes(
    run_l4, tdd_repo, raw, capsys
):  # fmt: skip
    assert run_l4([blocked_step()]).code == 11
    waiting = plan_entry(tdd_repo, capsys)
    assert (waiting["next_action"], waiting["actionable"]) == ("none", False)
    assert waiting["reason"] == "awaiting_human: no new answers (open: Q-001)"
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="Round half up.")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    ready = plan_entry(tdd_repo, capsys)
    assert (ready["next_action"], ready["actionable"], ready["phase"]) == ("implement", True, "awaiting_human")
    assert ready["reason"] == "answers submitted: Q-001"
    resumed = run_l4([red_step(), green_step()], unit=False)
    assert resumed.code == 0 and resumed.outcome["units"][0]["phase_after"] == "implemented"
    assert resumed.triggers()[-2:] == ["answers_submitted", "all_leaves_done"]
    assert [e["id"] for e in resumed.events("question.raised")] == ["Q-001"]
    [red_request, _] = resumed.adapter.requests
    assert '<l4:data kind="answer" id="Q-001" by="human">\nRound half up.\n</l4:data>' in red_request.prompt


def test_a_draft_answer_leaves_the_plan_at_none_and_run_without_unit_does_nothing(run_l4, tdd_repo, raw, capsys):
    run_l4([blocked_step()])
    edit_questions_on_origin(tdd_repo, raw, status="open", answer="Round half up?")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    entry = plan_entry(tdd_repo, capsys)
    assert (entry["next_action"], entry["actionable"]) == ("none", False)
    # a draft committed after the hand-off is told to the human by the plan, with no run needed (SCN-QMD-03)
    assert "answer written but Status is still open: Q-001" in entry["reason"]
    again = run_l4([red_step(), green_step()], unit=False)
    assert again.code == 0 and again.adapter.requests == []
    assert [e["id"] for e in again.events("question.raised")] == ["Q-001"]


def test_a_unit_left_in_clarifying_is_planned_as_clarify_and_run_without_unit_takes_it_on(
    run_l4, tdd_repo, install_hooks, capsys
):  # fmt: skip
    def crash(ctx):
        raise RuntimeError("clarifier crashed")

    install_hooks(clarify=crash)
    assert run_l4([blocked_step()], roles=CLARIFIER_ROLE).code == 1
    entry = plan_entry(tdd_repo, capsys)
    assert (entry["phase"], entry["next_action"], entry["actionable"]) == ("clarifying", "clarify", True)
    install_hooks(clarify=lambda ctx: ClarifyOutcome("awaiting_human", 11))
    again = run_l4([], unit=False, roles=CLARIFIER_ROLE)
    assert again.code == 11 and again.triggers()[-1] == "clarifier_needs_human"


# --- M1.10 line 14 (C2, live F5): an accepted answer to change a frozen test lets green finish ---


def test_an_accepted_answer_to_change_a_frozen_test_lets_green_finish(
    run_l4, tdd_repo, raw, valid_spec, forge_env, use_fake_gitlab, monkeypatch
):
    """Green finds a red test wrong and raises Q-001 naming it. The human sets it `accepted`; the next run resumes at
    green, the scripted agent corrects the test and the code, the task is done, no second question is raised, and the
    round's integrity is ok with the path listed."""
    from l4.specs.criteria import openspec_criteria

    from ..conftest import FIXTURE
    from ..implementer.conftest import IMPL, TESTS
    from ..verifier.conftest import judge_reply

    monkeypatch.setitem(services.HOOKS, "verify", "l4.verifier.ladder:verify_hook")  # the real verifier for this one
    criteria = [c.id for c in openspec_criteria(FIXTURE / "openspec" / "changes" / "add-discount-codes")]
    judge = Step(structured=judge_reply(criteria))
    asks = [
        {
            "title": "The known-code test freezes a wrong amount",
            "context": "tests/test_discount.py:9 expects 45.0 for 50.0, but the scenario is about 100.0",
            "kind": "technical", "options": ["Correct the test", "Keep it"],
        }
    ]  # fmt: skip
    first = run_l4([red_step(), Step(structured=result("green", status="blocked", questions=asks))])
    assert first.code == 11, first.adapter.requests[-1].prompt[-400:]
    [raised] = first.events("question.raised")
    assert raised["id"] == "Q-001" and raised["kind"] == "technical"
    edit_questions_on_origin(
        tdd_repo, raw, status="accepted", suggestion="Change `tests/test_discount.py:9` to use an amount of 100.0."
    )
    corrected = TESTS.replace('apply_discount(50.0, "SAVE10") == 45.0', 'apply_discount(100.0, "SAVE10") == 90.0')
    fix = Step(writes={"tests/test_discount.py": corrected, "src/pytdd/pricing.py": IMPL}, structured=result("green"))
    second = run_l4([fix, judge])
    assert second.code == 0, second.adapter.requests[-1].prompt[-600:] if second.adapter.requests else ""
    assert [e["id"] for e in second.events("question.raised")] == ["Q-001"]  # no Q-002: green was not blocked again
    [unfrozen] = second.events("task.unfrozen")
    assert unfrozen["paths"] == ["tests/test_discount.py"] and unfrozen["question"] == "Q-001"
    assert second.pushed("tests/test_discount.py") == corrected
    assert second.events("guard.test_tamper") == []
    verdicts = second.events("verify.verdict")
    assert verdicts and verdicts[-1]["verdict"] == "PASS"
    assert [s["status"] for s in second.events("verify.step") if s["step"] == "1"][-1] == "ok"  # integrity is ok
    report = second.pushed(f"{UNIT_DIR}/verification.md")
    assert "(+1 unfrozen by human answers)" in report  # step 1's note, in the ladder table
    assert "## Tests unfrozen by human answers" in report and "tests/test_discount.py" in report


# --- SCN-RES-01 end to end: a member's label resumes the halted task only (M1.11, W2) ----------------------------


def test_a_label_resumed_unit_retries_only_the_halted_task(
    run_l4, tdd_repo, raw, forge_env, use_fake_gitlab, monkeypatch
):
    from l4.ci import sweeper
    from l4.forge.gitlab import GitLabForge

    from ..forge.conftest import API, PROJECT, TOKEN

    gitlab = use_fake_gitlab
    gitlab.members = [{"id": 3, "username": "maintainer", "access_level": 40, "state": "active"}]
    monkeypatch.setattr(
        sweeper, "make_forge",
        lambda cfg, environ, **kw: GitLabForge(API, PROJECT, TOKEN, transport=gitlab.transport(), sleep=lambda s: None),
    )  # fmt: skip
    new_origin_main(tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": TWO_TASKS})
    no_test = Step(structured=result("red", task_ids=["1.2"]))
    halted = run_l4([red_step(), green_step(), no_test, no_test], implementer={"max_task_attempts": 2})
    assert halted.code == 13
    assert [e["task"] for e in halted.events("task.done")] == ["1.1"]
    assert gitlab.mrs[1]["labels"] == ["l4:halted"]

    gitlab.mrs[1]["labels"].append("l4:resume")  # a member sets the label; the forge records who
    gitlab.label_events[1] = [
        {"id": 200, "action": "add", "user": {"id": 3}, "label": {"name": "l4:resume"}, "created_at": "2026-10-06"}
    ]
    sweep = ["plan", "--sweep", "--repo", str(tdd_repo.repo)]
    assert main(sweep, environ=tdd_repo.environ) == 0
    assert [e["signal"] for e in halted.events("unit.resumed")] == ["label:200"]
    assert main(sweep, environ=tdd_repo.environ) == 0  # the same event again: nothing
    assert len(halted.events("unit.resumed")) == 1

    stub_second = Step(
        writes={"tests/test_shout.py": SHOUT_TEST, "src/pytdd/pricing.py": _with_shout("raise NotImplementedError")},
        structured=result("red", task_ids=["1.2"]),
    )
    green_second = Step(
        writes={"src/pytdd/pricing.py": _with_shout("return name.upper()")},
        structured=result("green", task_ids=["1.2"]),
    )
    resumed = run_l4([stub_second, green_second], implementer={"max_task_attempts": 2})
    assert resumed.code == 0, resumed.outcome
    first, second = resumed.adapter.requests
    assert "Add `shout`" in first.prompt and "previous attempt was rejected" not in first.prompt  # red attempt 1 again
    assert "Add `apply_discount`" not in first.prompt and len(resumed.adapter.requests) == 2  # 1.1 untouched
    assert [e["task"] for e in resumed.events("task.done")] == ["1.1", "1.2"]
    labels = gitlab.mrs[1]["labels"]
    assert "l4:resume" not in labels and "l4:halted" not in labels  # the mirror's sync took them away
