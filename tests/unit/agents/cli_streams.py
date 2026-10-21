"""Synthetic stream lines of opencode 1.18 (`--format json`) and kiro-cli 2.x (`--output-format stream-json`), shaped
like the recorded ones (tests/fixtures/recorded). Synthetic: they are built here, not recorded."""

import json

SESSION = "5f53be83-795a-4db8-95ad-bd07535e6e2a"
REFUSED = "The user has specified a rule which prevents you from using this specific tool call."


def oc_event(kind: str, part: dict) -> str:
    return json.dumps({"type": kind, "sessionID": "ses_1", "part": part})


def oc_text(text: str) -> str:
    return oc_event("text", {"type": "text", "text": text})


def oc_tool(tool: str, status: str = "completed", error: str | None = None) -> str:
    state = {"status": status, "input": {}, **({"error": error} if error else {})}
    return oc_event("tool_use", {"type": "tool", "tool": tool, "state": state})


def oc_finish(reason: str = "stop", cost: float | None = 0) -> str:
    """A `step_finish`; `cost` None leaves the field out (a provider that reports none)."""
    part = {"reason": reason, "tokens": {"input": 1, "output": 1, "cache": {}}}
    return oc_event("step_finish", {**part, **({} if cost is None else {"cost": cost})})


def kiro_event(kind: str, data: dict) -> str:
    return json.dumps({"type": kind, "data": data})


def kiro_chunk(text: str) -> str:
    update = {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}
    return kiro_event("sessionUpdate", {"sessionId": SESSION, "update": update})


def kiro_call(tool: str, kind: str = "tool_call") -> str:
    update = {
        "sessionUpdate": kind,
        "toolCallId": "t1",
        "title": f"Using {tool}",
        "_meta": {"kiro": {"toolName": tool}},
    }
    return kiro_event("sessionUpdate", {"sessionId": SESSION, "update": update})


def kiro_stream(*events: str, final: str = "", engine: str = "v2") -> list[str]:
    started = kiro_event("runStarted", {"payloadSchema": "acp", "acpProtocolVersion": 1, "engine": engine})
    finished = kiro_event(
        "runFinished", {"sessionId": SESSION, "status": "success", "stopReason": "end_turn", "finalText": final}
    )
    return [started, *events, finished]


def kiro_metering(*credits: float) -> str:
    """A `metadata` event that meters the given amounts, in credits."""
    meters = [{"value": value, "unit": "credit", "unitPlural": "credits"} for value in credits]
    return kiro_event("metadata", {"sessionId": SESSION, "contextUsagePercentage": 3.0, "meteringUsage": meters})
