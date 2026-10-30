"""A verdict question counts only in the attempt that raised it (SPEC L4-VER-070, SCN-VER-257..260). A consumer unit
after `l4 restart` kept three answered verdict questions in `questions.md` while the old ledgers were dropped: the
answers read as `ready`, every run verified again, and nothing was ever asked anew. The fixtures here build that state
the way the restart leaves it: a real unit that waits on a real verdict question, whose ledger no longer names the
question and whose answer stays in `questions.md`."""

import json

import pytest

from l4.specs.questions import QuestionsFile, QuestionStatus
from l4.verifier import ladder

from ..archive.conftest import forge_env, use_fake_gitlab  # noqa: F401
from ..forge.conftest import gitlab  # noqa: F401, F811
from ..implementer.conftest import green_step
from ..orchestrator.conftest import BRANCH, UNIT_DIR, edit_questions_on_origin
from .test_ladder_depth import JUDGE, red_known_only

QUESTIONS = f"{UNIT_DIR}/questions.md"


def carry_over(tdd_repo, raw, *, answer: str = "accept: fine", qid: str = "Q-001") -> None:
    """What `l4 restart` of an older harness left: the verdict question is answered in `questions.md`, and no
    `question.raised` of the unit's ledgers names it (the old attempt's ledgers are gone)."""
    clone = tdd_repo.repo.parent / "carried"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
    unit = clone / UNIT_DIR
    for path in (unit / ".l4" / "ledger").glob("*.jsonl"):
        events = [json.loads(line) for line in path.read_text().splitlines()]
        kept = [e for e in events if not (e["type"] == "question.raised" and e.get("kind") == "verdict")]
        assert len(kept) < len(events)
        for seq, event in enumerate(kept, 1):
            event["seq"] = seq
        path.write_text("".join(json.dumps(e) + "\n" for e in kept))
    file = QuestionsFile.load(unit / "questions.md")
    assert file is not None
    file = file.set_status(qid, QuestionStatus.ANSWERED)
    body = file.get(qid).answer.body  # type: ignore[union-attr]
    file = QuestionsFile.parse(file.data[: body.end] + answer.encode() + b"\n" + file.data[body.end :])
    file.save(unit / "questions.md")
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", "as a restart of an older harness left it")
    raw(clone, "push", "-q", "origin", BRANCH)
    raw(tdd_repo.repo, "fetch", "-q", "origin")


def verdict_questions(run) -> dict[str, tuple[str, str]]:
    file = QuestionsFile.parse(run.pushed(QUESTIONS))
    return {q.id: (q.status.value, q.kind.value if q.kind else "") for q in file.questions}


@pytest.fixture
def carried(run_l4, valid_spec, tdd_repo, raw):
    """Round 1 NEEDS_HUMAN on the criterion nothing traces (Q-001), then Q-001 answered `accept: fine` and unnamed."""
    first = run_l4([red_known_only(), green_step(), JUDGE])
    assert first.code == 11
    [asked] = first.events("question.raised")
    assert (asked["id"], asked["kind"]) == ("Q-001", "verdict")
    judged = len(first.events("verify.judge"))
    carry_over(tdd_repo, raw)
    return asked["target"], judged


def test_scn_ver_257_a_carried_over_answer_does_not_make_the_unit_verify_again(carried, run_l4, tdd_repo, raw):
    target, judged = carried
    run = run_l4([])
    assert run.code == 11 and run.adapter.requests == []
    assert "verdicts_answered" not in run.triggers() and run.events("human.verdict") == []
    # events are cumulative over the runs of the unit: the judge calls and rounds are the first attempt's, no more
    assert len(run.events("verify.judge")) == judged and judged >= 1, "a judge was called for a carried-over answer"
    assert [e["round"] for e in run.events("verify.verdict")] == [1]  # no new round
    [asked] = run.events("question.raised")  # the first run's Q-001 was taken out of the ledger by the fixture
    assert (asked["kind"], asked["target"], asked["id"]) == ("verdict", target, "Q-002")
    questions = verdict_questions(run)
    assert (questions["Q-001"][0], questions["Q-002"][0]) == ("answered", "open")


def test_scn_ver_258_an_answer_to_a_question_this_attempt_raised_is_consumed_as_before(carried, run_l4, tdd_repo, raw):
    target, _ = carried
    assert run_l4([]).code == 11  # raises Q-002
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="accept: fine", qid="Q-002")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    run = run_l4([], unit=False)
    assert [(v["question"], v["target"], v["decision"]) for v in run.events("human.verdict")] == [
        ("Q-002", target, "accept")
    ]
    assert [e["id"] for e in run.events("question.raised")] == ["Q-002"]  # Q-001 is not asked again, nothing new
    assert run.code == 0 and run.outcome["units"][0]["verdict"] == "PASS"


def test_a_stale_question_is_not_the_delegate_s_and_the_plan_says_verify(carried, run_l4, tdd_repo, capsys):
    from l4.cli import main

    capsys.readouterr()
    assert main(["plan", "--json", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 0
    [unit] = json.loads(capsys.readouterr().out)["units"]
    assert (unit["phase"], unit["next_action"], unit["actionable"]) == ("awaiting_human", "verify", True)
    assert unit["reason"].startswith("legacy round 1: NEEDS_HUMAN without verdict questions")
    assert "verdicts answered" not in unit["reason"]


def test_the_sticky_note_asks_for_the_new_question_only(carried, run_l4, forge_env, use_fake_gitlab):  # noqa: F811
    fake = use_fake_gitlab
    run = run_l4([])
    assert run.code == 11
    assert sorted(fake.mrs[1]["labels"]) == ["l4:awaiting_human", "l4:needs-answers"]
    note = fake.notes[1][-1]["body"]
    assert "Q-002" in note and "Q-001" not in note and "Start each answer with `accept` or `reject`" in note


def test_scn_ver_260_a_unit_that_already_loops_stops_on_the_fixed_harness(carried, run_l4, tdd_repo, raw, monkeypatch):
    target, _ = carried
    from l4 import orchestrator

    # Three rounds as the unfixed harness ran them: the carried-over answer reads as ready, the unit verifies again
    # (the old rule), and the round asks nothing new because the answer reads as still waiting.
    old_rule = lambda self: ["Q-001"]  # noqa: E731
    with monkeypatch.context() as patch:
        patch.setattr(orchestrator.Orchestrator, "_verdicts_ready", old_rule)
        patch.setattr(ladder, "raise_verdict_questions", lambda *a, **k: [])
        for _ in range(2):
            looping = run_l4([JUDGE])
            assert looping.code == 11
    rounds = [e["verdict"] for e in looping.events("verify.verdict")]
    assert rounds == ["NEEDS_HUMAN"] * 3 and looping.events("question.raised") == []  # round 1, then the two loops
    judged = len(looping.events("verify.judge"))
    fixed = run_l4([])
    assert fixed.code == 11 and fixed.adapter.requests == []
    assert len(fixed.events("verify.judge")) == judged  # no judge call of this run
    assert len(fixed.events("verify.verdict")) == len(looping.events("verify.verdict"))  # no new round
    [asked] = fixed.events("question.raised")
    assert (asked["kind"], asked["target"]) == ("verdict", target)
    assert verdict_questions(fixed)[asked["id"]] == ("open", "verdict")
