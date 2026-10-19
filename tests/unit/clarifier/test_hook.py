"""`clarify_hook` through the real orchestrator, `FakeAdapter` as every role's agent: the script is consumed in call
order (implementer, clarifier, S1 router, S1 support, implementer...)."""

import pytest

from l4 import services
from l4.agents.factory import RoleUnavailable
from l4.agents.fake import Step
from l4.clarifier.clarifier import clarify_hook
from l4.clarifier.notify import UNAVAILABLE_SENTENCE
from l4.clarifier.ports import ClarifyOutcome

from ..implementer.conftest import green_step, red_step, result
from ..orchestrator.conftest import UNIT_DIR, edit_questions_on_origin

CLARIFIER_CONFIG = {
    "roles": {"clarifier": ["judge"], "s1_judge": ["judge"]},
    "clarifier": {"s1_standin": "llm_boolean"},
}
QUOTE = "Unknown codes are rejected with `ValueError`."  # proposal.md of the fixture unit


@pytest.fixture(autouse=True)
def only_the_implementer_and_the_clarifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(services.HOOKS, "verify", "l4_test_no_verifier:verify_hook")
    monkeypatch.setitem(services.HOOKS, "clarify", "l4.clarifier.clarifier:clarify_hook")


def blocked(kind: str) -> Step:
    question = {"title": "Which error?", "context": "what does an unknown code raise", "kind": kind, "options": []}
    return Step(structured=result("red", status="blocked", questions=[question]))


def clarifier_reply(**over: object) -> Step:
    base = {
        "question_id": "Q-001", "answer": "Raise ValueError.", "confidence": "high", "kind": "technical",
        "citations": [{"ref": "proposal.md", "quote": QUOTE, "claim": "c"}], "rationale": "the proposal says so",
    }  # fmt: skip
    return Step(structured={**base, **over})


def s1(answer: bool) -> Step:
    return Step(structured={"answer": answer})


def test_a_technical_question_is_answered_and_the_same_run_goes_on_to_green(run_l4):
    run = run_l4(
        [blocked("technical"), clarifier_reply(), s1(False), s1(True), red_step(), green_step()], **CLARIFIER_CONFIG
    )
    assert run.code == 0
    triggers = run.triggers()
    assert triggers[triggers.index("questions_to_clarifier") :][:3] == [
        "questions_to_clarifier", "clarifier_answered_all", "all_leaves_done",
    ]  # fmt: skip
    (looked,) = run.events("clarifier.result")
    assert (looked["id"], looked["status"], looked["auto_accepted"]) == ("Q-001", "ok", True)
    assert looked["profile"] == "judge"
    (answered,) = run.events("question.answered")
    assert (answered["id"], answered["by"]) == ("Q-001", "clarifier") and len(answered["answer_sha256"]) == 64
    assert run.events("question.override") == []
    assert 'kind="answer" id="Q-001" by="clarifier"' in run.adapter.requests[4].prompt  # the red prompt
    assert "Raise ValueError." in run.adapter.requests[4].prompt
    assert "docs(add-discount-codes): clarifier [skip ci]" in run.subjects()
    questions = run.pushed(f"{UNIT_DIR}/questions.md")  # pushed by the hook, before the agent went on
    assert "answered-by-clarifier" in questions and "confidence: high · kind: technical (S1 p=0.00)" in questions


def test_a_product_question_gets_a_suggestion_exit_11_a_label_and_a_sticky_note(run_l4, forge_env, use_fake_gitlab):
    gitlab = use_fake_gitlab
    run = run_l4([blocked("product"), clarifier_reply(kind="product", confidence="medium")], **CLARIFIER_CONFIG)
    assert run.code == 11 and run.outcome["units"][0]["phase_after"] == "awaiting_human"
    assert run.triggers()[-2:] == ["questions_to_clarifier", "clarifier_needs_human"]
    questions = run.pushed(f"{UNIT_DIR}/questions.md")
    assert "- **Status:** open" in questions and "needs a human" in questions and "Raise ValueError." in questions
    assert len(run.adapter.requests) == 2  # no S1 call: a cheaper condition already blocked
    assert "l4:needs-answers" in gitlab.mrs[1]["labels"] and "l4:awaiting_human" in gitlab.mrs[1]["labels"]
    (note,) = gitlab.notes[1]
    assert note["body"].startswith("<!-- l4:sticky -->\n### Waiting for you: a human answer")
    assert "- Q-001 (product): Which error?" in note["body"]
    assert f"{UNIT_DIR}/questions.md" in note["body"] and "/-/blob/l4/openspec/add-discount-codes/" in note["body"]
    assert gitlab.writes().count(("POST", "/projects/118/merge_requests/1/notes")) == 1


def test_an_answer_that_unblocks_the_unit_clears_the_sticky_note(run_l4, forge_env, use_fake_gitlab, tdd_repo, raw):
    gitlab = use_fake_gitlab
    run_l4([blocked("product"), clarifier_reply(kind="product", confidence="medium")], **CLARIFIER_CONFIG)
    edit_questions_on_origin(tdd_repo, raw, status="accepted")  # a human takes the suggestion
    resumed = run_l4([red_step(), green_step()], **CLARIFIER_CONFIG)
    assert resumed.code == 0
    (note,) = gitlab.notes[1]
    assert note["body"].endswith("Nothing is waiting for a human answer.")
    prompt = resumed.adapter.requests[0].prompt
    assert 'by="human"' in prompt and "Raise ValueError." in prompt
    assert len(resumed.events("question.answered")) == 1  # the human's `accepted`; `reenter` found no override


def test_a_clarifier_that_hits_its_limit_sends_the_question_to_a_human_not_to_exit_12(run_l4):
    run = run_l4([blocked("technical"), Step(status="quota")], **CLARIFIER_CONFIG)
    assert run.code == 11
    last = run.events("phase.changed")[-1]
    assert last["trigger"] == "clarifier_needs_human" and last["reason"].startswith("clarifier unavailable")
    (looked,) = run.events("clarifier.result")
    assert looked["status"] == "unavailable" and looked["auto_accepted"] is False
    questions = run.pushed(f"{UNIT_DIR}/questions.md")
    assert "- **Status:** open" in questions and "Clarifier suggestion" not in questions


def test_a_clarifier_profile_that_cannot_run_tool_less_goes_to_a_human_before_any_call(run_l4):
    run = run_l4(
        [blocked("technical")],
        roles={"clarifier": ["kirox"]},
        profiles={"kirox": {"backend": "openai-chat", "model": "x"}},
    )
    assert run.code == 11 and len(run.adapter.requests) == 1  # only the implementer ran
    last = run.events("phase.changed")[-1]
    assert last["trigger"] == "clarifier_needs_human" and "tool-less" in last["reason"]
    assert [e["status"] for e in run.events("clarifier.result")] == ["unavailable"]


def test_the_hook_returns_the_outcome_the_orchestrator_acts_on(run_l4, install_hooks):
    seen: list[ClarifyOutcome] = []

    def spy(ctx):
        seen.append(clarify_hook(ctx))
        return seen[-1]

    install_hooks(clarify=spy)
    script = [blocked("technical"), clarifier_reply(), s1(False), s1(True), red_step(), green_step()]
    assert run_l4(script, **CLARIFIER_CONFIG).code == 0
    (outcome,) = seen
    assert (outcome.next_phase, outcome.exit_code, outcome.sticky_section) == ("implementing", 0, None)
    assert outcome.results["Q-001"].status == "answered-by-clarifier" and outcome.clarifier_available


def test_a_model_chosen_ref_the_os_rejects_goes_to_a_human_not_to_exit_1(run_l4):
    bad = clarifier_reply(citations=[{"ref": "x" * 300 + ".py", "quote": QUOTE, "claim": "c"}])
    run = run_l4([blocked("technical"), bad], **CLARIFIER_CONFIG)
    assert run.code == 11
    (looked,) = run.events("clarifier.result")
    assert looked["auto_accepted"] is False and looked["reasons"][0].endswith("file not found")


def test_clarifier_and_s1_cost_reach_the_budget_and_the_prompts_are_published(run_l4):
    def priced(step: Step, usd: float) -> Step:
        return Step(structured=step.structured, cost_usd=usd)

    script = [blocked("technical"), priced(clarifier_reply(), 0.25), priced(s1(False), 0.5), priced(s1(True), 0.125)]
    run = run_l4([*script, red_step(), green_step()], **CLARIFIER_CONFIG)
    assert run.code == 0
    costs = {e["role"]: e["usd"] for e in run.events("budget.cost") if e.get("role") in ("clarifier", "s1_judge")}
    assert costs["clarifier"] == 0.25 and costs["s1_judge"] in (0.5, 0.125)
    assert sum(e["usd"] for e in run.events("budget.cost") if e.get("role") == "s1_judge") == 0.625
    assert run.outcome["units"][0]["profiles"]["clarifier"] == "judge"
    assert run.outcome["units"][0]["cost_usd"] >= 0.875
    prompts = {p.name: p.read_text() for p in (run.tdd.repo / ".l4-out" / "agent").rglob("*.prompt.md")}
    assert "Q-001" in prompts["clarify-1.prompt.md"] and '<l4:data kind="s1-state">' in prompts["s1-2.prompt.md"]
    assert "s1-3.prompt.md" in prompts
    published = run.tdd.repo / ".l4-out" / "agent"
    stems = lambda suffix: {p.name.removesuffix(suffix) for p in published.rglob(f"*{suffix}")}  # noqa: E731
    assert stems(".prompt.md") >= {"clarify-1", "s1-2", "s1-3"}
    assert {s for s in stems(".jsonl") if s.split("-")[0] in ("clarify", "s1")} == {
        s for s in stems(".prompt.md") if s.split("-")[0] in ("clarify", "s1")
    }  # every prompt sits beside the events of the call that got it


@pytest.mark.parametrize("ref", [".", "./", "./.", ".#L1", ".#L1-L2"])
def test_a_ref_without_a_file_name_goes_to_a_human_and_is_recorded_not_exit_1(run_l4, ref):
    bad = clarifier_reply(citations=[{"ref": ref, "quote": QUOTE, "claim": "c"}])
    run = run_l4([blocked("technical"), bad], **CLARIFIER_CONFIG)
    assert run.code == 11
    (looked,) = run.events("clarifier.result")
    assert looked["auto_accepted"] is False and looked["reasons"][0].endswith("the path must name a file")
    assert run.events("phase.changed")[-1]["trigger"] == "clarifier_needs_human"


def test_the_unavailable_sentence_reaches_the_sticky_note_when_the_clarifier_hits_its_limit(
    run_l4, forge_env, use_fake_gitlab
):
    gitlab = use_fake_gitlab
    run = run_l4([blocked("technical"), Step(status="quota")], **CLARIFIER_CONFIG)
    assert run.code == 11
    assert UNAVAILABLE_SENTENCE in gitlab.notes[1][0]["body"]


def test_the_unavailable_sentence_reaches_the_sticky_note_when_the_hook_raises_role_unavailable(
    run_l4, install_hooks, forge_env, use_fake_gitlab
):
    def down(ctx):
        raise RoleUnavailable("clarifier", "no login")

    install_hooks(clarify=down)
    gitlab = use_fake_gitlab
    run = run_l4([blocked("technical")], **CLARIFIER_CONFIG)
    assert run.code == 11
    assert run.events("phase.changed")[-1]["reason"].startswith("clarifier unavailable: role clarifier")
    assert UNAVAILABLE_SENTENCE in gitlab.notes[1][0]["body"]


def test_a_question_later_in_a_batch_sees_the_answers_the_clarifier_gave_earlier_in_it(run_l4):
    two = Step(
        structured=result(
            "red", status="blocked",
            questions=[
                {"title": "Which error?", "context": "c1", "kind": "technical", "options": []},
                {"title": "Which code type?", "context": "c2", "kind": "technical", "options": []},
            ],
        )
    )  # fmt: skip
    script = [
        two, clarifier_reply(), s1(False), s1(True), clarifier_reply(question_id="Q-002", answer="Use str."),
        s1(False), s1(True), red_step(), green_step(),
    ]  # fmt: skip
    run = run_l4(script, **CLARIFIER_CONFIG)
    assert run.code == 0
    second = run.adapter.requests[4].prompt  # implementer, clarifier Q-001, two S1 calls, clarifier Q-002
    assert 'id="Q-001" by="clarifier"' in second and "Raise ValueError." in second


def test_a_task_that_keeps_blocking_goes_to_a_human_after_two_clarifier_rounds(run_l4):
    def round_of(n: int) -> list[Step]:
        return [blocked("technical"), clarifier_reply(question_id=f"Q-00{n}"), s1(False), s1(True)]

    script = [*round_of(1), *round_of(2), blocked("technical"), red_step(), green_step()]
    run = run_l4(script, **CLARIFIER_CONFIG)
    assert run.code == 11
    assert [e["id"] for e in run.events("clarifier.result")] == ["Q-001", "Q-002"]  # none for Q-003
    last = run.events("phase.changed")[-1]
    assert last["trigger"] == "questions_blocking" and last["reason"] == "clarifier rounds exhausted for task 1.1"
    assert run.outcome["units"][0]["phase_after"] == "awaiting_human"


def test_the_edge_reason_names_the_question_that_found_the_clarifier_unavailable(run_l4):
    questions = [
        {"title": "Which error?", "context": "c1", "kind": "technical", "options": []},
        {"title": "Which code type?", "context": "c2", "kind": "technical", "options": []},
    ]
    script = [
        Step(structured=result("red", status="blocked", questions=questions)),
        clarifier_reply(kind="product", confidence="medium"), Step(status="quota"),
    ]  # fmt: skip
    run = run_l4(script, **CLARIFIER_CONFIG)
    assert run.code == 11
    reason = run.events("phase.changed")[-1]["reason"]
    assert reason.startswith("clarifier unavailable") and "auto_accept_kinds" not in reason


def test_an_exception_from_the_clarifier_call_is_unavailable_exit_11_not_exit_1(run_l4, forge_env, use_fake_gitlab):
    gitlab = use_fake_gitlab
    run = run_l4([blocked("technical")], **CLARIFIER_CONFIG)  # the script is exhausted at the clarifier's call
    assert run.code == 11
    last = run.events("phase.changed")[-1]
    assert (last["to"], last["trigger"]) == ("awaiting_human", "clarifier_needs_human")
    assert last["reason"].startswith("clarifier unavailable: AdapterError")
    (looked,) = run.events("clarifier.result")
    assert looked["status"] == "unavailable" and looked["auto_accepted"] is False
    assert "- **Status:** open" in run.pushed(f"{UNIT_DIR}/questions.md")
    assert UNAVAILABLE_SENTENCE in gitlab.notes[1][0]["body"]


def test_an_oserror_spawning_the_cli_is_unavailable_too(run_l4, monkeypatch):
    from l4.clarifier.backend import BackendClarifier

    def boom(self, question, prompt):
        raise FileNotFoundError("sandbox-exec")

    monkeypatch.setattr(BackendClarifier, "answer", boom)
    run = run_l4([blocked("technical")], **CLARIFIER_CONFIG)
    assert run.code == 11
    assert run.events("phase.changed")[-1]["reason"].startswith("clarifier unavailable: FileNotFoundError")


def test_a_unit_parked_in_clarifying_by_a_crashed_run_is_resumed_by_the_next_run(run_l4, install_hooks):
    def crash(ctx):
        raise RuntimeError("the hook died")

    install_hooks(clarify=crash)
    assert run_l4([blocked("technical")], **CLARIFIER_CONFIG).code == 1
    install_hooks(clarify=clarify_hook)
    again = run_l4([clarifier_reply(), s1(False), s1(True), red_step(), green_step()], unit=False, **CLARIFIER_CONFIG)
    assert again.code == 0
    assert "clarifier_answered_all" in again.triggers()
    assert [e["status"] for e in again.events("clarifier.result")] == ["ok"]


def test_a_sticky_note_that_cannot_be_written_never_changes_the_exit_code(
    run_l4, forge_env, use_fake_gitlab, monkeypatch
):
    gitlab = use_fake_gitlab
    gitlab.user_status = 403  # GET /user refused and no bot member to fall back on: the write is skipped
    run = run_l4([blocked("technical"), Step(status="quota")], **CLARIFIER_CONFIG)
    assert run.code == 11 and gitlab.notes.get(1, []) == []


def test_a_forge_auth_error_from_the_sticky_write_is_a_warning_not_exit_3(
    run_l4, forge_env, use_fake_gitlab, monkeypatch
):
    from l4.forge.base import ForgeAuthError
    from l4.forge.gitlab import GitLabForge

    def refuse(self, number, body):
        raise ForgeAuthError("GitLab POST /notes: HTTP 403", status=403)

    monkeypatch.setattr(GitLabForge, "upsert_sticky_note", refuse)
    assert run_l4([blocked("technical"), Step(status="quota")], **CLARIFIER_CONFIG).code == 11
