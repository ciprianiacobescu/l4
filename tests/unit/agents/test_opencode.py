import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.agents.base import AdapterError, PermissionPolicy, RunRequest
from l4.agents.opencode import OpenCodeAdapter
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile
from l4.sandbox.base import WrappedCommand

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "opencode" / "1.18.33"
CLI_MAJOR = Path(__file__).parents[2] / "fixtures" / "cli_major" / "opencode"
PROFILE = Profile(adapter="opencode", model="opencode/big-pickle", vendor="unknown")


def request(tmp_path: Path, **kw) -> RunRequest:
    kw.setdefault("profile", PROFILE)
    kw.setdefault("role", "implementer")
    (tmp_path / "bin").mkdir(exist_ok=True)
    exe = tmp_path / "bin" / "opencode"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return RunRequest(
        cwd=tmp_path / "wt", prompt="the prompt", result_path=tmp_path / "res" / "result.json",
        raw_events_path=tmp_path / "raw" / "events.jsonl", env={"PATH": str(tmp_path / "bin"), "HOME": "/h"}, **kw,
    )  # fmt: skip


class FakeProc:
    def __init__(self, stdout: str = "", outcome: ProcOutcome | None = None, stderr: str = "") -> None:
        self.stdout, self.outcome, self.calls, self.stderr = stdout, outcome or ProcOutcome(0), [], stderr

    def run(self, argv, env, cwd, *, stdout_path, timeout_s, stdin=None, stderr_path=None, interrupt=None,
            on_line=None, stall_timeout_s=None, watch=None, reader=None):  # fmt: skip
        self.calls.append({"argv": list(argv), "env": dict(env), "cwd": cwd, "stdin": stdin, "stall": stall_timeout_s,
                           "watch": watch, "reader": reader})  # fmt: skip
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(self.stdout)
        if stderr_path is not None:
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
            stderr_path.write_text(self.stderr)
        return self.outcome


def config_of(env: dict[str, str]) -> dict:
    return json.loads(env["OPENCODE_CONFIG_CONTENT"])


def test_command_and_env(tmp_path):
    proc = FakeProc((RECORDED / "hello-ok-stdin-prompt.jsonl").read_text())
    req = request(tmp_path, permission_policy=PermissionPolicy("implement", gate_prefix=".venv/bin/python -m pytest"))
    OpenCodeAdapter(proc).run(req)
    (call,) = proc.calls
    assert call["argv"][1:] == [
        "run", "--pure", "--format", "json", "-m", "opencode/big-pickle", "--dir", str(req.cwd), "--title",
        "l4 implementer events",
    ]  # fmt: skip
    assert call["stdin"] == "the prompt"  # the prompt goes on stdin, never in argv
    env = call["env"]
    assert env["XDG_CONFIG_HOME"] == str(tmp_path / "res" / "opencode-config")
    assert list((tmp_path / "res" / "opencode-config").iterdir()) == []  # empty: no user config can leak in
    assert "XDG_DATA_HOME" not in env  # auth.json lives there
    assert {env[k] for k in env if k.startswith("OPENCODE_DISABLE_")} == {"1"}
    assert {k for k in env if k.startswith("OPENCODE_DISABLE_")} == {
        "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_DISABLE_CLAUDE_CODE",
        "OPENCODE_DISABLE_EXTERNAL_SKILLS", "OPENCODE_DISABLE_AUTOUPDATE",
    }  # fmt: skip
    assert env["PATH"] == req.env["PATH"] and env["HOME"] == "/h"


def test_config_content_is_the_spec_831_map_with_the_external_directory_order_pinned(tmp_path):
    proc = FakeProc((RECORDED / "hello-ok-stdin-prompt.jsonl").read_text())
    OpenCodeAdapter(proc).run(request(tmp_path))
    result_dir = str(tmp_path / "res")
    config = config_of(proc.calls[0]["env"])
    assert config["snapshot"] is False and config["share"] == "disabled" and config["autoupdate"] is False
    permission = config["permission"]
    assert [permission[k] for k in ("edit", "read", "glob", "grep", "list")] == ["allow"] * 5
    assert permission["bash"] == {
        "*": "allow", "git commit*": "deny", "git push*": "deny", "git reset*": "deny", "git checkout*": "deny",
    }  # fmt: skip
    assert all(permission[k] == "deny" for k in ("webfetch", "websearch", "question", "doom_loop"))
    # OpenCode applies the LAST matching rule, so the broad deny must come first (SPEC 8.3.1, [I])
    assert list(permission["external_directory"].items()) == [
        ("*", "deny"), (f"{result_dir}/**", "allow"), (f"{result_dir}/*", "allow"),
    ]  # fmt: skip
    assert "ask" not in json.dumps(config)  # an `ask` is auto-rejected and ends the run with exit 0


GOOGLE = Profile(adapter="opencode", model="google/gemini-3.5-flash", vendor="google")


def test_read_only_denies_edit_and_bash_and_judge_has_no_tools(tmp_path):
    proc = FakeProc((RECORDED / "hello-ok-stdin-prompt.jsonl").read_text())
    OpenCodeAdapter(proc).run(request(tmp_path, profile=GOOGLE, permission_policy=PermissionPolicy("read_only")))
    permission = config_of(proc.calls[0]["env"])["permission"]
    # 0.4.22 (L4-DLG-016): deny by default, the three read tools allowed; no `edit` or `bash` entry to re-enable
    assert permission["*"] == "deny" and "edit" not in permission and "bash" not in permission
    assert permission["glob"] == "allow" and permission["grep"] == "allow" and permission["read"]["*"] == "allow"
    proc = FakeProc((RECORDED / "hello-ok-stdin-prompt.jsonl").read_text())
    judge = request(tmp_path, profile=GOOGLE, role="judge", permission_policy=PermissionPolicy("judge"))
    OpenCodeAdapter(proc).run(judge)
    config = config_of(proc.calls[0]["env"])
    assert config["tools"] == {"*": False} and config["permission"] == {"*": "deny"}


def test_zen_free_models_get_ask_where_others_get_deny_for_bash_and_read(tmp_path):
    """Denying `bash` or `read` makes the Zen free tier answer 403 (live, 2026-10-04); `ask` is rejected on the spot."""
    proc = FakeProc((RECORDED / "hello-ok-stdin-prompt.jsonl").read_text())
    OpenCodeAdapter(proc).run(request(tmp_path, role="judge", permission_policy=PermissionPolicy("judge")))
    config = config_of(proc.calls[0]["env"])
    assert config["permission"] == {"*": "deny", "read": "ask", "bash": "ask"} and "tools" not in config
    proc = FakeProc((RECORDED / "hello-ok-stdin-prompt.jsonl").read_text())
    OpenCodeAdapter(proc).run(request(tmp_path, permission_policy=PermissionPolicy("read_only")))
    permission = config_of(proc.calls[0]["env"])["permission"]
    # a Zen model keeps `bash` in the request, every command refused (L4-DLG-016): `deny`, plus one sentinel `ask`
    assert permission["*"] == "deny" and permission["bash"]["*"] == "deny" and "ask" in permission["bash"].values()


def test_the_judge_runs_in_an_empty_directory_not_the_worktree(tmp_path):
    proc = FakeProc((RECORDED / "hello-ok-stdin-prompt.jsonl").read_text())
    req = request(tmp_path, role="judge", permission_policy=PermissionPolicy("judge"))
    OpenCodeAdapter(proc).run(req)
    argv = proc.calls[0]["argv"]
    workdir = Path(argv[argv.index("--dir") + 1])
    assert workdir != req.cwd and workdir.parent == tmp_path / "res" and list(workdir.iterdir()) == []


def test_the_wrapper_receives_the_isolated_environment(tmp_path):
    proc = FakeProc((RECORDED / "hello-ok-stdin-prompt.jsonl").read_text())
    seen = {}

    def wrap(argv, env):
        seen.update(env)
        return WrappedCommand(["bwrap", "--", *argv], {"PATH": "/x"})

    OpenCodeAdapter(proc).run(request(tmp_path, wrap=wrap))
    assert "OPENCODE_CONFIG_CONTENT" in seen and "XDG_CONFIG_HOME" in seen
    assert proc.calls[0]["argv"][:2] == ["bwrap", "--"] and proc.calls[0]["env"] == {"PATH": "/x"}


def test_a_leftover_result_file_is_removed_before_the_run(tmp_path):
    req = request(tmp_path)
    req.result_path.parent.mkdir(parents=True)
    req.result_path.write_text('{"status": "done"}')
    req.result_schema = {"type": "object"}
    out = OpenCodeAdapter(FakeProc((RECORDED / "hello-ok-stdin-prompt.jsonl").read_text())).run(req)
    assert not req.result_path.exists() and out.status == "error"  # no stale result is read as this run's


def test_stall_watchdog_kills_silent_run(tmp_path):
    proc = FakeProc("", ProcOutcome(-9, stalled=True))
    out = OpenCodeAdapter(proc).run(request(tmp_path, stall_timeout_s=90.0))
    assert out.status == "timeout" and proc.calls[0]["stall"] == 90.0


def test_wall_clock_timeout_is_timeout(tmp_path):
    out = OpenCodeAdapter(FakeProc("", ProcOutcome(-9, timed_out=True))).run(request(tmp_path))
    assert out.status == "timeout"


def test_run_mode_cooldown_default_when_retry_after_hidden(tmp_path):
    """A 429 whose body names no reset leaves `resets_at` empty; the Factory then applies `default_cooldown`."""
    event = {"type": "error", "sessionID": "s", "error": {"name": "APIError", "data": {
        "message": "Too many requests", "statusCode": 429, "responseHeaders": {}}}}  # fmt: skip
    out = OpenCodeAdapter().parse(
        [json.dumps(event)], exit_code=1, raw_events_path=tmp_path / "e", now=datetime(2026, 10, 4, tzinfo=UTC)
    )
    assert out.status == "rate_limited" and out.limit is not None and out.limit.resets_at is None


def test_retry_after_header_sets_the_reset(tmp_path):
    event = {"type": "error", "sessionID": "s", "error": {"name": "APIError", "data": {
        "message": "slow down", "statusCode": 429, "responseHeaders": {"retry-after": "120"}}}}  # fmt: skip
    now = datetime(2026, 10, 4, tzinfo=UTC)
    out = OpenCodeAdapter().parse([json.dumps(event)], exit_code=1, raw_events_path=tmp_path / "e", now=now)
    assert out.limit is not None and out.limit.resets_at == datetime(2026, 10, 4, 0, 2, tzinfo=UTC)


def test_a_profile_without_a_model_is_refused(tmp_path):
    with pytest.raises(AdapterError, match="model"):
        OpenCodeAdapter(FakeProc()).run(request(tmp_path, profile=Profile(adapter="opencode")))


def test_missing_binary_is_an_adapter_error(tmp_path):
    req = request(tmp_path)
    req.env["PATH"] = str(tmp_path / "empty")
    with pytest.raises(AdapterError, match="not found"):
        OpenCodeAdapter(FakeProc()).run(req)


def test_capabilities_are_prompt_contract_without_resume_or_served_model():
    caps = OpenCodeAdapter().capabilities()
    assert caps.schema_mode == "prompt_contract" and not caps.resume and not caps.served_model
    assert OpenCodeAdapter.model_unverified is True


def test_the_runner_gets_the_requests_watch_and_the_opencode_reader(tmp_path):
    from l4.agents.activity import ActivityWatch, opencode_signals

    watch = ActivityWatch(0, lambda beat: None)
    proc = FakeProc()
    OpenCodeAdapter(proc).run(request(tmp_path, watch=watch))
    assert proc.calls[0]["watch"] is watch and proc.calls[0]["reader"] is opencode_signals


def test_a_judge_request_has_no_watch(tmp_path):
    proc = FakeProc()
    OpenCodeAdapter(proc).run(request(tmp_path))
    assert proc.calls[0]["watch"] is None


def _help_lines() -> list[str]:
    return (CLI_MAJOR / "v2-2.0.32.run-help.stdout.txt").read_text().splitlines()


def test_a_rejected_v1_flag_is_an_unsupported_version_error(tmp_path):
    """SCN-OCG-07: the recorded v2 help as raw events, the --dir rejection as the stderr tail."""
    stderr = (CLI_MAJOR / "v2-2.0.32.run-dir.stderr.txt").read_text()
    out = OpenCodeAdapter().parse(_help_lines(), exit_code=1, raw_events_path=tmp_path / "e", stderr_tail=stderr)
    assert out.status == "error" and (out.detail or "").startswith("unsupported_version:")
    assert "opencode --version" in (out.detail or "")


def test_without_a_stderr_tail_the_exit_code_detail_is_unchanged(tmp_path):
    out = OpenCodeAdapter().parse(_help_lines(), exit_code=1, raw_events_path=tmp_path / "e")
    assert out.status == "error" and out.detail == "opencode exited with code 1"


def test_run_passes_the_stderr_file_tail_to_parse(tmp_path):
    stderr = (CLI_MAJOR / "v2-2.0.32.run-pure.stderr.txt").read_text()
    padded = "x" * 20000 + stderr  # only the last 8 KiB is read, and the rejection is at the end
    proc = FakeProc("", ProcOutcome(1), stderr=padded)
    out = OpenCodeAdapter(proc).run(request(tmp_path))
    assert out.status == "error" and (out.detail or "").startswith("unsupported_version:")


def error_stream(message: str, status: int | None = None, **data) -> list[str]:
    """A v1 `error` event; `statusCode` is left out the way OpenCode 1.x leaves it out of an upstream error."""
    fields = {"message": message, **({"statusCode": status} if status is not None else {}), **data}
    return [json.dumps({"type": "error", "sessionID": "s", "error": {"name": "APIError", "data": fields}})]


def run_error(tmp_path: Path, message: str, status: int | None = None, **data):
    return OpenCodeAdapter().parse(
        error_stream(message, status, **data), exit_code=1, raw_events_path=tmp_path / "e", model="opencode/big-pickle"
    )


@pytest.mark.parametrize(
    ("message", "status", "api_status", "detail"),
    [
        ("[502] Bad Gateway", None, 502, "opencode reported an error (status 502), retryable"),
        ("Service temporarily overloaded", None, None, "opencode reported an error, retryable"),
        ("connection reset by peer", None, None, "opencode reported an error, retryable"),
        ("upstream hiccup", 503, 503, "opencode reported an error (status 503), retryable"),
    ],
)
def test_a_server_error_of_a_run_is_marked_transient(tmp_path, message, status, api_status, detail):
    """L4-AVL-006: the judge, the verifier agent and the clarifier retry a result marked `transient`."""
    out = run_error(tmp_path, message, status)
    assert out.status == "error" and out.transient is True and out.limit is None
    assert out.api_status == api_status and out.detail == detail


@pytest.mark.parametrize(
    ("message", "status", "detail"),
    [
        ("[400] bad request", None, "opencode reported an error (status 400)"),
        ("something else went wrong", None, "opencode reported an error"),
        ("bad", 400, "opencode reported an error (status 400)"),
    ],
)
def test_another_error_of_a_run_is_not_transient(tmp_path, message, status, detail):
    out = run_error(tmp_path, message, status)
    assert out.status == "error" and out.transient is False and out.detail == detail


def test_a_bracketed_401_of_a_run_is_auth_and_a_bracketed_429_is_a_limit_and_neither_is_transient(tmp_path):
    out = run_error(tmp_path, "[401] key rejected")
    assert out.status == "auth" and out.transient is False
    out = run_error(tmp_path, "[429] Too many requests")
    assert out.status == "rate_limited" and out.limit is not None and out.transient is False


def test_the_provider_unavailable_error_is_unchanged_and_not_marked_transient(tmp_path):
    out = run_error(tmp_path, "HTTP 400: grammar binding failed", 400)
    assert out.detail is not None and out.detail.startswith("provider_unavailable") and out.transient is False
