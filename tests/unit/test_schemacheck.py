"""SCN-IMP-M2: an enum failure names the allowed values, built from the schema's own constants, and never the value
the agent wrote (the message goes into a prompt and a ledger: "names paths, never values")."""

from l4.implementer.result import RESULT_SCHEMA
from l4.schemacheck import validate


def test_an_enum_failure_lists_the_allowed_values() -> None:
    errors = validate({"status": "red", "phase": "red", "task_ids": ["1.1"], "summary": "s"}, RESULT_SCHEMA)
    assert errors == ["status: not one of the allowed values (done, blocked, failed, partial)"]


def test_the_list_follows_the_schema() -> None:
    schema = {"type": "object", "properties": {"mode": {"enum": ["a", "b", 3]}}}
    assert validate({"mode": "z"}, schema) == ["mode: not one of the allowed values (a, b, 3)"]
    assert validate({"mode": "a"}, schema) == []


def test_the_agents_value_never_enters_the_message() -> None:
    bad = "X" * 10_000
    errors = validate({"status": bad, "phase": "red", "task_ids": ["1"], "summary": "s"}, RESULT_SCHEMA)
    assert errors and "X" * 10 not in " ".join(errors) and all(len(e) < 200 for e in errors)
    secret = "sk-ant-abcdefghijklmnopqrstuvwx"
    leak = validate({"status": secret, "phase": "red", "task_ids": ["1"], "summary": "s"}, RESULT_SCHEMA)
    assert secret not in " ".join(leak)


def test_a_nested_enum_failure_keeps_its_path() -> None:
    errors = validate({"questions": [{"title": "t", "context": "c", "kind": "nope"}], "status": "done", "phase": "red",
                       "task_ids": ["1"], "summary": "s"}, RESULT_SCHEMA)  # fmt: skip
    assert errors == ["questions[0].kind: not one of the allowed values (technical, product, ambiguous)"]


def test_a_very_long_enum_is_cut() -> None:
    schema = {"enum": [f"value-{n:03d}" for n in range(200)]}
    (message,) = validate("nope", schema)
    assert len(message) < 260 and message.endswith("...)")


def test_other_messages_are_unchanged() -> None:
    schema = {"type": "object", "required": ["a"], "properties": {"b": {"type": "string", "maxLength": 2}}}
    assert validate({"b": 1}, schema) == ["a: required", "b: expected string"]
    assert validate({"a": 1, "b": "long"}, schema) == ["b: longer than 2"]
