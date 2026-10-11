import dataclasses
import json

import pytest

from l4.agents.claude_code import ClaudeCodeAdapter
from l4.agents.codex import CodexAdapter
from l4.availability.probes import normalise_hello
from l4.config.schema import Profile
from l4.doctor.context import CmdResult

from .conftest import RECORDED

CODEX = RECORDED / "codex" / "0.160.0"
CLAUDE = RECORDED / "claude-code" / "2.1.288"
codex_profile = Profile(adapter="codex", model="gpt-6-luna", auth="subscription", vendor="openai")
claude_profile = Profile(adapter="claude-code", model="claude-haiku-4-5", auth="subscription", vendor="anthropic")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("L4-OK", "L4-OK"), (" L4-OK\n", "L4-OK"), ("`L4-OK`", "L4-OK"), ('"L4-OK"', "L4-OK"), ("'L4-OK'", "L4-OK"),
        ("```\nL4-OK\n```", "L4-OK"), ("```text\nL4-OK\n```\n", "L4-OK"), ("  `  L4-OK  ` ", "L4-OK"),
        ("L4-OK.", "L4-OK."), ("Sure! L4-OK", "Sure! L4-OK"), ("``L4-OK``", "`L4-OK`"), ("", ""),
    ],
)  # fmt: skip
def test_normalise_hello_removes_exactly_one_wrapping_layer(raw, expected):
    assert normalise_hello(raw) == expected


def hello_cmd(adapter, profile, ctx, run_result):
    return adapter.probe(profile, "hello", ctx)


def test_hello_accepts_wrapped_reply_rejects_other_and_times_out(make_ctx):
    ok_stream = (CODEX / "exec_hello_gpt-6-luna.jsonl").read_text()
    ctx, run = make_ctx(
        {("exec",): CmdResult(0, ok_stream, ""), ("--version",): CmdResult(0, "codex-cli 0.160.0\n", "")}
    )
    out = CodexAdapter().probe(codex_profile, "hello", ctx)
    assert out.ok and out.detail["ms"] >= 0
    argv = next(c[0] for c in run.calls if c[0][1] == "exec")
    assert argv[1:] == [
        "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules", "-s",
        "read-only", "-m", "gpt-6-luna", "-c", "model_reasoning_effort=low", "Reply with exactly: L4-OK",
    ]  # fmt: skip
    wrapped = ok_stream.replace('"L4-OK"', '"`L4-OK`"')
    ctx2, _ = make_ctx({("exec",): CmdResult(0, wrapped, ""), ("--version",): CmdResult(0, "codex-cli 0.160.0", "")})
    assert CodexAdapter().probe(codex_profile, "hello", ctx2).ok
    other = ok_stream.replace('"L4-OK"', '"hello there"')
    ctx3, _ = make_ctx({("exec",): CmdResult(0, other, ""), ("--version",): CmdResult(0, "codex-cli 0.160.0", "")})
    bad = CodexAdapter().probe(codex_profile, "hello", ctx3)
    assert not bad.ok and bad.reason == "unexpected reply"
    ctx4, _ = make_ctx(
        {("exec",): CmdResult(124, "", "timed out"), ("--version",): CmdResult(0, "codex-cli 0.160.0", "")}
    )
    slow = CodexAdapter().probe(codex_profile, "hello", ctx4)
    assert not slow.ok and slow.reason == "timeout"


def test_codex_hello_with_a_bad_model_fails_with_a_fixed_reason(make_ctx):
    stream = (CODEX / "exec_hello_bad_model.jsonl").read_text()
    ctx, _ = make_ctx({("exec",): CmdResult(1, stream, ""), ("--version",): CmdResult(0, "codex-cli 0.160.0", "")})
    out = CodexAdapter().probe(codex_profile, "hello", ctx)
    assert not out.ok and out.reason == "codex reported turn.failed" and "gpt-nonexistent" not in repr(out)


def test_claude_hello_uses_the_confirmed_command_and_accepts_the_recorded_reply(make_ctx):
    stream = (CLAUDE / "hello_haiku_warm.stream.jsonl").read_text()
    ctx, run = make_ctx(
        {("-p",): CmdResult(0, stream, ""), ("--version",): CmdResult(0, "2.1.288 (Claude Code)\n", "")}
    )
    out = ClaudeCodeAdapter().probe(claude_profile, "hello", ctx)
    assert out.ok
    argv = next(c[0] for c in run.calls if c[0][1] == "-p")
    assert argv[1:] == [
        "-p", "--safe-mode", "--no-session-persistence", "--model", "claude-haiku-4-5", "--tools", "",
        "--max-turns", "1", "--output-format", "stream-json", "--verbose", "Reply with exactly: L4-OK",
    ]  # fmt: skip
    env = next(c[2] for c in run.calls if c[0][1] == "-p")
    assert "L4_FORGE_TOKEN" not in env and env["CLAUDE_CODE_MAX_RETRIES"] == "1"


def test_claude_hello_with_a_bad_model_reports_the_status_not_the_text(make_ctx):
    stream = (CLAUDE / "hello_bad_model.stream.jsonl").read_text()
    ctx, _ = make_ctx({("-p",): CmdResult(1, stream, ""), ("--version",): CmdResult(0, "2.1.288 (Claude Code)", "")})
    out = ClaudeCodeAdapter().probe(claude_profile, "hello", ctx)
    assert not out.ok and out.reason == "claude reported an error (api_error_status 404)"


def test_binary_step_reports_version_or_missing(make_ctx, tmp_path):
    ctx, _ = make_ctx({("--version",): CmdResult(0, (CLAUDE / "version.stdout.txt").read_text(), "")})
    out = ClaudeCodeAdapter().probe(claude_profile, "binary", ctx)
    assert out.ok and out.detail == {"version": "2.1.288"}
    empty, _ = make_ctx({}, path=str(tmp_path / "nowhere"))
    missing = ClaudeCodeAdapter().probe(claude_profile, "binary", empty)
    assert not missing.ok and "not found" in (missing.reason or "")
    garbled, _ = make_ctx({("--version",): CmdResult(0, "no digits", "")})
    assert not ClaudeCodeAdapter().probe(claude_profile, "binary", garbled).ok


def test_a_binary_inside_the_checkout_is_not_used(make_ctx, tmp_path):
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    (repo / "bin" / "codex").write_text("#!/bin/sh\n")
    (repo / "bin" / "codex").chmod(0o755)
    ctx, _ = make_ctx({}, path=str(repo / "bin"), forbid=(repo,))
    assert not CodexAdapter().probe(codex_profile, "binary", ctx).ok


def test_auth_probe_never_logs_identity(make_ctx):
    status = json.loads((CLAUDE / "auth_status_logged_in.stdout.json").read_text())
    status.update(
        email="alice@example.com", orgName="Acme Corp", orgId="org-123", configDirectory="/home/alice/.claude"
    )
    ctx, _ = make_ctx(
        {("auth", "status"): CmdResult(0, json.dumps(status), ""), ("--version",): CmdResult(0, "2.1.288", "")}
    )
    out = ClaudeCodeAdapter().probe(claude_profile, "auth", ctx)
    assert out.ok and out.detail == {"logged_in": True, "auth_method": "claude.ai", "plan": "max"}
    assert not any(secret in repr(out) for secret in ("alice", "Acme", "org-123", "/home/alice"))


def test_claude_logged_out_and_garbled_status(make_ctx):
    out_json = (CLAUDE / "auth_status_logged_out.stdout.json").read_text()
    ctx, _ = make_ctx({("auth", "status"): CmdResult(1, out_json, ""), ("--version",): CmdResult(0, "2.1.288", "")})
    out = ClaudeCodeAdapter().probe(claude_profile, "auth", ctx)
    assert not out.ok and out.reason == "claude is not logged in (or set CLAUDE_CODE_OAUTH_TOKEN)"
    ctx2, _ = make_ctx({("auth", "status"): CmdResult(0, "<html>", ""), ("--version",): CmdResult(0, "2.1.288", "")})
    assert "unrecognised" in (ClaudeCodeAdapter().probe(claude_profile, "auth", ctx2).reason or "")


def test_codex_hello_skips_the_git_repo_check_because_the_probe_cwd_is_not_a_repo(make_ctx):
    ok_stream = (CODEX / "exec_hello_gpt-6-luna.jsonl").read_text()
    ctx, run = make_ctx({("exec",): CmdResult(0, ok_stream, ""), ("--version",): CmdResult(0, "codex-cli 0.160.0", "")})
    assert not (ctx.cwd / ".git").exists()
    CodexAdapter().probe(codex_profile, "hello", ctx)
    assert "--skip-git-repo-check" in next(c[0] for c in run.calls if c[0][1] == "exec")


def test_binary_missing_and_version_floor(make_ctx, tmp_path):
    ctx, _ = make_ctx({("--version",): CmdResult(0, "codex-cli 0.160.0\n", "")})
    assert CodexAdapter().probe(codex_profile.model_copy(update={"min_version": "0.160.0"}), "binary", ctx).ok
    assert CodexAdapter().probe(codex_profile.model_copy(update={"min_version": "0.9"}), "binary", ctx).ok
    low = CodexAdapter().probe(codex_profile.model_copy(update={"min_version": "0.161.0"}), "binary", ctx)
    assert not low.ok and low.reason == "version 0.160.0 < min_version 0.161.0"
    garbled = CodexAdapter().probe(codex_profile.model_copy(update={"min_version": "newest"}), "binary", ctx)
    assert garbled.ok  # a floor that is not a version cannot be compared: the doctor reports it, the probe passes
    empty, _ = make_ctx({}, path=str(tmp_path / "nowhere"))
    assert "not found" in (CodexAdapter().probe(codex_profile, "binary", empty).reason or "")


def test_codex_hello_that_hits_the_usage_limit_carries_a_limit_signal(make_ctx):
    failed = json.dumps(
        {"type": "turn.failed", "error": {"message": "You've hit your usage limit. Try again at 3:45 PM."}}
    )
    ctx, _ = make_ctx({("exec",): CmdResult(1, failed, ""), ("--version",): CmdResult(0, "codex-cli 0.160.0", "")})
    out = CodexAdapter().probe(codex_profile, "hello", ctx)
    assert not out.ok and out.reason == "codex usage limit reached"
    assert out.limit is not None and out.limit.kind == "usage_limit" and out.limit.tool == "codex"
    assert "3:45" not in repr(out.reason)


def _spy_adapter(plan: dict, seen: list):
    from l4.agents.base import ProbeResult
    from l4.agents.fake import FakeAdapter

    class Spy(FakeAdapter):
        def probe(self, profile, step, ctx):
            seen.append(step)
            outcome = plan.get(step)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome or ProbeResult(step, True)

    return Spy([])


def test_ladder_stops_at_first_failure_and_api_key_skips_quota(make_ctx):
    from l4.agents.base import ProbeResult
    from l4.availability.probes import ProbeLadder

    ctx, _ = make_ctx({})
    seen: list[str] = []
    skip_quota = ProbeResult("quota", True, skipped=True)
    adapter = _spy_adapter({"auth": ProbeResult("auth", False, reason="logged out"), "quota": skip_quota}, seen)
    report = ProbeLadder(ctx, ["binary", "auth", "quota", "hello"]).run(adapter, claude_profile)
    assert seen == ["binary", "auth"] and not report.ok and report.failed.reason == "logged out"
    assert list(report.steps) == ["binary", "auth"] and report.failed.limit is None  # no limit, so no cool-down
    seen.clear()
    ok = ProbeLadder(ctx, ["binary", "quota", "hello"]).run(_spy_adapter({"quota": skip_quota}, seen), claude_profile)
    assert ok.ok and seen == ["binary", "quota", "hello"] and ok.steps["quota"].skipped


def test_ladder_follows_the_configured_order_and_skips_steps_that_are_not_built(make_ctx):
    from l4.availability.probes import ProbeLadder

    ctx, _ = make_ctx({})
    seen: list[str] = []
    report = ProbeLadder(ctx, ["hello", "mcp", "binary", "custom"]).run(_spy_adapter({}, seen), claude_profile)
    assert seen == ["hello", "binary"] and report.ok
    assert report.steps["mcp"].skipped and report.steps["custom"].skipped


def test_ladder_turns_an_adapter_error_into_a_failed_step(make_ctx):
    from l4.agents.base import AdapterError
    from l4.availability.probes import ProbeLadder

    ctx, _ = make_ctx({})
    report = ProbeLadder(ctx, ["binary", "auth"]).run(
        _spy_adapter({"binary": OSError("boom /secret/path")}, []), claude_profile
    )
    assert not report.ok and report.failed.reason == "binary probe failed (OSError)" and "secret" not in repr(report)
    report = ProbeLadder(ctx, ["auth"]).run(_spy_adapter({"auth": AdapterError("x")}, []), claude_profile)
    assert report.failed.reason == "auth probe failed (AdapterError)"


def test_a_report_survives_the_probe_cache_round_trip_with_its_limit(make_ctx):
    from datetime import UTC, datetime

    from l4.agents.base import LimitSignal, ProbeResult
    from l4.availability.probes import LadderReport

    limit = LimitSignal("codex", "m", "usage_limit", datetime(2026, 10, 3, 14, 32, tzinfo=UTC), "s", "x", 300, 100)
    report = LadderReport(
        {
            "binary": ProbeResult("binary", True, {"version": "0.160.0"}),
            "quota": ProbeResult("quota", False, {"windows": []}, "5h window 100% used, 0% remaining", limit),
        }
    )
    again = LadderReport.from_json(json.loads(json.dumps(report.to_json())))
    assert again.steps["binary"].detail == {"version": "0.160.0"} and not again.ok
    assert again.failed.limit == limit and again.failed.reason == report.failed.reason


def test_a_529_hello_is_retried_once(make_ctx):
    stream = (CLAUDE / "hello_haiku_warm.stream.jsonl").read_text()
    overloaded = json.dumps(
        {"type": "result", "is_error": True, "api_error_status": 529, "result": "API Error: 529 Overloaded"}
    )
    answers = [CmdResult(1, overloaded, ""), CmdResult(0, stream, "")]
    ctx, run = make_ctx({("--version",): CmdResult(0, "2.1.288 (Claude Code)\n", "")})
    waits: list[float] = []
    base = run

    def sequenced(argv, cwd, env, timeout):
        return answers.pop(0) if argv[1] == "-p" else base(argv, cwd, env, timeout)

    ctx = dataclasses.replace(ctx, run=sequenced, sleep=waits.append)
    assert ClaudeCodeAdapter().probe(claude_profile, "hello", ctx).ok
    assert waits == [20.0] and answers == []
    # a second 529 is the answer: no third try
    twice = [CmdResult(1, overloaded, ""), CmdResult(1, overloaded, ""), CmdResult(0, stream, "")]
    again = dataclasses.replace(
        ctx, run=lambda argv, cwd, env, timeout: twice.pop(0) if argv[1] == "-p" else base(argv, cwd, env, timeout)
    )
    out = ClaudeCodeAdapter().probe(claude_profile, "hello", again)
    assert not out.ok and out.reason == "claude reported an error (api_error_status 529)" and len(twice) == 1
    # a 404 is not retried
    bad = [CmdResult(1, json.dumps({"type": "result", "is_error": True, "api_error_status": 404}), "")]
    third = dataclasses.replace(
        ctx, run=lambda argv, cwd, env, timeout: bad.pop(0) if argv[1] == "-p" else base(argv, cwd, env, timeout)
    )
    assert not ClaudeCodeAdapter().probe(claude_profile, "hello", third).ok and bad == []
