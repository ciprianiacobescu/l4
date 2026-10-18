"""An inconclusive check holds the task (L4-IMP-063, L4-IMP-017; SCN-IMP-305, 310, 312, 313): no attempt is counted,
no profile escalates, one question of the kind `harness` is raised and the changes of the step are discarded."""

from l4.agents.fake import Step
from l4.implementer import loop, tdd
from l4.implementer.base_run import BaseRunResult
from l4.implementer.discrimination import AtRed, PreSatisfied
from l4.implementer.loop import run_task
from l4.implementer.tdd import run_red
from l4.specs.questions import QuestionKind, QuestionsFile, QuestionStatus

from .conftest import KNOWN, UNKNOWN, Bench, result
from .test_earlier_red import OTHER, TASK, commit_old
from .test_escalation import BAD, TWO, Hook
from .test_tdd_green import TASK as GREEN_TASK
from .test_tdd_green import answer_naming, two_test_red

REASON = (
    "the test-presatisfied run ran no test (exit 2, 45 collection errors): E   TypeError: 'NoneType' object is not "
    "callable"
)
EXEMPTION = {"reason": "already_satisfied by 0.9"}


def no_test(*criteria: str) -> Step:
    return Step(structured=result("red", criteria_ids=list(criteria or (KNOWN,)), tdd_exemption=EXEMPTION))


def zero_says(monkeypatch, *, refuted: tuple[str, ...] = ()) -> None:
    """The zero-value run refutes the criteria in `refuted` and cannot decide the others; the base run confirms none."""

    def confirm(wb, candidates, *, real=None):
        return PreSatisfied(
            unconfirmed={c: tuple(t) for c, t in candidates.items() if c in refuted},
            inconclusive={c: REASON for c in candidates if c not in refuted},
        )

    monkeypatch.setattr(tdd, "confirm_pre_satisfied", confirm)
    monkeypatch.setattr(
        tdd,
        "confirmed_by_base_run",
        lambda wb, cands, ids, *, real=None: BaseRunResult(reason="none of its new tests fails by assertion"),
    )


def held_bench(make_bench, script: list[Step], **config) -> Bench:
    bench: Bench = make_bench(script, **config)
    commit_old(bench)  # the test exists and passes; no earlier red saw it fail
    return bench


def test_scn_imp_312_an_inconclusive_presatisfied_check_consumes_no_attempt(make_bench, monkeypatch):
    zero_says(monkeypatch)
    bench = held_bench(make_bench, [no_test(), no_test()], implementer={"escalate_after": 2}, **TWO)
    hook = Hook()
    outcome = run_task(bench.wb, TASK, escalate=hook)
    assert (outcome.status, outcome.reason) == ("blocked", "red") and len(outcome.question_ids) == 1
    qid = outcome.question_ids[0]
    assert bench.events("task.attempt_failed") == [] and bench.events("implementer.escalated") == []
    assert hook.requests == [] and len(bench.adapter.requests) == 1
    [held] = bench.events("check.inconclusive")
    assert (held["task"], held["phase"], held["check"], held["question"]) == ("1.1", "red", "pre_satisfied", qid)
    assert held["criteria"] == [KNOWN] and held["tests"] == ["tests.test_old::test_old_total"]
    assert held["reason"] == REASON and held["runs"] and held["kept"] == []
    [raised] = bench.events("question.raised")
    assert (raised["id"], raised["kind"], raised["check"], raised["criteria"]) == (
        qid,
        "harness",
        "pre_satisfied",
        [KNOWN],
    )
    file = QuestionsFile.load(bench.wb.ref.path / "questions.md")
    question = file.get(qid)
    assert question.kind is QuestionKind.HARNESS and question.status is QuestionStatus.OPEN
    assert question.blocking_tasks == ("1.1",)
    text = (bench.wb.ref.path / "questions.md").read_text()
    assert "- **Kind:** harness" in text and f"- **Criteria:** {KNOWN}" in text and REASON in text
    assert "accept: count these on the evidence of the real run" in text and "retry: run the check again" in text
    assert bench.wb.is_clean()  # the step's changes are discarded


def test_scn_imp_313_an_inconclusive_check_starts_no_escalation(make_bench, monkeypatch):
    zero_says(monkeypatch)
    bench = held_bench(make_bench, [BAD, no_test()], implementer={"escalate_after": 2}, **TWO)
    hook = Hook()
    outcome = run_task(bench.wb, TASK, escalate=hook)
    assert outcome.status == "blocked"
    assert len(bench.events("task.attempt_failed")) == 1  # only the first
    assert hook.requests == [] and bench.events("implementer.escalated") == []


def test_scn_imp_310_a_refuted_criterion_fails_the_attempt_beside_an_inconclusive_one(make_bench, monkeypatch):
    zero_says(monkeypatch, refuted=(KNOWN,))
    bench: Bench = make_bench([no_test(KNOWN, UNKNOWN)], implementer={"max_task_attempts": 1})
    commit_old(bench)
    (bench.wb.worktree / "tests" / "test_other.py").write_text(OTHER)
    bench.wb.git.run("add", "tests/test_other.py")
    bench.wb.commit("test: other", task="0.9", attempt=1, phase="red", tdd="red")
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt"  # a counted failure: the one attempt allowed was used
    [failed] = bench.events("task.attempt_failed")
    assert f"not discriminating: {KNOWN}" in failed["reason"] and f"inconclusive: {UNKNOWN}" in failed["reason"]
    assert bench.events("question.raised") == [] and bench.events("check.inconclusive") == []


def test_scn_imp_305_an_inconclusive_test_at_red_run_holds_the_green_step(make_bench, raw, monkeypatch):
    bench = make_bench([two_test_red(), Step(structured=result("green"))])
    red = run_red(bench.wb, GREEN_TASK, attempt=1)
    assert red.status == "ok", red.reason
    answer_naming(bench, raw, "Change `tests/test_discount.py`.")
    reason = "the test-at-red run ran no test (exit 2, 0 collection errors)"
    monkeypatch.setattr(tdd, "fails_at_red", lambda *a, **k: AtRed([], reason))
    monkeypatch.setattr(loop, "resume_red", lambda wb, task: red)  # the red commit is the last checkpoint, as in a run
    outcome = run_task(bench.wb, GREEN_TASK)
    assert (outcome.status, outcome.reason) == ("blocked", "green") and len(outcome.question_ids) == 1
    assert bench.events("task.attempt_failed") == [] and bench.events("task.done") == []
    [held] = bench.events("check.inconclusive")
    assert (held["phase"], held["check"], held["reason"]) == ("green", "at_red", reason)
    assert held["tests"] and all(t.startswith("tests.test_discount::") for t in held["tests"])
    [raised] = bench.events("question.raised")[-1:]
    assert raised["kind"] == "harness" and raised["check"] == "at_red" and raised["tests"] == held["tests"]
    assert bench.wb.head() == red.sha  # the red commit stays
