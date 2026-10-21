"""A read-only request gets the read-then-reply suffix, not the tool-less one (L4-DLG-015)."""

import json
from types import SimpleNamespace

from l4.agents.base import RunResult
from l4.llm.agent_judge import READ_THEN_REPLY, SCHEMA_INSTRUCTION, AgentJudge, schema_suffix, strip_suffix

SCHEMA = {"type": "object", "required": ["decision"], "properties": {"decision": {"type": "string"}}}


class Recorder:
    def __init__(self, mode: str = "prompt_contract") -> None:
        self.prompts: list[str] = []
        self.mode = mode

    def capabilities(self):
        return SimpleNamespace(schema_mode=self.mode)

    def run(self, req) -> RunResult:
        self.prompts.append(req)
        return RunResult(status="ok", raw_events_path=None, structured={"decision": "x"})  # type: ignore[arg-type]


def judge(adapter, **kw) -> AgentJudge:
    return AgentJudge(adapter, lambda prompt, schema, timeout: prompt, **kw)  # type: ignore[arg-type,return-value]


def test_a_read_only_request_gets_the_read_then_reply_suffix():
    adapter = Recorder()
    judge(adapter, reading=True).complete_structured("system", [], SCHEMA)
    (prompt,) = adapter.prompts
    assert "Do not call any tool" not in prompt
    assert "Read the files you need" in prompt and "nothing after it" in prompt
    assert prompt.endswith(json.dumps(SCHEMA, separators=(",", ":")))


def test_a_judge_request_keeps_the_schema_instruction():
    adapter = Recorder()
    judge(adapter).complete_structured("system", [], SCHEMA)
    assert adapter.prompts[0].endswith(schema_suffix(SCHEMA)) and SCHEMA_INSTRUCTION in adapter.prompts[0]
    assert READ_THEN_REPLY not in adapter.prompts[0]


def test_a_native_adapter_gets_no_suffix_in_either_mode():
    for reading in (True, False):
        adapter = Recorder("native")
        judge(adapter, reading=reading).complete_structured("system", [], SCHEMA)
        assert adapter.prompts == ["system"]


def test_the_published_prompt_and_the_digest_leave_the_suffix_out():
    document = "system\n\nuser"
    for reading in (True, False):
        assert strip_suffix(document + schema_suffix(SCHEMA, reading=reading), SCHEMA) == document
    assert strip_suffix(document, SCHEMA) == document
