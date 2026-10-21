"""The redesigned System-One questions of the clarifier (docs/eval-framework.md 6.3)."""

import json
from pathlib import Path

import httpx
import pytest

from l4.clarifier.answer import Citation, ClarifierAnswer
from l4.clarifier.ports import QuestionView
from l4.clarifier.router import S1Unavailable
from l4.clarifier.s1_decisions import (
    QUESTION_SET,
    SystemOneDecisions,
    citation_state,
    cut_around,
    route_questions,
)
from l4.config.schema import S1Cfg
from l4.llm.system_one import SystemOneBackend
from l4.redact import Redactor
from l4.specs.questions import QuestionKind, QuestionStatus

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "system-one" / "jev-1.13.0"


def view() -> QuestionView:
    return QuestionView(
        "Q-001", "Method or property?", QuestionStatus.OPEN, QuestionKind.TECHNICAL, (), "Cart has subtotal().",
        ("method", "property"), "", "", None,
    )  # fmt: skip


def answer() -> ClarifierAnswer:
    cite = Citation(ref="cart.py", quote="def subtotal(self)", claim="subtotal is a method")
    return ClarifierAnswer(
        question_id="Q-001", answer="A method.", confidence="high", kind="technical", citations=(cite,), rationale="r"
    )  # fmt: skip


def judge(handler, tmp_path: Path, engine: str = "jev") -> tuple[SystemOneDecisions, list[dict]]:
    seen: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return handler(request)

    backend = SystemOneBackend(
        engine, model="jev-1.13.0", base_url="http://s1.test", transport=httpx.MockTransport(record),  # type: ignore[arg-type]
        log_path=tmp_path / "s1.jsonl", redactor=Redactor({}),
    )  # fmt: skip
    return SystemOneDecisions(backend), seen


def reply(a: float, b: float, internal: float):
    def probs(p: float) -> dict:
        return {"type": "choice", "choice": "technical", "confidence": 0.9,
                "probabilities": {"technical": p, "product": 1 - p, "ambiguous": 0.0}}  # fmt: skip

    return lambda request: httpx.Response(200, json={
        "model": "jev-1.13.0",
        "answers": {"route_a": probs(a), "route_b": probs(b), "internal": {"type": "noul", "noul": internal}},
    })  # fmt: skip


def test_the_recorded_jev_reply_parses_with_the_probabilities_map(tmp_path: Path):
    recorded = json.loads((RECORDED / "reply.json").read_text())
    recorded["answers"]["route_a"] = recorded["answers"].pop("r")
    recorded["answers"]["route_b"] = dict(recorded["answers"]["route_a"])
    del recorded["answers"]["y"]
    j, _ = judge(lambda request: httpx.Response(200, json=recorded), tmp_path)
    verdict = j.route(view(), S1Cfg())
    assert verdict.p_technical == 0.94 and verdict.p_internal is None and verdict.model == "jev-1.13.0"


def test_router_asks_both_option_orders_in_one_request_and_averages(tmp_path: Path):
    j, seen = judge(reply(0.80, 0.94, 0.9), tmp_path)
    verdict = j.route(view(), S1Cfg())
    assert len(seen) == 1  # one request, three questions
    questions = seen[0]["questions"]
    assert set(questions) == {"route_a", "route_b"}
    assert list(questions["route_a"]["criteria"]) == ["technical", "product", "ambiguous"]
    assert list(questions["route_b"]["criteria"]) == ["ambiguous", "product", "technical"]
    assert verdict.p_technical == pytest.approx(0.87) and verdict.p_internal is None
    assert verdict.detail == {"route_a": 0.80, "route_b": 0.94}
    assert j.question_set == QUESTION_SET


def citation_reply(shows: float, opposite: float, establishes: float = 0.95, internal: float = 0.95):
    values = {"shows": shows, "opposite": opposite, "establishes": establishes, "internal": internal}
    answers = {key: {"type": "noul", "noul": p} for key, p in values.items()}
    return lambda request: httpx.Response(200, json={"model": "jev-1.13.0", "answers": answers})


def test_support_asks_about_the_answer_the_claim_its_opposite_and_the_project(tmp_path: Path):
    j, seen = judge(citation_reply(0.96, 0.04, 0.93, 0.91), tmp_path)
    cite = answer().citations[0]
    verdict = j.support(answer(), cite, "def subtotal(self) -> Decimal:\n    return 1", S1Cfg(), question=view())
    assert (verdict.support, verdict.opposite, verdict.truncated) == (0.96, 0.04, False)
    assert (verdict.establishes, verdict.internal) == (0.93, 0.91)
    state = json.loads(seen[0]["state"])
    assert state == {
        "question": "Method or property?", "answer": "A method.", "claim": "subtotal is a method",
        "cited_text": "def subtotal(self) -> Decimal:\n    return 1",
    }  # fmt: skip
    assert set(seen[0]["questions"]) == {"shows", "opposite", "establishes", "internal"}
    assert "opposite" in seen[0]["questions"]["opposite"]["instructions"]


# The numbers are the reviewer's live Jev probes (jev-1.13.0, 2026-10-05) for these shapes, not replies recorded here:
# technical and repo-answerable (shows 0.96, opposite 0.03, derivable 0.96), a product question (derivable 0.10), and
# a true claim under a wrong answer ("A float." under `def subtotal(self) -> Decimal:`: the claim is shown at 0.96).
# `establishes` live (jev-1.13.0, later probes): 0.84, 0.96 and 0.93 for true answers, 0.06 for a wrong one; the values
# below keep the gate's shape.
CART = "class Cart:\n    def subtotal(self) -> Decimal:\n        return total\n"


def routed(tmp_path: Path, *, technical: float, shows: float, establishes: float, internal: float, text: str):
    from l4.clarifier.router import Router
    from l4.config.schema import ClarifierCfg

    (tmp_path / "cart.py").write_text(CART)
    cite = Citation(ref="cart.py#L2", quote="def subtotal(self) -> Decimal:", claim="Cart.subtotal is a method")
    ans = ClarifierAnswer(
        question_id="Q-001", answer=text, confidence="high", kind="technical", citations=(cite,), rationale="r"
    )  # fmt: skip

    def handler(request: httpx.Request) -> httpx.Response:
        if "route_a" in json.loads(request.content)["questions"]:
            return reply(technical, technical, 0.0)(request)
        return citation_reply(shows, 0.03, establishes, internal)(request)

    j, _ = judge(handler, tmp_path)
    return Router(ClarifierCfg(), S1Cfg(), j, [tmp_path]).route(view(), ans)


def test_a_repo_answerable_technical_question_is_auto_accepted_at_the_shipped_gates(tmp_path: Path):
    decision = routed(tmp_path, technical=0.99, shows=0.96, establishes=0.92, internal=0.96, text="Decimal.")
    assert decision.auto_accept and decision.reasons == () and decision.p_internal == 0.96
    assert decision.s1_questions == QUESTION_SET


def test_a_product_question_the_project_cannot_settle_is_refused_on_derivability(tmp_path: Path):
    decision = routed(tmp_path, technical=0.99, shows=0.96, establishes=0.9, internal=0.10, text="Round half up.")
    assert not decision.auto_accept and "p(derivable from the project)=0.10 is below 0.80" in decision.reasons[0]


def test_a_true_claim_under_a_wrong_answer_is_refused(tmp_path: Path):
    decision = routed(tmp_path, technical=0.99, shows=0.96, establishes=0.05, internal=0.9, text="A float.")
    assert not decision.auto_accept and "establishes the answer)=0.05 is below 0.80" in decision.reasons[0]


def test_gates_are_the_configured_starting_values():
    gates = SystemOneDecisions.gates(None, S1Cfg())  # type: ignore[arg-type]
    assert (gates.technical_min, gates.internal_min, gates.support_min, gates.opposite_max) == (0.85, 0.8, 0.9, 0.2)
    assert gates.establishes_min == 0.8
    custom = S1Cfg.model_validate({"decisions": {"router": {"technical_min": 0.95}, "citation": {"opposite_max": 0.1}}})
    gates = SystemOneDecisions.gates(None, custom)  # type: ignore[arg-type]
    assert gates.technical_min == 0.95 and gates.opposite_max == 0.1 and gates.internal_min == 0.8


def test_the_cited_text_is_cut_around_the_quote_not_from_the_start():
    text = "".join(f"line {n:03d} filler filler\n" for n in range(100)) + "def subtotal(self): pass\n" + "x" * 3000
    cut = cut_around(text, "def subtotal(self): pass", 200)
    assert "def subtotal(self): pass" in cut and len(cut) == 200 and not text.startswith(cut)
    assert cut_around("short", "x", 200) == "short" and cut_around("anything", "x", 0) == ""


def test_citation_state_leaves_room_for_the_questions_and_never_cuts_the_claim():
    state, cut = citation_state("q?", "a", "claim", "c" * 4000, "cccccccc", max_tokens=100, reserve="q" * 100)
    assert cut and len(state) <= 4 * 100 and json.loads(state)["claim"] == "claim"
    assert json.loads(state)["answer"] == "a" and json.loads(state)["question"] == "q?"
    whole, cut = citation_state("q?", "a", "claim", "short text", "short", max_tokens=450, reserve="q")
    assert not cut and json.loads(whole)["cited_text"] == "short text"


def test_jev_gets_the_full_budget_and_laya_the_window_cap():
    limits = S1Cfg()
    assert limits.budget("jev") == 450 and limits.budget("laya-local") == 300 and limits.budget("remote") == 300
    assert S1Cfg(max_state_tokens=2000).budget("jev") == 2000 and S1Cfg(max_state_tokens=2000).budget("remote") == 300


def test_a_failed_server_is_s1_unavailable_and_stays_down(tmp_path: Path):
    calls = []

    def down(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    j, _ = judge(down, tmp_path)
    with pytest.raises(S1Unavailable, match="503"):
        j.route(view(), S1Cfg())
    with pytest.raises(S1Unavailable):
        j.route(view(), S1Cfg())
    assert len(calls) == 1
    j.close()


@pytest.mark.parametrize("bad", [{"route_a": {"type": "noul", "noul": 0.9}}, {}])
def test_a_reply_without_the_choice_probabilities_is_unavailable(tmp_path: Path, bad):
    j, _ = judge(lambda request: httpx.Response(200, json={"model": "m", "answers": bad}), tmp_path)
    with pytest.raises(S1Unavailable):
        j.route(view(), S1Cfg())


def test_the_choice_questions_name_the_three_options():
    questions = route_questions()
    assert questions["route_a"].kind == "choice" and set(questions["route_a"].criteria) == {
        "technical", "product", "ambiguous"
    }


def test_a_secret_in_the_question_never_reaches_the_wire_or_the_log(tmp_path: Path):
    token = "glpat-" + "w" * 20
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content.decode())
        return reply(0.9, 0.9, 0.9)(request)

    backend = SystemOneBackend(
        "remote", model="m", base_url="http://s1.test", transport=httpx.MockTransport(handler),
        log_path=tmp_path / "s1.jsonl", redactor=Redactor({"L4_FORGE_TOKEN": token}),
    )  # fmt: skip
    q = view()
    leaky = QuestionView(**{**q.__dict__, "context": f"the log shows {token}"})
    SystemOneDecisions(backend).route(leaky, S1Cfg())
    assert token not in bodies[0] and "[REDACTED:" in bodies[0]
    assert token not in (tmp_path / "s1.jsonl").read_text()


def test_a_server_that_cannot_start_is_unavailable(tmp_path: Path):
    from l4.llm.system_one import LayaServe

    serve = LayaServe([str(tmp_path / "missing")], {"PATH": "/usr/bin"})
    backend = SystemOneBackend("laya-local", model="typed-decisions", serve=serve, redactor=Redactor({}))
    with pytest.raises(S1Unavailable):
        SystemOneDecisions(backend).route(view(), S1Cfg())


def test_the_state_budget_follows_the_engine(tmp_path: Path):
    long_view = QuestionView(**{**view().__dict__, "context": "word " * 2000})
    sizes = {}
    for engine in ("jev", "remote"):
        j, seen = judge(reply(0.9, 0.9, 0.9), tmp_path, engine)
        j.route(long_view, S1Cfg(max_state_tokens=1000))
        sizes[engine] = len(seen[0]["state"])
    assert sizes["jev"] > 3 * 800 and sizes["remote"] <= 300 * 4


def test_every_log_line_names_its_engine_so_jev_rows_can_be_kept_out_of_training(tmp_path: Path):
    j, _ = judge(reply(0.9, 0.9, 0.9), tmp_path, "jev")
    j.route(view(), S1Cfg())
    [line] = (tmp_path / "s1.jsonl").read_text().splitlines()
    assert json.loads(line)["engine"] == "jev"  # TypeSafe MCA 2.3(b): never a training label for Laya
