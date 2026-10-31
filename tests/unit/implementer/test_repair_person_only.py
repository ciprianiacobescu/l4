"""own-test-repair (L4-IMP-091, design D4): only a person's `accept` applies a repair of a test. An accept recorded
`by: agent` or `by: delegate` gives no override for a `repair` question, whatever the configuration says, the run says
so once, and the saved edit is never replayed; the other held checks keep their rule."""

import pytest

from l4.implementer.held import accepted_overrides
from l4.implementer.tdd import run_single
from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, QuestionStatus, answer_sha256, raise_questions

from .test_held_accept import commit_all
from .test_repair_step import E2E_FINDING, E2E_FIXED, TASK, X, accept, e2e_bench, hold, repair_step

ASKED = "2026-10-16T10:00:00Z by implementer `codex`, run r-20261016T1000Z-aaaa, task 1.1"


def answer_by(bench, raw, qid: str, by: str, text: str = "accept: apply this edit") -> str:
    """The answer of `qid` is committed and `question.answered` records who gave it."""
    unit = bench.wb.ref.path
    file = QuestionsFile.load(unit / "questions.md").set_answer(qid, text).set_status(qid, QuestionStatus.ANSWERED)
    file.save(unit / "questions.md")
    commit_all(bench, raw, f"answer {qid}")
    digest = answer_sha256(QuestionsFile.load(unit / "questions.md").get(qid))
    bench.wb.emit("question.answered", id=qid, by=by, answer_sha256=digest)
    return digest


def repair_bench(make_bench, monkeypatch):
    bench, _ = e2e_bench(make_bench, monkeypatch, [repair_step({"e2e/check_a.py": E2E_FIXED})] * 3)
    return bench


@pytest.mark.parametrize("by", ["agent", "delegate"])
def test_an_accept_by_an_agent_or_the_delegate_gives_no_override_for_a_repair(
    make_bench, monkeypatch, raw, by
):  # SCN-IMP-473
    bench = repair_bench(make_bench, monkeypatch)
    answer_by(bench, raw, hold(bench), by)
    assert accepted_overrides(bench.wb, "1.1", "repair", for_replay=True) == {}
    assert accepted_overrides(bench.wb, "1.1", "repair") == {}


def test_a_persons_accept_gives_the_override_for_the_repaired_tests(make_bench, monkeypatch, raw):  # SCN-IMP-471
    bench = repair_bench(make_bench, monkeypatch)
    qid = hold(bench)
    answer_by(bench, raw, qid, "human")
    found = accepted_overrides(bench.wb, "1.1", "repair", for_replay=True)
    assert set(found) == {X} and found[X].question == qid and found[X].by == "human"


@pytest.mark.parametrize("by", ["agent", "delegate"])
def test_an_accept_by_another_actor_replays_nothing_and_is_recorded_once(
    make_bench, monkeypatch, raw, by
):  # SCN-IMP-473
    bench = repair_bench(make_bench, monkeypatch)
    qid = hold(bench)
    patch = bench.wb.ref.path / ".l4" / "held" / "1.1-repair.patch"
    answer_by(bench, raw, qid, by)
    before = bench.wb.head()
    first = run_single(bench.wb, TASK, [E2E_FINDING], attempt=2, kind="repair")
    second = run_single(bench.wb, TASK, [E2E_FINDING], attempt=3, kind="repair")
    assert bench.events("held.replayed") == [] and bench.events("task.repaired") == []  # nothing was applied
    assert bench.events("task.done") == [] and bench.wb.head() == before  # nothing was committed
    ignored = bench.events("held.accept_ignored")
    assert [(e["question"], e["task"], e["check"], e["by"]) for e in ignored] == [(qid, "1.1", "repair", by)]
    assert (first.status, second.status) == ("held", "held")  # a new proposal each time: a person decides
    assert len(bench.adapter.requests) == 3  # the agent ran again; the accept replayed nothing
    assert patch.is_file()  # the saved edit stays for a person's answer: it was not queued for removal


def test_an_accept_by_an_agent_is_not_a_person_whatever_the_questions_file_says(make_bench, monkeypatch, raw):
    """The ledger names who answered; the file alone (Status answered, accept) is not enough for a repair."""
    bench = repair_bench(make_bench, monkeypatch)
    qid = hold(bench)
    unit = bench.wb.ref.path
    QuestionsFile.load(unit / "questions.md").set_answer(qid, "accept: ok").set_status(
        qid, QuestionStatus.ANSWERED
    ).save(unit / "questions.md")  # no `question.answered` record at all
    commit_all(bench, raw, "answer")
    assert accepted_overrides(bench.wb, "1.1", "repair", for_replay=True) == {}


# --- the other held checks keep their rule --------------------------------------------------------------------------


def raise_other(bench, check: str, subjects: dict[str, list[str]]) -> str:
    """A harness question of another check, raised as the loop raises it (no saved step: the rule by id)."""
    [qid] = raise_questions(
        bench.wb.ref.path,
        bench.wb.ref.name,
        [
            NewQuestion(
                title=f"Task 1.1: the {check} check could not decide",
                kind=QuestionKind.HARNESS,
                blocking_tasks=("1.1",),
                context="c",
                asked=ASKED,
                options=("accept: x", "retry: y"),
            )
        ],
        redactor=bench.wb.redactor,
    )
    bench.wb.emit(
        "question.raised", id=qid, task="1.1", kind="harness", title="t", check=check,
        criteria=subjects.get("criteria", []), tests=subjects.get("tests", []),
    )  # fmt: skip
    return qid


OTHERS = [
    ("pre_satisfied", {"criteria": ["C-1"]}, "C-1"),
    ("vacuity", {"criteria": ["C-1"]}, "C-1"),
    ("at_red", {"tests": ["tests.test_x::test_a"]}, "tests.test_x::test_a"),
    ("tests", {"tests": ["tests.test_x::test_a"]}, "tests.test_x::test_a"),
]


@pytest.mark.parametrize("by", ["human", "agent", "delegate"])
@pytest.mark.parametrize(("check", "subjects", "subject"), OTHERS)
def test_the_other_checks_count_an_accept_whoever_gave_it(make_bench, monkeypatch, raw, check, subjects, subject, by):
    bench = repair_bench(make_bench, monkeypatch)
    qid = raise_other(bench, check, subjects)
    answer_by(bench, raw, qid, by, "accept: the run cannot decide")
    found = accepted_overrides(bench.wb, "1.1", check)  # type: ignore[arg-type]
    assert set(found) == {subject} and found[subject].question == qid and found[subject].by == by


def test_a_persons_accept_still_replays_after_the_ignored_ones_are_out_of_the_way(make_bench, monkeypatch, raw):
    """A new question after an ignored accept is answered by a person: that one replays."""
    bench = repair_bench(make_bench, monkeypatch)
    first = hold(bench)
    answer_by(bench, raw, first, "agent")
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=2, kind="repair")
    assert done.status == "held" and done.held is not None
    from l4.implementer import loop

    [second] = loop._raise_held(bench.wb, TASK, done.held, 2)
    accept(bench, raw, second)
    replay = run_single(bench.wb, TASK, [E2E_FINDING], attempt=3, kind="repair")
    assert replay.status == "ok", replay.reason
    [replayed] = bench.events("held.replayed")
    assert replayed["question"] == second
