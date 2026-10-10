import json
from pathlib import Path

import httpx
import pytest

from l4.config.schema import L4Config
from l4.llm.system_one import SystemOneBackend
from l4.redact import Redactor
from l4.specs.base import Criterion, Framework
from l4.verifier.s1 import (
    CalibrationContext,
    Evidence,
    effective_budget,
    record_calibration,
    run_s1,
)

BIG = "x" * 8000


def criterion(n: int, text="WHEN a user opens the page THEN the badge shows 3") -> Criterion:
    cid = f"C-{n:08x}"
    return Criterion(cid, f"web › Item › S{n}", Framework.OPENSPEC, "web", "Item", f"S{n}", text, "spec.md", n)


class Server:
    def __init__(self, p=0.7, fail_on: set[str] | None = None, choice: dict | None = None) -> None:
        self.choice = choice
        self.states: list[str] = []
        self.p, self.fail_on = p, fail_on or set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.states.append(body["state"])
        if any(f in body["state"] for f in self.fail_on):
            return httpx.Response(500)
        assert set(body["questions"]) == {"p", "evidence"}
        answers = {"p": {"type": "noul", "noul": self.p}}
        if self.choice:
            answers["evidence"] = {"type": "choice", "choice": "x", "confidence": 0.9, "probabilities": self.choice}
        return httpx.Response(200, json={"model": "m-served", "answers": answers})


def backend(server) -> SystemOneBackend:
    return SystemOneBackend("remote", model="typed-decisions", base_url="http://s1.test",
                            transport=httpx.MockTransport(server), redactor=Redactor({}))  # fmt: skip


def evidence(**kw) -> Evidence:
    return Evidence(kw.pop("tests", (("e2e/test_l4_c_00000001.py::test_badge", "passed"),)), kw.pop("excerpt", ""))


def test_budget_is_capped_by_the_laya_window():
    cfg = L4Config()
    assert cfg.verifier.s1.max_state_tokens == 450 and effective_budget(cfg) == 300
    cfg.verifier.s1.max_state_tokens = 120
    assert effective_budget(cfg) == 120


def test_oversized_state_is_trimmed_to_max_tokens():
    server = Server()
    with backend(server) as b:
        outcome = run_s1(b, [criterion(1)], {"C-00000001": evidence(excerpt=BIG)}, budget=200)
    (state,) = server.states
    assert len(state) // 4 <= 200 and "[truncated]" in state
    assert "WHEN a user opens the page" in state and "e2e/test_l4_c_00000001.py::test_badge: passed" in state
    assert outcome.status == "ok" and outcome.criteria[0].p == 0.7 and outcome.criteria[0].truncated

def test_the_state_leaves_room_for_the_longest_question_of_the_request_not_only_the_first():
    """Both questions go in one request: the 4-way choice is the longer one, and Laya truncates what does not fit."""
    from l4.clarifier.router import approx_tokens
    from l4.clarifier.s1_decisions import question_text
    from l4.verifier.s1 import QUESTION, QUESTIONS

    assert len(question_text(QUESTIONS)) > len(QUESTION) * 3
    server = Server()
    with backend(server) as b:
        run_s1(b, [criterion(1)], {"C-00000001": evidence(excerpt=BIG)}, budget=200)
    (state,) = server.states
    assert approx_tokens(state + question_text(QUESTIONS)) <= 200


def test_a_state_that_cannot_fit_even_without_the_excerpt_is_unavailable():
    server = Server()
    with backend(server) as b:
        outcome = run_s1(b, [criterion(1, BIG), criterion(2)], {}, budget=200)
    first, second = outcome.criteria
    assert (first.status, first.p) == ("unavailable", None) and "does not fit" in first.reason
    assert second.status == "ok" and len(server.states) == 1  # the other criterion is still judged
    assert outcome.status == "unavailable"


def test_missing_laya_marks_step_unavailable():
    crits = [criterion(n) for n in (1, 2, 3)]
    with backend(Server(fail_on={"badge"})) as b:  # every state names the badge: the server is "down"
        outcome = run_s1(b, crits, {}, budget=300)
    assert outcome.status == "unavailable"
    assert [c.status for c in outcome.criteria] == ["unavailable"] * 3 and all(c.p is None for c in outcome.criteria)
    assert "500" in outcome.criteria[0].reason and "earlier" in outcome.criteria[1].reason


def test_not_started_backend_is_unavailable_not_an_exception():
    outcome = run_s1(backend(Server()), [criterion(1)], {}, budget=300)  # never started
    assert outcome.status == "unavailable"


def ctx(tmp_path: Path) -> CalibrationContext:
    return CalibrationContext(
        cache_file=tmp_path / "cache" / "s1-calibration.jsonl", run_file=tmp_path / ".l4-out/s1/r-1.jsonl",
        unit="openspec:x", run_id="r-1", round=2,
    )  # fmt: skip


def test_one_jsonl_line_per_judgment(tmp_path: Path):
    server = Server(p=0.93)
    with backend(server) as b:
        outcome = run_s1(b, [criterion(1), criterion(2)], {}, budget=300)
    n = record_calibration(
        outcome, ctx(tmp_path), model="typed-decisions", deterministic={"C-00000001": "passed"},
        judge={"C-00000001": "satisfied", "C-00000002": None},
    )  # fmt: skip
    assert n == 2
    for path in (ctx(tmp_path).cache_file, ctx(tmp_path).run_file):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert [r["criterion"] for r in rows] == ["C-00000001", "C-00000002"]
        assert rows[0]["p"] == 0.93 and rows[0]["model"] == "typed-decisions" and rows[0]["round"] == 2
        assert rows[0]["deterministic"] == "passed" and rows[0]["judge"] == "satisfied" and rows[1]["judge"] is None
        assert len(rows[0]["state_sha256"]) == 64 and rows[0]["question"] and "state" not in rows[0]


def test_no_line_when_s1_unavailable(tmp_path: Path):
    with backend(Server(fail_on={"badge"})) as b:
        outcome = run_s1(b, [criterion(1)], {}, budget=300)
    assert record_calibration(outcome, ctx(tmp_path), model="m", deterministic={}, judge={}) == 0
    assert not ctx(tmp_path).cache_file.exists() and not ctx(tmp_path).run_file.exists()


def test_calibration_appends_across_rounds(tmp_path: Path):
    with backend(Server()) as b:
        outcome = run_s1(b, [criterion(1)], {}, budget=300)
    record_calibration(outcome, ctx(tmp_path), model="m", deterministic={}, judge={})
    record_calibration(outcome, ctx(tmp_path), model="m", deterministic={}, judge={})
    assert len(ctx(tmp_path).cache_file.read_text().splitlines()) == 2


@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_criterion_text_is_still_a_question(bad):
    server = Server()
    with backend(server) as b:
        outcome = run_s1(b, [criterion(1, bad)], {}, budget=300)
    assert outcome.criteria[0].status == "ok"


def test_the_wire_holds_no_secret_for_step_8():
    token = "glpat-" + "w" * 20
    server = Server()
    redacting = SystemOneBackend(
        "remote", model="typed-decisions", base_url="http://s1.test", transport=httpx.MockTransport(server),
        redactor=Redactor({"L4_FORGE_TOKEN": token}),
    )  # fmt: skip
    with redacting as b:
        outcome = run_s1(b, [criterion(1, f"WHEN it logs {token} THEN the badge shows 3")], {}, budget=300)
    assert outcome.status == "ok" and token not in server.states[0] and "[REDACTED:" in server.states[0]


def test_one_malformed_answer_costs_only_its_own_criterion():
    class Flaky(Server):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.states.append(body["state"])
            value = 1.7 if "S1" in body["state"] or "C-00000001" in body["state"] else self.p
            return httpx.Response(200, json={"model": "m", "answers": {"p": {"type": "noul", "noul": value}}})

    with backend(Flaky()) as b:
        outcome = run_s1(b, [criterion(1), criterion(2), criterion(3)], {}, budget=300)
    assert [c.status for c in outcome.criteria] == ["unavailable", "ok", "ok"]
    assert "outside 0..1" in outcome.criteria[0].reason and outcome.criteria[1].p == 0.7


def test_the_calibration_hash_is_that_of_the_state_on_the_wire():
    import hashlib

    token = "glpat-" + "w" * 20
    server = Server()
    redacting = SystemOneBackend(
        "remote", model="typed-decisions", base_url="http://s1.test", transport=httpx.MockTransport(server),
        redactor=Redactor({"L4_FORGE_TOKEN": token}),
    )  # fmt: skip
    with redacting as b:
        outcome = run_s1(b, [criterion(1, f"WHEN it logs {token} THEN the badge shows 3")], {}, budget=300)
    assert outcome.criteria[0].state_sha256 == hashlib.sha256(server.states[0].encode("utf-8")).hexdigest()


def test_step_8_asks_true_false_criteria_and_the_four_way_choice_and_records_both(tmp_path: Path):
    odds = {"implemented": 0.9, "contradicted": 0.02, "not_implemented": 0.05, "unrelated": 0.03}
    server = Server(p=0.96, choice=odds)
    with backend(server) as b:
        outcome = run_s1(b, [criterion(1)], {}, budget=300)
    got = outcome.criteria[0]
    assert got.p == 0.96 and got.evidence == odds and got.served_model == "m-served"
    record_calibration(outcome, ctx(tmp_path), model="jev-latest", deterministic={}, judge={}, engine="jev")
    [row] = [json.loads(line) for line in ctx(tmp_path).run_file.read_text().splitlines()]
    assert row["evidence"] == odds and row["served_model"] == "m-served" and row["engine"] == "jev"
    assert row["question_set"] == "criterion-s1@1"


def test_a_reply_without_the_choice_still_counts_as_judged():
    with backend(Server(p=0.5)) as b:
        outcome = run_s1(b, [criterion(1)], {}, budget=300)
    assert outcome.criteria[0].status == "ok" and outcome.criteria[0].evidence is None


def test_calibration_rows_tell_checkpoints_apart(tmp_path: Path):
    """Laya answers `model: laya-rl-agent` whatever it loaded: the row carries the checkpoint, the laya version and
    the server's own token count and truncation flag."""

    def laya(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "model": "laya-rl-agent", "answers": {"p": {"type": "noul", "noul": 0.9}},
            "usage": {"state_tokens": 287, "truncated": False},
        })  # fmt: skip

    with backend(laya) as b:
        outcome = run_s1(b, [criterion(1)], {}, budget=300)
    record_calibration(
        outcome, ctx(tmp_path), model="typed-decisions", deterministic={}, judge={}, server_version="0.3.24"
    )
    [row] = [json.loads(line) for line in ctx(tmp_path).run_file.read_text().splitlines()]
    assert (row["served_model"], row["model"], row["server_version"]) == ("laya-rl-agent", "typed-decisions", "0.3.24")
    assert row["state_tokens"] == 287 and row["server_truncated"] is False
