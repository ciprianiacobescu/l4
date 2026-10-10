"""A deterministic repair of the trivial schema breaks of a weak judge's reply (live wave D, W-D1).

Most NEEDS_HUMAN rounds of wave D came from judge replies that were discarded for a trivial reason: an evidence quote
over the schema's 300 characters, a `suggested_fix` that was a list. The repair fixes only what has one obvious,
meaning-preserving fix, walking the reply with the schema:

- a string over its `maxLength` is cut there, ending in an ellipsis;
- a free-text field (`suggested_fix`, `reasoning`, ...) that is a list becomes its lines joined, an object its JSON,
  a number its text;
- a key the schema does not list is dropped, and so is a `null` in an optional field that does not allow one.

Nothing else is touched. The enums (a verdict, a severity, a confidence) are never guessed, a missing field is never
invented, and a repair that would change the id or the verdict of any criterion, or that leaves the reply invalid,
returns the reply unchanged: a reply is never repaired into a PASS that it did not state. The fields are named by
schema path, never with their values (they may be secrets).
"""

import copy
import json
from typing import Any

from l4.schemacheck import validate

ELLIPSIS = "…"
UNKNOWN_KEY = "(unknown key)"
# free text whose type can be fixed without changing what it says (an id, a path or a call is never coerced)
COERCED_TEXT = frozenset({"suggested_fix", "reasoning", "reason", "detail", "title", "quote", "expected", "actual"})


def _text(value: Any) -> str | None:
    """The string a list, object or number stands for; None for a value with no safe text (a bool, a null)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    if isinstance(value, list):
        lines = [x if isinstance(x, str) else json.dumps(x, sort_keys=True, ensure_ascii=False) for x in value]
        return "\n".join(lines)
    return None


def _allows(schema: dict[str, Any], name: str) -> bool:
    kind = schema.get("type")
    return name in (kind if isinstance(kind, list) else [kind])


def _walk(value: Any, schema: dict[str, Any], path: str, fields: list[str]) -> Any:
    kind = schema.get("type")
    if isinstance(value, dict) and "properties" in schema:
        props, required = schema["properties"], set(schema.get("required", []))
        out: dict[str, Any] = {}
        for key, item in value.items():
            where = f"{path}.{key}" if path else key
            if key not in props:
                fields.append(f"{path or '(top level)'}.{UNKNOWN_KEY}")
            elif item is None and key not in required and not _allows(props[key], "null"):
                fields.append(where)
            else:
                out[key] = _walk(item, props[key], where, fields)
        return out
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [_walk(item, schema["items"], f"{path}[]", fields) for item in value]
    coercible = kind == "string" and not isinstance(value, str) and path.rsplit(".", 1)[-1] in COERCED_TEXT
    if coercible and (text := _text(value)) is not None:
        fields.append(path)
        value = text
    if kind == "string" and isinstance(value, str) and len(value) > schema.get("maxLength", len(value)):
        fields.append(path)
        value = value[: schema["maxLength"] - len(ELLIPSIS)] + ELLIPSIS
    return value


def _verdicts(reply: Any) -> list[tuple[Any, Any]]:
    criteria = reply.get("criteria") if isinstance(reply, dict) else None
    return (
        [(c.get("id"), c.get("verdict")) for c in criteria if isinstance(c, dict)] if isinstance(criteria, list) else []
    )


def repair_reply(reply: Any, schema: dict[str, Any]) -> tuple[Any, tuple[str, ...]]:
    """(the reply to use, the schema paths that were repaired). A reply that is valid, not an object, or that no
    repair makes valid comes back unchanged with no fields; the argument is never modified."""
    if not isinstance(reply, dict) or not validate(reply, schema):
        return reply, ()
    fields: list[str] = []
    fixed = _walk(copy.deepcopy(reply), schema, "", fields)
    if not fields or validate(fixed, schema) or _verdicts(fixed) != _verdicts(reply):
        return reply, ()
    return fixed, tuple(dict.fromkeys(fields))
