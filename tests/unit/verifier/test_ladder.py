"""The ladder end to end: `l4 run` with a scripted fake agent for the implementer and for the judge (the shared fake
adapter serves both profiles; the judge's reply is the last step of the script)."""

import dataclasses
import sys
import types

import pytest

from l4 import services
from l4.agents.base import LimitSignal
from l4.agents.fake import Step
from l4.specs.criteria import openspec_criteria
from l4.state.ledger import read_ledger
from l4.verifier.ladder import verify_hook

from ..conftest import FIXTURE
from ..implementer.conftest import green_step, red_step
from .conftest import judge_reply

CRITERIA = [c.id for c in openspec_criteria(FIXTURE / "openspec" / "changes" / "add-discount-codes")]
FAILING_TEST = (
    "from pytdd.pricing import apply_discount\n\n\ndef test_cx():\n    assert apply_discount(50.0, 'SAVE10') == 40.0\n"
)
IMPLEMENT = [red_step(), green_step()]


def judge_step(reply: dict | None = None, **over) -> Step:
    return Step(structured=reply or judge_reply(CRITERIA), **over)


def failing_reply(counterexample: str | None = FAILING_TEST) -> dict:
    reply = judge_reply(CRITERIA)
    reply["criteria"][0]["verdict"] = "fail"
    if counterexample is not None:
        reply["criteria"][0]["counterexample"] = {"call": counterexample, "expected": "40.0", "actual": "45.0"}
    return reply


def test_a_passing_judge_reaches_verified_and_pushes_the_evidence(run_l4, valid_spec):
    run = run_l4([*IMPLEMENT, judge_step()])
    assert run.code == 0
    assert run.triggers()[-2:] == ["verification_started", "verify_pass"]
    assert run.outcome["units"][0]["phase_after"] == "verified" and run.outcome["units"][0]["verdict"] == "PASS"
    steps = {e["step"]: e["status"] for e in run.events("verify.step")}
    assert steps == {"0": "ok", "1": "ok", "2": "ok", "3": "ok", "4": "ok", "9": "ok", "10": "ok"}  # no step 4a event
    [verdict] = run.events("verify.verdict")
    assert verdict["verdict"] == "PASS" and verdict["round"] == 1 and verdict["findings"] == 0
    assert {e["role"] for e in run.events("availability.selected")} == {"implementer", "judges"}
    text = run.pushed("openspec/changes/add-discount-codes/verification.md")
    assert "PASS (round 1)" in text and "traceability: 2/2 criteria covered" in text and CRITERIA[0] in text
    assert "| 4a | audit sampling | not_run |" in text and "roles.verifier_agent is empty" in text
    assert run.pushed("openspec/changes/add-discount-codes/.l4/evidence/round-1/verdict.json")
    assert "docs(add-discount-codes): verification round 1 [skip ci]" in run.subjects()
    assert run.ledger()[-1]["type"] == "run.finished"


def test_the_judge_prompt_carries_spec_criteria_diff_and_the_gate_report_but_not_the_implementer_transcript(
    run_l4, valid_spec
):
    notes_red = red_step()
    notes_red.structured = {**notes_red.structured, "notes_for_verifier": "I considered rounding carefully."}
    run = run_l4([notes_red, green_step(), judge_step()])
    assert run.code == 0
    prompt = run.adapter.requests[-1].prompt
    assert all(c in prompt for c in CRITERIA) and "Discount codes" in prompt
    assert "+def apply_discount" in prompt or "apply_discount" in prompt.split("## Diff")[1]
    assert "tests.test_discount::test_known_code  passed" in prompt  # the gate report, per test
    assert "I considered rounding carefully." in prompt and "UNVERIFIED" in prompt
    assert ".l4/ledger" not in prompt.split("## Diff")[1].split("## Gate report")[0]  # no harness files in the diff
    assert run.adapter.requests[-1].permission_policy.mode == "judge"


def test_a_judge_fail_is_needs_human_exit_11_never_fail_and_its_counterexample_is_not_run(run_l4, valid_spec):
    run = run_l4([*IMPLEMENT, judge_step(failing_reply())])
    assert run.code == 11
    unit = run.outcome["units"][0]
    assert unit["phase_after"] == "awaiting_human" and unit["verdict"] == "NEEDS_HUMAN"
    assert [e["status"] for e in run.events("verify.counterexample")] == ["unexecuted"]
    text = run.pushed("openspec/changes/add-discount-codes/verification.md")
    assert "NEEDS_HUMAN (round 1)" in text and "counterexample unexecuted" in text
    assert run.triggers()[-1] == "verify_needs_human"


@pytest.mark.parametrize(
    "counterexample",
    [None, "assert apply_discount(50.0, 'SAVE10') == 40.0"],
    ids=["none", "not-pytest-style"],
)
def test_a_judge_fail_without_a_reproducing_counterexample_is_needs_human_never_fail(
    run_l4, valid_spec, counterexample
):
    run = run_l4([*IMPLEMENT, judge_step(failing_reply(counterexample))])
    assert run.code == 11
    assert run.outcome["units"][0]["phase_after"] == "awaiting_human"
    assert run.outcome["units"][0]["verdict"] == "NEEDS_HUMAN"


def test_a_judge_only_major_finding_is_needs_human(run_l4, valid_spec):
    reply = judge_reply(CRITERIA, findings=[{"severity": "major", "title": "t", "detail": "d", "evidence": []}])
    run = run_l4([*IMPLEMENT, judge_step(reply)])
    assert run.code == 11 and run.outcome["units"][0]["verdict"] == "NEEDS_HUMAN"


def test_minor_judge_findings_do_not_block(run_l4, valid_spec):
    reply = judge_reply(CRITERIA, findings=[{"severity": "minor", "title": "t", "detail": "d", "evidence": []}])
    assert run_l4([*IMPLEMENT, judge_step(reply)]).code == 0


def test_a_criterion_the_judge_skipped_is_needs_human(run_l4, valid_spec):
    run = run_l4([*IMPLEMENT, judge_step(judge_reply(CRITERIA[:1]))])
    assert run.code == 11


def test_a_reply_that_breaks_the_schema_twice_discards_the_judge(run_l4, valid_spec):
    bad = judge_reply(CRITERIA, riskiest_assumptions=["only one"])
    run = run_l4([*IMPLEMENT, judge_step(bad), judge_step(bad)])
    assert run.code == 11
    assert "discarded" in run.pushed("openspec/changes/add-discount-codes/verification.md")
    assert "riskiest_assumptions" in run.adapter.requests[-1].prompt  # the repair asked with the violated path


def test_a_judge_of_the_same_vendor_is_no_independent_verifier_exit_12_and_never_called(run_l4, valid_spec):
    run = run_l4([*IMPLEMENT], judge_vendor="fakeco")
    assert run.code == 12
    assert len(run.adapter.requests) == 2  # red and green only
    assert run.outcome["units"][0]["phase_after"] == "waiting_capacity"
    assert not run.events("verify.verdict")


def test_a_judge_that_cannot_run_is_exit_12(run_l4, valid_spec):
    run = run_l4([*IMPLEMENT, Step(status="error")])
    assert run.code == 12 and run.outcome["units"][0]["phase_after"] == "waiting_capacity"


def test_a_usage_limit_of_the_judge_is_exit_12_with_the_limit_recorded(run_l4, valid_spec):
    limit = LimitSignal("claude-code", None, "usage_limit", None, "claude.rate_limit_event", "")
    run = run_l4([*IMPLEMENT, Step(status="quota", limit=limit)])
    assert run.code == 12 and run.events("availability.limit")


def test_an_exception_leaves_the_unit_verifying_with_exit_1_and_no_verdict(run_l4, valid_spec):
    run = run_l4(IMPLEMENT)  # the script ends before the judge's turn: the fake raises
    assert run.code == 1
    assert run.events("verify.verdict") == [] and [e["to"] for e in run.events("phase.changed")][-1] == "verifying"


def test_step_2_failure_is_a_blocker_fail_and_the_judge_is_never_called(run_l4, valid_spec):
    # a lint that already fails at the base does not block the implementer (L4-IMP-002) but it does block the verifier
    run = run_l4(IMPLEMENT, lint=["sh -c 'echo preexisting lint error; exit 1'"])
    assert run.code == 10 and len(run.adapter.requests) == 2
    steps = {e["step"]: e["status"] for e in run.events("verify.step")}
    assert steps == {"0": "ok", "1": "ok", "2": "failed", "10": "ok"}
    text = run.pushed("openspec/changes/add-discount-codes/verification.md")
    assert "FAIL (round 1)" in text and "lint gate failed" in text and ".l4-out/gates/" in text
    assert "| 3 | tests | not_run |" in text and "| 9 | judge | not_run |" in text
    assert run.events("verify.verdict")[0]["findings"] == 1


def test_a_new_test_missing_at_verification_time_fails_step_3(run_l4, valid_spec):
    # the build gate runs first and deletes the implementer's test file: the report no longer holds the new test
    run = run_l4(IMPLEMENT, build=["sh -c 'rm -f tests/test_discount.py'"])
    assert run.code == 10 and len(run.adapter.requests) == 2
    steps = {e["step"]: e["status"] for e in run.events("verify.step")}
    assert steps == {"0": "ok", "1": "ok", "2": "ok", "3": "failed", "10": "ok"}
    assert "expected tests missing" in run.pushed("openspec/changes/add-discount-codes/verification.md")


def test_the_verify_command_runs_only_the_verifier_on_an_implemented_unit(run_verify, valid_spec):
    first = run_verify(IMPLEMENT, via="run")
    assert first.code == 1  # all tasks done, then the judge's turn failed: the unit stays `verifying`
    again = run_verify([judge_step()], via="verify")
    assert again.code == 0 and again.outcome["units"][0]["phase_before"] == "verifying"
    assert again.outcome["units"][0]["phase_after"] == "verified"
    assert again.events("verify.verdict")[0]["round"] == 1


def test_the_verify_command_refuses_a_unit_that_is_not_implemented(run_verify, valid_spec):
    refused = run_verify([], via="verify")
    assert refused.code == 2


def test_secrets_in_the_diff_and_the_notes_never_reach_the_judge(run_l4, valid_spec, monkeypatch):
    """Defence in depth: the step check (L4-SEC-008, tests/unit/implementer/test_step_secrets.py) and the pre-push scan
    (HB-4, tests/unit/orchestrator/test_push_secret_scan.py) would stop this commit first, so both are switched off here
    to prove the judge prompt is redacted on its own."""
    monkeypatch.setattr("l4.implementer.tdd.worktree_secrets", lambda *a, **k: [])
    monkeypatch.setattr("l4.orchestrator.outgoing_secrets", lambda *a, **k: [])
    token = "glpat-" + "A1b2C3d4" * 3
    key = "sk-ant-" + "Z9y8X7w6" * 3
    red = red_step()
    red.structured = {**red.structured, "notes_for_verifier": f"I used {key} to try it"}
    green = green_step()
    green.writes = {**green.writes, "src/pytdd/secret.py": f"TOKEN = '{token}'\n"}
    run = run_l4([red, green, judge_step()])
    assert run.code == 0
    prompt = run.adapter.requests[-1].prompt
    assert "src/pytdd/secret.py" in prompt and "REDACTED" in prompt
    assert token not in prompt and key not in prompt
    [judged] = run.events("verify.judge")
    assert judged["prompt_sha256"] != ""


def test_the_hook_pushes_the_committed_evidence_before_it_emits_the_verdict(run_l4, valid_spec, monkeypatch):
    seen: list[dict] = []

    def spy(ctx):
        def push() -> None:
            ledger = [e.type for e in read_ledger(ctx.services.ref.path).events]
            head = ctx.services.git.run("show", "--stat", "--format=%s", "HEAD").stdout
            seen.append({"verdict_emitted": "verify.verdict" in ledger, "head": head})
            ctx.push()

        return verify_hook(dataclasses.replace(ctx, push=push))

    module = types.ModuleType("l4_test_spy_verifier")
    module.verify_hook = spy  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "l4_test_spy_verifier", module)
    monkeypatch.setitem(services.HOOKS, "verify", "l4_test_spy_verifier:verify_hook")
    run = run_l4([*IMPLEMENT, judge_step()])
    assert run.code == 0
    [push] = seen
    assert push["verdict_emitted"] is False
    assert "verification round 1 [skip ci]" in push["head"] and "verification.md" in push["head"]


def test_the_verifier_gate_logs_do_not_overwrite_the_implementers(run_l4, valid_spec):
    run = run_l4([*IMPLEMENT, judge_step()])
    assert run.code == 0
    logs = [e["log"] for e in run.events("gate.finished")]
    assert len(logs) == len(set(logs)) and len(logs) > 4  # implementer and verifier gates, one file each


def test_base_merge_runs_before_the_reuse_decision(run_l4, valid_spec, tdd_repo, raw):
    """Round 1 ends NEEDS_HUMAN, then `main` moves and the verdicts are answered. The merge comes first and is a new
    subject, so the round is judged afresh instead of resuming from round 1's steps (L4-VER-011)."""
    from ..orchestrator.conftest import edit_questions_on_origin, new_origin_main
    from .test_ladder_depth import JUDGE, red_known_only

    assert run_l4([red_known_only(), *IMPLEMENT[1:], JUDGE]).code == 11
    new_origin_main(tdd_repo, raw, {"NEWS.md": "main moved\n"})
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="Accept: it is covered elsewhere")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    second = run_l4([JUDGE])
    assert second.code in (0, 11)
    [merged] = second.events("base.merged")
    assert merged["behind"] == 1 and merged["base_sha"] == raw(tdd_repo.repo, "rev-parse", "origin/main").strip()
    parents = raw(tdd_repo.origin, "rev-list", "--parents", "-n1", merged["merge_sha"]).split()
    assert parents[2] == merged["base_sha"]
    steps = [e for e in second.events("verify.step") if e["round"] == 2]
    assert steps and all(e["status"] != "reused" for e in steps)
    assert len(second.events("verify.judge")) == 2  # round 1's judge and the one of the fresh round 2
    assert second.adapter.requests, "the judge was called"
    assert "base merged:" in second.pushed("openspec/changes/add-discount-codes/verification.md")


def test_the_judge_prompt_is_published_and_its_hash_is_the_verdicts(run_l4, valid_spec):
    """HB-5: a reviewer can read exactly what the judge was sent, and the file hashes to verdict.json's value."""
    import hashlib
    import json

    run = run_l4([*IMPLEMENT, judge_step()])
    assert run.code == 0
    verdict = json.loads(run.pushed("openspec/changes/add-discount-codes/.l4/evidence/round-1/verdict.json"))
    [path] = sorted((run.tdd.repo / ".l4-out" / "agent").rglob("verify-judge-r1-*.prompt.md"))
    sent = run.adapter.requests[-1].prompt
    assert path.read_text(encoding="utf-8") == sent
    assert hashlib.sha256(path.read_bytes()).hexdigest() == verdict["prompt_sha256"]


def test_a_prompt_contract_judge_publishes_the_document_whose_hash_is_the_verdicts(run_l4, valid_spec, monkeypatch):
    """HB-5 / L4-VER-005, live job 5553 (opencode judge): a prompt-contract adapter is sent the prompt document with
    the schema instruction appended after it. The published `.prompt.md` is that document, so it hashes to
    verdict.json's `prompt_sha256`; before the fix it held the instruction too and hashed to something else."""
    import dataclasses
    import hashlib
    import json

    from l4.agents.fake import FakeAdapter
    from l4.llm.agent_judge import SCHEMA_INSTRUCTION

    native = FakeAdapter.capabilities
    monkeypatch.setattr(
        FakeAdapter, "capabilities", lambda self: dataclasses.replace(native(self), schema_mode="prompt_contract")
    )
    run = run_l4([*IMPLEMENT, judge_step()])
    assert run.code == 0
    verdict = json.loads(run.pushed("openspec/changes/add-discount-codes/.l4/evidence/round-1/verdict.json"))
    [path] = sorted((run.tdd.repo / ".l4-out" / "agent").rglob("verify-judge-r1-*.prompt.md"))
    request = run.adapter.requests[-1]
    instruction = SCHEMA_INSTRUCTION + json.dumps(request.result_schema, separators=(",", ":"))
    assert request.prompt.endswith(instruction), "the agent still gets the schema instruction"
    assert path.read_text(encoding="utf-8") + instruction == request.prompt
    assert hashlib.sha256(path.read_bytes()).hexdigest() == verdict["prompt_sha256"]


def test_verdict_json_records_the_judge_template_and_the_harness_commit(run_l4, valid_spec, monkeypatch):
    import json

    monkeypatch.setattr("l4.verifier.report.harness_commit", lambda: "abc1234")
    run = run_l4([*IMPLEMENT, judge_step()])
    verdict = json.loads(run.pushed("openspec/changes/add-discount-codes/.l4/evidence/round-1/verdict.json"))
    assert verdict["template"].startswith("judge@") and verdict["harness_commit"] == "abc1234"


def test_step8_not_run_when_s1_judge_holds_only_adapter_profiles(run_l4, valid_spec):
    """A7 (M1.8): an adapter profile on `roles.s1_judge` serves the clarifier's llm_boolean stand-in only; step 8 used
    to be `unavailable` on every round for it."""
    run = run_l4([*IMPLEMENT, judge_step()], roles={"s1_judge": ["judge"]})
    assert run.code == 0
    text = run.pushed("openspec/changes/add-discount-codes/verification.md")
    assert "| 8 | s1 judge | not_run |" in text
    assert "no System One profile on roles.s1_judge" in text and "llm_boolean" in text
    assert "| 8 | s1 judge | unavailable |" not in text
    assert "8" not in {e["step"] for e in run.events("verify.step")}


def test_an_overloaded_audit_writer_is_retried_in_the_run(
    run_l4,
    valid_spec,
    with_verifier,
    monkeypatch,
):
    """W3 end to end: the verifier agent answers 529 once, then a test; no `waiting_capacity` follows."""
    from l4.llm import agent_judge

    from .test_ladder_depth import AUDIT_KNOWN, JUDGE, audited_criterion, writer_step

    waits: list[float] = []
    monkeypatch.setattr(agent_judge.time, "sleep", waits.append)
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    overloaded = Step(status="error", transient=True, api_status=529, final_text="API Error: 529 Overloaded")
    run = run_l4([red_step(), green_step(), overloaded, writer_step(cid, AUDIT_KNOWN), JUDGE], **config)
    assert run.code == 0
    [transient] = run.events("availability.transient")
    assert (transient["role"], transient["status"], transient["attempt"], transient["wait_s"]) == (
        "verifier_agent", 529, 1, 20.0,
    )  # fmt: skip
    assert [e["status"] for e in run.events("verify.audit")] == ["accepted"]
    assert "waiting_capacity" not in {e["to"] for e in run.events("phase.changed")}
    assert 20.0 in waits
