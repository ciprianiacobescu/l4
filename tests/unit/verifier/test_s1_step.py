"""Step 8's glue (plan line 34): the evidence per criterion, the unavailable paths, and the calibration rows that are
written after the judge has spoken (the `judge` column of a row is step 9's word)."""

import json
from pathlib import Path

import httpx

from l4.agents.factory import RoleUnavailable
from l4.config.schema import L4Config
from l4.llm.system_one import SystemOneBackend
from l4.redact import Redactor
from l4.specs.base import Criterion, Framework
from l4.verifier.s1 import Evidence
from l4.verifier.s1_step import S1Wiring, evidence_for, excerpt_for, record_rows, run_step
from l4.verifier.types import CriterionEvidence, TracingTest

DIFF = """\
diff --git a/src/web/page.py b/src/web/page.py
--- a/src/web/page.py
+++ b/src/web/page.py
@@ -1 +1 @@
-BADGE = "3 items"
+BADGE = "4 items"
diff --git a/src/pricing/total.py b/src/pricing/total.py
--- a/src/pricing/total.py
+++ b/src/pricing/total.py
@@ -1 +1 @@
-RATE = 1
+RATE = 2
"""


def crit(cid: str, text: str) -> Criterion:
    return Criterion(cid, f"web › {cid}", Framework.OPENSPEC, "web", "R", cid, text, "spec.md", 1)


BADGE = crit("C-de7f2d3f", "WHEN the cart opens THEN the badge shows 4 items")
RATE = crit("C-68f2e098", "WHEN the pricing rate is read THEN it is 2")


def test_the_excerpt_is_the_diff_file_that_shares_the_most_words_with_the_criterion():
    assert "src/web/page.py" in excerpt_for(BADGE, DIFF) and "src/pricing" not in excerpt_for(BADGE, DIFF)
    assert "src/pricing/total.py" in excerpt_for(RATE, DIFF)
    assert excerpt_for(crit("C-00000001", "xyz"), DIFF) == "" and excerpt_for(BADGE, "") == ""


def test_the_evidence_lists_the_tracing_tests_with_their_status():
    trace = [CriterionEvidence(BADGE.id, "a", "covered", (TracingTest("e2e::t", "passed", "generated"),))]
    found = evidence_for([BADGE, RATE], trace, DIFF)
    assert found[BADGE.id].tests == (("e2e::t", "passed"),) and found[RATE.id].tests == ()
    assert isinstance(found[BADGE.id], Evidence) and "4 items" in found[BADGE.id].excerpt


class Server:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.status != 200:
            return httpx.Response(self.status)
        answers = {"p": {"type": "noul", "noul": 0.75}}
        return httpx.Response(200, json={"model": "served-1", "answers": answers})


def wiring(server: Server, tmp_path: Path, engine: str = "remote") -> S1Wiring:
    def open_() -> SystemOneBackend:
        return SystemOneBackend(
            engine, model="m", base_url="http://s1.test", transport=httpx.MockTransport(server),  # type: ignore[arg-type]
            redactor=Redactor({}),
        )  # fmt: skip

    return S1Wiring(open_, tmp_path / "cache" / "s1-calibration.jsonl")


def test_a_working_backend_gives_a_record_per_criterion_with_the_served_model(tmp_path):
    out = run_step(wiring(Server(), tmp_path), L4Config(), [BADGE], {})
    assert out.status == "ok" and "1/1" in out.note
    (record,) = out.records
    assert (record.criterion, record.status, record.p, record.model, record.engine) == (
        BADGE.id, "ok", 0.75, "served-1", "remote",
    )  # fmt: skip


def test_a_server_that_errors_makes_the_step_unavailable_and_raises_nothing(tmp_path):
    out = run_step(wiring(Server(500), tmp_path), L4Config(), [BADGE, RATE], {})
    assert out.status == "unavailable" and [r.status for r in out.records] == ["unavailable"] * 2


def test_a_profile_that_cannot_be_opened_is_unavailable_with_the_reason(tmp_path):
    def refuse() -> SystemOneBackend:
        raise RoleUnavailable("s1_judge", "laya-serve is not on PATH")

    out = run_step(S1Wiring(refuse, tmp_path / "c.jsonl"), L4Config(), [BADGE], {})
    assert out.status == "unavailable" and "laya-serve is not on PATH" in out.note and out.records == []


def test_calibration_rows_pair_p_with_the_deterministic_state_and_the_judges_word(tmp_path):
    w = wiring(Server(), tmp_path, engine="jev")
    out = run_step(w, L4Config(), [BADGE], {})
    lines = record_rows(
        out, w, run_file=tmp_path / "out" / "s1" / "run-1.jsonl", unit="u", run_id="run-1", round_no=1,
        deterministic={BADGE.id: "covered"}, judge={BADGE.id: "pass"},
    )  # fmt: skip
    assert lines == 1
    for path in (w.cache_file, tmp_path / "out" / "s1" / "run-1.jsonl"):
        row = json.loads(path.read_text())
        assert (row["engine"], row["served_model"], row["deterministic"], row["judge"], row["p"]) == (
            "jev", "served-1", "covered", "pass", 0.75,
        )  # fmt: skip


def test_nothing_is_written_when_nothing_was_judged(tmp_path):
    out = run_step(wiring(Server(500), tmp_path), L4Config(), [BADGE], {})
    w = wiring(Server(500), tmp_path)
    assert record_rows(out, w, run_file=tmp_path / "r.jsonl", unit="u", run_id="r", round_no=1,
                       deterministic={}, judge={}) == 0  # fmt: skip
    assert not w.cache_file.exists()


def test_scn_ver_24_an_unwritable_s1_log_directory_leaves_the_step_unavailable_or_ok_never_raising(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    bad_log = blocker / "s1.jsonl"

    def remote() -> SystemOneBackend:
        return SystemOneBackend(
            "remote", model="m", base_url="http://s1.test", transport=httpx.MockTransport(Server()),  # type: ignore[arg-type]
            log_path=bad_log, redactor=Redactor({}),
        )  # fmt: skip

    assert run_step(S1Wiring(remote, tmp_path / "c.jsonl"), L4Config(), [BADGE], {}).status == "ok"

    from l4.llm.system_one import LayaServe

    def local() -> SystemOneBackend:
        serve = LayaServe(["/nonexistent/laya-serve"], {}, log_path=blocker / "laya-serve.log", ready_timeout_s=1)
        return SystemOneBackend("laya-local", model="m", serve=serve, redactor=Redactor({}))

    out = run_step(S1Wiring(local, tmp_path / "c.jsonl"), L4Config(), [BADGE], {})
    assert out.status == "unavailable" and "laya-local" in out.note
