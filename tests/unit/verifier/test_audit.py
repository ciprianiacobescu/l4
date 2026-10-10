"""Step 4a (verifier 3.7): the sample, the cap and the writer's view."""

from l4.verifier.audit import MAX_AUDIT_PER_ROUND, choose
from l4.verifier.types import CriterionEvidence, TracingTest

UNIT = "openspec:u"


def covered(cid: str, proof: str = "zero_value") -> CriterionEvidence:
    return CriterionEvidence(cid, "a", "covered", (TracingTest(f"t::{cid}", "passed", proof),))


def ids(n: int) -> list[str]:
    return [f"C-{i:08x}" for i in range(1, n + 1)]


def test_seeded_choice_is_reproducible_and_min_one():
    pool = [covered(c) for c in ids(10)]
    first = choose(pool, 0.1, UNIT, 1)
    assert first == choose(pool, 0.1, UNIT, 1) and len(first[0]) == 1 and first[1] == []
    assert choose(pool, 0.1, UNIT, 2) != first or choose(pool, 0.1, UNIT, 3) != first  # the round reseeds
    assert choose(pool, 0.0, UNIT, 1) == ([], [])  # 0 turns the step off
    assert choose([], 0.5, UNIT, 1) == ([], [])


def test_ratio_counts_the_covered_criteria_and_the_cap_is_two():
    pool = [covered(c) for c in ids(10)]
    chosen, skipped = choose(pool, 0.5, UNIT, 1)  # ceil(5) criteria drawn, two audited, three over the cap
    assert len(chosen) == MAX_AUDIT_PER_ROUND == 2 and len(skipped) == 3
    assert set(chosen).isdisjoint(skipped)


def test_pre_satisfied_criteria_come_first_and_are_always_audited():
    pool = [covered(c) for c in ids(8)] + [
        covered("C-0000ffff", "pre_satisfied"),
        covered("C-0000fffe", "pre_satisfied"),
    ]
    chosen, skipped = choose(pool, 0.1, UNIT, 1)
    assert sorted(chosen) == ["C-0000fffe", "C-0000ffff"] and len(skipped) == 0
    three = [*pool, covered("C-0000fffd", "pre_satisfied")]
    chosen, skipped = choose(three, 0.1, UNIT, 1)
    assert len(chosen) == 2 and len(skipped) == 1 and skipped[0].startswith("C-0000fff")


# --- an invalid reply is retried once with the reason (P3) ---------------------------------------------------------


class Replies:
    """A writer that answers with the next scripted structured result and keeps what it was sent."""

    def __init__(self, *parsed) -> None:
        self.parsed, self.sent = list(parsed), []

    def complete_structured(self, system, messages, json_schema, *, effort, max_tokens, timeout_s):
        from l4.agents.base import Usage
        from l4.llm.agent_judge import StructuredResult

        self.sent.append(messages[0].content)
        return StructuredResult("ok", parsed=self.parsed.pop(0), usage=Usage(cost_usd=0.01), model_resolved="m")


CID = "C-0a1b2c3d"
RELOAD = "import importlib\nimport pytdd.pricing as p\n\n\ndef test_x():\n    importlib.reload(p)\n"


def audit(make_bench, *parsed):
    from l4.specs.base import Criterion, Framework
    from l4.verifier.audit import run_audit

    bench = make_bench([])
    wb = bench.wb
    criterion = Criterion(CID, "a > b > c", Framework.OPENSPEC, "pricing", "b", "c", "WHEN x THEN y", "specs/x.md", 1)
    writer = Replies(*parsed)
    emitted: list[tuple] = []
    out = run_audit(
        wb, writer, {CID: criterion}, [CID], [], base_sha="HEAD", head="HEAD", round_no=1, timeout_s=5,
        emit=lambda kind, **data: emitted.append((kind, data)),
    )  # fmt: skip
    return out, writer, emitted


def test_an_invalid_reply_is_retried_once_with_the_reason(make_bench):
    out, writer, emitted = audit(
        make_bench,
        {"criterion": CID, "code": RELOAD},
        {"criterion": CID, "not_testable": "the criterion needs a browser"},
    )
    assert len(writer.sent) == 2 and "## Your previous attempt was rejected" not in writer.sent[0]
    assert "## Your previous attempt was rejected" in writer.sent[1] and "importlib.reload" in writer.sent[1]
    assert [(r.criterion, r.status) for r in out.records] == [(CID, "not_testable")] and out.findings == []
    assert emitted[0][1]["status"] == "not_testable"


def test_a_second_invalid_reply_is_a_minor_finding_and_not_a_third_call(make_bench):
    out, writer, _ = audit(make_bench, {"criterion": CID, "code": RELOAD}, {"criterion": CID, "code": RELOAD})
    assert len(writer.sent) == 2  # one retry only
    [record] = out.records
    assert record.status == "invalid" and "importlib.reload" in record.reason
    [finding] = out.findings
    assert finding.title == "an audit test could not be written" and finding.severity.value == "minor"


INSPECT = "import inspect\nimport pytdd.pricing as p\n\n\ndef test_x():\n    assert inspect.getmembers(p)\n"


def test_a_rejected_reply_is_retried_once_with_the_reason(make_bench):
    """W7: the reflection rule is a rejection like the re-import rule: the writer is told why, once, and the answer of
    the retry is used."""
    out, writer, _ = audit(
        make_bench, {"criterion": CID, "code": INSPECT}, {"criterion": CID, "not_testable": "needs a browser"}
    )
    assert len(writer.sent) == 2 and "## Your previous attempt was rejected" in writer.sent[1]
    assert "inspect" in writer.sent[1] and "import the public names" in writer.sent[1]
    assert [(r.criterion, r.status) for r in out.records] == [(CID, "not_testable")] and out.findings == []
