import json
from pathlib import Path

import pytest

from l4.agents.base import AgentCaps, PermissionPolicy, RunRequest, RunResult
from l4.agents.claude_code import ClaudeCodeAdapter
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile
from l4.llm.agent_judge import AgentJudge, Msg
from l4.verifier.judge import JUDGE_SCHEMA

from .conftest import judge_reply

RECORDED = (
    Path(__file__).parents[2] / "fixtures" / "recorded" / "claude-code" / "2.1.288" / "judge-structured-output.json"
)
ID = "C-0a1b2c3d"


class SpyProc:
    """Stands in for the `claude` process: records the call, prints a recorded reply with `structured_output`
    replaced."""

    def __init__(self, structured, *, outcome: ProcOutcome | None = None, **over) -> None:
        self.outcome = outcome or ProcOutcome(0)
        document = json.loads(RECORDED.read_text())
        document["structured_output"] = structured
        document["result"] = json.dumps(structured)
        document.update(over)
        self.text = json.dumps(document)
        self.calls: list[dict] = []

    def run(self, argv, env, cwd, **kw):
        self.calls.append({"argv": list(argv), "env": dict(env), "stdin": kw.get("stdin"), **kw})
        kw["stdout_path"].parent.mkdir(parents=True, exist_ok=True)
        kw["stdout_path"].write_text(self.text)
        return self.outcome


def judge(tmp_path: Path, proc: SpyProc) -> tuple[AgentJudge, list[RunRequest]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "claude").write_text("#!/bin/sh\n")
    (bin_dir / "claude").chmod(0o755)
    (tmp_path / "wt").mkdir(exist_ok=True)
    made: list[RunRequest] = []

    def make(prompt: str, schema: dict, timeout_s: int) -> RunRequest:
        req = RunRequest(
            profile=Profile(adapter="claude-code", model="claude-sonnet-5-5", auth="subscription", vendor="anthropic"),
            role="judge", cwd=tmp_path / "wt", prompt=prompt, result_path=tmp_path / "res" / "result.json",
            raw_events_path=tmp_path / "raw" / f"{len(made)}.jsonl", env={"PATH": str(bin_dir)},
            result_schema=schema, permission_policy=PermissionPolicy("judge"), timeout_s=timeout_s,
        )  # fmt: skip
        made.append(req)
        return req

    return AgentJudge(ClaudeCodeAdapter(proc), make), made  # type: ignore[arg-type]


def test_claude_judge_structured_output(tmp_path):
    proc = SpyProc(judge_reply([ID]))
    backend, _ = judge(tmp_path, proc)
    result = backend.complete_structured(
        "SYSTEM", [Msg("user", "EVIDENCE")], JUDGE_SCHEMA, effort=None, max_tokens=0, timeout_s=90
    )
    assert result.status == "ok" and result.parsed == judge_reply([ID])
    assert result.model_resolved == "claude-sonnet-5-5" and result.usage.cost_usd == pytest.approx(0.068776)
    call = proc.calls[0]
    argv = call["argv"]
    assert argv[0].endswith("/claude") and argv[1] == "-p"
    flags = {"--output-format": "json", "--max-turns": "3", "--tools": "", "--model": "claude-sonnet-5-5"}
    for flag, value in flags.items():
        assert argv[argv.index(flag) + 1] == value
    for flag in ("--safe-mode", "--strict-mcp-config", "--no-session-persistence"):
        assert flag in argv
    assert json.loads(argv[argv.index("--json-schema") + 1]) == JUDGE_SCHEMA
    assert call["stdin"] == "SYSTEM\n\nEVIDENCE" and call["timeout_s"] == 90 and call["stall_timeout_s"] is None


def test_a_reply_that_breaks_the_schema_is_schema_invalid_with_paths_only(tmp_path):
    bad = judge_reply([ID], riskiest_assumptions=["only one"])
    backend, _ = judge(tmp_path, SpyProc(bad))
    result = backend.complete_structured("s", [Msg("user", "u")], JUDGE_SCHEMA, effort=None, max_tokens=0, timeout_s=9)
    assert result.status == "schema_invalid" and "riskiest_assumptions" in result.detail and result.parsed is None


def test_the_backend_validates_again_even_when_the_adapter_did_not():
    class Lenient:
        name = "lenient"

        def capabilities(self) -> AgentCaps:
            return AgentCaps("native", False, False, False, False, False, False, True)

        def probe(self, *a): ...

        def run(self, req: RunRequest) -> RunResult:
            return RunResult("ok", Path("/dev/null"), structured={"criteria": []})

    backend = AgentJudge(Lenient(), lambda prompt, schema, t: None)  # type: ignore[arg-type,return-value]
    result = backend.complete_structured("s", [], JUDGE_SCHEMA, effort=None, max_tokens=0, timeout_s=9)
    assert result.status == "schema_invalid"


@pytest.mark.parametrize(
    ("over", "status"),
    [
        ({"is_error": True, "api_error_status": 401}, "limit"),
        ({"is_error": True, "api_error_status": 429}, "limit"),
        ({"is_error": True, "api_error_status": 404}, "error"),
        ({"subtype": "error_max_turns", "is_error": True}, "schema_invalid"),  # a repair, not "cannot run"
    ],
)
def test_run_failures_map_to_limit_or_error(tmp_path, over, status):
    backend, _ = judge(tmp_path, SpyProc(judge_reply([ID]), **over))
    result = backend.complete_structured("s", [Msg("user", "u")], JUDGE_SCHEMA, effort=None, max_tokens=0, timeout_s=9)
    assert result.status == status and result.parsed is None


def test_a_timeout_is_a_timeout(tmp_path):
    backend, _ = judge(tmp_path, SpyProc(judge_reply([ID]), outcome=ProcOutcome(-9, timed_out=True)))
    result = backend.complete_structured("s", [Msg("user", "u")], JUDGE_SCHEMA, effort=None, max_tokens=0, timeout_s=9)
    assert result.status == "timeout"


def test_an_earlier_reply_is_labelled_in_the_single_prompt(tmp_path):
    proc = SpyProc(judge_reply([ID]))
    backend, _ = judge(tmp_path, proc)
    backend.complete_structured("S", [Msg("user", "U"), Msg("assistant", "A"), Msg("user", "R")], JUDGE_SCHEMA,
                                effort=None, max_tokens=0, timeout_s=9)  # fmt: skip
    assert proc.calls[0]["stdin"] == "S\n\nU\n\nYour previous reply was:\nA\n\nR"


# --- a server-side overload is retried inside the run (M1.11, W3) ------------------------------------------------


class Scripted:
    """An adapter that answers from a script of `RunResult`s, one per call."""

    name = "scripted"

    def __init__(self, *results: RunResult) -> None:
        self.results = list(results)
        self.calls = 0

    def capabilities(self) -> AgentCaps:
        return AgentCaps("native", False, False, False, False, False, False, False)

    def run(self, req: RunRequest) -> RunResult:
        self.calls += 1
        return self.results.pop(0)


class Events:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def append(self, event_type: str, /, **data):
        self.events.append((event_type, data))


def overloaded(tmp_path: Path, **over) -> RunResult:
    return RunResult(
        "error", tmp_path / "e.jsonl", detail="claude reported an error (api_error_status 529)", transient=True,
        api_status=529, **over,
    )  # fmt: skip


def ok(tmp_path: Path) -> RunResult:
    return RunResult("ok", tmp_path / "e.jsonl", structured=judge_reply([ID]))


def retrying(tmp_path: Path, *results: RunResult):
    adapter, events, sleeps = Scripted(*results), Events(), []
    made = lambda prompt, schema, timeout_s: RunRequest(  # noqa: E731
        profile=Profile(adapter="claude-code", model="m", auth="subscription"), role="judge", cwd=tmp_path,
        prompt=prompt, result_path=tmp_path / "r.json", raw_events_path=tmp_path / "e.jsonl", env={},
    )  # fmt: skip
    backend = AgentJudge(adapter, made, events=events, role="judge", profile="claude", sleep=sleeps.append)
    return backend, adapter, events, sleeps


def ask(backend: AgentJudge):
    return backend.complete_structured("S", [Msg("user", "E")], JUDGE_SCHEMA, effort=None, max_tokens=0, timeout_s=90)


def test_a_529_is_retried_and_the_answer_is_used(tmp_path):
    backend, adapter, events, sleeps = retrying(tmp_path, overloaded(tmp_path), ok(tmp_path))
    result = ask(backend)
    assert result.status == "ok" and adapter.calls == 2
    assert events.events == [
        ("availability.transient", {"role": "judge", "profile": "claude", "status": 529, "attempt": 1, "wait_s": 20.0})
    ]
    assert sleeps == [20.0]


def test_three_529s_end_as_error_with_two_transient_events(tmp_path):
    backend, adapter, events, sleeps = retrying(tmp_path, *(overloaded(tmp_path) for _ in range(3)))
    result = ask(backend)
    assert result.status == "error" and adapter.calls == 3
    assert [(e[1]["attempt"], e[1]["wait_s"]) for e in events.events] == [(1, 20.0), (2, 60.0)]


def test_a_limit_or_schema_error_is_not_retried(tmp_path):
    limited = RunResult("quota", tmp_path / "e.jsonl", detail="five hour window")
    backend, adapter, events, _ = retrying(tmp_path, limited)
    assert ask(backend).status == "limit" and adapter.calls == 1 and events.events == []
    plain = RunResult("error", tmp_path / "e.jsonl", detail="claude reported an error (api_error_status 500)")
    backend, adapter, events, _ = retrying(tmp_path, plain)
    assert ask(backend).status == "error" and adapter.calls == 1 and events.events == []
    bad = RunResult("ok", tmp_path / "e.jsonl", structured={"verdicts": "no"})
    backend, adapter, events, _ = retrying(tmp_path, bad)
    assert ask(backend).status == "schema_invalid" and adapter.calls == 1


def test_waits_are_20_and_60_seconds(tmp_path):
    backend, _, _, sleeps = retrying(tmp_path, *(overloaded(tmp_path) for _ in range(3)))
    ask(backend)
    assert sleeps == [20.0, 60.0]
    told = overloaded(tmp_path, retry_after_s=400.0)  # a wait an adapter reports is used, capped at 60 s
    backend, _, events, sleeps = retrying(tmp_path, told, overloaded(tmp_path, retry_after_s=7.0), ok(tmp_path))
    assert ask(backend).status == "ok" and sleeps == [60.0, 7.0]


def test_a_claude_reply_that_breaks_the_schema_keeps_the_object_for_the_repair(tmp_path):
    reply = judge_reply([ID])
    reply["criteria"][0]["evidence"][0]["quote"] = "q" * 400
    backend, _ = judge(tmp_path, SpyProc(reply))
    result = backend.complete_structured("s", [Msg("user", "u")], JUDGE_SCHEMA, effort=None, max_tokens=0, timeout_s=9)
    assert result.status == "schema_invalid" and result.raw == reply and result.parsed is None
