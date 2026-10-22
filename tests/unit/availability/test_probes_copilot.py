"""The Copilot CLI probe ladder (copilot-cli 4.1; SCN-FAC-45 to SCN-FAC-47, SCN-OCG-15, SCN-PRV-135 probe part)."""

import dataclasses
from pathlib import Path

from l4.agents.copilot_cli import CopilotCliAdapter
from l4.availability.probes import ProbeLadder
from l4.config.defaults import copilot_cache
from l4.config.schema import Profile
from l4.doctor.context import CmdResult

from .conftest import RECORDED as ALL_RECORDED

BYOK = ALL_RECORDED / "copilot-cli" / "1.0.102-byok"
FIRST = ALL_RECORDED / "copilot-cli" / "1.0.102-firstcalls"
TOKEN = "github_pat_" + "x" * 40
PROFILE = Profile(adapter="copilot-cli", model="claude-sonnet-5.5", vendor="anthropic", auth="subscription")
VERSION = {
    ("--version",): CmdResult(0, "GitHub Copilot CLI 1.0.102.\nRun 'copilot update' to check for updates.\n", "")
}


def hello_rules(stdout: str, code: int = 0, stderr: str = ""):
    return {**VERSION, ("--output-format",): CmdResult(code, stdout, stderr)}


def ctx_of(make_ctx, rules, token=True, **kw):
    ctx, run = make_ctx(rules, **kw)
    if token:  # a placeholder built at run time; the fake runner never sends it anywhere
        ctx = dataclasses.replace(ctx, environ={**ctx.environ, "COPILOT_GITHUB_TOKEN": TOKEN})
    return ctx, run


def step(name, make_ctx, rules, profile=PROFILE, token=True, **kw):
    ctx, run = ctx_of(make_ctx, rules, token, **kw)
    return CopilotCliAdapter().probe(profile, name, ctx), run, ctx


def hello(make_ctx, stdout, code=0, stderr="", profile=PROFILE, token=True):
    return step("hello", make_ctx, hello_rules(stdout, code, stderr), profile, token)


def test_auth_passes_on_the_variable_and_fails_without_it_and_starts_no_process(make_ctx):
    """SCN-FAC-45: whatever `auth:` says, the variable decides; no process starts."""
    out, run, _ = step("auth", make_ctx, {})
    assert out.ok and out.detail == {"auth_method": "env"} and run.calls == []
    for auth in ("subscription", "api_key", None):
        profile = Profile(adapter="copilot-cli", model="claude-sonnet-5.5", vendor="anthropic", auth=auth)
        out, run, _ = step("auth", make_ctx, {}, profile, token=False)
        assert not out.ok and out.reason == "COPILOT_GITHUB_TOKEN is not set" and run.calls == []


def test_the_quota_step_is_skipped_and_starts_no_process(make_ctx):
    out, run, _ = step("quota", make_ctx, {})
    assert out.ok and out.skipped and out.reason == "copilot-cli has no headless quota query" and run.calls == []


def test_the_binary_step_environment_has_the_copilot_cache(make_ctx):
    """SCN-PRV-135, probe part: `copilot --version` runs with the package cache and no self-update."""
    out, run, ctx = step("binary", make_ctx, VERSION, token=False)
    assert out.ok and out.detail["version"] == "1.0.102"
    env = run.calls[-1][2]
    assert env["XDG_CACHE_HOME"] == str(copilot_cache(ctx.environ)) and env["COPILOT_AUTO_UPDATE"] == "false"


def test_the_hello_is_a_tool_less_call_with_the_prompt_as_an_argument(make_ctx):
    """SCN-FAC-46."""
    out, run, ctx = hello(make_ctx, (BYOK / "judge-hello.jsonl").read_text())
    assert out.ok and out.detail["ms"] >= 0
    argv, cwd, env, _ = run.calls[-1]
    assert argv[0].endswith("copilot") and "--available-tools=l4_no_tools" in argv
    assert argv[-2:] == ["-p", "Reply with exactly: L4-OK"]
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5.5"
    for flag in ("--no-ask-user", "--no-auto-update", "--disable-builtin-mcps", "--disallow-temp-dir"):
        assert flag in argv
    assert not [a for a in argv if a.startswith(("--allow", "--yolo", "--deny", "--sandbox"))]
    assert "--available-tools" not in argv and "--available-tools=" not in argv
    home, usage = Path(env["COPILOT_HOME"]), Path(argv[argv.index("--usage-output-file") + 1])
    assert home.parent == usage.parent and home.name == "copilot-home" and home.parent.parent == ctx.cwd
    assert Path(cwd) == home.parent / "cwd"
    assert env["COPILOT_AUTO_UPDATE"] == "false" and env["XDG_CACHE_HOME"] == str(copilot_cache(ctx.environ))
    assert env["COPILOT_GITHUB_TOKEN"] == TOKEN
    assert not home.exists()  # the temporary directory is gone after the step


def test_the_hello_of_a_profile_with_no_model_names_auto(make_ctx):
    profile = Profile(adapter="copilot-cli", auth="subscription")
    out, run, _ = hello(make_ctx, (FIRST / "judge-auto.jsonl").read_text(), profile=profile)
    argv = run.calls[-1][0]
    assert out.ok and argv[argv.index("--model") + 1] == "auto"


def test_the_hello_does_not_pass_a_token_the_host_lacks(make_ctx):
    _, run, _ = hello(make_ctx, (BYOK / "judge-hello.jsonl").read_text(), token=False)
    assert "COPILOT_GITHUB_TOKEN" not in run.calls[-1][2]


def test_a_hello_that_waited_out_a_429_is_a_rate_limit(make_ctx):
    """SCN-FAC-47: the first six lines of the 429 recording, then the runner's timeout."""
    head = "".join((BYOK / "error-429-retrying.jsonl").read_text().splitlines(True)[:6])
    out, _, _ = hello(make_ctx, head, code=124)
    assert not out.ok and out.reason == "copilot-cli was retrying a rate limit (hello)"
    assert out.failure_class == "limit"
    assert out.limit is not None and out.limit.kind == "rate_limit" and out.limit.source == "copilot.model_call_failure"
    assert out.limit.resets_at is None


def test_a_rate_limit_retry_alone_is_a_rate_limit_too(make_ctx):
    line = '{"type":"assistant.turn_retry","data":{"reason":"rate_limit"}}\n'
    out, _, _ = hello(make_ctx, line, code=1)
    assert not out.ok and out.limit is not None and out.limit.source == "copilot.turn_retry"


def test_a_session_error_401_fails_with_the_auth_text_and_class(make_ctx):
    out, _, _ = hello(make_ctx, (BYOK / "error-401.jsonl").read_text(), code=1)
    assert not out.ok and out.failure_class == "auth"
    assert out.reason == "copilot-cli could not authenticate (COPILOT_GITHUB_TOKEN is missing, expired or rejected)"


def test_a_rejected_token_on_standard_error_is_auth(make_ctx):
    out, _, _ = hello(make_ctx, "", code=1, stderr=(FIRST / "bad-token.stderr.txt").read_text())
    assert not out.ok and out.failure_class == "auth" and "could not authenticate" in (out.reason or "")


def test_a_session_error_500_is_transient_and_a_plain_exit_is_other(make_ctx):
    out, _, _ = hello(make_ctx, (BYOK / "error-500.jsonl").read_text(), code=1)
    assert not out.ok and out.failure_class == "transient" and "status 500" in (out.reason or "")
    out, _, _ = hello(make_ctx, "", code=3, stderr="boom")
    assert not out.ok and out.failure_class == "other" and out.reason == "copilot-cli exited with code 3"


def test_a_402_is_a_credits_limit(make_ctx):
    out, _, _ = hello(make_ctx, (BYOK / "error-402.jsonl").read_text(), code=1)
    assert not out.ok and out.limit is not None and out.limit.kind == "credits" and out.failure_class == "limit"


def test_a_plain_timeout_is_transient(make_ctx):
    out, _, _ = hello(make_ctx, "", code=124)
    assert not out.ok and out.failure_class == "transient" and out.limit is None


def test_a_hello_that_started_a_tool_fails_with_the_tool_name(make_ctx):
    out, _, _ = hello(make_ctx, (BYOK / "implement-bash.jsonl").read_text())
    assert not out.ok and out.failure_class == "other" and out.limit is None
    assert out.reason is not None and out.reason.startswith("copilot-cli hello called a tool (")
    assert out.reason.endswith(")") and "()" not in out.reason


def test_a_wrong_reply_is_unexpected(make_ctx):
    stream = (BYOK / "judge-hello.jsonl").read_text().replace('"L4-OK"', '"hi there"')
    out, _, _ = hello(make_ctx, stream)
    assert not out.ok and out.reason == "unexpected reply"


def test_copilot_cli_2_stops_the_ladder_at_the_binary_step_by_name(make_ctx):
    """SCN-OCG-15: no auth, quota or hello step runs."""
    rules = {("--version",): CmdResult(0, "GitHub Copilot CLI 2.0.0.\n", "")}
    ctx, run = ctx_of(make_ctx, rules)
    report = ProbeLadder(ctx, ["binary", "auth", "quota", "hello"]).run(CopilotCliAdapter(), PROFILE)
    assert list(report.steps) == ["binary"]
    assert report.failed is not None and report.failed.reason == (
        "copilot 2.0.0 is Copilot CLI 2; L4 runs Copilot CLI 1: install copilot 1.0.102 (in CI l4 doctor --ci --fix "
        "installs it; l4 doctor prints the command for this machine); Copilot CLI 2 support comes in a later L4 release"
    )
    assert len(run.calls) == 1


def test_the_hello_gates_the_major_too(make_ctx):
    rules = {("--version",): CmdResult(0, "GitHub Copilot CLI 2.0.0.\n", "")}
    out, run, _ = step("hello", make_ctx, rules)
    assert not out.ok and "Copilot CLI 2" in (out.reason or "") and len(run.calls) == 1


def test_the_ladder_passes_end_to_end_on_the_recordings(make_ctx):
    ctx, _ = ctx_of(make_ctx, hello_rules((BYOK / "judge-hello.jsonl").read_text()))
    report = ProbeLadder(ctx, ["binary", "auth", "quota", "hello"]).run(CopilotCliAdapter(), PROFILE)
    assert report.ok and report.steps["quota"].skipped
