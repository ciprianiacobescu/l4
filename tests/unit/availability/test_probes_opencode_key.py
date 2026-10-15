"""L4-PRV-028 (SCN-PRV-76): OpenCode's own key decides the auth step before any model call."""

from l4.agents.opencode import OpenCodeAdapter
from l4.config.schema import Profile
from l4.doctor.context import CmdResult

from .conftest import RECORDED

OC = RECORDED / "opencode" / "1.18.33"
VERSION = {("--version",): CmdResult(0, "1.18.34\n", "")}
SECRET = "oc-test-VALUE-123"
GO = Profile(adapter="opencode", model="opencode-go/deepseek-v4.1-flash", auth="api_key", vendor="deepseek")
ZEN_KEY = Profile(adapter="opencode", model="opencode/big-pickle", auth="api_key", vendor="unknown")


def with_env(ctx, **extra):
    return type(ctx)(**{**ctx.__dict__, "environ": {**ctx.environ, **extra}})


def test_an_unset_key_fails_the_auth_step_and_asks_nothing(make_ctx):
    ctx, run = make_ctx(VERSION)
    out = OpenCodeAdapter().probe(GO, "auth", ctx)
    assert not out.ok and out.reason == "OPENCODE_API_KEY is not set"
    assert [c for c in run.calls if c[0][1] != "--version"] == []  # neither `auth list` nor a hello
    blank = OpenCodeAdapter().probe(GO, "auth", with_env(ctx, OPENCODE_API_KEY="  "))
    assert blank.reason == "OPENCODE_API_KEY is not set"
    assert OpenCodeAdapter().probe(ZEN_KEY, "auth", ctx).reason == "OPENCODE_API_KEY is not set"


def test_a_set_key_passes_auth_by_presence_and_reaches_only_the_hello(make_ctx):
    ok = CmdResult(0, (OC / "hello-ok-stdin-prompt.jsonl").read_text(), "")
    ctx, run = make_ctx({**VERSION, ("run",): ok})
    ctx = with_env(ctx, OPENCODE_API_KEY=SECRET)
    out = OpenCodeAdapter().probe(GO, "auth", ctx)
    assert out.ok and out.detail == {"auth_method": "env"} and SECRET not in repr(out)
    assert OpenCodeAdapter().probe(GO, "hello", ctx).ok
    assert not any(c[0][1:2] == ["auth"] for c in run.calls)
    for argv, _, env, _ in run.calls:
        if argv[1] == "--version":
            assert "OPENCODE_API_KEY" not in env
        else:
            assert env["OPENCODE_API_KEY"] == SECRET and SECRET not in " ".join(argv)


def test_a_free_model_without_api_key_is_unchanged(make_ctx):
    free = Profile(adapter="opencode", model="opencode/big-pickle", vendor="unknown")
    ctx, run = make_ctx(VERSION)
    out = OpenCodeAdapter().probe(free, "auth", with_env(ctx, OPENCODE_API_KEY=SECRET))
    assert out.ok and out.skipped
    assert [c for c in run.calls if c[0][1] != "--version"] == []


def test_other_providers_still_ask_auth_list(make_ctx):
    google = Profile(adapter="opencode", model="google/gemini-3.5-flash", auth="api_key", vendor="google")
    listing = CmdResult(0, (OC / "auth_list.stdout.txt").read_text(), "")
    ctx, run = make_ctx({**VERSION, ("auth", "list"): listing})
    assert OpenCodeAdapter().probe(google, "auth", with_env(ctx, OPENCODE_API_KEY=SECRET)).ok
    assert run.calls[-1][0][1:] == ["auth", "list"]
    assert "OPENCODE_API_KEY" not in run.calls[-1][2]


def test_a_subscription_profile_is_unchanged(make_ctx):
    sub = Profile(adapter="opencode", model="opencode-go/kimi-k2", auth="subscription", vendor="moonshot")
    listing = CmdResult(0, (OC / "auth_list.stdout.txt").read_text(), "")
    ctx, run = make_ctx({**VERSION, ("auth", "list"): listing})
    assert OpenCodeAdapter().probe(sub, "auth", with_env(ctx, OPENCODE_API_KEY=SECRET)).ok
    assert run.calls[-1][0][1:] == ["auth", "list"]
