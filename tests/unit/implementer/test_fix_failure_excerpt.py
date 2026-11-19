"""L4-IMP-102: a fix chore's prompt and questions carry the failure text of the tests its findings name."""

from l4.agents.fake import Step
from l4.implementer.loop import run_task
from l4.implementer.tdd import fix_failure_text, run_single

from .conftest import blocked_step, red_step, result
from .test_fix_chore_e2e import E2E_FINDING, NEW_FINDING, TASK, TEST_X, TEST_Z, seed_round
from .test_loop import TASK as LOOP_TASK

TOKEN = "glpat-" + "A1b2C3d4E5f6G7h8I9j0"
EXCERPT = "E       assert 1508 == 1500"
WITH_EXCERPT = {
    TEST_X: {"gate": "e2e", "kind": "assertion", "message": "assert 1508 == 1500", "excerpt": EXCERPT},
    TEST_Z: {"gate": "e2e", "kind": "assertion", "message": "assert 1 == 2"},
}
PROPOSAL_LINE = "Shoppers expect to enter a discount code at checkout"
BLOCKED = Step(structured=result("single", status="blocked", questions=[]))
HEADING = "# Failures of this task's tests"


def first_prompt(bench) -> str:
    return bench.adapter.requests[0].prompt


def test_scn_imp_558_the_first_prompt_of_a_fix_chore_holds_the_failure_even_when_the_proposal_is_cut(make_bench):
    bench = make_bench([BLOCKED], implementer={"context_budget_tokens": 1})
    seed_round(bench, failures=WITH_EXCERPT)
    run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)
    prompt = first_prompt(bench)
    assert PROPOSAL_LINE not in prompt  # the unit context was cut to fit the budget
    assert HEADING in prompt and EXCERPT in prompt and f"{TEST_X} (assertion, e2e):" in prompt
    assert f"{TEST_Z} (assertion, e2e):\n  assert 1 == 2" in prompt  # no excerpt: its message


def test_the_block_is_a_data_block_after_the_previous_attempt(make_bench):
    bench = make_bench([BLOCKED])
    seed_round(bench, failures=WITH_EXCERPT)
    run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, previous_failure="the e2e tests of the finding do not pass")
    prompt = first_prompt(bench)
    assert PROPOSAL_LINE in prompt
    block = prompt.split(HEADING, 1)[1]
    assert '<l4:data source="failing tests">' in block.split("# ", 1)[0]
    assert prompt.index("# Your previous attempt was rejected") < prompt.index(HEADING) < prompt.index("# Phase")


def test_only_the_tests_the_tasks_findings_name_are_shown(make_bench):
    bench = make_bench([BLOCKED])
    seed_round(
        bench, failures={**WITH_EXCERPT, "tests.t::other": {"gate": "test", "kind": "assertion", "message": "x"}}
    )
    run_single(bench.wb, TASK, [NEW_FINDING], attempt=1)  # `new tests failed` names TEST_X only
    prompt = first_prompt(bench)
    assert f"{TEST_X} (assertion, e2e):" in prompt and TEST_Z not in prompt.split(HEADING, 1)[1]


def test_scn_imp_561_no_stored_round_and_a_round_without_failures_add_no_block(make_bench):
    unspawned = make_bench([BLOCKED])
    seed_round(unspawned, failures=WITH_EXCERPT, spawned=False)
    run_single(unspawned.wb, TASK, [E2E_FINDING], attempt=1)
    assert HEADING not in first_prompt(unspawned)
    older = make_bench([BLOCKED])
    seed_round(older, failures=None)
    run_single(older.wb, TASK, [E2E_FINDING], attempt=1)
    assert HEADING not in first_prompt(older)
    assert fix_failure_text(older.wb, [E2E_FINDING]) == ""


def test_a_chore_of_another_kind_gets_no_block(make_bench):
    bench = make_bench([BLOCKED])
    seed_round(bench, failures=WITH_EXCERPT)
    run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="refactor")
    assert HEADING not in first_prompt(bench)


# the questions (D6)

ASKING = {
    "title": "Unfreeze e2e/conftest.py?",
    "context": "the fixture must change",
    "kind": "technical",
    "options": ["Edit `e2e/conftest.py`: set the environment in a fixture"],
}
NOTE = "Harness note: the verifier recorded these failures for the tests of this task's findings:"


def asked_in_a_chore(bench, monkeypatch) -> str:
    import l4.implementer.loop as loop

    monkeypatch.setattr(loop, "chore_findings", lambda path, title: (E2E_FINDING,))
    assert run_task(bench.wb, LOOP_TASK).status == "blocked"
    return (bench.wb.ref.path / "questions.md").read_text()


def test_scn_imp_559_a_fix_chores_question_shows_the_failure_and_still_ends_with_the_fix_task_note(
    make_bench, monkeypatch
):
    bench = make_bench([Step(structured=result("single", status="blocked", questions=[ASKING]))])
    seed_round(bench, failures=WITH_EXCERPT)
    text = asked_in_a_chore(bench, monkeypatch)
    context = text.split("the fixture must change", 1)[1]
    assert NOTE in context and EXCERPT in context
    assert context.index(NOTE) < context.index("Harness note: this is a fix task.")  # SCN-IMP-398: that note is last
    assert "A person must commit the change" in context.split(NOTE, 1)[1]  # the fix task note comes after


def test_a_bare_blocked_chore_gets_the_block_in_the_question_made_from_its_summary(make_bench, monkeypatch):
    bench = make_bench([Step(structured=result("single", status="blocked", summary="stuck", questions=[]))])
    seed_round(bench, failures=WITH_EXCERPT)
    text = asked_in_a_chore(bench, monkeypatch)
    assert "stuck" in text and NOTE in text and EXCERPT in text


def test_a_chore_question_without_a_stored_round_has_no_block(make_bench, monkeypatch):
    bench = make_bench([Step(structured=result("single", status="blocked", questions=[ASKING]))])
    text = asked_in_a_chore(bench, monkeypatch)
    assert NOTE not in text and "Harness note: this is a fix task." in text


def test_a_token_in_the_excerpt_does_not_reach_questions_md(make_bench, monkeypatch):
    leaked = {TEST_X: {"gate": "e2e", "kind": "assertion", "message": "m", "excerpt": f"E   token {TOKEN}"}}
    bench = make_bench([Step(structured=result("single", status="blocked", questions=[ASKING]))])
    seed_round(bench, failures=leaked)
    text = asked_in_a_chore(bench, monkeypatch)
    assert "token" in text and TOKEN not in text


# a question after a failed attempt (SCN-IMP-560)

REJECTED = "Harness note: the previous attempt of this task was rejected: red tests still failing:"


def green_question_after_a_failure(make_bench) -> tuple[object, str]:
    asking = {
        "title": "Which rounding?",
        "context": "the scenarios disagree",
        "kind": "ambiguous",
        "options": ["a", "b"],
    }
    bench = make_bench(
        [
            red_step(),
            Step(structured=result("green")),
            Step(structured=result("green", status="blocked", questions=[asking])),
        ]
    )
    assert run_task(bench.wb, LOOP_TASK).status == "blocked"
    return bench, (bench.wb.ref.path / "questions.md").read_text()


def test_scn_imp_560_a_question_after_a_failed_attempt_says_why_that_attempt_failed(make_bench):
    bench, text = green_question_after_a_failure(make_bench)
    context = text.split("the scenarios disagree", 1)[1]
    assert REJECTED in context and "tests.test_discount::test_known_code" in context
    assert "NotImplementedError" in context.split(REJECTED, 1)[1]  # a line of the ledger excerpt


def test_a_question_of_a_first_attempt_has_no_such_note(make_bench):
    bench = make_bench([blocked_step()])
    assert run_task(bench.wb, LOOP_TASK).status == "blocked"
    assert "rejected" not in (bench.wb.ref.path / "questions.md").read_text()


def test_the_previous_attempt_note_comes_before_greens_unfreeze_note(make_bench):
    asking = {
        "title": "Unfreeze tests/test_discount.py?",
        "context": "the test is wrong",
        "kind": "technical",
        "options": ["Edit `tests/test_discount.py`: change the expected value"],
    }
    bench = make_bench(
        [
            red_step(),
            Step(structured=result("green")),
            Step(structured=result("green", status="blocked", questions=[asking])),
        ]
    )
    assert run_task(bench.wb, LOOP_TASK).status == "blocked"
    context = (bench.wb.ref.path / "questions.md").read_text().split("the test is wrong", 1)[1]
    assert REJECTED in context and "frozen" in context
    assert context.index(REJECTED) < context.index("frozen")


def test_a_full_size_block_leaves_the_fix_task_note_last_and_whole(make_bench, monkeypatch):
    lines = "\n".join(f"E   line {n} " + "z" * 60 for n in range(8))
    many = {
        f"e2e.test_big::test_{n:02}": {"gate": "e2e", "kind": "assertion", "message": "m", "excerpt": lines}
        for n in range(12)
    }
    bench = make_bench([Step(structured=result("single", status="blocked", questions=[ASKING]))])
    seed_round(bench, failures=many)
    text = asked_in_a_chore(bench, monkeypatch)
    context = text.split("the fixture must change", 1)[1].split("### Options", 1)[0]
    assert len(context) > 5000 and context.count("(assertion, e2e):") == 8
    assert "and 4 more failing tests" in context
    assert context.index(NOTE) < context.index("Harness note: this is a fix task.")
    assert context.rstrip().endswith(f'`l4 questions answer Q-NNN --unit {bench.wb.ref.id} --text "..."`).')
