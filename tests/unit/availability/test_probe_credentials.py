"""L4-PRV-024: the credential variable of a profile reaches that profile's probe only, and a missing one is named."""

import pytest

from l4.agents.claude_code import ClaudeCodeAdapter
from l4.agents.codex import CodexAdapter
from l4.agents.kiro_cli import KiroCliAdapter
from l4.config.schema import Profile
from l4.doctor.context import CmdResult

from .conftest import RECORDED

CODEX_OK = (RECORDED / "codex" / "0.160.0" / "exec_hello_gpt-6-luna.jsonl").read_text()
# the first version is the one a gated CLI (Kiro: major 2) reports
VERSIONS = {("--version",): CmdResult(0, "kiro-cli 2.28.0 codex-cli 0.160.0 2.1.288", "")}
SECRET = "sk-test-VALUE-123"
CODEX_KEY = Profile(adapter="codex", model="gpt-6-luna", auth="api_key", vendor="openai")
CLAUDE_SUB = Profile(adapter="claude-code", model="claude-haiku-4-5", auth="subscription", vendor="anthropic")
CLAUDE_KEY = CLAUDE_SUB.model_copy(update={"auth": "api_key"})
KIRO = Profile(adapter="kiro-cli", model="claude-sonnet-4", vendor="anthropic")
KIRO_KEY = KIRO.model_copy(update={"auth": "api_key"})
CODEX_SUB = CODEX_KEY.model_copy(update={"auth": "subscription"})
NAMES = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "CODEX_API_KEY", "KIRO_API_KEY")


def with_env(ctx, **extra):
    return type(ctx)(**{**ctx.__dict__, "environ": {**ctx.environ, **extra}})


def test_missing_variable_is_named_and_codex_api_key_is_probed(make_ctx):
    ctx, run = make_ctx(VERSIONS)
    out = CodexAdapter().probe(CODEX_KEY, "auth", ctx)
    assert not out.ok and out.reason == "CODEX_API_KEY is not set"
    assert "supported" not in (out.reason or "")
    assert CodexAdapter().probe(CODEX_KEY, "binary", ctx).ok
    # an empty or blank value is as good as unset
    blank, _ = make_ctx(VERSIONS)
    assert CodexAdapter().probe(CODEX_KEY, "auth", with_env(blank, CODEX_API_KEY="  ")).reason == (
        "CODEX_API_KEY is not set"
    )
    # set: auth passes without a status or login command, and the hello runs with the variable; quota stays skipped
    ctx2, run2 = make_ctx({**VERSIONS, ("exec",): CmdResult(0, CODEX_OK, "")})
    ctx2 = with_env(ctx2, CODEX_API_KEY=SECRET)
    auth = CodexAdapter().probe(CODEX_KEY, "auth", ctx2)
    assert auth.ok and auth.detail == {"auth_method": "env"} and SECRET not in repr(auth)
    assert CodexAdapter().probe(CODEX_KEY, "quota", ctx2).skipped
    assert CodexAdapter().probe(CODEX_KEY, "hello", ctx2).ok
    assert [c[0][1] for c in run2.calls if c[0][1] != "--version"] == ["exec"]
    assert all(c[2].get("CODEX_API_KEY") == SECRET for c in run2.calls if c[0][1] == "exec")


@pytest.mark.parametrize(
    ("adapter", "profile", "variable"),
    [
        (ClaudeCodeAdapter(), CLAUDE_KEY, "ANTHROPIC_API_KEY"),
        (KiroCliAdapter(), KIRO_KEY, "KIRO_API_KEY"),
    ],
)
def test_an_api_key_profile_without_its_variable_is_named(make_ctx, adapter, profile, variable):
    ctx, _ = make_ctx(VERSIONS)
    out = adapter.probe(profile, "auth", ctx)
    assert not out.ok and out.reason == f"{variable} is not set"


@pytest.mark.parametrize(
    ("adapter", "profile", "variable", "status"),
    [
        (ClaudeCodeAdapter(), CLAUDE_SUB, "CLAUDE_CODE_OAUTH_TOKEN", ("auth", "status")),
        (KiroCliAdapter(), KIRO, "KIRO_API_KEY", ("whoami",)),
    ],
)
def test_a_set_variable_passes_auth_without_the_status_command(make_ctx, adapter, profile, variable, status):
    ctx, run = make_ctx({**VERSIONS, status: CmdResult(1, "{}", "")})
    out = adapter.probe(profile, "auth", with_env(ctx, **{variable: SECRET}))
    assert out.ok and out.detail == {"auth_method": "env"} and SECRET not in repr(out)
    assert [c for c in run.calls if tuple(c[0][1 : 1 + len(status)]) == status] == []


@pytest.mark.parametrize(
    ("adapter", "profile", "variable", "suffix"),
    [
        (ClaudeCodeAdapter(), CLAUDE_SUB, "CLAUDE_CODE_OAUTH_TOKEN", " (or set CLAUDE_CODE_OAUTH_TOKEN)"),
        (KiroCliAdapter(), KIRO, "KIRO_API_KEY", " (or set KIRO_API_KEY)"),
        (CodexAdapter(), CODEX_SUB, None, ""),
    ],
)
def test_subscription_login_failure_names_the_variable(make_ctx, adapter, profile, variable, suffix):
    ctx, _ = make_ctx(
        {
            **VERSIONS,
            ("auth", "status"): CmdResult(1, '{"loggedIn": false}', ""),
            ("whoami",): CmdResult(1, '{"account": null}', ""),
        }
    )
    if variable is None:
        ctx = type(ctx)(**{**ctx.__dict__, "rpc": lambda *a: {2: {"result": {"account": None}}}})
    out = adapter.probe(profile, "auth", ctx)
    reason = out.reason or ""
    assert not out.ok and reason.endswith(suffix) and ("(or set" in reason) == bool(suffix)


def test_the_variable_reaches_only_its_own_profiles_probe_calls(make_ctx):
    ctx, run = make_ctx({**VERSIONS, ("exec",): CmdResult(0, CODEX_OK, ""), ("chat",): CmdResult(0, "", "")})
    ctx = with_env(ctx, **{name: SECRET + name for name in NAMES})
    CodexAdapter().probe(CODEX_KEY, "hello", ctx)
    KiroCliAdapter().probe(KIRO, "hello", ctx)
    ClaudeCodeAdapter().probe(CLAUDE_SUB, "hello", ctx)
    for argv, _, env, _ in run.calls:
        exe = argv[0].rsplit("/", 1)[-1]
        mine = {"codex": "CODEX_API_KEY", "kiro-cli": "KIRO_API_KEY", "claude": "CLAUDE_CODE_OAUTH_TOKEN"}[exe]
        if argv[1] == "--version":
            assert not set(NAMES) & set(env)  # the binary step needs no credential
            continue
        assert {n for n in NAMES if n in env} == {mine}, argv
        assert env[mine] == SECRET + mine
