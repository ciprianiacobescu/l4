import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from l4.agents.base import AdapterError, RunRequest
from l4.agents.command import CommandAdapter, command_argv
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile

SCHEMA = {"type": "object", "required": ["status"], "properties": {"status": {"type": "string"}}}


def profile(**options) -> Profile:
    options.setdefault("argv", ["mytool", "--model", "{model}", "--in", "{prompt_file}", "--out", "{result_path}"])
    return Profile(adapter="command", model="m-1", vendor="acme", options=options)


def request(tmp_path: Path, prof: Profile | None = None, **kw) -> RunRequest:
    (tmp_path / "bin").mkdir(exist_ok=True)
    exe = tmp_path / "bin" / "mytool"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return RunRequest(
        profile=prof or profile(), role="implementer", cwd=tmp_path / "wt", prompt="the prompt text",
        result_path=tmp_path / "res" / "result.json", raw_events_path=tmp_path / "raw" / "events.jsonl",
        env={"PATH": str(tmp_path / "bin")}, **kw,
    )  # fmt: skip


class FakeProc:
    def __init__(self, outcome: ProcOutcome | None = None, writes: str | None = None) -> None:
        self.outcome, self.writes, self.calls = outcome or ProcOutcome(0), writes, []

    def run(self, argv, env, cwd, *, stdout_path, timeout_s, stdin=None, stderr_path=None, **kw):
        self.calls.append({"argv": list(argv), "env": dict(env), "cwd": cwd, "stdin": stdin, "kw": kw})
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text("")
        if self.writes is not None:  # the command writes where {result_path} told it to
            Path(argv[argv.index("--out") + 1]).write_text(self.writes)
        return self.outcome


def test_unknown_placeholder_rejected():
    for bad in (["tool", "{nope}"], ["tool", "{prompt_file.__class__}"], ["{who}"]):
        with pytest.raises(ValidationError, match="placeholder"):
            profile(argv=bad)
    with pytest.raises(ValidationError, match="placeholder"):
        profile(probe_argv=["tool", "{result_path}"])  # only {model} means something to a probe
    assert profile(argv=["tool", '{"literal": 1}', "{session_id}"]).options["argv"][1] == '{"literal": 1}'


def test_the_load_error_names_the_option_and_never_the_configured_text():
    from l4.config.loader import _issues
    from l4.config.schema import L4Config

    raw = {"profiles": {"cmd": {"adapter": "command", "options": {"argv": ["tool", "{xyz123}"]}}}}
    with pytest.raises(ValidationError) as err:
        L4Config.model_validate(raw)
    [issue] = _issues(err.value)
    assert issue.path == "$.profiles.cmd" and "options.argv" in issue.message and "xyz123" not in issue.message


@pytest.mark.parametrize("argv", [[], "tool --x", ["tool", 3], None])
def test_argv_must_be_a_non_empty_list_of_strings(argv):
    with pytest.raises(ValidationError, match="options.argv"):
        profile(argv=argv)


def test_other_adapters_options_are_not_checked_here():
    assert Profile(adapter="opencode", options={"argv": "anything {nope}"}).adapter == "opencode"


def test_placeholders_are_substituted_without_format_semantics():
    argv = command_argv(["t", "--x={model}", "a{prompt_file}b", "{result_path}", "{session_id}", "{ }"],
                        model="m", prompt_file="/p", result_path="/r", session_id="s")  # fmt: skip
    assert argv == ["t", "--x=m", "a/pb", "/r", "s", "{ }"]


def test_run_writes_the_prompt_file_and_runs_the_resolved_executable(tmp_path):
    proc = FakeProc(writes=json.dumps({"status": "done"}))
    req = request(tmp_path, result_schema=SCHEMA)
    out = CommandAdapter(proc).run(req)
    assert out.status == "ok" and out.structured == {"status": "done"}
    call = proc.calls[0]
    prompt_file = Path(call["argv"][call["argv"].index("--in") + 1])
    # exactly the prompt that was published and hashed: the contract (where to write) is part of that prompt already
    assert prompt_file.parent == tmp_path / "res" and prompt_file.read_text() == "the prompt text"
    assert call["argv"][0] == str(tmp_path / "bin" / "mytool") and call["argv"][1:3] == ["--model", "m-1"]
    assert call["stdin"] is None and call["env"] == req.env  # the allow-listed environment, unchanged


def test_nonzero_exit_missing_or_invalid_result_and_timeout(tmp_path):
    assert CommandAdapter(FakeProc(ProcOutcome(2))).run(request(tmp_path, result_schema=SCHEMA)).status == "error"
    assert CommandAdapter(FakeProc()).run(request(tmp_path, result_schema=SCHEMA)).status == "error"  # no file
    bad = CommandAdapter(FakeProc(writes='{"status": 1}')).run(request(tmp_path, result_schema=SCHEMA))
    assert bad.status == "error" and bad.structured is None
    assert CommandAdapter(FakeProc(ProcOutcome(-9, stalled=True))).run(request(tmp_path)).status == "timeout"
    assert CommandAdapter(FakeProc(ProcOutcome(-2, interrupted=True))).run(request(tmp_path)).status == "cancelled"


def test_a_leftover_result_file_is_not_this_runs_result(tmp_path):
    req = request(tmp_path, result_schema=SCHEMA)
    req.result_path.parent.mkdir(parents=True)
    req.result_path.write_text('{"status": "stale"}')
    assert CommandAdapter(FakeProc()).run(req).status == "error"


def test_model_placeholder_without_a_model_is_refused(tmp_path):
    prof = Profile(adapter="command", options={"argv": ["mytool", "{model}"]})
    with pytest.raises(AdapterError, match="model"):
        CommandAdapter(FakeProc()).run(request(tmp_path, prof))


def test_an_executable_that_is_not_on_the_path_is_an_adapter_error(tmp_path):
    prof = profile(argv=["absent-tool", "{prompt_file}"])
    with pytest.raises(AdapterError, match="not found"):
        CommandAdapter(FakeProc()).run(request(tmp_path, prof))


def test_a_relative_path_executable_is_refused(tmp_path):
    prof = profile(argv=["./mytool", "{prompt_file}"])
    with pytest.raises(AdapterError, match="absolute"):
        CommandAdapter(FakeProc()).run(request(tmp_path, prof))


def test_an_absolute_executable_is_used_as_is(tmp_path):
    exe = tmp_path / "abs-tool"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    prof = profile(argv=[str(exe), "--out", "{result_path}"])
    proc = FakeProc()
    CommandAdapter(proc).run(request(tmp_path, prof))
    assert proc.calls[0]["argv"][0] == str(exe) and os.access(exe, os.X_OK)


def test_capabilities_and_declared_model():
    caps = CommandAdapter().capabilities()
    assert caps.schema_mode == "prompt_contract" and not caps.resume and not caps.served_model
    assert CommandAdapter.model_unverified is True


def test_the_runner_gets_the_requests_watch_and_no_reader(tmp_path):
    from l4.agents.activity import ActivityWatch

    watch = ActivityWatch(0, lambda beat: None)
    proc = FakeProc()
    CommandAdapter(proc).run(request(tmp_path, watch=watch))
    assert proc.calls[0]["kw"]["watch"] is watch and proc.calls[0]["kw"]["reader"] is None
    plain = FakeProc()
    CommandAdapter(plain).run(request(tmp_path))
    assert plain.calls[0]["kw"]["watch"] is None
