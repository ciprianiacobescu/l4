"""Client-side JSON Schema validation for the subset the harness schemas use (SPEC L4-FAC-003: validation is
mandatory, and the dependency list has no JSON Schema library). A keyword outside the subset raises at validation
time instead of being ignored, so a schema change cannot silently weaken a check."""

import re
from typing import Any

SUPPORTED = frozenset(
    {
        "type", "enum", "required", "properties", "additionalProperties", "items", "minItems", "maxItems",
        "pattern", "maxLength", "minLength",
    }
)  # fmt: skip
ANNOTATIONS = frozenset({"$id", "$schema", "title", "description", "default", "examples"})

_TYPES: dict[str, Any] = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


class SchemaUnsupported(ValueError):
    pass


def _join(path: str, name: str) -> str:
    return name if path == "$" else f"{path}.{name}"


MAX_ALLOWED_CHARS = 160


def _allowed(values: list[Any]) -> str:
    """The schema's own constants, never the value that failed: the message goes into prompts and ledgers."""
    text = ", ".join(str(v) for v in values)
    return text if len(text) <= MAX_ALLOWED_CHARS else text[: MAX_ALLOWED_CHARS - 3] + "..."


def validate(instance: Any, schema: dict[str, Any]) -> list[str]:
    """Violations as `<path>: <rule>` lines; empty when valid. Values are never echoed (they may be secrets)."""
    errors: list[str] = []
    _check(instance, schema, "$", errors)
    return errors


def _check(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    unknown = set(schema) - SUPPORTED - ANNOTATIONS
    if unknown:
        raise SchemaUnsupported(f"unsupported JSON Schema keyword(s): {', '.join(sorted(unknown))}")
    if "type" in schema:
        wanted = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](value) for t in wanted):
            errors.append(f"{path}: expected {' or '.join(wanted)}")
            return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: not one of the allowed values ({_allowed(schema['enum'])})")
    if isinstance(value, str):
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match the pattern")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for index, item in enumerate(value):
                _check(item, schema["items"], f"{path}[{index}]", errors)
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{_join(path, name)}: required")
        properties = schema.get("properties", {})
        for name, item in value.items():
            if name in properties:
                _check(item, properties[name], _join(path, name), errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{_join(path, name)}: not allowed")
