"""The prompt contract (SPEC 8.1): an adapter with no native schema flag asks, in the prompt, for the result object in
the file `$L4_RESULT_PATH` names, and reads it back here. Shared by opencode, kiro-cli and command."""

import json
from typing import Any

from l4.agents.base import RunResult
from l4.agents.codex import drop_nulls
from l4.schemacheck import validate


def phase_hint(parsed: Any, schema: dict[str, Any] | None) -> str | None:
    """One more sentence for the mistake that was observed (magnitude-qwen, 2026-10-06): a result whose `status` is its
    own `phase` name. The phase names and the allowed statuses come from the schema. Any other unknown status gets
    nothing."""
    if not isinstance(parsed, dict) or schema is None:
        return None
    properties = schema.get("properties") or {}
    status = parsed.get("status")
    if status not in ((properties.get("phase") or {}).get("enum") or ()) or status != parsed.get("phase"):
        return None
    allowed = (properties.get("status") or {}).get("enum")
    if not allowed:
        return None
    return (
        f'status is the outcome of the step ({", ".join(str(v) for v in allowed)}); "{status}" is the phase and '
        'belongs in "phase"'
    )


def attach_file_result(result: RunResult, text: str | None, schema: dict[str, Any] | None, who: str) -> None:
    """A finished run (exit 0, nothing wrong with the stream) becomes `ok` with `structured` from the result file.
    Missing or invalid with a schema requested stays `error` with a one-line detail. `null` for an optional field is
    taken as absent, as the implementer prompt tells the model to write it."""
    if text is None:
        if schema is None:
            result.status = "ok"
        else:
            result.detail = f"result missing: {who} wrote no result file"
        return
    try:
        parsed = drop_nulls(json.loads(text))
    except ValueError:
        result.detail = "result invalid: not JSON"
        return
    problems = validate(parsed, schema) if schema is not None else []
    if not isinstance(parsed, dict) or problems:
        hint = phase_hint(parsed, schema)
        result.detail = "result invalid: " + "; ".join(
            [*(problems[:3] or ["not an object"]), *([hint] if hint else [])]
        )
        return
    result.structured = parsed
    result.status = "ok"
