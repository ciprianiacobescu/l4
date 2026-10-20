"""The `binary`, `auth` and `quota` steps use `availability.probe_step_timeout`; a step that does not answer is named
(L4-AVL-012, SCN-AVL-22, -23, -25)."""

import contextlib
import os
import stat
import sys
import time

import httpx
import pytest

from l4.agents.claude_code import ClaudeCodeAdapter
from l4.agents.codex import CodexAdapter
from l4.agents.command import CommandAdapter
from l4.agents.kiro_cli import KiroCliAdapter
from l4.agents.opencode import OpenCodeAdapter
from l4.availability import quota as quota_mod
from l4.availability.probes import ProbeLadder
from l4.config.schema import Profile
from l4.doctor.context import CmdResult
from l4.proc import run_process

from ._rpc_helpers import silent_rpc

CLAUDE = Profile(adapter="claude-code", model="claude-haiku-4-5", auth="subscription", vendor="anthropic")
CODEX = Profile(adapter="codex", model="gpt-6-luna", auth="subscription", vendor="openai")
OPENCODE = Profile(adapter="opencode", model="google/gemini-3.5-flash", vendor="google")
OPENROUTER = Profile(adapter="opencode", model="openrouter/openai/gpt-5.4-mini", vendor="openai")
KIRO = Profile(adapter="kiro-cli", model="claude-sonnet-4", auth="subscription", vendor="anthropic")
VERSIONS = {
    "claude": ("--version", "2.1.288\n"),
    "codex": ("--version", "codex-cli 0.160.0\n"),
    "opencode": ("--version", "1.18.34\n"),
    "kiro-cli": ("--version", "2.27.1\n"),
}
CASES = [
    (ClaudeCodeAdapter, CLAUDE, "claude", ("binary", "auth", "quota")),
    (CodexAdapter, CODEX, "codex", ("binary", "auth", "quota")),
    (OpenCodeAdapter, OPENCODE, "opencode", ("binary", "auth")),
    (KiroCliAdapter, KIRO, "kiro-cli", ("binary", "auth", "quota")),
]


def rules_for(cli: str) -> dict:
    flag, out = VERSIONS[cli]
    return {(flag,): CmdResult(0, out, "")}


class RecordingRpc:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def __call__(self, argv, cwd, env, timeout, messages):
        self.timeouts.append(timeout)
        return {}


@pytest.mark.parametrize(("adapter", "profile", "cli", "steps"), CASES)
@pytest.mark.parametrize(("step_s", "expected"), [(5, 5), (90, 60)])
def test_every_non_hello_step_gets_the_step_timeout(  # SCN-AVL-25
    make_ctx, adapter, profile, cli, steps, step_s, expected
):
    for step in steps:
        rpc = RecordingRpc()
        ctx, run = make_ctx(rules_for(cli), timeout_s=60, step_timeout_s=step_s, rpc=rpc)
        adapter().probe(profile, step, ctx)
        seen = [call[3] for call in run.calls] + rpc.timeouts
        assert seen and set(seen) == {expected}, (cli, step, seen)


KIRO_AUTO = Profile(adapter="kiro-cli")  # no model: `auto`, so the `auth` step also lists the models (kiro-judge)
KIRO_LOGGED_IN = CmdResult(0, '{"accountType": "ApiKey"}', "")


@pytest.mark.parametrize(("step_s", "expected"), [(5, 5), (90, 60)])
def test_the_kiro_model_listing_of_the_auth_step_gets_the_step_timeout(make_ctx, step_s, expected):  # SCN-AVL-25
    listing = CmdResult(1, "", "error: service error")
    rules = {**rules_for("kiro-cli"), ("whoami",): KIRO_LOGGED_IN, ("chat", "--list-models"): listing}
    ctx, run = make_ctx(rules, timeout_s=60, step_timeout_s=step_s)
    out = KiroCliAdapter().probe(KIRO_AUTO, "auth", ctx)
    listed = [call[3] for call in run.calls if "--list-models" in call[0]]
    assert out.ok and listed == [expected]
    assert {call[3] for call in run.calls} == {expected}


def test_a_kiro_model_listing_that_does_not_answer_keeps_the_auth_step(make_ctx):
    silent = CmdResult(124, "", "timed out")
    rules = {**rules_for("kiro-cli"), ("whoami",): KIRO_LOGGED_IN, ("chat", "--list-models"): silent}
    ctx, _ = make_ctx(rules, timeout_s=60, step_timeout_s=5)
    report = ProbeLadder(ctx, ["binary", "auth"]).run(KiroCliAdapter(), KIRO_AUTO)
    auth = report.steps["auth"]
    assert auth.ok and auth.detail["routed"]["source"] == "built-in"
    assert auth.detail["routed"]["reason"] == "kiro-cli chat --list-models failed (timed out)"


@pytest.mark.parametrize(("adapter", "profile", "cli", "steps"), CASES)
def test_the_hello_keeps_the_probe_timeout(make_ctx, adapter, profile, cli, steps):
    ctx, run = make_ctx(rules_for(cli), timeout_s=60, step_timeout_s=5, rpc=RecordingRpc())
    adapter().probe(profile, "hello", ctx)
    hello = [call[3] for call in run.calls if call[0][1:2] != [VERSIONS[cli][0]]]
    assert hello and set(hello) == {60}


def test_the_openrouter_quota_client_uses_the_step_timeout(make_ctx, monkeypatch):
    seen = []

    class Client:
        def __init__(self, *, timeout):
            seen.append(timeout)

        def get(self, *a, **k):
            raise httpx.ConnectError("down")

        def close(self):
            pass

    monkeypatch.setattr(quota_mod.httpx, "Client", Client)
    ctx, _ = make_ctx(rules_for("opencode"), timeout_s=60, step_timeout_s=5)
    ctx.environ["OPENROUTER_API_KEY"] = "k"
    OpenCodeAdapter().probe(OPENROUTER, "quota", ctx)
    assert seen == [5]


def opencode_reason(seconds: float, step: str) -> str:
    return (
        f"opencode did not answer within {seconds:g} s ({step} step); an OpenCode v2 daemon or a login prompt can "
        "cause this: run l4 doctor"
    )


def test_a_step_that_times_out_is_named(make_ctx):  # SCN-AVL-22 with a fake runner
    rules = {**rules_for("opencode"), ("auth", "list"): CmdResult(124, "", "timed out")}
    ctx, run = make_ctx(rules, timeout_s=60, step_timeout_s=5)
    report = ProbeLadder(ctx, ["binary", "auth", "quota", "hello"]).run(OpenCodeAdapter(), OPENCODE)
    auth = report.steps["auth"]
    assert not auth.ok and auth.failure_class == "transient" and auth.reason == opencode_reason(5, "auth")
    assert list(report.steps) == ["binary", "auth"]
    assert not any(call[0][1:2] == ["run"] for call in run.calls)  # the hello never ran


def test_a_binary_step_that_times_out_is_named(make_ctx):
    ctx, _ = make_ctx({("--version",): CmdResult(124, "", "timed out")}, timeout_s=60, step_timeout_s=5)
    report = ProbeLadder(ctx, ["binary", "auth"]).run(ClaudeCodeAdapter(), CLAUDE)
    binary = report.steps["binary"]
    assert binary.reason == (
        "claude did not answer within 5 s (binary step); a login prompt or a helper process that keeps the output "
        "open can cause this: run l4 doctor"
    )
    assert "did not report a version" not in binary.reason and binary.failure_class == "transient"


def test_a_codex_rpc_that_answers_nothing_in_time_is_named(make_ctx):
    def slow_rpc(argv, cwd, env, timeout, messages):
        time.sleep(0.3)
        return {}

    ctx, _ = make_ctx(rules_for("codex"), timeout_s=60, step_timeout_s=0.2, rpc=slow_rpc)
    report = ProbeLadder(ctx, ["binary", "auth"]).run(CodexAdapter(), CODEX)
    assert report.steps["auth"].reason.startswith("codex did not answer within")
    assert "(auth step)" in report.steps["auth"].reason


def test_a_codex_rpc_that_answers_wrongly_but_in_time_keeps_its_old_reason(make_ctx):
    ctx, _ = make_ctx(rules_for("codex"), timeout_s=60, step_timeout_s=5, rpc=silent_rpc())
    report = ProbeLadder(ctx, ["binary", "auth"]).run(CodexAdapter(), CODEX)
    assert report.steps["auth"].reason == "codex app-server gave an unrecognised account answer"


def hello_reason(cli: str, seconds: float) -> str:
    cause = (
        "an OpenCode v2 daemon or a login prompt can cause this"
        if cli == "opencode"
        else "a login prompt or a helper process that keeps the output open can cause this"
    )
    return f"{cli} did not answer within {seconds:g} s (hello step); {cause}: run l4 doctor"


@pytest.mark.parametrize(("adapter", "profile", "cli", "steps"), CASES)
def test_a_hello_that_times_out_is_named(make_ctx, adapter, profile, cli, steps):  # SCN-AVL-23
    flag, out = VERSIONS[cli]
    ctx, _ = make_ctx({(flag,): CmdResult(0, out, ""), (): CmdResult(124, "", "timed out")}, timeout_s=30)
    result = adapter().probe(profile, "hello", ctx)
    assert not result.ok and result.failure_class == "transient" and result.reason == hello_reason(cli, 30)


def test_a_command_hello_that_times_out_is_named(make_ctx, tmp_path):  # SCN-AVL-23
    tool = tmp_path / "bin" / "mytool"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    profile = Profile(adapter="command", options={"argv": ["mytool"], "probe_argv": ["mytool", "ping"]})
    ctx, _ = make_ctx({(): CmdResult(124, "", "timed out")}, timeout_s=30)
    result = CommandAdapter().probe(profile, "hello", ctx)
    assert not result.ok and result.reason == hello_reason("mytool", 30)


def test_the_real_runner_names_a_hanging_cli(make_ctx, tmp_path):  # SCN-AVL-22, end to end
    bin_dir = tmp_path / "realbin"
    bin_dir.mkdir()
    pid_file = tmp_path / "child.pid"
    script = bin_dir / "opencode"
    script.write_text(
        f"#!{sys.executable}\n"
        "import subprocess, sys, time\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('1.18.34')\n"
        "elif sys.argv[1:3] == ['auth', 'list']:\n"
        "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"    open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        "    time.sleep(60)\n"
    )
    script.chmod(0o755)
    ctx, _ = make_ctx({}, path=str(bin_dir), timeout_s=60, step_timeout_s=2, run=run_process)
    started = time.monotonic()
    try:
        report = ProbeLadder(ctx, ["binary", "auth"]).run(OpenCodeAdapter(), OPENCODE)
        assert time.monotonic() - started < 6
        assert report.steps["auth"].reason == opencode_reason(2, "auth")
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        if pid_file.exists():
            with contextlib.suppress(ProcessLookupError, ValueError):
                os.kill(int(pid_file.read_text()), 9)
