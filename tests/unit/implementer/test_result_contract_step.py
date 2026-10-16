"""result-contract wave 2: `agent_step` finds the result object, normalizes it, and fails an attempt for its result only
when there is none (L4-IMP-019, L4-IMP-020, L4-IMP-021, L4-FAC-011)."""

import dataclasses
import json

import pytest

from l4.agents.fake import Step
from l4.implementer.loop import run_task
from l4.implementer.result import RESULT_SCHEMA
from l4.implementer.tdd import run_red

from .conftest import KNOWN, STUB, TESTS, UNKNOWN, green_step, red_step, result
from .test_tdd_red import TASK

WRITES = {"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB}
NO_RESULT = "no result was delivered (no result file and no result object in the final message)"


def prompt_contract(bench) -> None:
    caps = dataclasses.replace(bench.adapter.capabilities(), schema_mode="prompt_contract")
    bench.adapter.capabilities = lambda: caps  # type: ignore[method-assign]


def fixes(bench) -> list[dict]:
    return [f for e in bench.events("result.normalized") for f in e["fixes"]]


def test_the_request_schema_is_canonical_for_a_native_adapter(make_bench):
    bench = make_bench([red_step()])
    run_red(bench.wb, TASK, attempt=1)
    assert bench.adapter.requests[0].result_schema == RESULT_SCHEMA


def test_the_request_schema_is_none_for_a_prompt_contract_adapter(make_bench):
    bench = make_bench([red_step()])
    prompt_contract(bench)
    run_red(bench.wb, TASK, attempt=1)
    assert bench.adapter.requests[0].result_schema is None


def test_a_phase_name_status_and_a_missing_summary_are_repaired_and_the_checks_run(make_bench):
    """SCN-IMP-188 at bench level: the observed `qwen3.6-35b-a3b` object."""
    obj = {"status": "red", "phase": "red", "task_ids": ["1.1"], "criteria_ids": [KNOWN, UNKNOWN]}
    bench = make_bench([Step(writes=WRITES, structured=obj, last_message="I wrote two tests.")])
    prompt_contract(bench)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok"  # the red checks ran and passed on the work
    [event] = bench.events("result.normalized")
    assert (event["task"], event["phase"], event["attempt"], event["source"]) == ("1.1", "red", 1, "result")
    assert {"field": "status", "fix": "set", "to": "done", "was": "red"} in event["fixes"]
    assert {"field": "summary", "fix": "set", "from": "final_message"} in event["fixes"]
    assert "I wrote two tests." not in json.dumps(event)  # no agent text in the record


def test_a_normalized_object_still_faces_the_checks(make_bench):
    bench = make_bench([Step(structured={"status": "great"})])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and outcome.reason == "no tests added"
    assert {"field": "status", "fix": "set", "to": "done"} in fixes(bench)


def test_an_object_printed_in_the_final_text_is_taken_when_there_is_no_file(make_bench):
    """SCN-IMP-191: the object with `status` wins over a code sample before it."""
    text = 'Here is a sample: {"a": 1}\n\n```json\n{"status": "Done", "summary": "added two tests"}\n```\n'
    bench = make_bench([Step(writes=WRITES, final_text=text)])
    prompt_contract(bench)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok"
    [event] = bench.events("result.normalized")
    assert event["source"] == "final_message"


def test_a_result_in_agent_tmp_is_not_taken_and_the_attempt_fails(make_bench):
    """SCN-IMP-194."""
    obj = result("red", criteria_ids=[KNOWN, UNKNOWN])
    bench = make_bench([Step(writes={**WRITES, "agent-tmp/result.json": json.dumps(obj)}, final_text="done, no json")])
    prompt_contract(bench)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and NO_RESULT in outcome.reason
    assert "agent-tmp" not in bench.wb.git.run("ls-files").stdout


@pytest.mark.parametrize("contract", [True, False])
def test_no_result_object_fails_the_attempt_and_the_next_prompt_has_the_reason_and_the_values_line(
    make_bench, contract
):
    """SCN-IMP-195, prompt-contract and native."""
    bench = make_bench([Step(), red_step(), green_step()])
    if contract:
        prompt_contract(bench)
    assert run_task(bench.wb, TASK).status == "done"
    [failed] = bench.events("task.attempt_failed")
    assert "the agent's result is invalid: no result was delivered" in failed["reason"]
    wanted = "no result file and no result object" if contract else "no result object in the final message"
    assert wanted in failed["reason"]
    second = bench.adapter.requests[1].prompt
    assert "no result was delivered" in second and second.count("result values:") == 2


def test_a_blocked_result_with_no_question_is_not_a_failed_attempt(make_bench):
    """SCN-IMP-196; the owner's decision of 2026-10-16: the one question is made from the summary."""
    bench = make_bench([Step(structured={"status": "blocked", "summary": "the tests need a database URL"})])
    prompt_contract(bench)
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "blocked" and bench.events("task.attempt_failed") == []
    text = (bench.wb.ref.path / "questions.md").read_text()
    assert "Task 1.1 is blocked" in text and "the tests need a database URL" in text
    assert "malformed" not in text


def test_a_blocked_result_whose_questions_were_all_malformed_says_how_many_were_dropped(make_bench):
    bad = {"status": "BLOCKED", "summary": "cannot go on", "questions": [{"context": "no title", "kind": "ambiguous"}]}
    bench = make_bench([Step(structured=bad)])
    prompt_contract(bench)
    assert run_task(bench.wb, TASK).status == "blocked"
    text = (bench.wb.ref.path / "questions.md").read_text()
    assert "Task 1.1 is blocked" in text and "cannot go on (1 malformed questions were dropped)" in text
    assert bench.events("task.attempt_failed") == []
    assert len(bench.events("question.raised")) == 1


QUESTION = {"title": "Which rounding?", "context": "they disagree", "kind": "ambiguous"}


def test_a_missing_status_with_a_question_raises_it(make_bench):
    """SCN-IMP-197."""
    bench = make_bench([Step(structured={"summary": "stuck", "questions": [QUESTION]})])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "blocked" and [q.title for q in outcome.questions] == ["Which rounding?"]
    assert {"field": "status", "fix": "set", "to": "blocked"} in fixes(bench)


def test_five_questions_keep_the_first_three(make_bench):
    bench = make_bench([Step(structured=result("red", status="blocked", questions=[QUESTION] * 5))])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "blocked" and len(outcome.questions) == 3
    assert {"field": "questions", "fix": "cut", "count": 2} in fixes(bench)


def test_a_native_schema_break_is_normalized_and_agent_finished_keeps_error(make_bench):
    rejected = {"status": "red", "task_ids": ["1.1"], "criteria_ids": [KNOWN, UNKNOWN], "summary": "two tests"}
    bench = make_bench([Step(status="error", writes=WRITES, result_problem="invalid", rejected=rejected)])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok"
    [finished] = bench.events("agent.finished")
    assert finished["status"] == "error"
    assert {"field": "status", "fix": "set", "to": "done", "was": "red"} in fixes(bench)


def test_an_errored_run_with_no_result_problem_fails_as_before(make_bench):
    bench = make_bench([Step(status="timeout")])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "reached its time limit" in outcome.reason


def test_the_agents_test_list_is_not_read_the_jUnit_diff_is(make_bench):
    """SCN-IMP-189 at bench level."""
    dotted = result("red", tests_added=["tests.test_discount.test_known_code"], criteria_ids=[KNOWN, UNKNOWN])
    none = make_bench([Step(writes={"src/pytdd/pricing.py": STUB}, structured=dotted)])
    outcome = run_red(none.wb, TASK, attempt=1)
    assert outcome.status == "failed" and outcome.reason == "no tests added"
    ok = make_bench([Step(writes=WRITES, structured=dotted)])
    assert run_red(ok.wb, TASK, attempt=1).status == "ok"
    [red_ok] = ok.events("task.red_ok")
    assert red_ok["tests"] and all("::" in t for t in red_ok["tests"])
    assert "tests.test_discount.test_known_code" not in red_ok["tests"]


def test_agent_finished_records_the_context_peak_when_the_run_has_one(make_bench):
    bench = make_bench([red_step(context_peak_tokens=51200, context_peak_percent=12.5), red_step()])
    run_red(bench.wb, TASK, attempt=1)
    bench.wb.discard_changes()
    run_red(bench.wb, TASK, attempt=2)
    first, second = bench.events("agent.finished")
    assert first["context_peak_tokens"] == 51200 and first["context_peak_percent"] == 12.5
    assert "context_peak_tokens" not in second and "context_peak_percent" not in second
