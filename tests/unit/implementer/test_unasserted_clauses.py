"""L4-IMP-095: a clause a step leaves unasserted is asked before the task goes on (SCN-IMP-510..515, 519)."""

import json

import pytest

from l4.agents.fake import Step
from l4.implementer.clauses import ClauseAsk, Split, clause_question, recorded_entries, split_clauses, text_sha
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
    sha = (
        {"text_sha": text_sha(c)}
        if (c := next((c for c in bench.wb.provider.criteria(bench.wb.ref) if c.id == criterion), None))
        else {}
    )
    bench.writer.append(
        "question.raised", id=qid, task=task, kind="ambiguous", title="t",
        clause={"criterion": criterion, "phase": phase, **sha}, **extra,
    )  # fmt: skip
    return qid


def clause_of(raised: dict) -> dict:
    """`question.raised.clause` without its `text_sha` (review decision 6), which is checked to be there."""
    clause = dict(raised["clause"])
    assert len(clause.pop("text_sha")) == 16
    return clause


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
    dismissed = frozenset({qid}) if status is QuestionStatus.DISMISSED else frozenset()
    assert split_clauses(bench.wb, TASK, [again]) == Split(new=(), settled=((again, qid),), dismissed=dismissed)


def test_a_step_with_no_entries_reads_no_ledger(make_bench, monkeypatch):
    bench = make_bench([])

    def boom(wb):
        raise AssertionError("the ledger was read")

    monkeypatch.setattr("l4.implementer.tdd._answer_events", boom)
    assert split_clauses(bench.wb, TASK, []) == Split(new=(), settled=())
    assert recorded_entries(bench.wb, TASK, []) == {}


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
    unit = make_bench([]).wb.provider.criteria(make_bench([]).wb.ref)
    asked = clause_question(TASK, "red", entry(), unit)
    [known] = [c for c in unit if c.id == KNOWN]
    assert isinstance(asked, ClauseAsk) and asked.criterion == KNOWN and asked.known is known
    assert asked.text_sha == text_sha(known)
    q = asked.question
    assert q.kind == "ambiguous" and q.blocking_tasks == ["1.1"] and q.options == []
    assert q.title == f"Task 1.1 (red) left a clause of {KNOWN} unasserted: its action is recorded"
    assert (
        "The red step of task 1.1 did not assert this clause of " + KNOWN + ", and listed it in `unasserted`:"
        in q.context
    )
    assert "> its action is recorded" in q.context and "Its reason: the spec does not say" in q.context
    assert "The step was not kept." in q.context and "is not one of this unit's criteria" not in q.context


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
    assert clause_of(raised) == {"criterion": KNOWN, "phase": "red"} and "fix_unit" not in raised
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
    assert [clause_of(e) for e in bench.events("question.raised")] == [{"criterion": KNOWN, "phase": "green"}]
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
    assert [e.get("clause") and clause_of(e) for e in bench.events("question.raised")] == [
        None,
        {"criterion": KNOWN, "phase": "red"},
    ]


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
    assert clause_of(raised) == {"criterion": KNOWN, "phase": "single"}
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


# review decision 1: a malformed entry is a failed attempt, never a step kept as if nothing was listed
LISTING = {"criterion": KNOWN, "clause": "its action is recorded", "why": "the spec does not say"}
MALFORMED = [
    ({"criterion": KNOWN, "clause": "its action is recorded"}, "unasserted item 1 has no why"),
    ({"criterion": KNOWN, "clause": "", "why": "w"}, "unasserted item 1 has no clause"),
    ({"criterion": "C-2d3a8daf (Req 1.2)", "clause": "c", "why": "w"}, '"C-2d3a8daf (Req 1.2)"'),
    ({"criterion": "Req 1.2", "clause": "c", "why": "w"}, '"Req 1.2"'),
    ({"criterion": KNOWN + "\n", "clause": "c", "why": "w"}, "unasserted item 1 has criterion"),
]


@pytest.mark.parametrize(("bad", "said"), MALFORMED)
def test_a_malformed_entry_is_a_failed_attempt_that_tells_the_agent(make_bench, bad, said):
    bench = make_bench([red_listing(bad), red_step(), green_step()])
    assert run_task(bench.wb, TASK).status == "done"  # the next attempt, told what was wrong, lists nothing
    [failed] = bench.events("task.attempt_failed")
    assert failed["phase"] == "red" and failed["attempt"] == 1 and said in failed["reason"]
    assert "the agent's result is invalid" in failed["reason"]
    assert said in bench.adapter.requests[1].prompt  # the retry prompt names the bad item
    assert bench.events("question.raised") == [] and len(bench.events("task.red_ok")) == 1


def test_a_malformed_entry_is_counted_like_an_invalid_result_and_bounded(make_bench):
    bench = make_bench([red_listing({"criterion": KNOWN, "clause": "c"}) for _ in range(4)])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt" and "max_task_attempts (3) reached in red" in outcome.reason
    assert "unasserted item 1 has no why" in outcome.reason
    assert len(bench.events("task.attempt_failed")) == 3 and len(bench.events("breaker.tripped")) == 1
    assert bench.events("question.raised") == [] and bench.events("task.red_ok") == []
    assert bench.subjects() == []  # nothing of any step was kept
    assert not (bench.wb.worktree / "tests" / "test_discount.py").exists()


def test_an_item_that_is_not_an_object_or_a_list_that_is_not_a_list_fails_the_attempt(make_bench):
    script = [red_listing("its action is recorded"), Step(structured=result("red", unasserted="x"))]
    bench = make_bench(script, implementer={"max_task_attempts": 2})
    assert run_task(bench.wb, TASK).status == "halt"
    reasons = [e["reason"] for e in bench.events("task.attempt_failed")]
    assert "unasserted item 1 is not an object" in reasons[0] and "unasserted is not a list" in reasons[1]


def test_a_malformed_entry_next_to_a_good_one_keeps_nothing(make_bench):
    bench = make_bench([red_listing(listed(), {"criterion": KNOWN, "clause": "c"}), red_step(), green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    assert bench.events("question.raised") == []  # the good entry is not asked either: the step is run again whole
    assert len(bench.events("task.attempt_failed")) == 1


def test_an_upper_case_hex_criterion_is_lowered_and_asked_as_the_units_criterion(make_bench):
    bench = make_bench([red_listing(listed(criterion="C-" + KNOWN[2:].upper()))])
    outcome = run_task(bench.wb, TASK)
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-001"])
    assert bench.events("task.attempt_failed") == []
    assert f"- **Criteria:** {KNOWN}" in questions_md(bench)


# review decision 2: a well-formed id that is not the unit's is a failed attempt, never a question
FOREIGN = ["C-99999999", "C-99999998", "C-99999997", "C-99999996"]


def test_a_criterion_that_is_not_the_units_fails_the_attempt_and_asks_nothing(make_bench):
    bench = make_bench([red_listing(listed(criterion=c)) for c in FOREIGN])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt" and "max_task_attempts (3) reached in red" in outcome.reason
    assert bench.events("question.raised") == [] and "questions.md" not in " ".join(bench.subjects())
    reasons = [e["reason"] for e in bench.events("task.attempt_failed")]
    assert [f"{c} is not one of this unit's criteria" in r for c, r in zip(FOREIGN, reasons, strict=False)] == [
        True
    ] * 3
    assert len(bench.events("breaker.tripped")) == 1 and len(bench.adapter.requests) == 3


def test_the_retry_prompt_names_the_foreign_id_and_the_units_criteria(make_bench):
    bench = make_bench([red_listing(listed(criterion=FOREIGN[0])), red_step(), green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    prompt = bench.adapter.requests[1].prompt
    assert f"{FOREIGN[0]} is not one of this unit's criteria" in prompt and KNOWN in prompt and UNKNOWN in prompt


def test_a_failing_step_that_lists_a_foreign_id_is_not_turned_into_blocked(make_bench):
    bench = make_bench(
        [red_listing(listed(criterion=FOREIGN[0]), status="failed")], implementer={"max_task_attempts": 1}
    )
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt" and outcome.question_ids == []
    assert len(bench.events("task.attempt_failed")) == 1 and bench.events("question.raised") == []


def test_a_foreign_id_in_a_blocked_result_fails_the_attempt_too(make_bench):
    step = Step(structured=result("red", status="blocked", unasserted=[listed(criterion=FOREIGN[0])]))
    bench = make_bench([step], implementer={"max_task_attempts": 1})
    assert run_task(bench.wb, TASK).status == "halt" and bench.events("question.raised") == []


# review decision 4: a dismissed question settles the entry and names no answer
def test_a_dismissed_question_settles_the_entry_and_the_record_names_no_answer(make_bench):
    bench = make_bench([red_listing(listed()), red_listing(listed(clause="again")), green_step()])
    assert run_task(bench.wb, TASK).status == "blocked"
    answer(bench, "Q-001", QuestionStatus.DISMISSED)
    assert run_task(bench.wb, TASK).status == "done"
    [red_ok] = bench.events("task.red_ok")
    assert red_ok["unasserted"] == [listed(clause="again")] and "question" not in red_ok["unasserted"][0]
    assert len(bench.events("question.raised")) == 1


def test_an_accepted_and_a_clarifier_answer_are_recorded_with_their_question(make_bench):
    bench = make_bench([])
    for status in (QuestionStatus.ACCEPTED, QuestionStatus.ANSWERED_BY_CLARIFIER):
        qid = ask(bench)
        path = bench.wb.ref.path / "questions.md"
        file = QuestionsFile.load(path).set_suggestion(
            qid, "null: the other spec sets it to null", redactor=bench.wb.redactor
        )
        file.set_status(qid, status).save(path)
        commit_answers(bench)
        assert recorded_entries(bench.wb, TASK, [entry()])["unasserted"][0]["question"] == qid, status


# review decision 6: an answer settles the criterion's text it was given for
def edit_scenario(bench) -> None:
    """The body of the scenario of `KNOWN` changes and is committed; its id, which hashes the name, does not."""
    path = bench.wb.ref.path / "specs" / "pricing" / "spec.md"
    path.write_text(path.read_text().replace("it returns `45.0`", "it returns `45.0` and records the code"))
    git = bench.wb.git
    git.run("add", str(path.relative_to(bench.wb.worktree)))
    git.run("commit", "-q", "-m", "edit", config=(("user.name", "t"), ("user.email", "t@x")))


def test_an_answer_does_not_settle_an_entry_once_the_scenario_body_changed(make_bench):
    bench = make_bench([])
    qid = ask(bench)
    answer(bench, qid)
    assert split_clauses(bench.wb, TASK, [entry()]).settled == ((entry(), qid),)
    edit_scenario(bench)
    assert [c.id for c in bench.wb.provider.criteria(bench.wb.ref)].count(KNOWN) == 1  # the same id
    assert split_clauses(bench.wb, TASK, [entry()]) == Split(new=(entry(),), settled=())
    assert recorded_entries(bench.wb, TASK, [entry()])["unasserted"] == [listed()]  # no question named


def test_a_question_without_a_text_hash_does_not_settle(make_bench):
    bench = make_bench([])
    [qid] = raise_questions(
        bench.wb.ref.path, bench.wb.ref.name, [NewQuestion("t", QuestionKind.AMBIGUOUS, ("1.1",), "c", "a")],
        redactor=bench.wb.redactor,
    )  # fmt: skip
    bench.writer.append(
        "question.raised", id=qid, task="1.1", kind="ambiguous", title="t",
        clause={"criterion": KNOWN, "phase": "red"},
    )  # fmt: skip
    answer(bench, qid)
    assert split_clauses(bench.wb, TASK, [entry()]).new == (entry(),)


def test_the_question_records_the_text_hash_and_the_edited_scenario_is_asked_again(make_bench):
    other = listed(clause="the action field holds a value")
    bench = make_bench([red_listing(listed()), red_listing(other), red_listing(other)])
    assert run_task(bench.wb, TASK).status == "blocked"
    [raised] = bench.events("question.raised")
    [known] = [c for c in bench.wb.provider.criteria(bench.wb.ref) if c.id == KNOWN]
    assert raised["clause"] == {"criterion": KNOWN, "phase": "red", "text_sha": text_sha(known)}
    answer_all(bench)
    edit_scenario(bench)
    outcome = run_task(bench.wb, TASK)  # the answer was given for the old text: asked again
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-002"])
    assert len(bench.events("question.raised")) == 2 and bench.events("task.red_ok") == []
