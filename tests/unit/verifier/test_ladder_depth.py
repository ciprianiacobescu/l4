"""The ladder's depth (M1.3 Stage B) end to end: `l4 run` with a scripted fake agent for the implementer, the judge and
the audit writer, a bare remote, and a human who answers in `questions.md`."""

import json

from l4.agents.fake import Step
from l4.specs.criteria import openspec_criteria
from l4.verifier.audit import choose
from l4.verifier.types import CriterionEvidence, TracingTest

from ..conftest import FIXTURE, UNIT
from ..implementer.conftest import HEADER, IMPL, KNOWN, KNOWN_TEST, UNKNOWN, green_step, red_step
from ..orchestrator.conftest import BRANCH, UNIT_DIR, edit_questions_on_origin
from .conftest import judge_reply

CRITERIA = [c.id for c in openspec_criteria(FIXTURE / "openspec" / "changes" / "add-discount-codes")]
JUDGE = Step(structured=judge_reply(CRITERIA))
HOOK = "def pytest_report_teststatus(report):\n    return None\n"


def red_known_only() -> Step:
    """Red cites and tests one of the two criteria: the other one has no tracing test."""
    step = red_step()
    step.writes = {**step.writes, "tests/test_discount.py": HEADER + KNOWN_TEST}
    step.structured = {**step.structured, "criteria_ids": [KNOWN]}
    return step


def steps_of(run) -> dict[str, str]:
    return {e["step"]: e["status"] for e in run.events("verify.step")}


def test_a_planted_conftest_hook_fails_step_1_and_the_judge_is_never_called(run_l4, valid_spec):
    red = red_step()
    red.writes = {**red.writes, "tests/conftest.py": HOOK}
    run = run_l4([red, green_step()])
    assert run.code == 10 and len(run.adapter.requests) == 2
    assert steps_of(run) == {"0": "ok", "1": "failed", "10": "ok"}
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert "FAIL (round 1)" in text and "| content scan | failed |" in text and "pytest_report_teststatus" in text


def test_an_undeclared_noqa_is_a_major_deterministic_finding_that_fails_the_unit(run_l4, valid_spec):
    green = green_step()
    green.writes = {"src/pytdd/pricing.py": IMPL + "\nUNUSED = 1  # noqa: E501\n"}
    run = run_l4([red_step(), green])
    assert run.code == 10 and steps_of(run)["1"] == "failed"
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert "[major, deterministic] an inline suppression was not declared" in text and "# noqa: E501" in text


def test_a_declared_noqa_passes_and_is_listed_for_the_judge(run_l4, valid_spec):
    green = green_step()
    green.writes = {"src/pytdd/pricing.py": IMPL + "\nUNUSED = 1  # noqa: E501\n"}
    green.structured = {
        **green.structured,
        "suppressions": [{"file": "src/pytdd/pricing.py", "line": 99, "rule": "E501", "reason": "a long literal"}],
    }
    run = run_l4([red_step(), green, JUDGE])
    assert run.code == 0
    assert "a long literal" in run.adapter.requests[-1].prompt  # the judge reviews declared suppressions
    assert "Declared suppressions" in run.pushed(f"{UNIT_DIR}/verification.md")


def test_a_criterion_with_no_tracing_test_is_needs_human_with_one_verdict_question_and_exit_11(run_l4, valid_spec):
    run = run_l4([red_known_only(), green_step(), JUDGE])
    assert run.code == 11
    assert steps_of(run) == {"0": "ok", "1": "ok", "2": "ok", "3": "ok", "4": "ok", "9": "ok", "10": "ok"}
    questions = run.pushed(f"{UNIT_DIR}/questions.md")
    assert questions.count("- **Kind:** verdict") == 1 and "**Blocking tasks:** none" in questions
    assert UNKNOWN in questions and "accept as satisfied?" in questions
    [raised] = run.events("question.raised")
    assert (raised["kind"], raised["target"], raised["source"]) == ("verdict", UNKNOWN, "verifier")
    assert "uncovered" in run.pushed(f"{UNIT_DIR}/verification.md")
    assert run.outcome["units"][0]["phase_after"] == "awaiting_human"
    assert run.triggers()[-1] == "verify_needs_human"


def plan_entry(tdd, capsys, raw) -> dict:
    from l4.cli import main

    raw(tdd.repo, "fetch", "-q", "origin")  # the human pushed to the remote
    capsys.readouterr()
    main(["plan", "--json", "--repo", str(tdd.repo)], environ=tdd.environ)
    [entry] = json.loads(capsys.readouterr().out)["units"]
    return entry


def test_the_accept_answer_makes_the_plan_say_verify_and_round_2_resumes_at_aggregation(
    run_l4, valid_spec, tdd_repo, raw, capsys
):
    first = run_l4([red_known_only(), green_step(), JUDGE])
    assert first.code == 11
    waiting = plan_entry(tdd_repo, capsys, raw)
    assert waiting["next_action"] == "none" and "verdicts open: Q-001" in waiting["reason"]
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="accept: the second code is untestable here")
    ready = plan_entry(tdd_repo, capsys, raw)
    assert ready["next_action"] == "verify" and ready["reason"] == "verdicts answered: Q-001"
    second = run_l4([])  # no step at all: the second round may not call any agent
    assert second.code == 0 and second.adapter.requests == []
    assert second.triggers()[-2:] == ["verdicts_answered", "verify_pass"]
    verdicts = second.events("human.verdict")
    assert [(v["question"], v["target"], v["decision"], v["by"]) for v in verdicts] == [
        ("Q-001", UNKNOWN, "accept", "human")
    ]
    assert second.outcome["units"][0]["verdict"] == "PASS"
    reused = {e["step"]: e["status"] for e in second.events("verify.step") if e["round"] == 2}
    assert reused == {
        "0": "reused",
        "1": "reused",
        "2": "reused",
        "3": "reused",
        "4": "reused",
        "9": "reused",
        "10": "ok",
    }
    [last] = [e for e in second.events("verify.verdict") if e["round"] == 2]
    assert last["verdict"] == "PASS"
    text = second.pushed(f"{UNIT_DIR}/verification.md")
    assert "PASS (round 2)" in text and "reused (round 1)" in text and "## Human verdicts" in text
    assert [e["kind"] for e in second.events("question.raised")] == ["verdict"]  # nothing was asked again


def test_an_answer_without_accept_or_reject_is_not_consumed_and_the_plan_says_none(
    run_l4, valid_spec, tdd_repo, raw, capsys
):
    run_l4([red_known_only(), green_step(), JUDGE])
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="yes")
    entry = plan_entry(tdd_repo, capsys, raw)
    assert entry["next_action"] == "none" and "must start with accept or reject: Q-001" in entry["reason"]
    again = run_l4([])  # a named unit still runs; it consumes nothing and stays where it is
    assert again.code == 11 and again.events("human.verdict") == [] and again.adapter.requests == []
    assert again.outcome["units"][0]["phase_after"] == "awaiting_human"


def test_a_reject_answer_fails_the_criterion_and_the_unit(run_l4, valid_spec, tdd_repo, raw):
    run_l4([red_known_only(), green_step(), JUDGE])
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="reject: WHEN a code is blank THEN refuse it")
    second = run_l4([])
    assert second.code == 10 and second.adapter.requests == []
    assert second.outcome["units"][0]["verdict"] == "FAIL"
    assert "rejected by human: WHEN a code is blank THEN refuse it" in second.pushed(f"{UNIT_DIR}/verification.md")


def audited_criterion() -> str:
    covered = [CriterionEvidence(c, "", "covered", (TracingTest("t", "passed", "zero_value"),)) for c in CRITERIA]
    [chosen], _ = choose(covered, 0.5, UNIT, 1)
    return chosen


AUDIT_KNOWN = (
    'import pytest\nfrom pytdd.pricing import apply_discount\n\n\n@pytest.mark.l4("{cid}")\n'
    'def test_audit_known_code():\n    assert apply_discount(100.0, "SAVE10") == 90.0\n'
)
AUDIT_CALL_ONLY = (
    'import pytest\nfrom pytdd.pricing import apply_discount\n\n\n@pytest.mark.l4("{cid}")\n'
    'def test_audit_calls():\n    apply_discount(100.0, "SAVE10")\n'
)


def writer_step(cid: str, code: str) -> Step:
    return Step(structured={"criterion": cid, "code": code.format(cid=cid)})


def test_an_accepted_audit_test_is_committed_once_per_round_and_counts_as_evidence(run_l4, valid_spec, with_verifier):
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    run = run_l4([red_step(), green_step(), writer_step(cid, AUDIT_KNOWN), JUDGE], **config)
    assert run.code == 0
    [audit] = run.events("verify.audit")
    path = f"tests/test_l4_audit_c_{cid.removeprefix('C-')}_r1.py"
    assert (audit["criterion"], audit["status"], audit["path"]) == (cid, "accepted", path)
    assert run.subjects().count("test(add-discount-codes): verifier round 1 [skip ci]") == 1
    assert "def test_audit_known_code" in run.pushed(path)
    trailers = run.raw(run.tdd.origin, "log", "-1", "--format=%(trailers:key=L4-Phase,valueonly)", f"{BRANCH}~2")
    assert trailers.strip() == "verifying"
    assert steps_of(run)["4a"] == "ok"
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert "## Audit" in text and f"| {cid} | accepted |" in text and "audit" in text
    prompt = run.adapter.requests[2].prompt  # the writer's: the criterion and the source, never a test of the unit
    assert cid in prompt and "src/pytdd/pricing.py" in prompt and "def apply_discount" in prompt
    assert "test_known_code" not in prompt and "tests/test_discount.py" not in prompt


def test_an_audit_test_that_passes_against_zero_values_is_rejected_with_a_minor_finding(
    run_l4, valid_spec, with_verifier
):
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    run = run_l4([red_step(), green_step(), writer_step(cid, AUDIT_CALL_ONLY), JUDGE], **config)
    assert run.code == 0
    [audit] = run.events("verify.audit")
    assert audit["status"] == "rejected"
    assert "verifier round 1" not in " ".join(run.subjects())
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert "[minor, deterministic] an audit test was rejected" in text
    assert run.raw(run.tdd.origin, "ls-tree", "--name-only", BRANCH, "tests/").split() == [
        "tests/test_discount.py",
        "tests/test_pricing.py",
    ]


def test_the_audit_step_is_off_without_a_verifier_agent_or_with_a_zero_ratio(run_l4, valid_spec, with_verifier):
    config = with_verifier(audit_sample_ratio=0)
    run = run_l4([red_step(), green_step(), JUDGE], **config)
    assert run.code == 0 and run.events("verify.audit") == []
    assert "verifier.audit_sample_ratio is 0" in run.pushed(f"{UNIT_DIR}/verification.md")
