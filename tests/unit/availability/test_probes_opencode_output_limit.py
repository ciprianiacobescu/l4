"""SCN-FAC-52 (hello and `auth` step of OpenCode 1), SCN-FAC-57 (the hello's 400 clause), SCN-OCV-52 (the hello and the
`auth list` step of OpenCode 2): the hello asks with the profile's output limit, `auth list` never does (L4-FAC-023,
L4-OCV-020). No binary is started."""

import json
import re

from l4.agents.opencode import OUTPUT_TOKEN_ENV, OpenCodeAdapter
from l4.agents.opencode_v2 import OpenCodeV2Adapter
from l4.config.schema import Profile
from l4.doctor.context import CmdResult

from .conftest import RECORDED
from .test_probes_opencode_v2 import GO_MODEL, OC2, V2_VERSION

OC = RECORDED / "opencode" / "1.18.33"
V1_VERSION = {("--version",): CmdResult(0, "1.18.34\n", "")}
OK = CmdResult(0, (OC / "hello-ok-stdin-prompt.jsonl").read_text(), "")
V2_OK = CmdResult(0, (OC2 / "hello-ok-step-finish.jsonl").read_text(), "")
CLAUSE = "; options.max_output_tokens is set: a provider refuses a maximum output above the model's own (HTTP 400)"


def v1(key: bool, model: str = "opencode-go/deepseek-v4.1-flash", vendor: str = "deepseek") -> Profile:
    options = {"max_output_tokens": 65536} if key else {}
    return Profile(adapter="opencode", model=model, vendor=vendor, options=options)


def v2(key: bool, model: str = GO_MODEL) -> Profile:
    options = {"cli_major": 2, **({"max_output_tokens": 65536} if key else {})}
    return Profile(adapter="opencode", model=model, vendor="deepseek", options=options)


def normalised(env: dict) -> str:
    """The hello's configuration text with its scratch directory (a fresh temporary one per call) made equal."""
    text = env["OPENCODE_CONFIG_CONTENT"]
    return re.sub(r"l4-opencode2?-probe-[A-Za-z0-9_]+", "l4-probe-X", text)


def call_of(run, name: str):
    return next(c for c in reversed(run.calls) if c[0][1] == name)


def hello(adapter, profile, rules, make_ctx):
    ctx, run = make_ctx(rules)
    return adapter.probe(profile, "hello", ctx), run


def error_event(status: int, message: str = "bad request") -> str:
    data = {"message": message, "statusCode": status}
    return json.dumps({"type": "error", "sessionID": "ses_x", "error": {"name": "APIError", "data": data}}) + "\n"


def v2_error_event(status: int) -> str:
    return json.dumps({"type": "error", "sessionID": "ses_x", "error": {"type": "x", "status": status}}) + "\n"


def v2_error_event_with(status: int, message: str) -> str:
    error = {"type": "x", "status": status, "message": message}
    return json.dumps({"type": "error", "sessionID": "ses_x", "error": error}) + "\n"


# --- OpenCode 1 ---


def test_a_v1_hello_runs_with_the_variable_and_the_unchanged_configuration(make_ctx):
    out, run = hello(OpenCodeAdapter(), v1(True), {**V1_VERSION, ("run",): OK}, make_ctx)
    assert out.ok
    env = call_of(run, "run")[2]
    assert env[OUTPUT_TOKEN_ENV] == "65536"
    _, plain = hello(OpenCodeAdapter(), v1(False), {**V1_VERSION, ("run",): OK}, make_ctx)
    plain_env = call_of(plain, "run")[2]
    assert OUTPUT_TOKEN_ENV not in plain_env
    assert normalised(env) == normalised(plain_env)  # SCN-FAC-52: the hello's configuration equals the run's, whole


HOST_VALUE = "99999"


def test_the_hosts_own_value_never_reaches_the_hello(make_ctx):
    ctx, run = make_ctx({**V1_VERSION, ("run",): OK})
    ctx.environ[OUTPUT_TOKEN_ENV] = HOST_VALUE
    assert OpenCodeAdapter().probe(v1(False), "hello", ctx).ok
    assert OUTPUT_TOKEN_ENV not in call_of(run, "run")[2]
    assert OpenCodeAdapter().probe(v1(True), "hello", ctx).ok
    assert call_of(run, "run")[2][OUTPUT_TOKEN_ENV] == "65536"


def test_the_v1_auth_step_does_not_get_the_variable(make_ctx):
    listing = CmdResult(0, (OC / "auth_list.stdout.txt").read_text(), "")
    profile = v1(True, "google/gemini-3.5-flash", "google")
    ctx, run = make_ctx({**V1_VERSION, ("auth", "list"): listing})
    assert OpenCodeAdapter().probe(profile, "auth", ctx).ok
    assert run.calls[-1][0][1:] == ["auth", "list"] and OUTPUT_TOKEN_ENV not in run.calls[-1][2]


def test_the_hosts_own_value_never_reaches_the_v1_auth_step(make_ctx):
    listing = CmdResult(0, (OC / "auth_list.stdout.txt").read_text(), "")
    for key in (True, False):
        ctx, run = make_ctx({**V1_VERSION, ("auth", "list"): listing})
        ctx.environ[OUTPUT_TOKEN_ENV] = HOST_VALUE
        assert OpenCodeAdapter().probe(v1(key, "google/gemini-3.5-flash", "google"), "auth", ctx).ok
        assert run.calls[-1][0][1:] == ["auth", "list"] and OUTPUT_TOKEN_ENV not in run.calls[-1][2]


def test_a_v1_hello_400_with_the_key_names_the_key(make_ctx):
    rules = {**V1_VERSION, ("run",): CmdResult(1, error_event(400), "")}
    out, _ = hello(OpenCodeAdapter(), v1(True), rules, make_ctx)
    assert not out.ok and out.reason == f"opencode reported an error (status 400){CLAUSE}"


def test_a_v1_hello_400_without_the_key_or_with_another_status_is_todays_text(make_ctx):
    plain, _ = hello(
        OpenCodeAdapter(), v1(False), {**V1_VERSION, ("run",): CmdResult(1, error_event(400), "")}, make_ctx
    )
    assert plain.reason == "opencode reported an error (status 400)"
    other, _ = hello(
        OpenCodeAdapter(), v1(True), {**V1_VERSION, ("run",): CmdResult(1, error_event(404), "")}, make_ctx
    )
    assert other.reason == "opencode reported an error (status 404)"


def test_a_v1_hello_grammar_failure_gets_no_clause(make_ctx):
    stdout = error_event(400, "grammar binding failed")
    out, _ = hello(OpenCodeAdapter(), v1(True), {**V1_VERSION, ("run",): CmdResult(1, stdout, "")}, make_ctx)
    assert out.reason == "opencode reported an error (status 400)"


# --- OpenCode 2 ---


def overlay(env: dict) -> dict | None:
    return json.loads(env["OPENCODE_CONFIG_CONTENT"]).get("providers")


def test_a_v2_hello_carries_the_overlay_and_no_environment_holds_the_variable(make_ctx):
    out, run = hello(OpenCodeV2Adapter(), v2(True), {**V2_VERSION, ("run",): V2_OK}, make_ctx)
    assert out.ok
    env = call_of(run, "run")[2]
    assert overlay(env) == {"opencode-go": {"models": {"deepseek-v4.1-flash": {"limit": {"output": 65536}}}}}
    assert all(OUTPUT_TOKEN_ENV not in call[2] for call in run.calls)
    _, plain = hello(OpenCodeV2Adapter(), v2(False), {**V2_VERSION, ("run",): V2_OK}, make_ctx)
    assert overlay(call_of(plain, "run")[2]) is None


def test_the_v2_auth_list_step_keeps_the_configuration_without_the_overlay(make_ctx):
    listing = CmdResult(0, (OC2 / "auth-list-env-key.json").read_text(), "")
    rules = {**V2_VERSION, ("auth", "list"): listing}
    ctx, run = make_ctx(rules)
    assert OpenCodeV2Adapter().probe(v2(True), "auth", ctx).ok
    keyed_env = run.calls[-1][2]
    assert run.calls[-1][0][1:3] == ["auth", "list"]
    ctx, run = make_ctx(rules)
    assert OpenCodeV2Adapter().probe(v2(False), "auth", ctx).ok
    keyed = keyed_env["OPENCODE_CONFIG_CONTENT"]
    assert keyed == run.calls[-1][2]["OPENCODE_CONFIG_CONTENT"] and "providers" not in keyed
    assert OUTPUT_TOKEN_ENV not in keyed_env and OUTPUT_TOKEN_ENV not in run.calls[-1][2]  # no variable in either


def test_the_hosts_own_value_never_reaches_a_v2_hello_or_auth_step(make_ctx):
    for key in (True, False):
        ctx, run = make_ctx({**V2_VERSION, ("run",): V2_OK})
        ctx.environ[OUTPUT_TOKEN_ENV] = HOST_VALUE
        assert OpenCodeV2Adapter().probe(v2(key), "hello", ctx).ok
        assert all(OUTPUT_TOKEN_ENV not in call[2] for call in run.calls)
        listing = CmdResult(0, (OC2 / "auth-list-env-key.json").read_text(), "")
        ctx, run = make_ctx({**V2_VERSION, ("auth", "list"): listing})
        ctx.environ[OUTPUT_TOKEN_ENV] = HOST_VALUE
        assert OpenCodeV2Adapter().probe(v2(key), "auth", ctx).ok
        assert all(OUTPUT_TOKEN_ENV not in call[2] for call in run.calls)


def test_a_v2_hello_400_with_the_key_names_the_key(make_ctx):
    rules = {**V2_VERSION, ("run",): CmdResult(1, v2_error_event(400), "")}
    out, _ = hello(OpenCodeV2Adapter(), v2(True), rules, make_ctx)
    assert not out.ok and out.reason == f"opencode2 reported an error (status 400){CLAUSE}"
    plain, _ = hello(OpenCodeV2Adapter(), v2(False), rules, make_ctx)
    assert plain.reason == "opencode2 reported an error (status 400)"
    other = {**V2_VERSION, ("run",): CmdResult(1, v2_error_event(404), "")}
    assert hello(OpenCodeV2Adapter(), v2(True), other, make_ctx)[0].reason == "opencode2 reported an error (status 404)"


def test_a_v2_hello_grammar_failure_gets_no_clause(make_ctx):
    rules = {**V2_VERSION, ("run",): CmdResult(1, v2_error_event_with(400, "grammar binding failed"), "")}
    out, _ = hello(OpenCodeV2Adapter(), v2(True), rules, make_ctx)
    assert not out.ok and out.reason == "opencode2 reported an error (status 400)"
    plain = {**V2_VERSION, ("run",): CmdResult(1, v2_error_event_with(400, "not a grammar problem"), "")}
    assert hello(OpenCodeV2Adapter(), v2(True), plain, make_ctx)[0].reason.endswith(CLAUSE)
