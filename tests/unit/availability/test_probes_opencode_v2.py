"""The OpenCode v2 probe (L4-OCV-001 probe part, -010, -011 hello, -012; SCN-OCV-02, -06 for the probes, -21, -22, -23,
amendment E1). Every answer is a recorded 2.0.32 fixture or a synthetic one that says so; no binary is started."""

import json
import os

import pytest

from l4.agents.base import PermissionPolicy
from l4.agents.opencode import OpenCodeAdapter
from l4.agents.opencode_v2 import OpenCodeV2Adapter, _auth_providers_v2, _auth_result_v2, config_content_v2
from l4.config.schema import L4Config, Profile
from l4.doctor.context import CmdResult
from l4.provision.catalog import effective_pins

from .conftest import RECORDED, FakeRun

OC2 = RECORDED / "opencode" / "2.0.32"
FREE_MODEL, GO_MODEL = "opencode/big-pickle", "opencode-go/deepseek-v4.1-flash"
V2_VERSION = {("--version",): CmdResult(0, (OC2 / "version.stdout.txt").read_text(), "")}
SWITCHES = {
    "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_DISABLE_CLAUDE_CODE", "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS",
    "OPENCODE_DISABLE_EXTERNAL_SKILLS", "OPENCODE_DISABLE_AUTOUPDATE",
}  # fmt: skip


def v2(model: str, **extra) -> Profile:
    options = {"cli_major": 2, **extra.pop("options", {})}
    return Profile(adapter="opencode", model=model, vendor="unknown", options=options, **extra)


FREE, GO, OPENROUTER = v2(FREE_MODEL), v2(GO_MODEL), v2("openrouter/openai/gpt-5.4-mini")


class SpyRun(FakeRun):
    """Also records what the call could see of its `XDG_STATE_HOME` the moment it started."""

    def __init__(self, rules):
        super().__init__(rules)
        self.states: list[list[str] | None] = []
        self.configs: list[tuple[list[str], int] | None] = []  # (listing, mode) of `XDG_CONFIG_HOME` at the start

    def __call__(self, argv, cwd, env, timeout):
        state = env.get("XDG_STATE_HOME")
        self.states.append(sorted(os.listdir(state)) if state and os.path.isdir(state) else None)
        config = env.get("XDG_CONFIG_HOME")
        self.configs.append(
            (sorted(os.listdir(config)), os.stat(config).st_mode & 0o777) if config and os.path.isdir(config) else None
        )
        return super().__call__(argv, cwd, env, timeout)


def probe(profile, step, rules, make_ctx, **kw):
    run = SpyRun({**V2_VERSION, **rules})
    ctx, _ = make_ctx({}, run=run, **kw)
    return OpenCodeV2Adapter().probe(profile, step, ctx), run


def out_of(name: str, code: int = 0) -> CmdResult:
    return CmdResult(code, (OC2 / name).read_text(), "")


def hello_call(run):
    return next(c for c in run.calls if c[0][1] == "run")


# --- SCN-OCV-02, SCN-OCV-12: the binary step is the profile's own ---


def test_a_v1_binary_at_opencode2_fails_binary_with_the_v2_reason_and_no_hello_runs(make_ctx):
    rules = {("--version",): CmdResult(0, "1.18.34\n", "")}
    out, run = probe(FREE, "hello", rules, make_ctx)
    assert not out.ok and out.step == "binary"
    assert out.reason is not None and out.reason.startswith("opencode2 1.18.34 is OpenCode v1; this profile runs v2")
    assert "options.cli_major: 2" in out.reason and "@opencode/cli@2.0.32" in out.reason
    assert [c[0][1:] for c in run.calls] == [["--version"]] and run.calls[0][0][0].endswith("/opencode2")


def test_the_recorded_v2_version_passes_binary_with_major_two_and_the_opencode2_pin(make_ctx):
    out, run = probe(FREE, "binary", {}, make_ctx)
    assert out.ok and out.detail["version"] == "2.0.32" and out.detail["major"] == 2
    assert out.detail["pin"] == "2.0.32" and out.detail["pin_source"] == "catalog"
    assert run.calls[0][0][0].endswith("/opencode2")


def test_ci_cli_versions_opencode2_reaches_the_probe_as_the_effective_pin(make_ctx):
    cfg = L4Config(profiles={"go": GO}, ci={"cli_versions": {"opencode2": "2.0.33"}})
    pins = effective_pins(cfg)
    assert pins["opencode2"] == ("2.0.33", "ci.cli_versions") and pins["opencode"][1] == "catalog"
    out, _ = probe(
        FREE, "binary", {}, make_ctx,
        pins={cli: version for cli, (version, _) in pins.items()},
        pin_sources={cli: source for cli, (_, source) in pins.items()},
    )  # fmt: skip
    assert out.ok and out.detail["pin"] == "2.0.33" and out.detail["pin_source"] == "ci.cli_versions"


def test_a_missing_opencode2_fails_binary_by_name(make_ctx):
    out, _ = probe(FREE, "binary", {}, make_ctx, path="/nonexistent")
    assert not out.ok and out.reason == "opencode2 not found on PATH"


def test_a_model_without_a_provider_fails_after_binary(make_ctx):
    out, _ = probe(v2("big-pickle"), "auth", {}, make_ctx)
    assert not out.ok and "provider/model" in (out.reason or "")


# --- SCN-OCV-21, SCN-OCV-22: auth from `auth list --format json` ---


def test_scn_ocv_21_the_recorded_listing_with_an_environment_key_passes_opencode_go(make_ctx):
    out, run = probe(GO, "auth", {("auth", "list"): out_of("auth-list-env-key.json")}, make_ctx)
    assert out.ok and out.detail == {"logged_in": True, "provider": "opencode-go"}
    argv, _, env, _ = run.calls[-1]
    assert argv[1:] == ["auth", "list", "--standalone", "--format", "json"] and argv[0].endswith("/opencode2")
    assert "XDG_DATA_HOME" not in env  # the credentials live in the real data dir


def test_the_auth_call_is_isolated_like_the_hello_an_empty_private_config_directory_and_the_switches(make_ctx):
    """`CREDENTIAL_PATHS["opencode"]` binds `~/.config/opencode` writable into every agent run, and `auth list` runs on
    the host, unsandboxed: a config or plugin an agent wrote there must never be loaded by it. So it gets an empty 0700
    `XDG_CONFIG_HOME` inside its scratch directory, the disable switches and the judge `OPENCODE_CONFIG_CONTENT`."""
    out, run = probe(GO, "auth", {("auth", "list"): out_of("auth-list-env-key.json")}, make_ctx)
    assert out.ok
    env = run.calls[-1][2]
    config, state = env["XDG_CONFIG_HOME"], env["XDG_STATE_HOME"]
    assert run.configs[-1] == ([], 0o700)  # it existed, empty and private, when `auth list` started
    assert os.path.dirname(config) == os.path.dirname(state) and config != state
    assert not os.path.exists(config)  # gone with the scratch directory
    assert {name for name in env if name.startswith("OPENCODE_DISABLE_")} == SWITCHES
    assert all(env[name] == "1" for name in SWITCHES) and "XDG_DATA_HOME" not in env
    content = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert content["permissions"] == [{"action": "*", "resource": "*", "effect": "deny"}]  # the hello's judge shape
    assert content["agents"] == {"build": {"steps": 3}}


def test_the_auth_call_has_an_empty_state_directory_of_its_own(make_ctx):
    out, run = probe(GO, "auth", {("auth", "list"): out_of("auth-list-env-key.json")}, make_ctx)
    assert out.ok
    assert run.states[-1] == []  # it existed, and was empty, when `auth list` started
    assert not os.path.exists(run.calls[-1][2]["XDG_STATE_HOME"])  # and is gone with the scratch directory


def test_scn_ocv_22_an_empty_listing_fails_an_openrouter_profile(make_ctx):
    out, _ = probe(OPENROUTER, "auth", {("auth", "list"): out_of("auth-list-empty.json")}, make_ctx)
    assert not out.ok and out.reason == "opencode2 has no credential for provider openrouter"


def test_scn_ocv_22_a_needs_auth_connection_fails_with_its_message_parser_directly():
    """Free models skip the step, so the recorded `opencode` entry is checked through the parser."""
    text = (OC2 / "auth-list-env-key.json").read_text()
    assert _auth_providers_v2(text) == {"opencode-go": None, "opencode": "Reconnect OpenCode Console to continue"}
    out = _auth_result_v2(text, "opencode")
    assert not out.ok
    assert out.reason == "opencode2 reports opencode needs auth (Reconnect OpenCode Console to continue)"
    assert _auth_result_v2("[]", "opencode").reason == "opencode2 has no credential for provider opencode"


def test_a_provider_with_one_usable_connection_among_needs_auth_ones_is_present():
    listing = [{"id": "p", "name": "P", "connections": [
        {"type": "oauth", "name": "a", "status": {"status": "needs_auth", "message": "m"}},
        {"type": "env", "name": "KEY"},
    ]}]  # fmt: skip
    assert _auth_providers_v2(json.dumps(listing)) == {"p": None}
    assert _auth_result_v2(json.dumps(listing), "p").ok


def test_a_connection_with_another_status_counts_and_an_entry_with_none_does_not():
    listing = [
        {"id": "a", "connections": [{"type": "oauth", "name": "x", "status": {"status": "connected"}}]},
        {"id": "b", "connections": []},
        {"id": "c"},
        {"name": "no id", "connections": [{"type": "env", "name": "K"}]},
        "not an entry",
    ]
    assert _auth_providers_v2(json.dumps(listing)) == {"a": None}


def test_a_needs_auth_message_is_one_short_line():
    listing = [{"id": "p", "connections": [{"type": "oauth", "name": "a", "status": {
        "status": "needs_auth", "message": "line one\nline\ttwo " + "x" * 300}}]}]  # fmt: skip
    message = _auth_providers_v2(json.dumps(listing))["p"]  # type: ignore[index]
    assert message is not None and "\n" not in message and "\t" not in message and len(message) <= 120


@pytest.mark.parametrize("text", ["", "not json", '{"id": "x"}', "null"])
def test_an_unparsable_listing_is_an_unrecognised_answer(make_ctx, text):
    rules = {("auth", "list"): CmdResult(0, text, "")}
    out, _ = probe(GO, "auth", rules, make_ctx)
    assert not out.ok and out.reason == "opencode2 auth list gave an unrecognised answer"


def test_a_failing_auth_list_is_named_by_its_exit_code(make_ctx):
    out, _ = probe(GO, "auth", {("auth", "list"): CmdResult(2, "", "boom")}, make_ctx)
    assert not out.ok and out.reason == "opencode2 auth list exited with code 2"


def test_free_models_need_no_login_and_ask_nothing(make_ctx):
    out, run = probe(FREE, "auth", {}, make_ctx)
    assert out.ok and out.skipped
    assert [c[0][1:] for c in run.calls] == [["--version"]]


def test_opencode_api_key_decides_auth_before_any_listing(make_ctx):
    keyed = v2(GO_MODEL, auth="api_key")
    ctx, run = make_ctx(V2_VERSION)
    assert OpenCodeV2Adapter().probe(keyed, "auth", ctx).reason == "OPENCODE_API_KEY is not set"
    ctx = type(ctx)(**{**ctx.__dict__, "environ": {**ctx.environ, "OPENCODE_API_KEY": "oc-test-VALUE-123"}})
    out = OpenCodeV2Adapter().probe(keyed, "auth", ctx)
    assert out.ok and out.detail == {"auth_method": "env"} and "oc-test-VALUE-123" not in repr(out)
    assert not any(c[0][1:2] == ["auth"] for c in run.calls)


def test_a_step_timeout_names_opencode2_and_the_daemon_cause(make_ctx):
    from l4.availability.steps import StepTimedOut

    with pytest.raises(StepTimedOut) as caught:
        probe(GO, "auth", {("auth", "list"): CmdResult(124, "", "timed out")}, make_ctx)
    assert caught.value.reason.startswith("opencode2 did not answer within ") and "daemon" in caught.value.reason


def test_quota_is_skipped_except_for_openrouter(make_ctx):
    assert probe(GO, "quota", {}, make_ctx)[0].skipped
    out, _ = probe(OPENROUTER, "quota", {}, make_ctx)  # no key in the probe environment
    assert out.ok and out.skipped


# --- SCN-OCV-23, SCN-OCV-06: the hello ---


@pytest.mark.parametrize(
    "name", ["hello-think-leak.jsonl", "hello-ok-no-step-finish.jsonl", "hello-ok-step-finish.jsonl"]
)
def test_scn_ocv_23_the_recorded_hellos_pass_with_or_without_a_step_finish_or_a_leaked_think_tag(make_ctx, name):
    out, _ = probe(FREE, "hello", {("run",): out_of(name)}, make_ctx)
    assert out.ok and out.detail["ms"] >= 0


def test_scn_ocv_23_the_same_leaked_text_still_fails_the_v1_hello_as_unexpected_reply(make_ctx):
    v1 = Profile(adapter="opencode", model=FREE_MODEL, vendor="unknown")
    rules = {("--version",): CmdResult(0, "1.18.34\n", ""), ("run",): out_of("hello-think-leak.jsonl")}
    ctx, _ = make_ctx(rules)
    out = OpenCodeAdapter().probe(v1, "hello", ctx)
    assert not out.ok and out.reason == "unexpected reply"


def test_the_recorded_free_tier_403_fails_the_hello_as_auth_not_a_limit(make_ctx):
    out, _ = probe(FREE, "hello", {("run",): out_of("error-403-free-tier-network.jsonl", 1)}, make_ctx)
    assert not out.ok and out.failure_class == "auth" and out.limit is None
    assert out.reason == "opencode2 authentication failed (login expired or rejected)"


def test_the_hello_argv_carries_standalone_the_title_and_the_prompt_and_no_v1_flags(make_ctx):
    out, run = probe(FREE, "hello", {("run",): out_of("hello-ok-step-finish.jsonl")}, make_ctx)
    assert out.ok
    argv, cwd, env, _ = hello_call(run)
    assert argv[0].endswith("/opencode2")
    assert argv[1:] == [
        "run", "--standalone", "--format", "json", "-m", FREE_MODEL, "--title", "l4 hello", "Reply with exactly: L4-OK",
    ]  # fmt: skip
    assert "--pure" not in argv and "--dir" not in argv
    assert cwd.name == "cwd" and "l4-opencode2-probe-" in str(cwd)  # an empty scratch directory, never a checkout


def test_scn_ocv_06_the_hello_has_an_empty_state_directory_of_its_own_and_no_data_directory(make_ctx):
    rules = {("run",): out_of("hello-ok-step-finish.jsonl"), ("auth", "list"): out_of("auth-list-env-key.json")}
    run = SpyRun({**V2_VERSION, **rules})
    ctx, _ = make_ctx({}, run=run)
    assert OpenCodeV2Adapter().probe(GO, "auth", ctx).ok and OpenCodeV2Adapter().probe(GO, "hello", ctx).ok
    (auth_call,) = [c for c in run.calls if c[0][1] == "auth"]
    hello = hello_call(run)
    assert run.states[run.calls.index(hello)] == [] and run.states[run.calls.index(auth_call)] == []
    assert auth_call[2]["XDG_STATE_HOME"] != hello[2]["XDG_STATE_HOME"]
    env = hello[2]
    assert "XDG_DATA_HOME" not in env and env["XDG_CONFIG_HOME"] != "" and "OPENCODE_CONFIG_CONTENT" in env
    assert {name for name in env if name.startswith("OPENCODE_DISABLE_")} == SWITCHES
    assert all(env[name] == "1" for name in SWITCHES)
    assert "L4_FORGE_TOKEN" not in env  # the probe environment is the allow-list, not the host's


def test_the_hello_config_is_the_judge_shape_with_a_step_bound_of_three(make_ctx):
    _, run = probe(GO, "hello", {("run",): out_of("hello-ok-step-finish.jsonl")}, make_ctx)
    config = json.loads(hello_call(run)[2]["OPENCODE_CONFIG_CONTENT"])
    assert config["agents"] == {"build": {"steps": 3}} and config["permissions"] == [
        {"action": "*", "resource": "*", "effect": "deny"}
    ]
    _, run = probe(FREE, "hello", {("run",): out_of("hello-ok-step-finish.jsonl")}, make_ctx)
    rules = json.loads(hello_call(run)[2]["OPENCODE_CONFIG_CONTENT"])["permissions"]
    assert [(r["action"], r["effect"]) for r in rules] == [("*", "deny"), ("read", "ask"), ("shell", "ask")]
    assert json.loads(config_content_v2(PermissionPolicy("judge"), hello_call(run)[1], FREE_MODEL)) is not None


def test_a_profile_judge_step_override_reaches_the_hello_config(make_ctx):
    profile = v2(GO_MODEL, options={"steps": {"judge": 5}})
    _, run = probe(profile, "hello", {("run",): out_of("hello-ok-step-finish.jsonl")}, make_ctx)
    assert json.loads(hello_call(run)[2]["OPENCODE_CONFIG_CONTENT"])["agents"] == {"build": {"steps": 5}}


def test_the_hello_gets_the_credential_variable_in_its_environment_only(make_ctx):
    keyed = v2(GO_MODEL, auth="api_key")
    ctx, run = make_ctx({**V2_VERSION, ("run",): out_of("hello-ok-step-finish.jsonl")})
    ctx = type(ctx)(**{**ctx.__dict__, "environ": {**ctx.environ, "OPENCODE_API_KEY": "oc-test-VALUE-123"}})
    assert OpenCodeV2Adapter().probe(keyed, "hello", ctx).ok
    argv, _, env, _ = hello_call(run)
    assert env["OPENCODE_API_KEY"] == "oc-test-VALUE-123" and "oc-test-VALUE-123" not in " ".join(argv)


def error_run(status, message="m", kind="unknown", code=1):
    error = {"type": kind, "message": message, "response": {"body": message}}
    if status is not None:
        error["status"] = status
    return CmdResult(code, json.dumps({"type": "error", "sessionID": "ses_x", "error": error}) + "\n", "")


def test_a_synthetic_429_is_a_rate_limit_class_limit_without_a_reset_status_only(make_ctx):
    """status_only (U1): a synthetic fallback pin, not a recorded shape."""
    out, _ = probe(GO, "hello", {("run",): error_run(429, "retry in 9h9m42s")}, make_ctx)
    assert not out.ok and out.failure_class == "limit" and out.reason == "opencode2 reported a rate limit"
    assert out.limit is not None and out.limit.kind == "rate_limit" and out.limit.resets_at is None


def test_a_synthetic_402_is_out_of_credits_status_only(make_ctx):
    """status_only (U1): a synthetic fallback pin, not a recorded shape."""
    out, _ = probe(GO, "hello", {("run",): error_run(402)}, make_ctx)
    assert not out.ok and out.failure_class == "limit" and out.reason == "opencode2 is out of credits"
    assert out.limit is not None and out.limit.kind == "credits"


def test_a_synthetic_5xx_is_transient_and_another_status_is_other(make_ctx):
    out, _ = probe(GO, "hello", {("run",): error_run(503)}, make_ctx)
    assert out.failure_class == "transient" and out.reason == "opencode2 reported an error (status 503)"
    out, _ = probe(GO, "hello", {("run",): error_run(400)}, make_ctx)
    assert out.failure_class == "other"
    out, _ = probe(GO, "hello", {("run",): error_run(None, "Token refresh failed: 401")}, make_ctx)
    assert out.failure_class == "auth"


@pytest.mark.parametrize(
    ("message", "kind", "reason"),
    [
        ("[503] Service temporarily overloaded", "transient", "opencode2 reported an error (status 503)"),
        ("Service temporarily overloaded", "transient", "opencode2 reported an error"),
        ("the gateway timed out", "transient", "opencode2 reported an error"),
        ("[401] key rejected", "auth", "opencode2 authentication failed (login expired or rejected)"),
        ("[429] Too many requests", "limit", "opencode2 reported an error (status 429)"),
        ("[400] bad request", "other", "opencode2 reported an error (status 400)"),
        ("something else went wrong", "other", "opencode2 reported an error"),
    ],
)
def test_an_error_with_no_status_is_classed_by_its_bracketed_status_or_its_words(make_ctx, message, kind, reason):
    out, _ = probe(GO, "hello", {("run",): error_run(None, message)}, make_ctx, sleep=lambda _s: None)
    assert not out.ok and out.failure_class == kind and out.reason == reason


def test_a_failing_exit_without_an_error_event_is_transient_and_names_the_code(make_ctx):
    out, _ = probe(GO, "hello", {("run",): CmdResult(2, "", "boom")}, make_ctx)
    assert not out.ok and out.failure_class == "transient" and out.reason == "opencode2 exited with code 2"


def test_a_hello_timeout_is_transient_and_names_opencode2(make_ctx):
    out, _ = probe(GO, "hello", {("run",): CmdResult(124, "", "timed out")}, make_ctx)
    assert not out.ok and out.failure_class == "transient"
    assert (out.reason or "").startswith("opencode2 did not answer within ") and "(hello step)" in (out.reason or "")


def test_a_wrong_reply_is_unexpected_reply_and_no_reply_is_too(make_ctx):
    wrong = CmdResult(0, json.dumps({"type": "text", "part": {"text": "hello there"}}) + "\n", "")
    for answer in (wrong, CmdResult(0, "", "")):
        out, _ = probe(GO, "hello", {("run",): answer}, make_ctx)
        assert not out.ok and out.reason == "unexpected reply" and out.failure_class == "other"


def test_the_adapter_probe_is_the_v2_probe_and_never_starts_opencode(make_ctx):
    """A v2 adapter's every step runs `opencode2`: the fake PATH holds both binaries, and none of the calls is v1's."""
    rules = {("run",): out_of("hello-ok-step-finish.jsonl"), ("auth", "list"): out_of("auth-list-env-key.json")}
    run = SpyRun({**V2_VERSION, **rules})
    ctx, _ = make_ctx({}, run=run)
    for step in ("binary", "auth", "quota", "hello"):
        assert OpenCodeV2Adapter().probe(GO, step, ctx).ok
    assert {os.path.basename(c[0][0]) for c in run.calls} == {"opencode2"}
