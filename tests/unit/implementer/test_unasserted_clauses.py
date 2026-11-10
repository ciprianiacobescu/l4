"""L4-IMP-095: a clause a step leaves unasserted is asked before the task goes on (SCN-IMP-510..515, 519)."""

import json

import pytest

from l4.agents.fake import Step
from l4.implementer.clauses import ClauseAsk, Split, clause_question, recorded_entries, split_clauses
from l4.implementer.loop import run_task
from l4.implementer.result import Unasserted
from l4.specs.base import Task
from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, QuestionStatus, raise_questions

from .conftest import IMPL, KNOWN, STUB, TESTS, UNKNOWN, green_step, red_step, result
from .test_already_satisfied_no_test import no_test, seeded
from .test_earlier_red import TASK as EARLIER_TASK
from .test_escalation import CHORE, tag_as_chore

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
FIX = "add-discount-codes-fix-1"


def entry(criterion: str = KNOWN, clause: str = "its action is recorded", why: str = "the spec does not say"):
    return Unasserted(criterion=criterion, clause=clause, why=why)


def ask(bench, *, task: str = "1.1", criterion: str = KNOWN, fix_unit: str | None = None, phase: str = "red") -> str:
    """A question of the harness for a clause, as `_raise_blocked` leaves it: in `questions.md` and in the ledger."""
    [qid] = raise_questions(
        bench.wb.ref.path,
        bench.wb.ref.name,
        [NewQuestion("t", QuestionKind.AMBIGUOUS, (task,), "c", "asked")],
        redactor=bench.wb.redactor,
    )
    extra = {"fix_unit": fix_unit} if fix_unit else {}
    bench.writer.append(
        "question.raised", id=qid, task=task, kind="ambiguous", title="t",
        clause={"criterion": criterion, "phase": phase}, **extra,
    )  # fmt: skip
    return qid


def commit_answers(bench) -> None:
    """A person's answer is a commit on the unit branch: a step's discard would drop a bare edit."""
    git = bench.wb.git
    git.run("add", f"{bench.wb.unit_rel}/questions.md")
    git.run("commit", "-q", "-m", "answer", config=(("user.name", "t"), ("user.email", "t@x")))


def answer(bench, qid: str, status: QuestionStatus = QuestionStatus.ANSWERED) -> None:
    path = bench.wb.ref.path / "questions.md"
    file = QuestionsFile.load(path)
    assert file is not None
    if status is QuestionStatus.ACCEPTED:  # accepts the clarifier's suggestion
        file = file.set_suggestion(qid, "null: the other spec sets it to null", redactor=bench.wb.redactor)
    elif status is QuestionStatus.ANSWERED:
        file = file.set_answer(qid, "null: the other spec sets it to null")
    file.set_status(qid, status).save(path)
    commit_answers(bench)


def test_an_entry_with_no_earlier_question_is_new(make_bench):
    bench = make_bench([])
    split = split_clauses(bench.wb, TASK, [entry()])
    assert split == Split(new=(entry(),), settled=())


@pytest.mark.parametrize("status", [QuestionStatus.ANSWERED, QuestionStatus.ACCEPTED, QuestionStatus.DISMISSED])
def test_an_answered_question_of_the_same_task_and_criterion_settles_the_entry(make_bench, status):
    bench = make_bench([])
    qid = ask(bench)
    answer(bench, qid, status)
    again = entry(clause="the same clause in other words")  # the key is the criterion, never the words
    assert split_clauses(bench.wb, TASK, [again]) == Split(new=(), settled=((again, qid),))


def test_an_open_question_does_not_settle_the_entry(make_bench):
    bench = make_bench([])
    ask(bench)
    assert split_clauses(bench.wb, TASK, [entry()]).new == (entry(),)


def test_a_question_of_another_task_or_criterion_does_not_settle(make_bench):
    bench = make_bench([])
    answer(bench, ask(bench, task="1.2"))
    answer(bench, ask(bench, criterion=UNKNOWN))
    assert split_clauses(bench.wb, TASK, [entry()]).new == (entry(),)


def test_a_question_without_a_clause_does_not_settle(make_bench):
    bench = make_bench([])
    [qid] = raise_questions(
        bench.wb.ref.path, bench.wb.ref.name, [NewQuestion("t", QuestionKind.AMBIGUOUS, ("1.1",), "c", "a")],
        redactor=bench.wb.redactor,
    )  # fmt: skip
    bench.writer.append("question.raised", id=qid, task="1.1", kind="ambiguous", title="t")
    answer(bench, qid)
    assert split_clauses(bench.wb, TASK, [entry()]).new == (entry(),)


def test_a_fix_units_question_settles_only_that_fix_units_steps_and_the_reverse(make_bench):
    bench = make_bench([])
    answer(bench, ask(bench, fix_unit=FIX))  # raised in a fix unit's step, the step is the unit's own
    assert split_clauses(bench.wb, TASK, [entry()]).new == (entry(),)
    bench.wb.event_context = {"fix_unit": FIX}
    qid = ask(bench, fix_unit=FIX, criterion=UNKNOWN)
    answer(bench, qid)
    assert split_clauses(bench.wb, TASK, [entry(UNKNOWN)]).settled == ((entry(UNKNOWN), qid),)
    plain = make_bench([])
    answer(plain, ask(plain))  # raised in the unit's own step, the step is a fix unit's
    plain.wb.event_context = {"fix_unit": FIX}
    assert split_clauses(plain.wb, TASK, [entry()]).new == (entry(),)


def test_the_newest_of_two_answered_questions_settles(make_bench):
    bench = make_bench([])
    first, second = ask(bench), ask(bench)
    answer(bench, first)
    answer(bench, second)
    assert split_clauses(bench.wb, TASK, [entry()]).settled == ((entry(), second),)


def test_entries_are_split_in_order(make_bench):
    bench = make_bench([])
    answer(bench, ask(bench))
    old, fresh = entry(), entry(UNKNOWN, clause="another")
    split = split_clauses(bench.wb, TASK, [fresh, old])
    assert split.new == (fresh,) and [e for e, _ in split.settled] == [old]


def test_the_clause_question(make_bench):
    unit = [type("C", (), {"id": KNOWN})()]
    asked = clause_question(TASK, "red", entry(), unit)  # type: ignore[arg-type]
    assert isinstance(asked, ClauseAsk) and asked.criterion == KNOWN and asked.known is unit[0]
    q = asked.question
    assert q.kind == "ambiguous" and q.blocking_tasks == ["1.1"] and q.options == []
    assert q.title == f"Task 1.1 (red) left a clause of {KNOWN} unasserted: its action is recorded"
    assert (
        "The red step of task 1.1 did not assert this clause of " + KNOWN + ", and listed it in `unasserted`:"
        in q.context
    )
    assert "> its action is recorded" in q.context and "Its reason: the spec does not say" in q.context
    assert "The step was not kept." in q.context and "is not one of this unit's criteria" not in q.context


def test_the_clause_question_of_a_criterion_that_is_not_the_units():
    asked = clause_question(TASK, "green", entry("C-99999999"), [])
    assert asked.known is None and asked.criterion == "C-99999999"
    assert asked.question.title.startswith("Task 1.1 (green) left a clause of C-99999999 unasserted:")
    assert "C-99999999 is not one of this unit's criteria." in asked.question.context


# through `run_task`
def listed(clause: str = "its action is recorded", why: str = "the spec does not say", criterion: str = KNOWN) -> dict:
    return {"criterion": criterion, "clause": clause, "why": why}


def red_listing(*entries: dict, **over: object) -> Step:
    """A red step that writes its failing tests and reports `done`, listing `entries` as unasserted."""
    return Step(
        writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB},
        structured=result(
            "red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN],
            unasserted=list(entries), **over,
        ),
    )  # fmt: skip


def green_listing(*entries: dict) -> Step:
    return Step(writes={"src/pytdd/pricing.py": IMPL}, structured=result("green", unasserted=list(entries)))


def answer_all(bench, text: str = "null: the other capability's spec sets it to null") -> None:
    path = bench.wb.ref.path / "questions.md"
    file = QuestionsFile.load(path)
    assert file is not None
    for question in file.questions:
        file = file.set_answer(question.id, text).set_status(question.id, QuestionStatus.ANSWERED)
    file.save(path)
    commit_answers(bench)


def questions_md(bench) -> str:
    return (bench.wb.ref.path / "questions.md").read_text()


def test_scn_imp_510_a_red_step_that_lists_a_clause_is_not_kept_and_asks(make_bench):
    bench = make_bench([red_listing(listed())])
    outcome = run_task(bench.wb, TASK)
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-001"])
    assert bench.subjects() == ["docs(add-discount-codes): questions [skip ci]"]  # no `test(` commit
    assert "[ ] 1.1" in (bench.wb.ref.path / "tasks.md").read_text()
    assert bench.events("task.attempt_failed") == [] and bench.events("task.red_ok") == []
    text = questions_md(bench)
    assert f"## Q-001: Task 1.1 (red) left a clause of {KNOWN} unasserted: its action is recorded" in text
    assert (
        "- **Kind:** ambiguous" in text and "- **Blocking tasks:** 1.1" in text and f"- **Criteria:** {KNOWN}" in text
    )
    assert "> its action is recorded" in text and "Its reason: the spec does not say" in text
    assert "The step was not kept." in text and "Task 1.1 is blocked" not in text
    [raised] = bench.events("question.raised")
    assert (raised["id"], raised["task"], raised["kind"]) == ("Q-001", "1.1", "ambiguous")
    assert raised["clause"] == {"criterion": KNOWN, "phase": "red"} and "fix_unit" not in raised
    assert bench.pushes and len(bench.adapter.requests) == 1
    assert not (bench.wb.worktree / "tests" / "test_discount.py").exists()  # the step's files are gone


def test_scn_imp_511_the_answer_reaches_the_next_step_and_the_criterion_is_not_asked_again(make_bench):
    other = listed(clause="the action field holds a value", why="another reading")
    bench = make_bench([red_listing(listed()), red_listing(other), green_step()])
    assert run_task(bench.wb, TASK).status == "blocked"
    answer_all(bench)
    assert run_task(bench.wb, TASK).status == "done"
    assert 'kind="answer" id="Q-001"' in bench.adapter.requests[1].prompt  # the red prompt holds the answer block
    assert "other capability" in bench.adapter.requests[1].prompt
    assert [s.split("(")[0] for s in bench.subjects()] == ["docs", "answer", "test", "feat"]
    [red_ok] = bench.events("task.red_ok")
    assert red_ok["unasserted"] == [{**other, "question": "Q-001"}]
    assert len(bench.events("question.raised")) == 1 and questions_md(bench).count("## Q-") == 1
    [done] = bench.events("task.done")
    assert "unasserted" not in done


def test_scn_imp_512_a_green_step_that_would_decide_what_the_spec_does_not_settle_is_not_kept(make_bench):
    bench = make_bench([red_step(), green_listing(listed(why="I chose continue; the spec does not say")), green_step()])
    outcome = run_task(bench.wb, TASK)
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-001"])
    red_sha = bench.events("task.red_committed")[0]["sha"]
    assert [s.split("(")[0] for s in bench.subjects()] == ["test", "docs"]  # no `feat(` commit
    assert bench.wb.git.run("rev-parse", "HEAD~1").stdout.strip() == red_sha
    assert (bench.wb.worktree / "src/pytdd/pricing.py").read_text() == STUB  # back at the red commit
    assert "[ ] 1.1" in (bench.wb.ref.path / "tasks.md").read_text()
    assert f"## Q-001: Task 1.1 (green) left a clause of {KNOWN} unasserted: its action is recorded" in questions_md(
        bench
    )
    assert [e["clause"] for e in bench.events("question.raised")] == [{"criterion": KNOWN, "phase": "green"}]
    assert bench.events("task.attempt_failed") == []
    answer_all(bench)
    assert run_task(bench.wb, TASK).status == "done"
    assert len(bench.events("task.red_resumed")) == 1
    assert 'kind="answer" id="Q-001"' in bench.adapter.requests[-1].prompt
    assert len(bench.adapter.requests) == 3  # red, the discarded green, the green with the answer


def test_a_green_step_that_lists_a_settled_clause_is_committed_and_records_it(make_bench):
    bench = make_bench([red_listing(listed()), red_step(), green_listing(listed(clause="again", why="still open"))])
    run_task(bench.wb, TASK)
    answer_all(bench)
    assert run_task(bench.wb, TASK).status == "done"
    [done] = bench.events("task.done")
    assert done["unasserted"] == [{"criterion": KNOWN, "clause": "again", "why": "still open", "question": "Q-001"}]


def test_scn_imp_515_the_words_of_a_note_are_not_a_signal(make_bench):
    note = "I did not assert entry.action, because the spec text is ambiguous there"
    step = red_step()
    step.structured = {**step.structured, "notes_for_verifier": note}
    bench = make_bench([step, green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    assert bench.events("question.raised") == []
    [red_ok] = bench.events("task.red_ok")
    assert note in red_ok["notes"] and "unasserted" not in red_ok


def test_scn_imp_519_a_blocked_result_raises_its_own_questions_first(make_bench):
    own = {"title": "Which rounding?", "context": "scenarios disagree", "kind": "ambiguous"}
    step = Step(structured=result("red", status="blocked", questions=[own], unasserted=[listed()]))
    bench = make_bench([step])
    outcome = run_task(bench.wb, TASK)
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-001", "Q-002"])
    text = questions_md(bench)
    assert "## Q-001: Which rounding?" in text and f"## Q-002: Task 1.1 (red) left a clause of {KNOWN}" in text
    assert "Task 1.1 is blocked" not in text
    assert [e.get("clause") for e in bench.events("question.raised")] == [None, {"criterion": KNOWN, "phase": "red"}]


def test_scn_imp_519_a_fix_units_step_asks_in_the_fix_units_file(make_bench):
    bench = make_bench(
        [Step(writes={"src/pytdd/pricing.py": IMPL}, structured=result("single", unasserted=[listed()]))]
    )
    tag_as_chore(bench)
    bench.wb.event_context = {"fix_unit": f"{bench.wb.ref.name}-fix-1"}
    outcome = run_task(bench.wb, CHORE)
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-001"])
    assert f"Task 1.1 (single) left a clause of {KNOWN} unasserted" in questions_md(bench)
    [raised] = bench.events("question.raised")
    assert raised["fix_unit"] == f"{bench.wb.ref.name}-fix-1"
    assert raised["clause"] == {"criterion": KNOWN, "phase": "single"}
    assert bench.subjects() == ["docs(add-discount-codes): questions [skip ci]"]  # the step's change is gone
    assert "[ ] 1.1" in (bench.wb.ref.path / "tasks.md").read_text()


def test_a_three_entry_step_raises_three_questions_in_order(make_bench):
    entries = [listed(clause=f"clause {n}", criterion=c) for n, c in enumerate([KNOWN, UNKNOWN, KNOWN], 1)]
    bench = make_bench([red_listing(*entries)])
    outcome = run_task(bench.wb, TASK)
    assert outcome.question_ids == ["Q-001", "Q-002", "Q-003"]
    text = questions_md(bench)
    assert [text.index(f"unasserted: clause {n}") for n in (1, 2, 3)] == sorted(
        text.index(f"unasserted: clause {n}") for n in (1, 2, 3)
    )
    assert len(bench.adapter.requests) == 1


def test_a_step_with_one_settled_and_one_new_entry_is_blocked_and_asks_only_the_new_one(make_bench):
    fresh = listed(clause="another clause", criterion=UNKNOWN)
    bench = make_bench([red_listing(listed()), red_listing(listed(clause="again"), fresh)])
    run_task(bench.wb, TASK)
    answer_all(bench)
    outcome = run_task(bench.wb, TASK)
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-002"])
    assert f"## Q-002: Task 1.1 (red) left a clause of {UNKNOWN} unasserted: another clause" in questions_md(bench)
    assert bench.events("task.red_ok") == []


# L4-IMP-095 D5: the settled entries are recorded where the step's notes are
TOKEN = "ghp_" + "a" * 36


def settle(bench) -> None:
    """A question of this task and `KNOWN` that a person has answered, as an earlier run left it."""
    answer(bench, ask(bench))


def test_the_recorded_entries_are_the_settled_ones_with_their_question_and_the_texts_redacted(make_bench):
    bench = make_bench([])
    settle(bench)
    got = recorded_entries(bench.wb, TASK, [entry(clause=f"holds {TOKEN}", why=f"see {TOKEN}")])
    assert got == {
        "unasserted": [
            {"criterion": KNOWN, "clause": "holds [REDACTED:github-token]", "why": "see [REDACTED:github-token]",
             "question": "Q-001"}
        ]
    }  # fmt: skip
    assert recorded_entries(bench.wb, TASK, []) == {}


def test_an_entry_that_is_no_longer_settled_is_recorded_without_a_question(make_bench):
    bench = make_bench([])
    settle(bench)
    got = recorded_entries(bench.wb, TASK, [entry(), entry(UNKNOWN, clause="other")])
    assert got["unasserted"] == [
        {"criterion": KNOWN, "clause": "its action is recorded", "why": "the spec does not say", "question": "Q-001"},
        {"criterion": UNKNOWN, "clause": "other", "why": "the spec does not say"},
    ]


def test_a_committed_red_records_the_settled_entry_in_task_red_ok(make_bench):
    bench = make_bench([red_listing(listed()), red_listing(listed(clause=f"holds {TOKEN}")), green_step()])
    run_task(bench.wb, TASK)
    answer_all(bench)
    assert run_task(bench.wb, TASK).status == "done"
    [red_ok] = bench.events("task.red_ok")
    assert red_ok["unasserted"] == [
        {"criterion": KNOWN, "clause": "holds [REDACTED:github-token]", "why": "the spec does not say",
         "question": "Q-001"}
    ]  # fmt: skip
    assert TOKEN not in json.dumps(bench.events("task.red_ok"))


def test_an_already_satisfied_red_records_the_entry_in_task_red_ok_and_not_in_task_done(make_bench):
    step = no_test()
    step.structured = {**step.structured, "unasserted": [listed()]}
    bench, _ = seeded(make_bench, step)
    settle(bench)
    assert run_task(bench.wb, EARLIER_TASK).status == "done"
    [red_ok] = bench.events("task.red_ok")[-1:]
    assert red_ok["unasserted"] == [{**listed(), "question": "Q-001"}] and red_ok["tdd"] == "already-satisfied"
    assert "unasserted" not in bench.events("task.done")[-1]


def test_a_single_step_records_the_settled_entry_in_its_task_done(make_bench):
    step = Step(writes={"src/pytdd/pricing.py": IMPL}, structured=result("single", unasserted=[listed()]))
    bench = make_bench([step])
    tag_as_chore(bench)
    settle(bench)
    assert run_task(bench.wb, CHORE).status == "done"
    [done] = bench.events("task.done")
    assert done["tdd"] == "exempt" and done["unasserted"] == [{**listed(), "question": "Q-001"}]
