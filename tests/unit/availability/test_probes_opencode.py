from l4.agents.opencode import OpenCodeAdapter
from l4.config.schema import Profile
from l4.doctor.context import CmdResult

from .conftest import RECORDED

OC = RECORDED / "opencode" / "1.18.33"
FREE = Profile(adapter="opencode", model="opencode/big-pickle", vendor="unknown")
GOOGLE = Profile(adapter="opencode", model="google/gemini-3.5-flash", vendor="google")
OPENROUTER = Profile(adapter="opencode", model="openrouter/openai/gpt-5.4-mini", vendor="openai")
VERSION = {("--version",): CmdResult(0, "1.18.34\n", "")}


def probe(profile, step, rules, make_ctx, **kw):
    ctx, run = make_ctx({**VERSION, **rules}, **kw)
    return OpenCodeAdapter().probe(profile, step, ctx), run


def test_binary_reports_the_version(make_ctx):
    out, _ = probe(FREE, "binary", {}, make_ctx)
    assert out.ok and out.detail["version"] == "1.18.34" and out.detail["major"] == 1


def test_binary_missing_fails(make_ctx):
    out, _ = probe(FREE, "binary", {}, make_ctx, path="/nonexistent")
    assert not out.ok and "not found" in (out.reason or "")


def test_free_models_need_no_login(make_ctx):
    out, run = probe(FREE, "auth", {}, make_ctx)
    assert out.ok and out.skipped
    assert not any(c[0][1:2] == ["auth"] for c in run.calls)  # nothing was asked


def test_auth_is_presence_of_the_provider_in_auth_list(make_ctx):
    listing = CmdResult(0, (OC / "auth_list.stdout.txt").read_text(), "")
    out, run = probe(GOOGLE, "auth", {("auth", "list"): listing}, make_ctx)
    assert out.ok and out.detail == {"logged_in": True, "provider": "google"}
    assert run.calls[-1][0][1:] == ["auth", "list"]
    assert "XDG_CONFIG_HOME" not in run.calls[-1][2]  # the real data dir: that is where auth.json is


def test_auth_matches_a_display_name_with_a_space_and_the_environment_section(make_ctx):
    go = Profile(adapter="opencode", model="opencode-go/kimi-k2", vendor="moonshot")
    listing = CmdResult(0, (OC / "auth_list.stdout.txt").read_text(), "")
    assert probe(go, "auth", {("auth", "list"): listing}, make_ctx)[0].ok
    env_only = CmdResult(0, (OC / "auth_list_env_only.stdout.txt").read_text(), "")
    assert probe(OPENROUTER, "auth", {("auth", "list"): env_only}, make_ctx)[0].ok


def test_auth_fails_when_the_provider_is_not_listed(make_ctx):
    empty = CmdResult(0, (OC / "auth_list_empty.stdout.txt").read_text(), "")
    out, _ = probe(GOOGLE, "auth", {("auth", "list"): empty}, make_ctx)
    assert not out.ok and "google" in (out.reason or "")


def test_quota_is_skipped_except_for_openrouter(make_ctx):
    out, _ = probe(GOOGLE, "quota", {}, make_ctx)
    assert out.ok and out.skipped


def test_openrouter_quota_without_a_key_is_skipped_not_failed(make_ctx):
    out, _ = probe(OPENROUTER, "quota", {}, make_ctx)  # no key in the probe environment
    assert out.ok and out.skipped


def test_hello_runs_isolated_with_tools_off_in_an_empty_directory(make_ctx):
    ok = CmdResult(0, (OC / "hello-ok-stdin-prompt.jsonl").read_text(), "")
    out, run = probe(FREE, "hello", {("run",): ok}, make_ctx)
    assert out.ok and out.detail["ms"] >= 0
    argv, cwd, env, _ = next(c for c in run.calls if c[0][1] == "run")
    assert argv[1:] == [
        "run", "--pure", "--format", "json", "-m", "opencode/big-pickle", "--title", "l4 hello",
        "Reply with exactly: L4-OK",
    ]  # fmt: skip
    assert cwd.name == "cwd" and "l4-opencode-probe-" in str(cwd)
    assert env["XDG_CONFIG_HOME"] != "" and "XDG_DATA_HOME" not in env
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1" and "L4_FORGE_TOKEN" not in env
    assert '"read":"ask"' in env["OPENCODE_CONFIG_CONTENT"]  # Zen free: a denied bash or read is a 403
    assert not cwd.exists()  # the scratch directory is removed


def test_hello_of_another_provider_runs_with_tools_off(make_ctx):
    ok = CmdResult(0, (OC / "hello-ok-stdin-prompt.jsonl").read_text(), "")
    _, run = probe(GOOGLE, "hello", {("run",): ok}, make_ctx)
    env = next(c for c in run.calls if c[0][1] == "run")[2]
    assert '"tools":{"*":false}' in env["OPENCODE_CONFIG_CONTENT"]


def test_hello_rejects_another_reply_and_times_out(make_ctx):
    other = (OC / "hello-ok-stdin-prompt.jsonl").read_text().replace('"L4-OK"', '"hi"')
    out, _ = probe(FREE, "hello", {("run",): CmdResult(0, other, "")}, make_ctx)
    assert not out.ok and out.reason == "unexpected reply"
    slow, _ = probe(FREE, "hello", {("run",): CmdResult(124, "", "timed out")}, make_ctx)
    assert not slow.ok and slow.failure_class == "transient"
    assert slow.reason == (
        "opencode did not answer within 60 s (hello step); an OpenCode v2 daemon or a login prompt can cause this: "
        "run l4 doctor"
    )


def test_hello_402_is_a_credits_limit_and_401_is_not_a_limit(make_ctx):
    credits = CmdResult(1, (OC / "error-openrouter-insufficient-credits.jsonl").read_text(), "")
    out, _ = probe(OPENROUTER, "hello", {("run",): credits}, make_ctx)
    assert not out.ok and out.limit is not None and out.limit.kind == "credits"
    expired = CmdResult(1, (OC / "error-auth-token-refresh-401.jsonl").read_text(), "")
    out, _ = probe(GOOGLE, "hello", {("run",): expired}, make_ctx)
    assert not out.ok and out.limit is None and "authentication" in (out.reason or "")


def test_hello_429_carries_the_google_reset(make_ctx):
    quota = CmdResult(1, (OC / "error-429-free-tier-quota.jsonl").read_text(), "")
    out, _ = probe(GOOGLE, "hello", {("run",): quota}, make_ctx)
    assert out.limit is not None and out.limit.kind == "rate_limit" and out.limit.resets_at is not None


def test_min_version_is_enforced(make_ctx):
    old = Profile(adapter="opencode", model="opencode/big-pickle", min_version="2.0.0")
    out, _ = probe(old, "binary", {}, make_ctx)
    assert not out.ok and "min_version" in (out.reason or "")


V2_REASON = (
    "opencode 2.0.32 is OpenCode v2; this profile runs v1 (opencode-ai 1.x): install opencode-ai@1.18.34 "
    "(l4 doctor --fix installs it user-locally) or set options.cli_major: 2 when supported"
)
V2_VERSION = {("--version",): CmdResult(0, "opencode v2.0.32\n", "")}


def test_a_v2_binary_fails_the_binary_step_with_the_named_reason(make_ctx):
    """SCN-OCG-03: no hello runs."""
    ctx, run = make_ctx(V2_VERSION)
    out = OpenCodeAdapter().probe(FREE, "binary", ctx)
    assert not out.ok and out.reason == V2_REASON and out.failure_class is None
    ctx, run = make_ctx(V2_VERSION)
    out = OpenCodeAdapter().probe(FREE, "hello", ctx)
    assert out.step == "binary" and out.reason == V2_REASON
    assert not any(c[0][1:2] == ["run"] for c in run.calls)


def test_the_major_is_checked_with_and_without_min_version(make_ctx):
    """SCN-OCG-02: no floor, or a floor the v2 number meets, still fails."""
    for floor in (None, "1.18.0"):
        profile = Profile(adapter="opencode", model="opencode/big-pickle", vendor="unknown", min_version=floor)
        ctx, _ = make_ctx(V2_VERSION)
        out = OpenCodeAdapter().probe(profile, "binary", ctx)
        assert not out.ok and out.reason == V2_REASON
