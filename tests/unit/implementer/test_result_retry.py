"""SCN-IMP-M2: after `result invalid` the retry prompt carries the validation error and the allowed values, on both
result paths (a prompt-contract adapter's `result invalid:` detail, a native adapter's `parse_result` failure)."""

import dataclasses
import re

from l4.agents.base import RunResult
from l4.implementer.loop import run_task

from .conftest import green_step, red_step, result
from .test_loop import TASK

ALLOWED = "status: not one of the allowed values (done, blocked, failed, partial)"
VALUES = "result values: status is one of done | blocked | failed | partial"


def fence(prompt: str) -> str:
    return prompt.split("# Your previous attempt was rejected", 1)[1].split("\n# ", 1)[0]


def wrong_status_step():
    step = red_step()
    step.structured = result("red", status="red", criteria_ids=step.structured["criteria_ids"])
    return step


def prompt_contract(bench) -> None:
    caps = dataclasses.replace(bench.adapter.capabilities(), schema_mode="prompt_contract")
    bench.adapter.capabilities = lambda: caps  # type: ignore[method-assign]


def test_a_native_adapter_retry_carries_the_error_the_allowed_values_and_the_values_line(make_bench):
    bench = make_bench([wrong_status_step(), red_step(), green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    first, second = (r.prompt for r in bench.adapter.requests[:2])
    assert "previous attempt was rejected" not in first
    block = fence(second)
    assert "the agent's result is invalid" in block and ALLOWED in block
    assert VALUES in block  # the harness's own line, from the schema, after the headline
    assert block.index("result is invalid") < block.index(VALUES)
    assert second.count("result values:") == 2  # the phase section's and the retry's


def test_a_prompt_contract_adapter_retry_carries_the_same(make_bench):
    bench = make_bench([red_step(), green_step()])
    prompt_contract(bench)
    original = bench.adapter.run
    first = {"done": False}

    def run(req):
        if not first["done"]:
            first["done"] = True
            req.raw_events_path.parent.mkdir(parents=True, exist_ok=True)
            req.raw_events_path.write_text("{}\n")
            detail = f"result invalid: {ALLOWED}"
            return RunResult(status="error", raw_events_path=req.raw_events_path, exit_code=0, detail=detail)
        return original(req)

    bench.adapter.run = run  # type: ignore[method-assign]
    assert run_task(bench.wb, TASK).status == "done"
    block = fence(bench.adapter.requests[0].prompt)
    assert "the agent step ended with status error: result invalid" in block and ALLOWED in block and VALUES in block


def test_the_ledger_keeps_the_headline_only_and_counts_the_added_line(make_bench):
    bench = make_bench([wrong_status_step(), red_step(), green_step()])
    run_task(bench.wb, TASK)
    [failed] = bench.events("task.attempt_failed")
    assert "result is invalid" in failed["reason"] and ALLOWED in failed["reason"]
    assert "result values:" not in failed["reason"]
    assert failed["excerpt_lines"] == 1
    for path in (bench.wb.ref.path / ".l4" / "ledger").glob("*.jsonl"):
        assert "result values:" not in path.read_text()  # the excerpt is harness text, kept out of the ledger anyway


def test_a_failure_that_is_not_a_result_error_gets_no_values_line(make_bench):
    step = red_step()
    step.status = "error"
    bench = make_bench([step, red_step(), green_step()])
    run_task(bench.wb, TASK)
    [failed] = bench.events("task.attempt_failed")
    assert failed["excerpt_lines"] == 0
    assert VALUES not in fence(bench.adapter.requests[1].prompt)


def test_a_green_retry_also_carries_it(make_bench):
    bad_green = green_step()
    bad_green.structured = result("green", status="green")
    bench = make_bench([red_step(), bad_green, green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    block = fence(bench.adapter.requests[2].prompt)
    assert ALLOWED in block and VALUES in block and re.search(r'phase is "green"', bench.adapter.requests[2].prompt)
