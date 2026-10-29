"""M1.12 line 1 (L4-AVL-005): a failed hello carries a class that decides how long the failure is remembered."""

import dataclasses
import json

import pytest

from l4.agents.base import ProbeResult
from l4.agents.claude_code import ClaudeCodeAdapter
from l4.agents.codex import CodexAdapter
from l4.agents.opencode import OpenCodeAdapter
from l4.availability.probes import LadderReport
from l4.config.schema import Profile
from l4.doctor.context import CmdResult

from .conftest import RECORDED

CLI_MAJOR = RECORDED.parent / "cli_major" / "opencode"
opencode_profile = Profile(adapter="opencode", model="opencode/big-pickle", vendor="unknown")
CLAUDE = RECORDED / "claude-code" / "2.1.288"
claude_profile = Profile(adapter="claude-code", model="claude-haiku-4-5", auth="subscription", vendor="anthropic")
codex_profile = Profile(adapter="codex", model="gpt-6-luna", auth="subscription", vendor="openai")
VERSION = {("--version",): CmdResult(0, "2.1.288 (Claude Code)\n", "")}


def claude_hello(make_ctx, result: dict | None, *, code: int = 1) -> ProbeResult:
    stdout = json.dumps(result) if result is not None else ""
    ctx, _ = make_ctx({("-p",): CmdResult(code, stdout, ""), **VERSION})
    return ClaudeCodeAdapter().probe(claude_profile, "hello", dataclasses.replace(ctx, sleep=lambda _s: None))


def error_result(status):
    return {"type": "result", "is_error": True, "api_error_status": status}


@pytest.mark.parametrize("status", [401, 403])
def test_a_claude_401_or_403_is_an_auth_failure_without_a_limit(make_ctx, status):
    out = claude_hello(make_ctx, error_result(status))
    assert not out.ok and out.failure_class == "auth" and out.limit is None
    assert out.reason == f"claude reported an error (api_error_status {status})"


def test_a_429_is_a_limit_and_a_wrong_reply_or_a_bad_model_is_other(make_ctx):
    assert claude_hello(make_ctx, error_result(429)).failure_class == "limit"
    assert claude_hello(make_ctx, error_result(404)).failure_class == "other"
    wrong = claude_hello(make_ctx, {"type": "result", "is_error": False, "result": "hello there"}, code=0)
    assert wrong.reason == "unexpected reply" and wrong.failure_class == "other"


@pytest.mark.parametrize("status", [500, 502, 503, 529])
def test_a_5xx_is_transient(make_ctx, status):
    assert claude_hello(make_ctx, error_result(status)).failure_class == "transient"


def test_a_timeout_and_a_missing_result_are_transient(make_ctx):
    assert claude_hello(make_ctx, None, code=124).failure_class == "transient"
    silent = claude_hello(make_ctx, None, code=1)
    assert silent.reason == "claude printed no result" and silent.failure_class == "transient"


def test_a_passing_hello_has_no_class(make_ctx):
    stream = (CLAUDE / "hello_haiku_warm.stream.jsonl").read_text()
    ctx, _ = make_ctx({("-p",): CmdResult(0, stream, ""), **VERSION})
    out = ClaudeCodeAdapter().probe(claude_profile, "hello", ctx)
    assert out.ok and out.failure_class is None


def test_codex_hello_failures_are_classified(make_ctx):
    def run(stdout: str, code: int = 1) -> ProbeResult:
        ctx, _ = make_ctx(
            {("exec",): CmdResult(code, stdout, ""), ("--version",): CmdResult(0, "codex-cli 0.160.0", "")}
        )
        return CodexAdapter().probe(codex_profile, "hello", ctx)

    def failed(message: str) -> str:
        return json.dumps({"type": "turn.failed", "error": {"message": message}})

    assert run(failed("unexpected status 401 Unauthorized: token expired")).failure_class == "auth"
    assert run(failed("403 Forbidden: your organization has no access")).failure_class == "auth"
    assert run(failed("stream error: 503 service unavailable")).failure_class == "transient"
    assert run(failed("the model gave up")).failure_class == "other"
    assert run("", code=124).failure_class == "transient"
    assert run("", code=2).failure_class == "transient"  # no result at all


def test_the_class_survives_the_probe_cache(make_ctx):
    report = LadderReport({"hello": ProbeResult("hello", False, reason="x", failure_class="auth")})
    again = LadderReport.from_json(json.loads(json.dumps(report.to_json())))
    assert again.steps["hello"].failure_class == "auth"
    plain = LadderReport({"binary": ProbeResult("binary", True)})
    assert LadderReport.from_json(plain.to_json()).steps["binary"].failure_class is None
    old = {"steps": [{"name": "hello", "ok": False, "skipped": False, "reason": "x", "detail": {}, "limit": None}]}
    assert LadderReport.from_json(old).steps["hello"].failure_class is None  # an entry written before M1.12


def opencode_hello(
    make_ctx, stdout: str, stderr: str, code: int = 1, *, waits: list[float] | None = None
) -> ProbeResult:
    ctx, _ = make_ctx({("run",): CmdResult(code, stdout, stderr), ("--version",): CmdResult(0, "1.18.34\n", "")})
    ctx = dataclasses.replace(ctx, sleep=(waits if waits is not None else []).append)  # no real 20 s wait
    return OpenCodeAdapter().probe(opencode_profile, "hello", ctx)


@pytest.mark.parametrize("flag", ["pure", "dir"])
def test_an_opencode_hello_rejected_for_a_v1_flag_is_unsupported_version(make_ctx, flag):
    """SCN-OCG-06: the recorded v2 help on stdout and the rejection on stderr; the binary answered 1.x (swapped)."""
    stdout = (CLI_MAJOR / "v2-2.0.32.run-help.stdout.txt").read_text()
    stderr = (CLI_MAJOR / f"v2-2.0.32.run-{flag}.stderr.txt").read_text()
    out = opencode_hello(make_ctx, stdout, stderr)
    assert not out.ok and out.failure_class == "unsupported_version"
    assert (out.reason or "").startswith(f"unsupported_version: opencode rejected --{flag}")
    assert "opencode --version" in (out.reason or "")


def test_an_opencode_exit_1_with_an_empty_stderr_is_still_transient(make_ctx):
    out = opencode_hello(make_ctx, "", "")
    assert out.failure_class == "transient" and out.reason == "opencode exited with code 1"


OPENCODE_1 = RECORDED / "opencode" / "1.18.33"


def opencode_error(message: str, status: int | None = None) -> str:
    """A v1 `error` event; `statusCode` is left out the way OpenCode 1.x leaves it out of an upstream error."""
    data: dict[str, object] = {"message": message}
    if status is not None:
        data["statusCode"] = status
    return json.dumps({"type": "error", "sessionID": "ses_x", "error": {"name": "APIError", "data": data}}) + "\n"


def test_a_503_named_only_in_the_message_is_transient_and_the_reason_names_it(make_ctx):
    """SCN-AVL-28: the recorded 1.18.33 shape, `[503] ... Service temporarily overloaded` and no `statusCode`."""
    out = opencode_hello(make_ctx, (OPENCODE_1 / "error-upstream-503.jsonl").read_text(), "")
    assert not out.ok and out.failure_class == "transient" and out.limit is None
    assert out.reason == "opencode reported an error (status 503)"


@pytest.mark.parametrize(
    ("message", "status", "kind", "reason"),
    [
        ("[502] Bad Gateway", None, "transient", "opencode reported an error (status 502)"),
        ("Service temporarily overloaded", None, "transient", "opencode reported an error"),
        ("the upstream is unavailable", None, "transient", "opencode reported an error"),
        ("connection reset by peer", None, "transient", "opencode reported an error"),
        ("[401] key rejected", None, "auth", "opencode authentication failed (login expired or rejected)"),
        ("[429] Too many requests", None, "limit", "opencode reported a rate limit"),
        ("You are out of credits", None, "limit", "opencode is out of credits"),
        ("[400] bad request", None, "other", "opencode reported an error (status 400)"),
        ("something else went wrong", None, "other", "opencode reported an error"),
        ("Invalid messages[503].content", None, "other", "opencode reported an error"),  # not a bracketed status
        ("Streaming failed: [503] Upstream error", None, "transient", "opencode reported an error (status 503)"),
        ("max_tokens must be <= 512", None, "other", "opencode reported an error"),  # a bare number is not a status
        ("503 authentication backend overloaded", None, "transient", "opencode reported an error"),
        ("EACCES: permission denied, open /x", None, "other", "opencode reported an error"),
        ("connect ETIMEDOUT 10.0.0.5:8080", None, "transient", "opencode reported an error"),
        ("[503] overloaded", 400, "other", "opencode reported an error (status 400)"),  # the structured status wins
        ("Service temporarily overloaded", 502, "transient", "opencode reported an error (status 502)"),
    ],
)
def test_an_opencode_error_with_a_bracketed_status_or_only_words_is_classed(make_ctx, message, status, kind, reason):
    out = opencode_hello(make_ctx, opencode_error(message, status), "")
    assert not out.ok and out.failure_class == kind and out.reason == reason
    assert (out.limit is not None) == (kind == "limit")
