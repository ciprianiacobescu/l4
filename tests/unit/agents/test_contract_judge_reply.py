"""The shared slicer of prompt-contract judges (kiro-judge L4-KJD-003, task 2.1): the first `{` to the last `}`."""

import json

from l4.agents.base import RunResult
from l4.agents.claude_code import STRUCTURED_DETAIL
from l4.agents.contract import attach_judge_reply

SCHEMA = {"type": "object", "required": ["verdict"], "properties": {"verdict": {"enum": ["pass", "fail"]}}}
GOOD = {"verdict": "pass"}


def attach(text: str | None, schema=SCHEMA) -> RunResult:
    result = RunResult(status="error", raw_events_path=None, exit_code=0)  # type: ignore[arg-type]
    attach_judge_reply(result, text, schema)
    return result


def test_a_fenced_object_is_the_reply() -> None:
    result = attach("```json\n" + json.dumps(GOOD) + "\n```")
    assert result.status == "ok" and result.structured == GOOD and result.detail is None


def test_prose_around_the_object_is_dropped() -> None:
    result = attach("Here is my verdict: " + json.dumps(GOOD) + " Thanks.")
    assert result.status == "ok" and result.structured == GOOD


def test_no_object_is_missing() -> None:
    for text in ("I think criterion 1 passes", "", None, "} then {", "{not json}"):
        result = attach(text)
        assert result.detail == f"{STRUCTURED_DETAIL} missing: the reply holds no JSON object"
        assert result.status == "error" and result.structured is None


def test_an_object_that_breaks_the_schema_is_invalid_and_kept() -> None:
    result = attach('{"verdict": "maybe"}')
    assert (result.detail or "").startswith(f"{STRUCTURED_DETAIL} invalid: ")
    assert result.rejected == {"verdict": "maybe"} and result.status == "error" and result.structured is None


def test_no_schema_accepts_any_object() -> None:
    assert attach('{"a": 1}', schema=None).structured == {"a": 1}
