import json

import pytest

from l4.clarifier.answer import CLARIFIER_ANSWER_SCHEMA, AnswerInvalid, ClarifierAnswer, validate_answer
from l4.schemacheck import validate


def reply(**over) -> dict:
    base = {
        "question_id": "Q-002", "answer": "Use bcrypt with cost 12.", "confidence": "high", "kind": "technical",
        "citations": [{"ref": "design.md#L42", "quote": "passwords are hashed with bcrypt", "claim": "c"}],
        "rationale": "design.md says so",
    }  # fmt: skip
    return {**base, **over}


def test_a_valid_reply_parses():
    parsed = validate_answer(reply())
    assert isinstance(parsed, ClarifierAnswer)
    assert parsed.question_id == "Q-002" and parsed.citations[0].ref == "design.md#L42"
    no_citations = validate_answer(json.dumps(reply(citations=[])))  # the router needs one, not the schema
    assert isinstance(no_citations, ClarifierAnswer)


def test_the_schema_uses_only_the_keywords_the_validator_supports():
    assert validate(reply(), CLARIFIER_ANSWER_SCHEMA) == []  # an unsupported keyword would raise here


def test_unknown_property_and_bad_question_id_are_invalid():
    assert validate_answer(reply(extra="x")) == AnswerInvalid(("extra: not allowed",))
    assert validate_answer(reply(question_id="Q2")) == AnswerInvalid(("question_id: does not match the pattern",))
    nested = validate_answer(reply(citations=[{"ref": "a.md", "quote": "q", "claim": "c", "line": 3}]))
    assert nested == AnswerInvalid(("citations[0].line: not allowed",))


@pytest.mark.parametrize(
    "bad",
    [
        reply(answer=""),
        reply(answer="x" * 1201),
        reply(citations=[{"ref": "a.md", "quote": "quoted text", "claim": "c"}] * 4),
        reply(citations=[{"ref": "x" * 513, "quote": "quoted text", "claim": "c"}]),
        reply(citations=[{"ref": "a.md", "quote": "q" * 2001, "claim": "c"}]),
        reply(confidence="certain"),
        reply(kind="verdict"),
        reply(citations=[{"ref": "a.md"}]),
        reply(rationale=None),
    ],
)
def test_out_of_range_values_are_invalid(bad):
    assert isinstance(validate_answer(bad), AnswerInvalid)


def test_missing_property_and_not_json():
    reply_ = reply()
    del reply_["rationale"]
    assert isinstance(validate_answer(reply_), AnswerInvalid)
    assert validate_answer("not json") == AnswerInvalid(("$: not valid JSON",))


def test_problems_never_echo_values():
    secret = "glpat-AAAAAAAAAAAAAAAAAAAA"
    out = validate_answer(reply(question_id=secret, kind=secret))
    assert isinstance(out, AnswerInvalid) and secret not in " ".join(out.problems)


def test_the_bounds_themselves_are_valid():
    edge = {"ref": "x" * 512, "quote": "q" * 2000, "claim": "c" * 400}
    assert validate_answer(reply(answer="x" * 1200, citations=[edge] * 3)).__class__ is ClarifierAnswer
