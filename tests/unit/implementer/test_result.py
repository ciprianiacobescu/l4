import json
from pathlib import Path

import pytest

from l4.implementer.result import RESULT_SCHEMA, RESULT_SCHEMA_ID, ImplementerResult, ResultInvalid, parse_result

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
GOOD = {"status": "done", "phase": "red", "task_ids": ["1.1"], "summary": "wrote tests"}


def test_the_packaged_schema_is_the_canonical_copy():
    canonical = json.loads((FIXTURES / "schemas" / "implementer-result.schema.json").read_text())
    assert canonical == RESULT_SCHEMA
    assert RESULT_SCHEMA_ID == "l4/implementer-result@1" == canonical["$id"]


def test_unknown_status_is_invalid():
    with pytest.raises(ResultInvalid, match="status"):
        parse_result(json.dumps({**GOOD, "status": "great"}))


def test_a_minimal_result_parses_with_empty_defaults():
    result = parse_result(json.dumps(GOOD))
    assert isinstance(result, ImplementerResult)
    assert (result.status, result.phase, result.task_ids) == ("done", "red", ["1.1"])
    assert result.criteria_ids == [] and result.questions == [] and result.tdd_exemption is None


def test_bytes_and_mappings_are_accepted_and_nulls_mean_absent():
    nulls = {**GOOD, "questions": None, "tests_added": None, "tdd_exemption": None, "notes_for_verifier": None}
    assert parse_result(json.dumps(nulls).encode()).tests_added == []
    assert parse_result(nulls).summary == "wrote tests"


@pytest.mark.parametrize(
    ("patch", "where"),
    [
        ({"task_ids": []}, "task_ids"),
        ({"phase": "refactor"}, "phase"),
        ({"criteria_ids": ["C-XYZ"]}, "criteria_ids"),
        ({"summary": "x" * 2001}, "summary"),
        ({"questions": [{"title": "t", "context": "c", "kind": "technical"}] * 4}, "questions"),
        ({"questions": [{"title": "t", "context": "c", "kind": "legal"}]}, "questions[0].kind"),
    ],
)
def test_schema_violations_name_the_path(patch: dict, where: str):
    with pytest.raises(ResultInvalid, match=where.replace("[", r"\[").replace("]", r"\]")):
        parse_result({**GOOD, **patch})


@pytest.mark.parametrize("raw", ["", "not json", "[1]", "null"])
def test_text_that_is_not_an_object_is_invalid(raw: str):
    with pytest.raises(ResultInvalid):
        parse_result(raw)


def test_a_blocked_result_carries_its_questions():
    raw = {
        **GOOD,
        "status": "blocked",
        "questions": [{"title": "Which?", "context": "two readings", "kind": "ambiguous", "options": ["a", "b"]}],
    }
    result = parse_result(raw)
    assert result.questions[0].kind == "ambiguous" and result.questions[0].options == ["a", "b"]
    assert result.questions[0].blocking_tasks == []


def test_the_recorded_codex_results_parse():
    recorded = FIXTURES / "recorded" / "codex" / "0.160.0"
    for name in ("red-ok", "green-ok", "blocked"):
        assert parse_result((recorded / f"{name}.result.json").read_text()).task_ids


def test_error_text_never_echoes_values():
    with pytest.raises(ResultInvalid) as info:
        parse_result({**GOOD, "status": "sk-ant-abcdefghijklmnopqrstuvwx"})
    assert "sk-ant" not in str(info.value)
