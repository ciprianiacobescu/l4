"""A read-only run on a prompt-contract adapter replies in its last message (L4-DLG-015; SCN-DLG-56, 57, 100, 101,
102): the last top-level JSON object of the text after the last tool call, no result file."""

import json
from pathlib import Path

import pytest

from l4.agents.contract import last_top_level_object
from l4.agents.kiro_cli import KiroCliAdapter
from l4.agents.opencode import OpenCodeAdapter

RAW = Path("events.jsonl")
SCHEMA = {
    "type": "object",
    "required": ["decision"],
    "properties": {"decision": {"enum": ["answer", "escalate"]}},
}
REPLY = '{"decision": "answer"}'
SESSION = "5f53be83-795a-4db8-95ad-bd07535e6e2a"


def oc_event(kind: str, part: dict) -> str:
    return json.dumps({"type": kind, "sessionID": "ses_1", "part": part})


def oc_text(text: str) -> str:
    return oc_event("text", {"type": "text", "text": text})


def oc_tool(tool: str, status: str = "completed", error: str | None = None) -> str:
    state = {"status": status, "input": {}, **({"error": error} if error else {})}
    return oc_event("tool_use", {"type": "tool", "tool": tool, "state": state})


def oc_finish(reason: str = "stop") -> str:
    return oc_event("step_finish", {"reason": reason, "cost": 0, "tokens": {"input": 1, "output": 1, "cache": {}}})


REFUSED = "The user has specified a rule which prevents you from using this specific tool call."


def oc_parse(lines, **kw):
    return OpenCodeAdapter().parse(lines, exit_code=0, raw_events_path=RAW, read_only=True, schema=SCHEMA, **kw)


def test_opencode_read_only_takes_the_object_after_the_last_tool():  # SCN-DLG-56
    lines = [
        oc_text("I will read {the file} first"),
        oc_tool("read"),
        oc_finish("tool-calls"),
        oc_text("The criterion holds, as the file shows.\n" + REPLY),
        oc_finish(),
    ]
    result = oc_parse(lines)
    assert result.status == "ok" and result.structured == {"decision": "answer"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('the case {x is open. {"a": 1}', {"a": 1}),  # (a) a `{` that decodes to nothing, then the object
        ('Schema:\n```json\n{"decision": "escalate"}\n```\nAnswer:\n{"decision": "answer"}', {"decision": "answer"}),
        ('{"a": 1} and then {"b": 2}', {"b": 2}),  # (c) two objects
        ('{"outer": {"decision": "x"}}', {"outer": {"decision": "x"}}),  # an object inside another does not count
        ('{"a": 1} then a stray { brace', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ("no object here", None),
        ("", None),
        (None, None),
        ("[1, 2] only an array", None),
    ],
)
def test_the_last_top_level_object_wins(text, expected):  # SCN-DLG-100
    assert last_top_level_object(text) == expected


def test_the_last_object_is_taken_not_the_first_brace_to_the_last():
    assert last_top_level_object('{"a": 1} text } more {"b": {"c": 2}}') == {"b": {"c": 2}}


def test_a_refused_call_then_a_valid_reply_is_kept():  # SCN-DLG-101
    lines = [
        oc_tool("bash", "error", REFUSED),
        oc_finish("tool-calls"),
        oc_text("Refused, so I answer.\n" + REPLY),
        oc_finish(),
    ]
    result = oc_parse(lines)
    assert result.status == "ok" and result.structured == {"decision": "answer"}
    assert result.permission_denials[0]["tool_name"] == "bash"


@pytest.mark.parametrize("final", ["no object at all", '{"decision": "maybe"}'])
def test_a_refused_call_with_no_valid_reply_gives_none(final):  # SCN-DLG-102
    lines = [oc_tool("bash", "error", REFUSED), oc_finish("tool-calls"), oc_text(final), oc_finish()]
    result = oc_parse(lines)
    assert result.status == "error" and result.structured is None
    assert "rejected a tool call (bash)" in (result.detail or "")
    assert not (result.detail or "").startswith("structured")  # an adapter error (a deferral), not a bad reply


def test_a_refused_call_with_no_stop_is_permission_blocked():  # SCN-DLG-102
    result = oc_parse([oc_tool("bash", "error", REFUSED), oc_finish("tool-calls")])
    assert result.status == "permission_blocked" and result.structured is None


def test_a_reply_without_a_refused_call_that_does_not_validate_is_a_bad_reply():
    result = oc_parse([oc_text('{"decision": "maybe"}'), oc_finish()])
    assert result.status == "error" and result.structured is None and result.rejected == {"decision": "maybe"}
    assert (result.detail or "").startswith("structured")


def test_the_whole_reply_text_is_used_when_there_is_no_last_message():
    result = oc_parse([oc_text(REPLY), oc_finish()])
    assert result.status == "ok"


# -- kiro-cli ---------------------------------------------------------------------------------------------------


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


def kiro_parse(lines, **kw):
    return KiroCliAdapter().parse(lines, exit_code=0, raw_events_path=RAW, read_only=True, schema=SCHEMA, **kw)


def test_kiro_read_only_takes_the_object_after_the_last_tool():
    lines = kiro_stream(
        kiro_chunk("Looking at {the code}. "),
        kiro_call("read"),
        kiro_chunk("Done.\n" + REPLY),
        final="Looking at {the code}. Done.\n" + REPLY,
    )
    result = kiro_parse(lines)
    assert result.status == "ok" and result.structured == {"decision": "answer"}


def test_kiro_read_only_falls_back_to_the_final_text():
    result = kiro_parse(kiro_stream(final="Verdict: " + REPLY))
    assert result.status == "ok" and result.structured == {"decision": "answer"}


def test_no_result_file_is_read_in_read_only(tmp_path):
    (tmp_path / "result.json").write_text(json.dumps({"decision": "escalate"}))
    result = OpenCodeAdapter().parse(
        [oc_text("no object"), oc_finish()],
        exit_code=0,
        raw_events_path=RAW,
        read_only=True,
        schema=SCHEMA,
        result_text=(tmp_path / "result.json").read_text(),
    )  # a file at `result_path` is ignored in read-only mode
    assert result.structured is None and result.status == "error"
    kiro = kiro_parse(kiro_stream(final="no object"), result_text=(tmp_path / "result.json").read_text())
    assert kiro.structured is None and kiro.status == "error"


@pytest.mark.parametrize("tool", ["shell", "write", "execute_bash"])
def test_a_tool_outside_the_read_set_is_no_reply_on_kiro(tool):  # SCN-DLG-57
    lines = kiro_stream(kiro_call(tool), kiro_chunk(REPLY), final=REPLY)
    result = kiro_parse(lines)
    assert result.status == "error" and result.structured is None and tool in (result.detail or "")


def test_a_tool_outside_the_read_set_is_no_reply_on_opencode():  # SCN-DLG-57
    result = oc_parse([oc_tool("bash"), oc_finish("tool-calls"), oc_text(REPLY), oc_finish()])
    assert result.status == "error" and result.structured is None and "bash" in (result.detail or "")
    edited = oc_parse([oc_tool("edit"), oc_finish("tool-calls"), oc_text(REPLY), oc_finish()])
    assert edited.status == "error" and edited.structured is None
