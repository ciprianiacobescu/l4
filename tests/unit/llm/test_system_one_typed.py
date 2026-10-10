import json
from pathlib import Path

import httpx
import pytest

from l4.agents.factory import RoleUnavailable
from l4.config.schema import L4Config
from l4.llm.system_one import (
    Question,
    Reply,
    SystemOneBackend,
    SystemOneBadAnswer,
    open_s1_profile,
    parse_typed,
)
from l4.redact import Redactor

RECORDED = Path(__file__).resolve().parents[2] / "fixtures" / "recorded" / "system-one"


def recorded(name: str) -> tuple[dict[str, Question], Reply]:
    data = json.loads((RECORDED / name).read_text())
    questions = {qid: Question(q["type"], q["instructions"], q.get("criteria")) for qid, q in data["questions"].items()}
    return questions, Reply(data["reply"]["model"], data["reply"]["answers"], data["reply"]["usage"])


def test_choice_and_score_parse_from_recorded_replies():
    questions, reply = recorded("jev-typed.json")
    answers = parse_typed(reply, questions)
    noul, choice, score = (answers[q] for q in ("is_product_decision", "finding_severity", "citation_support"))
    assert noul.p_true == 0.25 and noul.predicted is False and noul.answer_confidence == 0.75
    assert choice.choice == "major" and choice.probabilities["blocker"] == 0.22 and choice.answer_confidence == 0.78
    assert choice.confidence == 0.66  # the server's own number is kept, never used for comparison
    assert score.score == 2.71 and score.predicted == 3 and score.answer_confidence == 0.55
    laya_questions, laya_reply = recorded("laya-typed.json")  # a real laya-serve reply: its absence fails the test
    laya = parse_typed(laya_reply, laya_questions)
    assert set(laya) == set(laya_questions)
    assert laya["is_product_decision"].p_true == 0.4111 and laya["finding_severity"].choice == "major"
    assert laya["citation_support"].predicted == 4
    assert abs(sum(laya["finding_severity"].probabilities.values()) - 1) < 1e-3


@pytest.mark.parametrize(
    "qid,patch",
    [
        ("is_product_decision", {"noul": 1.2}),
        ("is_product_decision", {"noul": True}),
        ("finding_severity", {"choice": "catastrophic"}),
        ("finding_severity", {"probabilities": {"blocker": 0.9, "major": 0.9, "minor": 0.0}}),
        ("finding_severity", {"probabilities": {"blocker": 0.2, "major": 0.8, "other": 0.0}}),
        ("citation_support", {"score": 9.0}),
        ("citation_support", {"score": -0.5}),
        ("citation_support", {"type": "noul"}),
    ],
)
def test_out_of_range_or_wrong_kind_is_refused(qid: str, patch: dict):
    questions, reply = recorded("jev-typed.json")
    answers = {k: dict(v) for k, v in reply.answers.items()}
    answers[qid].update(patch)
    with pytest.raises(SystemOneBadAnswer):
        parse_typed(Reply(reply.model, answers), questions)


def test_ask_typed_goes_through_the_wire_and_ask_still_returns_floats(tmp_path: Path):
    questions, reply = recorded("jev-typed.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": reply.model, "answers": reply.answers, "usage": reply.usage})

    backend = SystemOneBackend(
        "jev", model="jev-latest", base_url="http://s1.test", api_key="k" * 12,
        transport=httpx.MockTransport(handler), redactor=Redactor({}),
    )  # fmt: skip
    with backend:
        assert backend.ask_typed("state", questions)["finding_severity"].choice == "major"
        noul_only = {"is_product_decision": questions["is_product_decision"]}
        assert backend.ask("state", noul_only) == {"is_product_decision": 0.25}


def test_open_s1_profile_names_one_profile_and_refuses_the_others():
    cfg = L4Config.model_validate({
        "profiles": {
            "jev": {"backend": "system-one", "engine": "jev", "api_key_env": "TYPESAFE_API_KEY"},
            "other": {"adapter": "claude-code"},
        }
    })  # fmt: skip
    backend = open_s1_profile(cfg, "jev", environ={"TYPESAFE_API_KEY": "k" * 12}, redactor=Redactor({}))
    assert backend.engine == "jev" and not backend.running
    with pytest.raises(RoleUnavailable, match="not a backend: system-one"):
        open_s1_profile(cfg, "other", environ={}, redactor=Redactor({}))
    with pytest.raises(RoleUnavailable, match="TYPESAFE_API_KEY"):
        open_s1_profile(cfg, "jev", environ={}, redactor=Redactor({}))
