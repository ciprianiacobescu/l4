"""A delegate's accepted suggestion unfreezes a frozen file with its own label (delegate-answers 6.2; L4-DLG-014,
design D15; SCN-DLG-55)."""

from datetime import UTC, datetime

from l4.implementer.guards import FreezeManifest, FrozenFile
from l4.implementer.tdd import run_green, run_red
from l4.implementer.unfreeze import unfrozen
from l4.redact import Redactor
from l4.specs.questions import (
    NewQuestion,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    answer_sha256,
    raise_questions,
)
from l4.state.ledger import LedgerEvent

from .test_tdd_green import CORRECTED, IMPL, TASK, Step, result, two_test_red

TEST = "tests/test_notices.py"
MANIFEST = FreezeManifest(
    "r" * 40,
    {TEST: FrozenFile("a" * 64, "test"), "tests/conftest.py": FrozenFile("c" * 64, "support")},
    ("**/conftest.py",),
)
SCOPE = frozenset({"1.1", "1"})
SUGGESTION = f"Change `{TEST}:8` to expect the 30-day wording."


def asked(tmp_path, status: QuestionStatus = QuestionStatus.ACCEPTED, *, suggestion: str = SUGGESTION):
    raise_questions(
        tmp_path,
        "add-x",
        [
            NewQuestion(
                "The test freezes a wrong constant", QuestionKind.TECHNICAL, ("1.1",), f"`{TEST}` is bad.", "now"
            )
        ],
        redactor=Redactor({}),
    )
    file = QuestionsFile.load(tmp_path / "questions.md").set_suggestion("Q-001", suggestion, redactor=Redactor({}))
    return file.set_status("Q-001", status)


def answered(file, by: str, *, profile: str | None = "delegate-opus", model: str | None = "claude-opus-5-5"):
    data = {"id": "Q-001", "by": by, "answer_sha256": answer_sha256(file.get("Q-001"))}
    if by == "delegate":
        data.update(profile=profile, model=model)
    return [
        LedgerEvent(
            datetime(2026, 10, 18, tzinfo=UTC), "r-20261018T0000Z-0001", "openspec:add-x", 1, "question.answered", data
        )
    ]


def test_a_delegate_accept_makes_a_delegate_grant(tmp_path):
    file = asked(tmp_path)
    got = unfrozen(file.questions, answered(file, "delegate"), SCOPE, MANIFEST, delegate_unfreeze=True)
    assert got.paths == (TEST,) and got.question == "Q-001"
    [grant] = got.grants
    assert (grant.reason, grant.by, grant.profile, grant.model) == (
        "delegate_answer",
        "delegate",
        "delegate-opus",
        "claude-opus-5-5",
    )
    assert grant.answer_sha256 == answer_sha256(file.get("Q-001"))


def test_without_the_base_branch_switch_a_delegate_answer_unfreezes_nothing(tmp_path):
    file = asked(tmp_path)
    assert unfrozen(file.questions, answered(file, "delegate"), SCOPE, MANIFEST).paths == ()
    assert unfrozen(file.questions, answered(file, "delegate"), SCOPE, MANIFEST, delegate_unfreeze=False).paths == ()


def test_only_the_accepted_suggestion_of_a_delegate_counts(tmp_path):
    free = asked(tmp_path, QuestionStatus.ANSWERED)  # a free-text answer of the delegate
    assert unfrozen(free.questions, answered(free, "delegate"), SCOPE, MANIFEST, delegate_unfreeze=True).paths == ()
    edited = asked(tmp_path / "e") if (tmp_path / "e").mkdir() is None else None
    events = answered(edited, "delegate")
    changed = edited.set_suggestion("Q-001", SUGGESTION + " And tests/conftest.py.", redactor=Redactor({}))
    assert unfrozen(changed.questions, events, SCOPE, MANIFEST, delegate_unfreeze=True).paths == ()  # digest differs


def test_a_person_still_wins_the_label(tmp_path):
    file = asked(tmp_path)
    got = unfrozen(file.questions, answered(file, "human"), SCOPE, MANIFEST, delegate_unfreeze=True)
    assert got.paths == (TEST,) and [g.reason for g in got.grants] == ["human_answer"]


def record_delegate(bench, raw, *, unfreeze: bool) -> None:
    """The delegate accepted a clarifier suggestion that names the test, and the pass recorded it."""
    unit = bench.wb.ref.path
    raise_questions(
        unit,
        "add-discount-codes",
        [
            NewQuestion(
                "The test freezes a wrong value",
                QuestionKind.TECHNICAL,
                ("1.1",),
                "tests/test_discount.py:9 expects 45.0 for 50.0",
                "now",
                ("a", "b"),
            )
        ],
        redactor=Redactor({}),
    )
    file = QuestionsFile.load(unit / "questions.md")
    file = file.set_suggestion(
        "Q-001", "Change `tests/test_discount.py:9` to use a 100.0 amount.", redactor=Redactor({})
    )
    file.set_status("Q-001", QuestionStatus.ACCEPTED).save(unit / "questions.md")
    raw(bench.wb.worktree, "add", "-A")
    raw(bench.wb.worktree, "-c", "user.name=L4", "-c", "user.email=l4@example.invalid", "commit", "-q", "-m", "answer")
    digest = answer_sha256(QuestionsFile.load(unit / "questions.md").get("Q-001"))
    bench.writer.append(
        "question.answered",
        id="Q-001",
        by="delegate",
        profile="delegate-opus",
        model="claude-opus-5-5",
        answer_sha256=digest,
    )
    bench.wb.cfg = bench.wb.cfg.model_copy(
        update={"delegate": bench.wb.cfg.delegate.model_copy(update={"unfreeze": unfreeze})}
    )


def test_a_delegate_accept_unfreezes_with_its_label(make_bench, raw):  # SCN-DLG-55
    fix = Step(writes={"tests/test_discount.py": CORRECTED, "src/pytdd/pricing.py": IMPL}, structured=result("green"))
    bench = make_bench([two_test_red(), fix])
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    record_delegate(bench, raw, unfreeze=True)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    assert (bench.wb.worktree / "tests" / "test_discount.py").read_text() == CORRECTED  # kept, not restored
    [event] = bench.events("task.unfrozen")
    assert event["reason"] == "delegate_answer" and event["by"] == "delegate" and event["question"] == "Q-001"
    assert event["profile"] == "delegate-opus" and event["model"] == "claude-opus-5-5"
    assert event["paths"] == ["tests/test_discount.py"] and len(event["answer_sha256"]) == 64
    assert event["red_sha"] == red.sha


def test_with_the_switch_off_the_file_stays_frozen(make_bench, raw):
    fix = Step(writes={"tests/test_discount.py": CORRECTED, "src/pytdd/pricing.py": IMPL}, structured=result("green"))
    bench = make_bench([two_test_red(), fix])
    red = run_red(bench.wb, TASK, attempt=1)
    record_delegate(bench, raw, unfreeze=False)
    run_green(bench.wb, TASK, red, attempt=1)
    assert bench.events("task.unfrozen") == []
    assert (bench.wb.worktree / "tests" / "test_discount.py").read_text() != CORRECTED  # restored
