"""A verdict question records the judges of the round that raised it (delegate-answers 3.1; L4-DLG-002, D3): the
delegate is never a mind that judged."""

from l4.config.loader import load_config
from l4.config.schema import L4Config, Profile
from l4.redact import Redactor
from l4.specs.questions import QuestionsFile
from l4.state.ledger import LedgerEvent
from l4.verifier.types import Finding, Severity
from l4.verifier.verdicts import raise_verdict_questions, round_judges

from ..implementer.conftest import green_step
from .test_ladder_depth import JUDGE, red_known_only  # noqa: F401

STAMP = "2026-10-18T10:00:00Z"
CFG = L4Config(
    profiles={
        "judge-opus": Profile(adapter="claude-code", model="claude-opus-5-5", vendor="anthropic"),
        "judge-sol": Profile(adapter="codex", model="gpt-6.1-sol", vendor="openai"),
        "judge-bare": Profile(adapter="fake", vendor="test"),
    }
)


def judged(seq: int, round_no: int, profile: str, model: str | None, **more) -> LedgerEvent:
    data = {"round": round_no, "profile": profile, "status": "ok", "calls": 1, "model": model, **more}
    return LedgerEvent(STAMP, "r-1", "u", seq, "verify.judge", data)


def test_the_judges_of_a_round_are_its_profiles_and_served_models():
    events = [
        judged(1, 1, "judge-sol", "gpt-6.1-sol"),  # an earlier round: not this question's
        judged(2, 2, "judge-opus", "claude-opus-5-5-20261001"),
        judged(3, 2, "judge-sol", None, part=1, parts=2),  # a panel's other part: the profile's configured model
        judged(4, 2, "judge-opus", "claude-opus-5-5-20261001"),  # the same judge twice is listed once
    ]
    assert round_judges(events, 2, CFG) == [
        {"profile": "judge-opus", "model": "claude-opus-5-5-20261001"},
        {"profile": "judge-sol", "model": "gpt-6.1-sol"},
    ]


def test_a_round_that_reused_the_judge_names_the_judge_of_the_round_it_reused():
    events = [judged(1, 1, "judge-sol", "gpt-6.1-sol"), judged(2, 2, "judge-opus", "claude-opus-5-5")]
    assert round_judges(events, 3, CFG) == [{"profile": "judge-opus", "model": "claude-opus-5-5"}]
    assert round_judges(events, 1, CFG) == [{"profile": "judge-sol", "model": "gpt-6.1-sol"}]


def test_a_judge_with_no_model_anywhere_is_recorded_with_none():
    assert round_judges([judged(1, 1, "judge-bare", None)], 1, CFG) == [{"profile": "judge-bare", "model": None}]
    assert round_judges([judged(1, 1, "gone", None)], 1, CFG) == [{"profile": "gone", "model": None}]


def test_a_round_with_no_judge_names_none():
    assert round_judges([], 1, CFG) == []


def test_raise_verdict_questions_puts_the_judges_on_every_event(tmp_path):
    class Sink:
        def __init__(self) -> None:
            self.events: list[dict] = []

        def append(self, event_type: str, /, **data) -> None:
            self.events.append({"type": event_type, **data})

    sink = Sink()
    judges = [{"profile": "judge-opus", "model": "claude-opus-5-5"}]
    finding = Finding(Severity.MAJOR, "Rounding is wrong", "half-up", "judge")
    ids = raise_verdict_questions(
        tmp_path, "add-x", outcomes=[], criteria=[], trace=[], findings=[finding], existing=None, consumed=(),
        ledger=sink, round_no=1, redactor=Redactor({}), judges=judges,
    )  # fmt: skip
    assert ids == ["Q-001"] and QuestionsFile.load(tmp_path / "questions.md") is not None
    [raised] = [e for e in sink.events if e["type"] == "question.raised"]
    assert raised["judges"] == judges


def test_a_verdict_question_records_the_judges(run_l4, valid_spec, tdd_repo):
    run = run_l4([red_known_only(), green_step(), JUDGE])
    assert run.code == 11
    [raised] = run.events("question.raised")
    [verify_judge] = run.events("verify.judge")
    configured = {name: profile.model for name, profile in load_config(tdd_repo.repo).profiles.items()}
    assert raised["judges"] == [
        {"profile": verify_judge["profile"], "model": verify_judge["model"] or configured[verify_judge["profile"]]}
    ]
