"""Pins (M1.14 line 40, expected `already satisfied`): the prompt contract's result details keep their text, so the
adapters' contract tests and the recorded fixtures stay green when the retry prompt gains the allowed values."""

import json

from l4.agents.base import RunResult
from l4.agents.contract import attach_file_result
from l4.implementer.result import RESULT_SCHEMA

GOOD = {"status": "done", "phase": "red", "task_ids": ["1.1"], "summary": "s"}


def attach(text: str | None, schema=RESULT_SCHEMA) -> RunResult:
    result = RunResult(status="error", raw_events_path=None, exit_code=0)  # type: ignore[arg-type]
    attach_file_result(result, text, schema, "the command")
    return result


def test_a_valid_result_is_ok() -> None:
    result = attach(json.dumps(GOOD))
    assert result.status == "ok" and result.structured == GOOD and result.detail is None


def test_not_json_keeps_its_text() -> None:
    assert attach("{nope").detail == "result invalid: not JSON"


def test_not_an_object_keeps_its_text() -> None:
    assert attach('"text"').detail == "result invalid: $: expected object"
    assert attach("[1, 2]", schema=None).detail == "result invalid: not an object"


def test_schema_problems_keep_the_headline_shape() -> None:
    detail = attach(json.dumps({**GOOD, "status": "red"})).detail
    assert detail is not None and detail.startswith("result invalid: status: not one of the allowed values")


def test_result_missing_is_untouched() -> None:
    assert attach(None).detail == "result missing: the command wrote no result file"
    assert attach(None, schema=None).status == "ok"
