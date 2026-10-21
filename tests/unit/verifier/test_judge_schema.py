import json
import re
from pathlib import Path

import pytest

from l4.verifier.judge import JUDGE_SCHEMA, JudgeVerdict, SchemaInvalid, parse_judge_output

from .conftest import judge_reply

SPEC = Path(__file__).parents[3] / "docs" / "SPEC.md"
ID = "C-0a1b2c3d"


def test_the_packaged_schema_is_the_one_in_spec_10_3():
    text = SPEC.read_text(encoding="utf-8")
    block = re.search(r"```json\n(\{\n  \"\$id\": \"l4/judge-verdict@1\".*?\n\})\n```", text, re.S)
    assert block is not None
    assert json.loads(block.group(1)) == JUDGE_SCHEMA


def test_a_valid_reply_parses():
    reply = judge_reply([ID], findings=[{"severity": "minor", "title": "t", "detail": "d", "evidence": []}])
    verdict = parse_judge_output(json.dumps(reply))
    assert isinstance(verdict, JudgeVerdict)
    assert verdict.criteria[0].id == ID and verdict.findings[0].severity == "minor"


def test_a_fail_keeps_its_counterexample():
    cx = {"call": "def test_x():\n    assert 1 == 2", "expected": "1", "actual": "2"}
    reply = judge_reply([ID], "fail")
    reply["criteria"][0]["counterexample"] = cx
    verdict = parse_judge_output(reply)
    assert isinstance(verdict, JudgeVerdict) and verdict.criteria[0].counterexample.call.startswith("def test_x")


def test_two_riskiest_assumptions_is_schema_invalid():
    reply = judge_reply([ID], riskiest_assumptions=["a", "b"])
    result = parse_judge_output(reply)
    assert isinstance(result, SchemaInvalid)
    assert any("riskiest_assumptions" in p for p in result.problems)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["criteria"][0].update(id="C-XYZ"),  # not the id pattern
        lambda r: r["criteria"][0].update(verdict="maybe"),
        lambda r: r.pop("test_adequacy"),
        lambda r: r["riskiest_assumptions"].append("fourth"),
        lambda r: r["criteria"][0]["evidence"][0].update(quote="q" * 301),
    ],
)
def test_schema_breaks_are_invalid_and_never_echo_the_value(mutate):
    reply = judge_reply([ID])
    reply["criteria"][0]["evidence"][0]["ref"] = "sk-secret-value"
    mutate(reply)
    result = parse_judge_output(reply)
    assert isinstance(result, SchemaInvalid) and "sk-secret-value" not in " ".join(result.problems)


def test_text_that_is_not_json_is_invalid():
    assert isinstance(parse_judge_output("here is my verdict: pass"), SchemaInvalid)
    assert isinstance(parse_judge_output("[1, 2]"), SchemaInvalid)


def test_a_reply_without_accepted_is_valid_and_one_with_it_is_kept():
    """review-resolution 3.3 (L4-YOLO-028): `accepted` is optional, like `feedback`."""
    assert isinstance(parse_judge_output(judge_reply([ID])), JudgeVerdict)
    reply = judge_reply([ID], accepted=[{"id": "F-0a1b2c", "addressed": False, "evidence": "not in the diff"}])
    verdict = parse_judge_output(reply)
    assert isinstance(verdict, JudgeVerdict) and verdict.accepted[0].id == "F-0a1b2c"


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "FB-001", "addressed": True, "evidence": "e"},  # a feedback id is not a finding id
        {"id": "F-xyz", "addressed": True, "evidence": "e"},
        {"id": "F-0a1b2c", "addressed": "yes", "evidence": "e"},
        {"id": "F-0a1b2c", "addressed": True},
    ],
)
def test_a_bad_accepted_entry_is_invalid(entry):
    assert isinstance(parse_judge_output(judge_reply([ID], accepted=[entry])), SchemaInvalid)
