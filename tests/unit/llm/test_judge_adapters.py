"""G18: opencode and codex as tool-less judges, replayed from recorded runs (no CLI is called)."""

import json
from pathlib import Path

import pytest

from l4.agents.base import PermissionPolicy, RunRequest
from l4.agents.codex import CodexAdapter, strictify_schema
from l4.agents.opencode import OpenCodeAdapter
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile
from l4.llm.agent_judge import JUDGE_ADAPTERS, AgentJudge, Msg
from l4.schemacheck import validate

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded"
OPENCODE = RECORDED / "opencode" / "1.18.33"
VERDICT_SCHEMA = json.loads((Path(__file__).parents[3] / "src/l4/verifier/judge-verdict.schema.json").read_text())
SIMPLE = {
    "type": "object", "required": ["verdict", "criteria"],
    "properties": {"verdict": {"enum": ["pass", "fail"]}, "criteria": {"type": "array"}},
}  # fmt: skip


class FakeProc:
    def __init__(self, stdout: str, outcome: ProcOutcome | None = None, on_run=None) -> None:
        self.stdout, self.outcome, self.on_run, self.calls = stdout, outcome or ProcOutcome(0), on_run, []

    def run(self, argv, env, cwd, *, stdout_path, timeout_s, stdin=None, **kw):
        self.calls.append({"argv": list(argv), "env": dict(env), "stdin": stdin})
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(self.stdout)
        if self.on_run:
            self.on_run()
        return self.outcome


def make_request(tmp_path: Path, profile: Profile):
    (tmp_path / "bin").mkdir(exist_ok=True)
    for name in ("opencode", "codex"):
        (tmp_path / "bin" / name).write_text("#!/bin/sh\n")
        (tmp_path / "bin" / name).chmod(0o755)

    def make(prompt: str, schema: dict, timeout_s: int) -> RunRequest:
        return RunRequest(
            profile=profile, role="judge", cwd=tmp_path / "wt", prompt=prompt,
            result_path=tmp_path / "res" / "result.json", raw_events_path=tmp_path / "raw" / "events.jsonl",
            env={"PATH": str(tmp_path / "bin")}, result_schema=schema,
            permission_policy=PermissionPolicy("judge"), timeout_s=timeout_s,
        )  # fmt: skip

    return make


# the same shape with the `items` a strict backend demands
STRICT_READY = {
    **SIMPLE,
    "properties": {**SIMPLE["properties"], "criteria": {"type": "array", "items": {"type": "string"}}},
}


def test_the_judge_adapters_are_claude_codex_opencode_kiro_copilot_and_fake():
    assert JUDGE_ADAPTERS == ("claude-code", "codex", "opencode", "kiro-cli", "copilot-cli", "fake")
    assert "kiro-cli" in JUDGE_ADAPTERS and "copilot-cli" in JUDGE_ADAPTERS


def test_the_escalation_keeper_counts_a_kiro_judge():
    from l4.config.schema import L4Config
    from l4.verifier.selection import independence_keeper

    cfg = L4Config.model_validate(
        {
            "profiles": {
                "impl-a": {"adapter": "opencode", "model": "m", "vendor": "deepseek"},
                "impl-b": {"adapter": "opencode", "model": "n", "vendor": "alibaba"},
                "kj": {"adapter": "kiro-cli", "model": "claude-sonnet-5.5"},
            },
            "roles": {"implementer": ["impl-a"], "judges": ["kj"]},
        }
    )
    keeper = independence_keeper(cfg, ["impl-a"])
    assert keeper("impl-b", cfg.profiles["impl-b"]) is None  # the Kiro judge on Claude stays independent
    clash = L4Config.model_validate(
        {**cfg.model_dump(), "profiles": {**cfg.model_dump()["profiles"], "impl-c": {"adapter": "claude-code"}}}
    )
    assert "no profile of roles.judges would be independent" in keeper_text(clash)


def keeper_text(cfg):
    from l4.verifier.selection import independence_keeper

    return independence_keeper(cfg, ["impl-a"])("impl-c", cfg.profiles["impl-c"]) or ""


def test_opencode_reply_sliced_and_codex_strict_schema(tmp_path):
    # opencode: the reply wraps its JSON in prose; the slice is validated and handed over
    profile = Profile(adapter="opencode", model="openrouter/openai/gpt-5.4-mini", vendor="openai")
    proc = FakeProc((OPENCODE / "judge-ok-openrouter-gpt-5.4-mini.jsonl").read_text())
    judge = AgentJudge(OpenCodeAdapter(proc), make_request(tmp_path, profile))
    out = judge.complete_structured("You are a judge.", [Msg("user", "Judge this.")], SIMPLE)
    assert out.status == "ok" and out.parsed is not None and validate(out.parsed, SIMPLE) == []
    assert "You are a judge." in proc.calls[0]["stdin"]
    assert json.dumps(SIMPLE, separators=(",", ":")) in proc.calls[0]["stdin"]  # the schema travels in the prompt
    # codex: the schema the CLI is given is the strict one, and the reply is read back from -o with nulls dropped
    reply = {"verdict": "pass", "criteria": [], "summary": None}
    schema = {**STRICT_READY, "properties": {**STRICT_READY["properties"], "summary": {"type": "string"}}}
    cdx = Profile(adapter="codex", model="gpt-6-luna", vendor="openai")
    request = make_request(tmp_path, cdx)

    def codex_answers() -> None:
        written = json.loads((tmp_path / "res" / "output-schema.strict.json").read_text())
        assert written == strictify_schema(schema) and written["additionalProperties"] is False
        (tmp_path / "res" / "result.json").write_text(json.dumps(reply))

    stream = '{"type":"thread.started","thread_id":"t"}\n{"type":"turn.completed","usage":{}}\n'
    cproc = FakeProc(stream, on_run=codex_answers)
    out = AgentJudge(CodexAdapter(cproc), request).complete_structured("sys", [Msg("user", "u")], schema)
    assert out.status == "ok" and out.parsed == {"verdict": "pass", "criteria": []}
    argv = cproc.calls[0]["argv"]
    assert argv[1:4] == ["exec", "--json", "--ephemeral"] and argv[argv.index("-s") + 1] == "read-only"
    assert "--ignore-user-config" in argv and "--ignore-rules" in argv and argv[-1] == "-"
    assert "workspace-write" not in argv


def test_a_codex_judge_reply_that_breaks_the_schema_is_a_schema_invalid_result_not_an_error(tmp_path):
    cdx = Profile(adapter="codex", model="gpt-6-luna", vendor="openai")
    stream = '{"type":"turn.completed","usage":{}}\n'
    proc = FakeProc(stream, on_run=lambda: (tmp_path / "res" / "result.json").write_text('{"verdict": "maybe"}'))
    out = AgentJudge(CodexAdapter(proc), make_request(tmp_path, cdx)).complete_structured("s", [], STRICT_READY)
    assert out.status == "schema_invalid"


def test_an_opencode_judge_that_hits_a_limit_reports_a_limit(tmp_path):
    profile = Profile(adapter="opencode", model="google/gemini-3.5-flash", vendor="google")
    proc = FakeProc((OPENCODE / "judge-error-429-google-free-tier.jsonl").read_text(), ProcOutcome(1))
    out = AgentJudge(OpenCodeAdapter(proc), make_request(tmp_path, profile)).complete_structured("s", [], SIMPLE)
    assert out.status == "limit" and out.run is not None and out.run.limit is not None


class SequencedProc(FakeProc):
    """The nth call prints the nth stdout (the last one repeats); `outcomes` likewise."""

    def __init__(self, *answers: tuple[str, ProcOutcome]) -> None:
        super().__init__("")
        self.answers = list(answers)

    def run(self, argv, env, cwd, **kw):
        self.stdout, self.outcome = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return super().run(argv, env, cwd, **kw)


class Events:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def append(self, event_type: str, /, **data):
        self.events.append((event_type, data))


def test_an_opencode_judge_call_that_ends_in_a_502_is_retried_in_the_run(tmp_path):
    """SCN-AVL-32: the error event names `[502] Bad Gateway` only in its message; the next call answers."""
    profile = Profile(adapter="opencode", model="openrouter/openai/gpt-5.4-mini", vendor="openai")
    failed = json.dumps(
        {"type": "error", "sessionID": "s", "error": {"name": "APIError", "data": {"message": "[502] Bad Gateway"}}}
    )
    good = (OPENCODE / "judge-ok-openrouter-gpt-5.4-mini.jsonl").read_text()
    proc, events, waits = SequencedProc((failed, ProcOutcome(1)), (good, ProcOutcome(0))), Events(), []
    judge = AgentJudge(
        OpenCodeAdapter(proc), make_request(tmp_path, profile), events=events, role="judge", profile="free",
        sleep=waits.append,
    )  # fmt: skip
    out = judge.complete_structured("You are a judge.", [Msg("user", "Judge this.")], SIMPLE)
    assert out.status == "ok" and len(proc.calls) == 2 and waits == [20.0]
    assert events.events == [
        ("availability.transient", {"role": "judge", "profile": "free", "status": 502, "attempt": 1, "wait_s": 20.0})
    ]


def test_an_opencode_judge_with_no_json_is_schema_invalid(tmp_path):
    profile = Profile(adapter="opencode", model="opencode/big-pickle")
    proc = FakeProc((OPENCODE / "hello-ok-stdin-prompt.jsonl").read_text())
    out = AgentJudge(OpenCodeAdapter(proc), make_request(tmp_path, profile)).complete_structured("s", [], SIMPLE)
    assert out.status == "schema_invalid"


def test_a_native_schema_adapter_gets_no_schema_text_appended(tmp_path):
    from l4.agents.fake import FakeAdapter, Step

    fake = FakeAdapter([Step(structured={"verdict": "pass", "criteria": []})])
    AgentJudge(fake, make_request(tmp_path, Profile(adapter="fake"))).complete_structured("sys", [], SIMPLE)
    assert fake.requests[0].prompt == "sys"


@pytest.mark.parametrize("schema", [VERDICT_SCHEMA])
def test_the_real_verdict_schema_survives_the_codex_strictifier(schema):
    strict = strictify_schema(schema)
    assert strict["additionalProperties"] is False and "$id" not in strict


def test_the_recorded_runner_judge_run_replays_through_the_codex_judge_mode(tmp_path):
    """Recorded live on the runner (codex 0.160.0, ChatGPT login): `exec --ephemeral -s read-only --output-schema
    <strictified verdict schema> -o R -`. The strict reply carries `counterexample: null`; it must come back absent."""
    from l4.verifier.judge import JUDGE_SCHEMA

    codex = RECORDED / "codex" / "0.160.0"
    out = CodexAdapter().parse(
        (codex / "runner-judge-ok.jsonl").read_text().splitlines(), exit_code=0, raw_events_path=tmp_path / "e",
        result_text=(codex / "runner-judge-ok.result.json").read_text(), schema=JUDGE_SCHEMA, judge=True,
    )  # fmt: skip
    assert out.status == "ok", out.detail
    assert out.structured is not None and "counterexample" not in out.structured["criteria"][0]
    assert validate(out.structured, JUDGE_SCHEMA) == []


def _text_run(text: str) -> str:
    """An opencode `--format json` stream whose one text part is `text` (the shape of the recorded runs)."""
    events = [
        {"type": "step_start", "part": {"type": "step-start"}},
        {"type": "text", "part": {"type": "text", "text": text}},
        {"type": "step_finish", "part": {"type": "step-finish", "reason": "stop"}},
    ]
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_an_opencode_reply_that_breaks_the_schema_keeps_the_parsed_object_for_the_repair(tmp_path):
    """Live wave D, W-D1: a weak judge's reply with an over-long quote was reported as `structured output invalid`
    with the object thrown away, so the harness could neither repair nor echo it."""
    from l4.verifier.judge import JUDGE_SCHEMA, JudgePrompt, run_judge

    reply = {
        "criteria": [
            {
                "id": "C-0a1b2c3d", "verdict": "pass",
                "evidence": [{"kind": "file", "ref": "src/x.py", "quote": "q" * 400}],
            }
        ],
        "test_adequacy": [], "findings": [],
        "riskiest_assumptions": ["a", "b", "c"],
    }  # fmt: skip
    profile = Profile(adapter="opencode", model="opencode/big-pickle")
    proc = FakeProc(_text_run("Here is my verdict:\n" + json.dumps(reply)))
    judge = AgentJudge(OpenCodeAdapter(proc), make_request(tmp_path, profile))
    out = judge.complete_structured("s", [Msg("user", "u")], JUDGE_SCHEMA)
    assert out.status == "schema_invalid" and out.raw == reply and out.parsed is None
    assert out.run is not None and out.run.structured is None  # a rejected reply is never presented as the result
    again = AgentJudge(OpenCodeAdapter(FakeProc(_text_run(json.dumps(reply)))), make_request(tmp_path, profile))
    run = run_judge(again, JudgePrompt("s", "u", "0" * 64, "judge@1"), timeout_s=5, redact=str)
    assert run.status == "ok" and run.calls == 1 and run.reply == "repaired"
    assert len(run.verdict.criteria[0].evidence[0].quote) == 300  # type: ignore[union-attr]
