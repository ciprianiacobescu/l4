"""A rejected hold goes all the way: the round fails, the fix unit's chore task runs (a single phase, no red test) and
the next round passes, with the hold asked once (m1.x fix F1; live M1.6 job 5543 asked it again)."""

# ruff: noqa: F811  (the imported fixtures are used by name as test arguments)
import pytest

from l4.agents.fake import Step

from ..evidence._multi import FIXTURE
from ..forge.conftest import API, PROJECT, TOKEN
from ..implementer.conftest import result
from .test_ladder_evidence import (  # noqa: F401  (the fixtures of the evidence suite)
    EXTRA_FUNCTION,
    GREEN,
    TESTS,
    UNIT_DIR,
    _answer_holds,
    _no_shadow,
    evidence,
    green,
    judge,
    multi,
    red,
    run_multi,
)
from .test_ladder_evidence import STOCK as STOCK_EDIT

BASE_STOCK = (FIXTURE / "units/04-low-stock-alerts/green/src/inventory/stock.py").read_text()


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """Overrides the verifier suite's switch: here the fix hook runs the fix unit."""


def revert_stock() -> Step:
    """The fix unit's chore, as an agent does it: put the out-of-scope file back to what the base has."""
    return Step(writes={"src/inventory/stock.py": BASE_STOCK}, structured=result("single"))


def test_a_rejected_scope_hold_is_fixed_by_a_chore_task_and_round_3_passes(run_multi, multi, raw, monkeypatch):
    _no_shadow(monkeypatch)
    first = run_multi([red(), green(STOCK_EDIT), judge()])
    assert first.code == 11 and len(first.events("question.raised")) == 1
    _answer_holds(multi, raw, first, "reject: inventory is not part of this unit")
    second = run_multi([revert_stock(), judge()])
    assert second.code == 0, second.outcome
    assert [e["status"] for e in second.events("doctor.check")] == ["pass", "pass"]  # COV-001: once per run
    assert second.triggers()[-3:] == ["verify_fail_fix", "fix_unit_done", "verify_pass"]
    assert [e["verdict"] for e in second.events("verify.verdict")] == ["NEEDS_HUMAN", "FAIL", "PASS"]
    [spawned] = second.events("fix.spawned")
    assert spawned["consumed"] == ["Q-001"]
    [exempt] = second.events("task.tdd_exempt")  # a chore: one phase, no red test
    assert exempt["kind"] == "harness" and exempt["finding"] in spawned["findings"]
    assert len(second.events("question.raised")) == 1  # the hold was asked once, in round 1
    assert second.pushed("src/inventory/stock.py") == BASE_STOCK
    assert "Decided by human in Q-001" in second.pushed(f"{UNIT_DIR}-fix-1/proposal.md")


APPENDED = (
    TESTS
    + """

def test_describe_lists_quantities():
    from shop.cart import describe

    assert describe([(100, 2)]) == "2 x 100"
"""
)
NEW_FILE = "from shop.cart import describe\n\n\ndef test_describe_of_nothing():\n    assert describe([]) == 'empty'\n"


def test_a_rejected_coverage_hold_is_fixed_by_tests_without_a_question(run_multi, multi, raw, monkeypatch):
    """M1.11 W5 (live MF-1: the chore's prompt said "do not add tests" and Codex asked twice): the hold's fix task adds
    tests, a new file and a test appended to the unit's own file, and round 3 has no coverage hold."""
    _no_shadow(monkeypatch)
    first = run_multi([red(), green({"src/shop/cart.py": GREEN + EXTRA_FUNCTION}), judge()])
    assert first.code == 11 and len(first.events("question.raised")) == 1
    _answer_holds(multi, raw, first, "reject: describe needs tests, not removal")
    chore = Step(
        writes={"tests/test_cart.py": APPENDED, "tests/test_describe_more.py": NEW_FILE}, structured=result("single")
    )
    second = run_multi([chore, judge()])
    assert second.code == 0, second.outcome
    assert second.triggers()[-3:] == ["verify_fail_fix", "fix_unit_done", "verify_pass"]
    [added] = second.events("task.tests_added")
    assert added["files"] == ["tests/test_cart.py", "tests/test_describe_more.py"]
    assert added["tests"] == [
        "tests.test_cart::test_describe_lists_quantities",
        "tests.test_describe_more::test_describe_of_nothing",
    ]
    assert len(second.events("question.raised")) == 1  # no question about a "no-new-tests" constraint
    assert "Do not add tests" not in second.adapter.requests[0].prompt
    assert "Phase: SINGLE (add tests" in second.adapter.requests[0].prompt
    assert evidence(second, 3)["holds"] == []  # round 3: the changed code is run by a test now
    assert "test_describe_lists_quantities" in second.pushed("tests/test_cart.py")


# --- W9: `l4:needs-answers` goes when the answer is recorded, not at the chore's push (M1.11, decision 11) ---------

FIX_QUESTIONS = (
    {"title": "Which file is meant?", "context": "the finding names two", "kind": "ambiguous", "options": ["a", "b"]},
    {"title": "Keep the helper?", "context": "it is shared", "kind": "ambiguous", "options": ["yes", "no"]},
)


def blocked_chore(count: int) -> Step:
    return Step(structured=result("single", status="blocked", questions=list(FIX_QUESTIONS[:count])))


def answer_fix_question(multi, raw, qid: str, text: str) -> None:
    """A person answers a question of the fix unit, in the fix unit's own `questions.md` on the unit branch."""
    from l4.specs.questions import QuestionsFile, QuestionStatus

    clone = multi.repo.parent / f"fix-answer-{qid}"
    raw(multi.repo.parent, "clone", "-q", "--branch", "l4/openspec/cart-totals", str(multi.origin), str(clone))
    path = clone / "openspec/changes/cart-totals-fix-1/questions.md"
    file = QuestionsFile.load(path)
    assert file is not None
    file = file.set_status(qid, QuestionStatus("answered"))
    body = file.get(qid).answer.body  # type: ignore[union-attr]
    file = QuestionsFile.parse(file.data[: body.end] + text.encode() + b"\n" + file.data[body.end :])
    file.save(path)
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", f"answer {qid}")
    raw(clone, "push", "-q", "origin", "l4/openspec/cart-totals")
    raw(multi.repo, "fetch", "-q", "origin")


@pytest.fixture
def forge_world(multi, use_fake_gitlab, monkeypatch):
    """The multi-unit world with the fake GitLab behind the mirror, and the MR's labels at every agent call."""
    from l4.agents.fake import FakeAdapter

    multi.environ.update(GITLAB_CI="true", CI_API_V4_URL=API, CI_PROJECT_ID=PROJECT, L4_FORGE_TOKEN=TOKEN)
    seen: list[list[str]] = []
    real = FakeAdapter.run

    def spy(self, req):
        if req.role == "implementer" and use_fake_gitlab.mrs:
            seen.append(sorted(use_fake_gitlab.mrs[1]["labels"]))
        return real(self, req)

    monkeypatch.setattr(FakeAdapter, "run", spy)
    return use_fake_gitlab, seen


def blocked_fix_unit(run_multi, multi, raw, monkeypatch, count: int):
    _no_shadow(monkeypatch)
    first = run_multi([red(), green(STOCK_EDIT), judge()])
    assert first.code == 11
    _answer_holds(multi, raw, first, "reject: inventory is not part of this unit")
    second = run_multi([blocked_chore(count)])
    assert second.code == 11 and [e["id"] for e in second.events("question.raised")][-count:]
    return second


def test_needs_answers_goes_when_the_fix_units_answer_is_recorded(run_multi, multi, raw, monkeypatch, forge_world):
    gitlab, seen = forge_world
    blocked_fix_unit(run_multi, multi, raw, monkeypatch, 1)
    assert "l4:needs-answers" in gitlab.mrs[1]["labels"]  # the question of the fix unit waits for a person
    answer_fix_question(multi, raw, "Q-001", "Use file a.")
    third = run_multi([revert_stock(), judge()])
    assert third.code == 0, third.outcome
    first_step = seen[-1]  # the labels the MR had when the chore's agent was called in the last run
    assert "l4:needs-answers" not in first_step, seen
    assert "l4:needs-answers" not in gitlab.mrs[1]["labels"]


def test_needs_answers_stays_while_another_question_is_open(run_multi, multi, raw, monkeypatch, forge_world):
    gitlab, seen = forge_world
    blocked_fix_unit(run_multi, multi, raw, monkeypatch, 2)
    answer_fix_question(multi, raw, "Q-001", "Use file a.")  # Q-002 is still open
    third = run_multi([blocked_chore(1)])
    assert third.code == 11
    assert "l4:needs-answers" in gitlab.mrs[1]["labels"]
