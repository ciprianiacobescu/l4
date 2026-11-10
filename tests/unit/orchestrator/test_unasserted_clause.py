# ruff: noqa: F811
"""L4-IMP-095, SCN-IMP-513: the unit does not reach verification while the question of an unasserted clause is open."""

from l4.agents.fake import Step

from ..archive.conftest import forge_env, gitlab, use_fake_gitlab  # noqa: F401  (a fake GitLab for the hand-off)
from ..implementer.conftest import KNOWN, STUB, TESTS, UNKNOWN, green_step, red_step, result
from ..verifier.conftest import valid_spec  # noqa: F401
from .conftest import UNIT_DIR, edit_questions_on_origin

LISTED = {"criterion": KNOWN, "clause": "its action is recorded", "why": "the spec does not say"}


def red_listing() -> Step:
    return Step(
        writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB},
        structured=result(
            "red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN],
            unasserted=[LISTED],
        ),
    )  # fmt: skip


def test_the_unit_waits_while_the_question_is_open_and_resumes_the_task_after_the_answer(run_l4, tdd_repo, raw):
    parked = run_l4([red_listing()])
    assert parked.code == 11 and parked.outcome["units"][0]["phase_after"] == "awaiting_human"
    [raised] = parked.events("question.raised")
    assert raised["kind"] == "ambiguous"
    assert {k: v for k, v in raised["clause"].items() if k != "text_sha"} == {"criterion": KNOWN, "phase": "red"}
    assert raised["clause"]["text_sha"]
    assert "- [ ] 1.1" in parked.pushed(f"{UNIT_DIR}/tasks.md")

    waiting = run_l4([red_step(), green_step()])  # the question is still open
    assert waiting.code == 11 and waiting.adapter.requests == []  # no step of task 1.1 runs
    assert waiting.outcome["units"][0]["phase_after"] == "awaiting_human"
    assert not [e for e in waiting.ledger() if e["type"].startswith("verify.")]  # no verification round starts

    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="null: the other spec sets it to null")
    resumed = run_l4([red_step(), green_step()])
    assert resumed.code == 0 and resumed.outcome["units"][0]["phase_after"] == "implemented"
    assert 'kind="answer" id="Q-001"' in resumed.adapter.requests[0].prompt
    assert [e["id"] for e in resumed.events("question.raised")] == ["Q-001"]  # not asked again
    assert "- [x] 1.1" in resumed.pushed(f"{UNIT_DIR}/tasks.md")
