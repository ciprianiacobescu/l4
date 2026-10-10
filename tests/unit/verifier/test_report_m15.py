"""The report, `verdict.json` and a restored round with M1.5's steps 5 (generated UI tests) and 8 (S1)."""

import json

from l4.verifier.evidence import restore_round
from l4.verifier.report import render_verification_md, verdict_json
from l4.verifier.types import (
    CriterionEvidence,
    CriterionOutcome,
    GateLine,
    GeneratedOutcome,
    S1Record,
    StepRecord,
    TracingTest,
    Verdict,
    VerifyResult,
)

UNIT = "openspec:show-item-count"
CID = "C-de7f2d3f"
TEST_ID = "e2e.test_l4_c_de7f2d3f::test_badge_shows_the_count"
ACCEPTED = GeneratedOutcome(
    CID, "accepted", "e2e/test_l4_c_de7f2d3f.py", 2, "", "def test_x(): ...", (), 0.02, "claude-sonnet-5-5", "p" * 64,
    "fail", "pass", (TEST_ID,), "f" * 64,
)  # fmt: skip
REFUSED = GeneratedOutcome(
    "C-68f2e098", "fails_at_head", "e2e/test_l4_c_68f2e098.py", 2, "the test fails at the head: t::x", "def t(): ...",
    ("test-results/t/trace.zip",), base="fail", head="fail",
)  # fmt: skip


def result(**over) -> VerifyResult:
    base = VerifyResult(
        UNIT, 1, Verdict.PASS, "a" * 40, "b" * 40,
        steps=[StepRecord("5", "ui test generation", "ok", 12.0, "1 accepted"), StepRecord("8", "s1 judge", "ok", 1.0)],
        gates=[GateLine("e2e", "pytest e2e", "pass", "", ".l4-out/gates/r-1/004-e2e.log")],
        trace=[CriterionEvidence(CID, "cart › Count", "covered", (TracingTest(TEST_ID, "passed", "generated"),))],
        criteria=[CriterionOutcome(CID, "cart › Count", "pass", "pass", "ok", tests=(TEST_ID,), s1_p=0.83)],
        generated=[ACCEPTED, REFUSED],
        s1=[S1Record(CID, "ok", 0.83, "laya-1", "laya-local", evidence={"implemented": 0.6, "unrelated": 0.4}),
            S1Record("C-68f2e098", "unavailable", reason="the state does not fit 300 tokens")],
    )  # fmt: skip
    for key, value in over.items():
        setattr(base, key, value)
    return base


def test_the_matrix_marks_the_generated_test_with_base_head_s1_and_links():
    text = render_verification_md(result())
    row = next(line for line in text.splitlines() if line.startswith(f"| {CID} | cart"))
    assert f"{TEST_ID} (passed, generated, base fail, head pass)" in row
    assert "0.83" in row and "e2e/test_l4_c_de7f2d3f.py" in row
    assert ".l4-out/e2e/page.html" in text


def test_a_test_generated_in_an_earlier_round_is_marked_without_base_and_head():
    text = render_verification_md(result(generated=[], s1=[]))
    assert f"{TEST_ID} (passed, generated)" in text and "base fail" not in text


def test_the_generated_section_lists_every_attempt_with_its_artifacts_and_reason():
    text = render_verification_md(result())
    assert "## Generated UI tests" in text
    refused = next(line for line in text.splitlines() if line.startswith("| C-68f2e098 | fails_at_head"))
    assert "test-results/t/trace.zip" in refused and "fails at the head" in refused
    assert "def t(): ..." not in text  # the writer's code is an artefact, not report text


def test_the_s1_section_says_it_decides_nothing_and_lists_the_unavailable():
    text = render_verification_md(result())
    assert "## S1" in text and "never decides" in text
    assert "| C-68f2e098 | unavailable" in text and "does not fit 300 tokens" in text


def test_a_round_without_step_5_or_8_renders_no_new_section_or_column():
    text = render_verification_md(result(generated=[], s1=[], gates=[]))
    assert "## Generated UI tests" not in text and "## S1" not in text and "S1 p" not in text


def test_verdict_json_carries_generated_and_s1_and_the_criterion_fields():
    body = verdict_json(result())
    back = json.loads(json.dumps(body))
    assert back["generated"] == body["generated"] and back["s1"] == body["s1"]
    accepted, refused = body["generated"]
    assert accepted["status"] == "accepted" and accepted["tests"] == [TEST_ID] and "code" not in accepted
    assert refused["code"] == "def t(): ..." and refused["artifacts"] == ["test-results/t/trace.zip"]
    assert body["s1"][0]["p"] == 0.83 and body["s1"][1]["status"] == "unavailable"
    assert body["criteria"][0]["tests"] == [TEST_ID] and body["criteria"][0]["s1_p"] == 0.83


def test_a_restored_round_keeps_steps_5_and_8_their_outcomes_and_their_status():
    original = result()
    original.steps[1] = StepRecord("8", "s1 judge", "unavailable", note="no laya")
    back = restore_round(json.loads(json.dumps(verdict_json(original))), UNIT, 2)
    assert [(s.step, s.status) for s in back.steps] == [("5", "reused"), ("8", "unavailable")]
    assert back.generated == [GeneratedOutcome(**{**ACCEPTED.__dict__, "code": ""}), REFUSED]
    assert back.s1 == original.s1
