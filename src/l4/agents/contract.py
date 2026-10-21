"""The prompt contract (SPEC 8.1): an adapter with no native schema flag asks, in the prompt, for the result object in
the file `$L4_RESULT_PATH` names, and reads it back here. Shared by opencode, kiro-cli and command."""

import json
from typing import Any

from l4.agents.base import RunResult
from l4.agents.claude_code import STRUCTURED_DETAIL
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
    Missing or invalid with a schema requested stays `error` with a one-line detail. `result_problem` says why there is
    no `structured` (a missing file with no schema is still `ok`), and `rejected` holds the object a schema refused;
    no status or detail changes with it (L4-FAC-010). `null` for an optional field is
    taken as absent, as the implementer prompt tells the model to write it."""
    if text is None:
        result.result_problem = "missing"
        if schema is None:
            result.status = "ok"
        else:
            result.detail = f"result missing: {who} wrote no result file"
        return
    try:
        parsed = drop_nulls(json.loads(text))
    except ValueError:
        result.detail = "result invalid: not JSON"
        result.result_problem = "not_json"
        return
    problems = validate(parsed, schema) if schema is not None else []
    if not isinstance(parsed, dict) or problems:
        hint = phase_hint(parsed, schema)
        result.detail = "result invalid: " + "; ".join(
            [*(problems[:3] or ["not an object"]), *([hint] if hint else [])]
        )
        if isinstance(parsed, dict):
            result.result_problem, result.rejected = "invalid", parsed
        else:
            result.result_problem = "not_object"
        return
    result.structured = parsed
    result.status = "ok"


def attach_judge_reply(result: RunResult, text: str | None, schema: dict[str, Any] | None) -> None:
    """A judge's reply may wrap its JSON in prose or a fence: slice from the first `{` to the last `}` (SPEC 8.3.1),
    parse and validate. A valid object is `structured` and the run `ok`; otherwise `detail` starts with
    `STRUCTURED_DETAIL` (so the judge takes its repair path) and an invalid object is kept as `rejected`."""
    text = text or ""
    start, end = text.find("{"), text.rfind("}")
    try:
        parsed = json.loads(text[start : end + 1]) if 0 <= start < end else None
    except ValueError:
        parsed = None
    _finish_reply(result, parsed, schema)


def last_top_level_object(text: str | None) -> dict[str, Any] | None:
    """The LAST top-level JSON object of `text` (L4-DLG-015): the text is scanned with `raw_decode` from each `{`.
    A scan resumes after an object it decoded (so an object inside another is not top-level), a `{` that does not
    decode is skipped, and code fences are only text. Never the slice from the first `{` to the last `}`, which a
    `{` in prose, a schema example before the answer or two objects would break."""
    text = text or ""
    decoder = json.JSONDecoder()
    found: dict[str, Any] | None = None
    at = text.find("{")
    while at != -1:
        try:
            value, end = decoder.raw_decode(text, at)
        except ValueError:
            at = text.find("{", at + 1)
            continue
        if isinstance(value, dict):
            found = value
        at = text.find("{", end)
    return found


def attach_read_only_reply(
    result: RunResult, last_message: str | None, final_text: str | None, schema: dict[str, Any] | None
) -> None:
    """The reply of a read-only run on a prompt-contract adapter (L4-DLG-015): the last top-level object of the text
    after the run's last tool call, else of the whole reply text; validated as a judge's reply. No result file."""
    text = last_message if last_message and last_message.strip() else final_text
    _finish_reply(result, last_top_level_object(text), schema)


def _finish_reply(result: RunResult, parsed: Any, schema: dict[str, Any] | None) -> None:
    if not isinstance(parsed, dict):
        result.detail = f"{STRUCTURED_DETAIL} missing: the reply holds no JSON object"
        return
    problems = validate(parsed, schema) if schema is not None else []
    if problems:
        result.detail = f"{STRUCTURED_DETAIL} invalid: " + "; ".join(problems[:3])
        result.rejected = parsed
        return
    result.structured = parsed
    result.status = "ok"
