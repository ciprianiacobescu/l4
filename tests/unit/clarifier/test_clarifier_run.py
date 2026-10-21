from pathlib import Path

import pytest

from l4.clarifier.backend import BackendClarifier
from l4.clarifier.clarifier import Clarifier, clarified_ids
from l4.clarifier.context import ClarifierPrompt
from l4.clarifier.ports import QuestionView, SpecQuestionsPort
from l4.clarifier.router import AskJudge, Router, S1Query, S1Unavailable
from l4.config.schema import ClarifierCfg, S1Cfg
from l4.llm.agent_judge import StructuredResult
from l4.redact import Redactor
from l4.specs.base import Task
from l4.specs.openspec import parse_openspec_tasks
from l4.specs.questions import (
    NewQuestion,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    answer_sha256,
    raise_questions,
)
from l4.state.ledger import LedgerWriter, read_ledger

from .conftest import ScriptedBackend, limit_run, ok

UNIT = "openspec:add-x"
REDACTOR = Redactor({})
TASKS = parse_openspec_tasks(b"- [ ] 1.1 a\n- [ ] 1.2 b\n- [ ] 1.3 c\n- [ ] 1.4 d\n")
QUOTE = "RATE_BP = 1900  # basis points"


class FakeS1(AskJudge):
    source = "llm_boolean"

    def __init__(self, *replies: float | Exception) -> None:
        self.replies = list(replies)

    def ask(self, query: S1Query) -> float:
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def reply(qid: str, **over) -> dict:
    base = {
        "question_id": qid, "answer": "Use basis points.", "confidence": "high", "kind": "technical",
        "citations": [{"ref": "src/vat.py#L1", "quote": QUOTE, "claim": "c"}], "rationale": "r",
    }  # fmt: skip
    return {**base, **over}


class Setup:
    def __init__(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.repo = tmp_path
        self.unit = tmp_path / "openspec" / "changes" / "add-x"
        self.unit.mkdir(parents=True)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "vat.py").write_text(QUOTE + "\n")
        self.writer = LedgerWriter.open(self.unit, UNIT, "r-20261004T0100Z-0001", redactor=REDACTOR)

    def ask(self, kind: QuestionKind, task: str, title: str = "Which type?") -> None:
        raise_questions(
            self.unit, "add-x", [NewQuestion(title, kind, (task,), "ctx", "asked")], redactor=REDACTOR
        )  # fmt: skip

    def port(self) -> SpecQuestionsPort:
        path = self.unit / "questions.md"
        return SpecQuestionsPort(path, QuestionsFile.parse(path.read_bytes()), redactor=REDACTOR)

    def run(
        self, backend: ScriptedBackend, s1: FakeS1, *, cfg: ClarifierCfg | None = None, tasks: list[Task] = TASKS,
        extra_blocking: tuple[str, ...] = (),
    ):  # fmt: skip
        cfg = cfg or ClarifierCfg()
        port = self.port()
        prompts: list[str] = []

        def prompt_for(view: QuestionView) -> ClarifierPrompt:
            prompts.append(view.id)
            return ClarifierPrompt("SYSTEM", f"USER {view.id}", "0" * 64, "clarifier@1")

        blocking = [q.id for q in port.load() if q.status is QuestionStatus.OPEN] + list(extra_blocking)
        outcome = Clarifier(self.unit, self.writer).run(
            port, prompt_for=prompt_for, answerer=BackendClarifier(backend, redact=lambda t: t),
            router=Router(cfg, S1Cfg(), s1, [self.unit, self.repo]), cfg=cfg, profile="claude", blocking=blocking,
            location=("openspec/changes/add-x/questions.md", "l4/openspec/add-x"), link=None,
        )  # fmt: skip
        self.writer.finish(0)
        return outcome, prompts

    def events(self, *types: str) -> list[dict]:
        return [{"type": e.type, **e.data} for e in read_ledger(self.unit).events if e.type in types]

    def file(self) -> QuestionsFile:
        file = QuestionsFile.load(self.unit / "questions.md")
        assert file is not None
        return file


@pytest.fixture
def s(tmp_path: Path) -> Setup:
    return Setup(tmp_path)


def test_auto_accept_returns_implementing_and_suggestion_returns_awaiting_human(s: Setup):
    s.ask(QuestionKind.TECHNICAL, "1.1")
    outcome, _ = s.run(ScriptedBackend(ok(reply("Q-001"))), FakeS1(0.0, 1.0))
    assert (outcome.next_phase, outcome.exit_code, outcome.sticky_section) == ("implementing", 0, None)
    question = s.file().get("Q-001")
    assert question is not None and question.status is QuestionStatus.ANSWERED_BY_CLARIFIER
    assert "confidence: high · kind: technical (S1 p=0.00)" in question.suggestion_text
    assert "Use basis points." in question.suggestion_text and "RATE_BP = 1900" in question.suggestion_text
    assert outcome.results["Q-001"].status == "answered-by-clarifier"

    other = Setup(s.repo / "second")  # a product question: a suggestion, Status stays open
    other.ask(QuestionKind.PRODUCT, "1.1", "Which rate?")
    held, _ = other.run(ScriptedBackend(ok(reply("Q-001", kind="product", confidence="medium"))), FakeS1())
    assert (held.next_phase, held.exit_code) == ("awaiting_human", 11)
    assert held.sticky_section is not None and "- Q-001 (product): Which rate?" in held.sticky_section
    product = other.file().get("Q-001")
    assert product is not None and product.status is QuestionStatus.OPEN
    assert "needs a human" in product.suggestion_text and "Use basis points." in product.suggestion_text
    assert held.results["Q-001"].suggestion is not None and held.results["Q-001"].reasons


def test_verdict_questions_skipped_and_batch_capped(s: Setup):
    s.ask(QuestionKind.TECHNICAL, "1.1")
    s.ask(QuestionKind.VERDICT, "1.2", "Accept the run?")
    for task in ("1.3", "1.4"):
        s.ask(QuestionKind.TECHNICAL, task)
    backend = ScriptedBackend(ok(reply("Q-001")), ok(reply("Q-003")))
    outcome, prompts = s.run(backend, FakeS1(0.0, 1.0, 0.0, 1.0), cfg=ClarifierCfg(max_open_questions=2))
    assert prompts == ["Q-001", "Q-003"] and len(backend.calls) == 2  # the verdict one is not the clarifier's
    assert sorted(outcome.results) == ["Q-001", "Q-003"]
    assert sorted(clarified_ids(read_ledger(s.unit).events)) == ["Q-001", "Q-003"]  # Q-004 waits for a later pass
    assert (outcome.next_phase, outcome.exit_code) == ("awaiting_human", 11)  # Q-002 and Q-004 are still open


def test_unavailable_clarifier_exit_11_not_12(s: Setup):
    s.ask(QuestionKind.TECHNICAL, "1.1")
    s.ask(QuestionKind.TECHNICAL, "1.2")
    backend = ScriptedBackend(StructuredResult("limit", detail="usage limit", run=limit_run()))
    outcome, _ = s.run(backend, FakeS1())
    assert (outcome.next_phase, outcome.exit_code, outcome.clarifier_available) == ("awaiting_human", 11, False)
    assert len(backend.calls) == 1  # the second question is not tried against a clarifier that just said no
    assert outcome.sticky_section is not None and "The clarifier was unavailable" in outcome.sticky_section
    file = s.file()
    for qid in ("Q-001", "Q-002"):
        q = file.get(qid)
        assert q is not None and q.status is QuestionStatus.OPEN and q.suggestion_text == ""
    results = s.events("clarifier.result")
    assert [(e["id"], e["status"]) for e in results] == [("Q-001", "unavailable"), ("Q-002", "unavailable")]


def test_invalid_twice_leaves_the_question_open_without_a_suggestion(s: Setup):
    s.ask(QuestionKind.TECHNICAL, "1.1")
    broken = ok(reply("Q-001", confidence="certain"))
    outcome, _ = s.run(ScriptedBackend(broken, broken), FakeS1())
    assert (outcome.next_phase, outcome.exit_code, outcome.clarifier_available) == ("awaiting_human", 11, True)
    assert outcome.sticky_section is not None and "invalid output for Q-001" in outcome.sticky_section
    q = s.file().get("Q-001")
    assert q is not None and q.status is QuestionStatus.OPEN and q.suggestion_text == ""
    (event,) = s.events("clarifier.result")
    assert event["status"] == "invalid" and event["auto_accepted"] is False and event["calls"] == 2


def test_events_emitted_for_each_question(s: Setup):
    s.ask(QuestionKind.TECHNICAL, "1.1")
    s.ask(QuestionKind.PRODUCT, "1.2", "Which rate?")
    s.ask(QuestionKind.TECHNICAL, "1.3", "Which index?")
    backend = ScriptedBackend(ok(reply("Q-001")), ok(reply("Q-002", kind="product")), ok(reply("Q-003")))
    s.run(backend, FakeS1(0.0, 1.0, S1Unavailable("usage limit")))
    results = {e["id"]: e for e in s.events("clarifier.result")}
    assert set(results) == {"Q-001", "Q-002", "Q-003"}
    first = results["Q-001"]
    assert (first["status"], first["profile"], first["kind"], first["confidence"], first["auto_accepted"]) == (
        "ok", "claude", "technical", "high", True,
    )  # fmt: skip
    assert first["reasons"] == [] and first["s1"] == "llm_boolean" and first["calls"] == 1
    assert results["Q-002"]["auto_accepted"] is False and results["Q-002"]["s1"] == "not_asked"
    assert results["Q-003"]["s1"] == "unavailable" and "S1 unavailable" in results["Q-003"]["reasons"][0]
    # one question.answered, for the accepted question, with the hash of what the implementer will read
    (answered,) = s.events("question.answered")
    q1 = s.file().get("Q-001")
    assert q1 is not None
    assert (answered["id"], answered["by"]) == ("Q-001", "clarifier")
    assert answered["answer_sha256"] == answer_sha256(q1) and answered["answer_sha256"] is not None
    # and `reenter` agrees: not an override, not a new answer
    again = LedgerWriter.open(s.unit, UNIT, "r-20261004T0200Z-0002", redactor=REDACTOR)
    result = Clarifier(s.unit, again).reenter(TASKS)
    assert result.answered == () and result.overrides == ()
    again.finish(0)


def test_a_limit_the_run_reported_is_recorded(s: Setup):
    s.ask(QuestionKind.TECHNICAL, "1.1")
    from l4.agents.base import LimitSignal, RunResult

    signal = LimitSignal("claude", None, "usage_limit", None, "stderr", "limit reached")
    run = RunResult("quota", Path("/dev/null"), detail="usage limit", limit=signal)
    s.run(ScriptedBackend(StructuredResult("limit", detail="usage limit", run=run)), FakeS1())
    (limit,) = s.events("availability.limit")
    assert (limit["tool"], limit["kind"], limit["excerpt"]) == ("claude", "usage_limit", "limit reached")


def test_an_implementer_product_kind_goes_to_a_human_even_if_the_config_lists_it(s: Setup):
    s.ask(QuestionKind.PRODUCT, "1.1", "Which rate?")
    cfg = ClarifierCfg(auto_accept_kinds=["technical", "product", "ambiguous"])
    outcome, _ = s.run(ScriptedBackend(ok(reply("Q-001"))), FakeS1(0.0, 1.0), cfg=cfg)
    result = outcome.results["Q-001"]
    assert result.status == "open" and "implementer kind product always goes to a human" in result.reasons
    assert s.events("clarifier.result")[0]["s1"] == "not_asked"


def test_clarifier_cost_is_emitted_as_budget_cost(s: Setup):
    s.ask(QuestionKind.TECHNICAL, "1.1")
    s.run(ScriptedBackend(ok(reply("Q-001"), cost=0.07)), FakeS1(0.0, 1.0))
    (cost,) = s.events("budget.cost")
    assert (cost["usd"], cost["role"], cost["profile"]) == (0.07, "clarifier", "claude")


def test_clarifier_credits_are_emitted_as_budget_cost_without_dollars(s: Setup):
    """SCN-KJD-12: a kiro-cli clarifier pass meters 0.03 credits; the event has credits and their source, no usd."""
    from l4.agents.base import Usage
    from l4.llm.agent_judge import StructuredResult

    s.ask(QuestionKind.TECHNICAL, "1.1")
    metered = StructuredResult(
        "ok", parsed=reply("Q-001"), model_resolved="claude-sonnet-5.5",
        usage=Usage(credits=0.03, credits_source="kiro.stream"),
    )  # fmt: skip
    s.run(ScriptedBackend(metered), FakeS1(0.0, 1.0))
    (cost,) = s.events("budget.cost")
    assert (cost["credits"], cost["credits_source"], cost["role"], cost["profile"]) == (
        0.03, "kiro.stream", "clarifier", "claude",
    )  # fmt: skip
    assert "usd" not in cost


def test_clarifier_credits_are_rounded_to_6_places_like_the_judges(s: Setup):
    from l4.agents.base import Usage
    from l4.llm.agent_judge import StructuredResult

    s.ask(QuestionKind.TECHNICAL, "1.1")
    metered = StructuredResult(
        "ok", parsed=reply("Q-001"), usage=Usage(credits=0.1 + 0.2, credits_source="kiro.stream")
    )
    s.run(ScriptedBackend(metered), FakeS1(0.0, 1.0))
    (cost,) = s.events("budget.cost")
    assert cost["credits"] == 0.3


def test_an_unavailable_reply_without_detail_still_has_a_reason(s: Setup):
    s.ask(QuestionKind.TECHNICAL, "1.1")
    s.run(ScriptedBackend(StructuredResult("error", detail="")), FakeS1())
    (event,) = s.events("clarifier.result")
    assert event["status"] == "unavailable" and event["reasons"] == ["unavailable"]


def test_a_cut_cited_text_is_named_in_the_reason_when_s1_says_no(s: Setup):
    s.ask(QuestionKind.TECHNICAL, "1.1")
    (s.repo / "src" / "vat.py").write_text("\n".join([QUOTE, *(f"# filler {n} " + "z" * 400 for n in range(10))]))
    long_answer = "Use basis points. " * 66  # 1188 characters, within the schema: the cited block gives way
    outcome, _ = s.run(ScriptedBackend(ok(reply("Q-001", answer=long_answer))), FakeS1(0.0, 0.0))
    reasons = outcome.results["Q-001"].reasons
    assert len(reasons) == 1 and "S1 support p=0.00" in reasons[0] and "truncated" in reasons[0]


def test_a_router_that_raises_leaves_the_question_open_and_the_run_going(s: Setup):
    s.ask(QuestionKind.TECHNICAL, "1.1")

    class Broken(Router):
        def route(self, question, answer):
            raise IndexError("tuple index out of range")

    cfg = ClarifierCfg()
    port = s.port()
    outcome = Clarifier(s.unit, s.writer).run(
        port, prompt_for=lambda v: ClarifierPrompt("S", "U", "0" * 64, "clarifier@1"),
        answerer=BackendClarifier(ScriptedBackend(ok(reply("Q-001"))), redact=lambda t: t),
        router=Broken(cfg, S1Cfg(), FakeS1(), []), cfg=cfg, profile="claude", blocking=["Q-001"],
        location=("openspec/changes/add-x/questions.md", "l4/openspec/add-x"), link=None,
    )  # fmt: skip
    s.writer.finish(0)
    assert outcome.exit_code == 11
    (event,) = s.events("clarifier.result")
    assert event["auto_accepted"] is False and event["reasons"] == ["router error: IndexError"]


def test_an_s1_limit_is_recorded_as_availability_limit(s: Setup):
    from l4.agents.base import LimitSignal, RunResult

    s.ask(QuestionKind.TECHNICAL, "1.1")
    signal = LimitSignal("claude", None, "usage_limit", None, "stderr", "s1 limit reached")
    run = RunResult("quota", Path("/dev/null"), detail="usage limit", limit=signal)
    outcome, _ = s.run(ScriptedBackend(ok(reply("Q-001"))), FakeS1(S1Unavailable("usage limit", run=run)))
    assert outcome.results["Q-001"].decision.s1 == "unavailable"  # type: ignore[union-attr]
    (limit,) = s.events("availability.limit")
    assert (limit["tool"], limit["excerpt"]) == ("claude", "s1 limit reached")


def test_a_call_that_reported_no_cost_is_recorded_as_unknown_not_free(s: Setup):
    from l4.agents.base import Usage

    s.ask(QuestionKind.TECHNICAL, "1.1")
    free = StructuredResult("ok", parsed=reply("Q-001"), usage=Usage())
    s.run(ScriptedBackend(free), FakeS1(0.0, 1.0))
    (event,) = s.events("clarifier.result")
    assert event["cost_usd"] is None and s.events("budget.cost") == []


def test_a_question_the_file_cannot_be_read_for_keeps_the_unit_with_a_human(s: Setup):
    s.ask(QuestionKind.TECHNICAL, "1.1")
    path = s.unit / "questions.md"  # an unclosed fence swallows the next heading: Q-002 has no readable section
    path.write_text(path.read_text() + "\n```\n## Q-002: b\n\n- **Status:** open\n- **Blocking tasks:** 1.2\n")
    assert s.file().unreadable_ids == ("Q-002",)
    outcome, _ = s.run(ScriptedBackend(ok(reply("Q-001"))), FakeS1(0.0, 1.0), extra_blocking=("Q-002",))
    assert (outcome.next_phase, outcome.exit_code) == ("awaiting_human", 11)
    assert outcome.sticky_section is not None and "Q-002" in outcome.sticky_section
    assert "unreadable" in outcome.sticky_section


def test_a_harness_error_in_the_prompt_is_unavailable_but_its_traceback_is_logged_at_debug(s: Setup, caplog):
    import logging

    s.ask(QuestionKind.TECHNICAL, "1.1")

    def broken_prompt(view: QuestionView) -> ClarifierPrompt:
        raise KeyError("no such section")

    cfg = ClarifierCfg()
    with caplog.at_level(logging.DEBUG, logger="l4.clarifier"):
        outcome = Clarifier(s.unit, s.writer).run(
            s.port(), prompt_for=broken_prompt,
            answerer=BackendClarifier(ScriptedBackend(ok(reply("Q-001"))), redact=lambda t: t),
            router=Router(cfg, S1Cfg(), FakeS1(), []), cfg=cfg, profile="claude", blocking=["Q-001"],
            location=("openspec/changes/add-x/questions.md", "l4/openspec/add-x"), link=None,
        )  # fmt: skip
    s.writer.finish(0)
    assert outcome.exit_code == 11
    traced = [r for r in caplog.records if r.levelno == logging.DEBUG and r.exc_info]
    assert traced and traced[0].exc_info[0] is KeyError
    assert not any(r.exc_info for r in caplog.records if r.levelno >= logging.WARNING)


def test_the_result_event_carries_every_s1_value_for_calibration(s: Setup):
    from .test_router import VerdictS1

    s.ask(QuestionKind.TECHNICAL, "1.1")
    s.run(ScriptedBackend(ok(reply("Q-001"))), VerdictS1())
    [event] = s.events("clarifier.result")
    assert event["s1"] == "system_one" and event["auto_accepted"] is True
    assert event["p_internal"] == 0.9 and event["citation_opposite"] == [0.05]
    assert event["s1_model"] == "jev-1.13.0" and event["s1_questions"] == "test@1"
    assert event["s1_detail"] == {"router.route_a": 0.95, "citation1.shows": 0.95}
    assert event["p_product"] == pytest.approx(0.05) and event["citation_support"] == [0.95]
    assert event["p_technical"] == pytest.approx(0.95)  # the router's own number, not the complement it is read as


def test_a_harness_question_is_never_clarified(s: Setup):
    """L4-IMP-063: the check was the harness's, not the project's: only a person (or an agent with consent) answers."""
    s.ask(QuestionKind.HARNESS, "1.1", "Task 1.1: the pre-satisfied check could not decide")
    backend = ScriptedBackend()
    outcome, prompts = s.run(backend, FakeS1())
    assert prompts == [] and backend.calls == [] and outcome.results == {}
    assert s.events("clarifier.result") == []
    assert (outcome.next_phase, outcome.exit_code) == ("awaiting_human", 11)
    harness = s.file().get("Q-001")
    assert harness is not None and harness.status is QuestionStatus.OPEN
