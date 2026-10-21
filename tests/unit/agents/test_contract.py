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


# result-contract 1.5 (SCN-FAC-16, the attach part): why no `structured`, with no change to a status or a detail
def test_no_schema_hands_over_the_object_as_written_and_flags_a_missing_file() -> None:
    result = attach('{"status": "red"}', schema=None)
    assert result.status == "ok" and result.structured == {"status": "red"} and result.result_problem is None
    missing = attach(None, schema=None)
    assert missing.status == "ok" and missing.structured is None and missing.result_problem == "missing"
    broken = attach("not json", schema=None)
    assert broken.status == "error" and broken.detail == "result invalid: not JSON"
    assert broken.result_problem == "not_json"


def test_a_schema_run_names_the_problem_and_keeps_the_refused_object() -> None:
    assert attach(None).result_problem == "missing"
    assert attach("{nope").result_problem == "not_json"
    for text in ('"text"', "[1, 2]"):
        out = attach(text)
        assert out.result_problem == "not_object" and out.rejected is None and out.status == "error"
    assert attach("[1, 2]", schema=None).result_problem == "not_object"
    bad = {**GOOD, "status": "red"}
    out = attach(json.dumps(bad))
    assert out.status == "error" and out.result_problem == "invalid" and out.rejected == bad
    assert out.detail is not None and out.detail.startswith("result invalid: status: not one of")
    assert out.structured is None


def test_a_valid_result_has_no_problem() -> None:
    result = attach(json.dumps(GOOD))
    assert result.result_problem is None and result.rejected is None
