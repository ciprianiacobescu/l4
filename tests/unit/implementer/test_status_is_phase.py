"""SCN-IMP-M3: the one mistake that was observed (`"status": "red"` for a red step) gets one more sentence in the
reason, and no other unknown status does."""

import json

import pytest

from l4.agents import contract
from l4.agents.base import RunResult
from l4.implementer import result as result_module
from l4.implementer.result import RESULT_SCHEMA, ResultInvalid, parse_result

BASE = {"task_ids": ["1.1"], "summary": "s"}


def hint(phase: str) -> str:
    return (
        f'status is the outcome of the step (done, blocked, failed, partial); "{phase}" is the phase and belongs in '
        '"phase"'
    )


@pytest.mark.parametrize("phase", ["red", "green", "single"])
def test_a_status_that_equals_its_phase_gets_the_sentence_on_the_native_path(phase: str) -> None:
    with pytest.raises(ResultInvalid) as info:
        parse_result({**BASE, "status": phase, "phase": phase})
    message = str(info.value)
    assert "status: not one of the allowed values (done, blocked, failed, partial)" in message
    assert hint(phase) in message


@pytest.mark.parametrize("phase", ["red", "green", "single"])
def test_and_on_the_prompt_contract_path(phase: str) -> None:
    result = RunResult(status="error", raw_events_path=None, exit_code=0)  # type: ignore[arg-type]
    contract.attach_file_result(result, json.dumps({**BASE, "status": phase, "phase": phase}), RESULT_SCHEMA, "the cmd")
    assert result.status == "error" and result.detail.startswith("result invalid: ")  # type: ignore[union-attr]
    assert hint(phase) in result.detail  # type: ignore[operator]


def test_any_other_unknown_status_does_not() -> None:
    for status, phase in (("finished", "red"), ("red", "green"), ("RED", "red"), ("done!", "green")):
        with pytest.raises(ResultInvalid) as info:
            parse_result({**BASE, "status": status, "phase": phase})
        assert "is the phase and belongs" not in str(info.value), (status, phase)


def test_a_valid_result_and_other_problems_get_no_hint() -> None:
    assert parse_result({**BASE, "status": "done", "phase": "red"}).status == "done"
    with pytest.raises(ResultInvalid) as info:
        parse_result({"status": "done", "phase": "red"})  # task_ids and summary missing
    assert "required" in str(info.value) and "belongs in" not in str(info.value)


def test_both_paths_share_one_function() -> None:
    assert result_module.phase_hint is contract.phase_hint
    assert contract.phase_hint({"status": "red", "phase": "red"}, RESULT_SCHEMA) == hint("red")
    assert contract.phase_hint({"status": "red", "phase": "green"}, RESULT_SCHEMA) is None
    assert contract.phase_hint({"status": "red", "phase": "red"}, None) is None  # no schema: nothing to name
    assert contract.phase_hint({"status": "red", "phase": "red"}, {"properties": {}}) is None
    assert contract.phase_hint("red", RESULT_SCHEMA) is None  # not an object


def test_the_hint_reads_the_phases_from_the_schema() -> None:
    """Review of M1.14: the phase names come from the schema's `phase` enum like the statuses do, so a new phase gets
    the hint and a removed one does not."""
    import copy

    schema = copy.deepcopy(RESULT_SCHEMA)
    schema["properties"]["phase"]["enum"] = ["red", "green", "single", "refactor"]
    assert contract.phase_hint({"status": "refactor", "phase": "refactor"}, schema) is not None
    assert contract.phase_hint({"status": "refactor", "phase": "refactor"}, RESULT_SCHEMA) is None
    schema["properties"]["phase"]["enum"] = ["red", "green"]
    assert contract.phase_hint({"status": "single", "phase": "single"}, schema) is None
