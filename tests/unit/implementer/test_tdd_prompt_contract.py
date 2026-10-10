"""A prompt-contract adapter (opencode, kiro-cli, command) is told where to write its result; a native one is not."""

import dataclasses
import json

from l4.implementer.result import RESULT_SCHEMA
from l4.implementer.tdd import run_red

from .conftest import red_step
from .test_tdd_red import TASK


def test_a_native_adapter_is_not_told_a_result_path(make_bench):
    bench = make_bench([red_step()])
    run_red(bench.wb, TASK, attempt=1)
    assert "Write your result object to" not in bench.adapter.requests[0].prompt


def test_a_prompt_contract_adapter_is_told_the_result_path(make_bench):
    bench = make_bench([red_step()])
    caps = dataclasses.replace(bench.adapter.capabilities(), schema_mode="prompt_contract")
    bench.adapter.capabilities = lambda: caps  # type: ignore[method-assign]
    run_red(bench.wb, TASK, attempt=1)
    request = bench.adapter.requests[0]
    # the short alias of the step directory (M1.13 MAG), not the long host path a weak model rewrites
    assert "Write your result object to `.l4-result/result.json`." in request.prompt


def test_a_prompt_contract_adapter_is_given_the_result_schema(make_bench):
    bench = make_bench([red_step()])
    caps = dataclasses.replace(bench.adapter.capabilities(), schema_mode="prompt_contract")
    bench.adapter.capabilities = lambda: caps  # type: ignore[method-assign]
    run_red(bench.wb, TASK, attempt=1)
    assert json.dumps(RESULT_SCHEMA, separators=(",", ":"), sort_keys=True) in bench.adapter.requests[0].prompt


def test_a_kiro_leaf_s_requirement_links_reach_the_prompt(make_bench):
    """kiro-e2e H1 K20: the `_Requirements:_` refs of the leaf are part of the task block the agent reads."""
    bench = make_bench([red_step()])
    run_red(bench.wb, dataclasses.replace(TASK, links=("1.1",)), attempt=1)
    assert "_Requirements: 1.1_" in bench.adapter.requests[0].prompt
