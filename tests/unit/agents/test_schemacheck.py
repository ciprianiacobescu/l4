import pytest

from l4.schemacheck import SchemaUnsupported, validate

SCHEMA = {
    "$id": "x@1",
    "type": "object",
    "required": ["status", "ids"],
    "properties": {
        "status": {"enum": ["done", "blocked"]},
        "ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^C-[0-9a-f]{8}$"},
            "minItems": 1,
            "maxItems": 2,
        },
        "summary": {"type": "string", "maxLength": 5},
        "n": {"type": "integer"},
        "ex": {"type": ["object", "null"], "properties": {"reason": {"type": "string"}}},
    },
    "additionalProperties": False,
}


def ok(**over):
    return {"status": "done", "ids": ["C-0123abcd"], **over}


def test_a_valid_instance_has_no_errors():
    assert validate(ok(summary="abc", n=3, ex=None), SCHEMA) == []
    assert validate(ok(ex={"reason": "r"}), SCHEMA) == []


@pytest.mark.parametrize(
    ("instance", "needle"),
    [
        ({"ids": ["C-0123abcd"]}, "status"),
        (ok(status="nope"), "status"),
        (ok(ids=[]), "ids"),
        (ok(ids=["C-0123abcd"] * 3), "ids"),
        (ok(ids=["bad"]), "ids[0]"),
        (ok(summary="toolong"), "summary"),
        (ok(n=True), "n"),
        (ok(n="3"), "n"),
        (ok(extra=1), "extra"),
        (ok(ex={"reason": 1}), "ex.reason"),
        ([], "$"),
    ],
)
def test_violations_are_reported_with_their_path(instance, needle):
    errors = validate(instance, SCHEMA)
    assert errors and any(needle in e for e in errors), errors


def test_errors_never_contain_the_offending_value():
    secret = "ghp_" + "a1B2c3D4e5" * 3
    assert all(secret not in e for e in validate(ok(status=secret), SCHEMA))


def test_unsupported_keywords_raise_instead_of_being_ignored():
    with pytest.raises(SchemaUnsupported, match="oneOf"):
        validate({}, {"oneOf": []})
