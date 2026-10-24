"""The OpenCode v2 run (L4-OCV-004 stdin, -007 run part, -003 state directories; SCN-OCV-06 for the real calls, -15 end
to end, amendment E1): the run, then `session export`, through a fake `ProcRunner` that replays the recorded 2.0.32
fixtures. No binary is started."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from l4.agents import opencode_v2
from l4.agents.base import AdapterError, PermissionPolicy, RunRequest
from l4.agents.opencode_v2 import OpenCodeV2Adapter
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile
from l4.implementer.workbench import Workbench
from l4.proc import run_process
from l4.redact import Redactor
from l4.sandbox.base import WrappedCommand

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "opencode" / "2.0.32"
CLI_MAJOR = Path(__file__).parents[2] / "fixtures" / "cli_major" / "opencode"
SESSION = "ses_eaaf118f5ffeKxj5Y8YnV3DZsF"  # the session of the recorded text run and its export
FREE, PAID = "opencode/big-pickle", "opencode-go/deepseek-v4.1-flash"
SWITCHES = {
    "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_DISABLE_CLAUDE_CODE", "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS",
    "OPENCODE_DISABLE_EXTERNAL_SKILLS", "OPENCODE_DISABLE_AUTOUPDATE",
}  # fmt: skip
JUDGE_SCHEMA = {"type": "object", "required": ["verdict"], "properties": {"verdict": {"type": "string"}}}
SUCCEEDED = json.dumps({"info": {"outcome": "succeeded"}, "messages": []})  # synthetic: says only the outcome


def profile(model: str = FREE, **extra) -> Profile:
    options = {"cli_major": 2, **extra.pop("options", {})}
    return Profile(adapter="opencode", model=model, vendor="unknown", options=options, **extra)


def request(tmp_path: Path, **kw) -> RunRequest:
    kw.setdefault("profile", profile())
    kw.setdefault("role", "implementer")
    (tmp_path / "bin").mkdir(exist_ok=True)
    exe = tmp_path / "bin" / "opencode2"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return RunRequest(
        cwd=tmp_path / "wt", prompt="the prompt", result_path=tmp_path / "step" / "result" / "result.json",
        raw_events_path=tmp_path / "step" / "raw-001.jsonl",
        env={"PATH": str(tmp_path / "bin"), "HOME": "/h"}, **kw,
    )  # fmt: skip


def exe_of(tmp_path: Path) -> str:
    return str(tmp_path / "bin" / "opencode2")


class V2Proc:
    """Answers per call: the run writes `stream` to its stdout file, the export writes `export` to its own. Records
    the call as the process would see it, including the state directory's listing at the moment it starts."""

    def __init__(
        self, stream: str = "", export: str | None = None, *, run_outcome: ProcOutcome | None = None,
        export_outcome: ProcOutcome | None = None, stderr: str = "",
    ) -> None:  # fmt: skip
        self.stream, self.export, self.stderr = stream, export, stderr
        self.run_outcome, self.export_outcome = run_outcome or ProcOutcome(0), export_outcome or ProcOutcome(0)
        self.calls: list[dict] = []

    def run(self, argv, env, cwd, *, stdout_path, timeout_s, stdin=None, stderr_path=None, interrupt=None,
            on_line=None, stall_timeout_s=None, watch=None, reader=None):  # fmt: skip
        is_export = "session" in argv
        state = env.get("XDG_STATE_HOME")
        self.calls.append({
            "kind": "export" if is_export else "run", "argv": list(argv), "env": dict(env), "cwd": cwd, "stdin": stdin,
            "timeout_s": timeout_s, "stdout_path": stdout_path, "stderr_path": stderr_path, "interrupt": interrupt,
            "state_listing": sorted(os.listdir(state)) if state and os.path.isdir(state) else None,
            "config_listing": sorted(os.listdir(env["XDG_CONFIG_HOME"])) if "XDG_CONFIG_HOME" in env else None,
        })  # fmt: skip
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text((self.export or "") if is_export else self.stream)
        if stderr_path is not None:
            stderr_path.write_text("" if is_export else self.stderr)
        return self.export_outcome if is_export else self.run_outcome


def recorded(name: str) -> str:
    return (RECORDED / name).read_text()


def text_run(**kw) -> V2Proc:
    """The recorded text run (no final `step_finish`) and its recorded export."""
    return V2Proc(recorded("text-no-step-finish.jsonl"), recorded("text-no-step-finish.export.json"), **kw)


def event(kind: str, **fields) -> str:
    return json.dumps({"type": kind, "sessionID": "ses_x", **fields})


def reply_stream(reply: str) -> str:
    return "\n".join([event("step_start", part={}), event("text", part={"type": "text", "text": reply})]) + "\n"


def judge_request(tmp_path: Path, **kw) -> RunRequest:
    return request(tmp_path, role="judge", permission_policy=PermissionPolicy("judge"), **kw)


# --- the run, then the export (L4-OCV-007 run part) ---


def test_the_run_then_the_export_through_the_same_wrap_with_a_60_second_timeout(tmp_path):
    proc = text_run()
    wrapped: list[list[str]] = []

    def wrap(argv, env, **kw):
        wrapped.append(list(argv))
        return WrappedCommand(["bwrap", "--", *argv], dict(env))

    req = request(tmp_path, wrap=wrap)
    out = OpenCodeV2Adapter(proc).run(req)
    exe = exe_of(tmp_path)
    assert [c["kind"] for c in proc.calls] == ["run", "export"]
    run_call, export_call = proc.calls
    assert wrapped == [
        [exe, "run", "--standalone", "--format", "json", "-m", FREE, "--title", "l4 implementer raw-001"],
        [exe, "session", "export", "--standalone", SESSION],
    ]  # fmt: skip
    assert run_call["argv"][:2] == ["bwrap", "--"] and export_call["argv"][:2] == ["bwrap", "--"]
    assert export_call["timeout_s"] == 60 and run_call["timeout_s"] == req.timeout_s
    assert run_call["cwd"] == req.cwd and export_call["cwd"] == req.cwd
    assert out.status == "ok" and out.session_id == SESSION
    assert (out.usage.input_tokens, out.usage.output_tokens, out.usage.cached_input_tokens) == (3310, 78, 605)


def test_the_export_is_saved_beside_the_raw_events_and_given_to_parse(tmp_path):
    proc = text_run()
    req = request(tmp_path)
    out = OpenCodeV2Adapter(proc).run(req)
    saved = req.raw_events_path.with_name("raw-001.export.json")
    assert saved.read_text() == recorded("text-no-step-finish.export.json")
    assert proc.calls[1]["stdout_path"] == saved
    assert proc.calls[1]["stderr_path"] == req.raw_events_path.with_name("raw-001.export.stderr")
    assert out.raw_events_path == req.raw_events_path and out.usage.context_peak_tokens == 3915  # from the export


def test_a_failed_export_is_scn_ocv_15_end_to_end(tmp_path):
    """The stream has no final step_finish and the export exits 1: `error`, and the detail names the export."""
    proc = text_run(export_outcome=ProcOutcome(1))
    out = OpenCodeV2Adapter(proc).run(request(tmp_path))
    assert out.status == "error" and out.exit_code == 0
    assert out.detail == "opencode2 session export failed (exit 1) and the stream has no final stop"


@pytest.mark.parametrize(
    ("export", "outcome", "why"),
    [
        ("not json at all", ProcOutcome(0), "not JSON"),
        ("[]", ProcOutcome(0), "not JSON"),
        ("", ProcOutcome(-9, timed_out=True), "timeout"),
    ],
)
def test_an_unusable_export_names_why(tmp_path, export, outcome, why):
    proc = V2Proc(recorded("text-no-step-finish.jsonl"), export, export_outcome=outcome)
    out = OpenCodeV2Adapter(proc).run(request(tmp_path))
    assert out.status == "error"
    assert out.detail == f"opencode2 session export failed ({why}) and the stream has no final stop"


def test_an_unusable_export_with_a_final_stop_falls_back_to_the_v1_rule_export_decides(tmp_path):
    """export_decides (U5): the export cannot decide, so the last step_finish `stop` does, as in v1."""
    proc = V2Proc(recorded("hello-ok-step-finish.jsonl"), "", export_outcome=ProcOutcome(1))
    assert OpenCodeV2Adapter(proc).run(request(tmp_path)).status == "ok"


def test_an_export_that_says_failed_is_never_ok_not_ok_named(tmp_path):
    export = json.loads(recorded("text-no-step-finish.export.json"))
    export["info"]["outcome"] = "failed"
    out = OpenCodeV2Adapter(V2Proc(recorded("text-no-step-finish.jsonl"), json.dumps(export))).run(request(tmp_path))
    assert out.status == "error" and "failed" in (out.detail or "")


def test_an_oversize_export_is_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(opencode_v2, "EXPORT_LIMIT", 100)
    out = OpenCodeV2Adapter(text_run()).run(request(tmp_path))
    assert out.status == "error" and "session export failed (larger than 100 bytes)" in (out.detail or "")


def test_no_session_id_means_no_export_call(tmp_path):
    proc = V2Proc("")
    out = OpenCodeV2Adapter(proc).run(request(tmp_path))
    assert [c["kind"] for c in proc.calls] == ["run"]
    assert out.detail == "opencode2 session export failed (no session id) and the stream has no final stop"


def test_an_unsafe_session_id_is_never_exported(tmp_path):
    proc = V2Proc(event("step_start", part={}).replace("ses_x", "--evil") + "\n")
    out = OpenCodeV2Adapter(proc).run(request(tmp_path))
    assert [c["kind"] for c in proc.calls] == ["run"]
    assert out.detail == "opencode2 session export failed (an unsafe session id) and the stream has no final stop"


def test_the_export_is_published_redacted_with_the_stream_and_its_raw_file_deleted(tmp_path):
    """L4-OBS-002: `publish_agent_logs` copies every sibling of the stream through the redactor, the export too."""
    secret = "sk-not-a-real-key-0123456789"
    export = recorded("text-no-step-finish.export.json").replace('"outcome"', f'"note": "{secret}", "outcome"', 1)
    req = request(tmp_path)
    OpenCodeV2Adapter(V2Proc(recorded("text-no-step-finish.jsonl"), export)).run(req)
    published = tmp_path / "out" / "agent" / "raw-001.jsonl"
    Workbench.publish_agent_logs(SimpleNamespace(redactor=Redactor({"KEY": secret})), req.raw_events_path, published)
    copy = published.with_name("raw-001.export.json").read_text()
    assert secret not in copy and '"outcome"' in copy
    assert sorted(p.name for p in published.parent.iterdir()) == [
        "raw-001.export.json", "raw-001.export.stderr", "raw-001.jsonl", "raw-001.stderr"
    ]  # fmt: skip
    assert not req.raw_events_path.with_name("raw-001.export.json").exists()


def test_a_timed_out_stalled_or_interrupted_run_starts_no_export(tmp_path):
    for outcome, status in (
        (ProcOutcome(-9, timed_out=True), "timeout"),
        (ProcOutcome(-9, stalled=True), "timeout"),
        (ProcOutcome(-2, interrupted=True), "cancelled"),
    ):
        proc = text_run(run_outcome=outcome)
        assert OpenCodeV2Adapter(proc).run(request(tmp_path)).status == status
        assert [c["kind"] for c in proc.calls] == ["run"]  # D7 rule 1 decides: the export could not change it


def test_a_run_with_an_error_event_still_exports_for_its_usage_and_keeps_the_error(tmp_path):
    proc = V2Proc(
        recorded("error-403-free-tier-network.jsonl"), recorded("text-no-step-finish.export.json"),
        run_outcome=ProcOutcome(1),
    )  # fmt: skip
    out = OpenCodeV2Adapter(proc).run(request(tmp_path))
    assert out.status == "auth" and [c["kind"] for c in proc.calls] == ["run", "export"]


def test_a_v1_flag_rejection_keeps_unsupported_version_through_the_run(tmp_path):
    stderr = (CLI_MAJOR / "v2-2.0.32.run-dir.stderr.txt").read_text()
    out = OpenCodeV2Adapter(V2Proc("", run_outcome=ProcOutcome(1), stderr=stderr)).run(request(tmp_path))
    assert out.status == "error" and (out.detail or "").startswith("unsupported_version:")


# --- the judge (L4-OCV-007 reply from the last message, L4-OCV-006 bound end to end) ---


def test_a_judge_reply_goes_through_the_export_and_the_shared_slicer(tmp_path):
    proc = V2Proc(reply_stream('{"verdict": "pass"}'), SUCCEEDED)
    req = judge_request(tmp_path, result_schema=JUDGE_SCHEMA)
    out = OpenCodeV2Adapter(proc).run(req)
    assert out.status == "ok" and out.structured == {"verdict": "pass"}
    run_call, export_call = proc.calls
    judge_dir = req.result_path.parent / "judge-cwd"
    assert run_call["cwd"] == judge_dir and export_call["cwd"] == judge_dir and list(judge_dir.iterdir()) == []


def test_a_leaked_think_tag_is_stripped_before_the_judge_reply_is_sliced(tmp_path):
    reply = 'The user wants {braces} here.</think>{"verdict": "pass"}'
    proc = V2Proc(reply_stream(reply), SUCCEEDED)
    out = OpenCodeV2Adapter(proc).run(judge_request(tmp_path, result_schema=JUDGE_SCHEMA))
    assert out.structured == {"verdict": "pass"}


def test_the_step_bound_reaches_parse_the_bounded_ask_loop_is_permission_blocked(tmp_path):
    """The judge's bound is 3 (config and parse alike): the recorded steps-3 ask loop is never ok."""
    proc = V2Proc(recorded("ask-loop-steps3.jsonl"), SUCCEEDED)
    out = OpenCodeV2Adapter(proc).run(judge_request(tmp_path))
    assert out.status == "permission_blocked" and len(out.permission_denials) == 2
    assert json.loads(proc.calls[0]["env"]["OPENCODE_CONFIG_CONTENT"])["agents"] == {"build": {"steps": 3}}


def test_an_implementer_run_has_the_200_step_bound_and_a_profile_override(tmp_path):
    proc = text_run()
    OpenCodeV2Adapter(proc).run(request(tmp_path))
    assert json.loads(proc.calls[0]["env"]["OPENCODE_CONFIG_CONTENT"])["agents"] == {"build": {"steps": 200}}
    proc = text_run()
    OpenCodeV2Adapter(proc).run(request(tmp_path, profile=profile(options={"steps": {"implement": 400}})))
    assert json.loads(proc.calls[0]["env"]["OPENCODE_CONFIG_CONTENT"])["agents"] == {"build": {"steps": 400}}


def test_an_implementer_reads_its_result_file_and_a_leftover_is_removed_first(tmp_path):
    req = request(tmp_path, result_schema={"type": "object", "required": ["status"]})
    req.result_path.parent.mkdir(parents=True)
    req.result_path.write_text('{"status": "stale"}')

    class Writes(V2Proc):
        def run(self, argv, env, cwd, **kw):
            if "session" not in argv:
                assert not req.result_path.exists()  # the stale file was removed before the agent started
                req.result_path.write_text('{"status": "done"}')
            return super().run(argv, env, cwd, **kw)

    proc = Writes(recorded("text-no-step-finish.jsonl"), recorded("text-no-step-finish.export.json"))
    out = OpenCodeV2Adapter(proc).run(req)
    assert out.status == "ok" and out.structured == {"status": "done"}


# --- SCN-OCV-06 for the real calls, amendment E1 ---


def test_run_and_export_each_have_an_empty_state_directory_of_their_own_and_no_data_directory(tmp_path):
    req = request(tmp_path)
    step_dir = req.result_path.parent
    stale = step_dir / "opencode2-state"
    stale.mkdir(parents=True)
    (stale / "service.json").write_text("{}")  # a leftover of an earlier attempt must not be found by the new run
    proc = text_run()
    OpenCodeV2Adapter(proc).run(req)
    run_call, export_call = proc.calls
    run_state, export_state = (Path(c["env"]["XDG_STATE_HOME"]) for c in proc.calls)
    assert run_state != export_state and run_state.parent == step_dir and export_state.parent == step_dir
    assert run_call["state_listing"] == [] and export_call["state_listing"] == []  # existed, and empty, at the start
    for call in proc.calls:
        env = call["env"]
        assert "XDG_DATA_HOME" not in env
        assert {name for name in env if name.startswith("OPENCODE_DISABLE_")} == SWITCHES
        assert all(env[name] == "1" for name in SWITCHES)
        assert call["config_listing"] == [] and Path(env["XDG_CONFIG_HOME"]).parent == step_dir
        assert env["PATH"] == req.env["PATH"] and env["HOME"] == "/h" and "OPENCODE_CONFIG_CONTENT" in env


def test_every_call_sees_eof_on_stdin_the_run_gets_the_prompt_the_export_none(tmp_path):
    """Amendment E1: OpenCode 2 waits without output while stdin stays open. `ProcRunner` writes the prompt and closes
    the pipe for a `str`, and gives a child with `stdin=None` /dev/null (pinned in test_proc.py): the run gets the
    prompt, the export None, never an inherited stdin."""
    proc = text_run()
    OpenCodeV2Adapter(proc).run(request(tmp_path))
    run_call, export_call = proc.calls
    assert run_call["stdin"] == "the prompt" and export_call["stdin"] is None


def test_the_probe_runner_gives_a_child_eof_on_stdin(tmp_path):
    """The hello and `auth list` probes go through `ProbeCtx.run` (`run_process` in production): it must hand the child
    /dev/null, or OpenCode 2 would wait on the harness's own stdin (amendment E1)."""
    done = run_process([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], tmp_path, os.environ, 30)
    assert done.returncode == 0 and done.stdout.strip() == "''"


# --- the credential loader wraps the run only ---


def test_the_credential_loader_wraps_only_the_run_argv_never_the_export(tmp_path):
    secret = "oc-test-VALUE-123"
    proc = text_run()
    req = request(tmp_path, profile=profile(PAID, auth="api_key"), host_env={"OPENCODE_API_KEY": secret})
    OpenCodeV2Adapter(proc).run(req)
    run_call, export_call = proc.calls
    assert run_call["argv"][:2] == ["/bin/sh", "-c"] and "export OPENCODE_API_KEY=" in run_call["argv"][2]
    assert run_call["argv"][5] == exe_of(tmp_path) and "--standalone" in run_call["argv"]
    assert export_call["argv"][0] == exe_of(tmp_path) and "/bin/sh" not in export_call["argv"]
    for call in proc.calls:
        assert secret not in " ".join(call["argv"]) and all(secret not in v for v in call["env"].values())
        assert "OPENCODE_API_KEY" not in call["env"]
    assert not (req.result_path.parent / "credential").exists()  # gone after the run


# --- refusals ---


def test_a_missing_binary_is_an_adapter_error(tmp_path):
    req = request(tmp_path)
    req.env["PATH"] = str(tmp_path / "nowhere")
    with pytest.raises(AdapterError, match="opencode2 was not found"):
        OpenCodeV2Adapter(V2Proc()).run(req)


def test_a_profile_without_a_model_is_an_adapter_error(tmp_path):
    req = request(tmp_path, profile=Profile(adapter="opencode", vendor="unknown", options={"cli_major": 2}))
    with pytest.raises(AdapterError, match="needs a model"):
        OpenCodeV2Adapter(V2Proc()).run(req)


def test_the_v2_run_resolves_opencode2_never_opencode(tmp_path):
    """Only `opencode` on the PATH: a v2 profile must not run the v1 binary."""
    req = request(tmp_path)
    (tmp_path / "bin" / "opencode2").rename(tmp_path / "bin" / "opencode")
    with pytest.raises(AdapterError, match="opencode2 was not found"):
        OpenCodeV2Adapter(V2Proc()).run(req)
