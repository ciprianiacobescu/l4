"""The probe ladder for an opencode profile that declares its own provider: the key is present (by variable name
only), the host answers, and the hello goes through the provider. A machine that is down is `unavailable`, never an
error, and neither the key nor the URL's path appears in any reason or detail."""

import json
import re
from pathlib import Path

import httpx
import pytest

import l4.agents.opencode_provider as provider
from l4.agents.opencode import OpenCodeAdapter
from l4.config.schema import Profile
from l4.doctor.context import CmdResult

from .conftest import RECORDED

OC = RECORDED / "opencode" / "1.18.33"
MODEL = "qwen3.6-35b-a3b:gguf:q5"
KEY = "sk-magnitude-test-0123456789abcdef"
URL = "http://192.0.2.10:10100/inference/v1"
MAG = Profile(
    adapter="opencode", model=f"magnitude/{MODEL}", auth="api_key", vendor="alibaba",
    options={
        "provider": {
            "id": "magnitude", "base_url": URL, "api_key_env": "MAGNITUDE_API_KEY",
            "models": {MODEL: {"context": 262144, "output": 16384}},
        },
        "tools": ["bash", "read"], "reasoning": "none",
    },
)  # fmt: skip
VERSION = {("--version",): CmdResult(0, "1.18.34\n", "")}


class SpyRun:
    """FakeRun that reads the key file at the moment `opencode run` starts (the probe's scratch dir goes away after)."""

    def __init__(self, rules):
        self.rules, self.calls, self.key_text = rules, [], None

    def __call__(self, argv, cwd, env, timeout):
        self.calls.append((list(argv), cwd, dict(env), timeout))
        if "OPENCODE_CONFIG_CONTENT" in env:
            ref = json.loads(env["OPENCODE_CONFIG_CONTENT"])["provider"]["magnitude"]["options"]["apiKey"]
            self.key_text = Path(re.fullmatch(r"\{file:(.+)\}", ref).group(1)).read_text()
        for key, result in self.rules.items():
            if tuple(argv[1 : 1 + len(key)]) == key:
                return result
        return CmdResult(127, "", "no rule")


def serve(monkeypatch, handler):
    monkeypatch.setattr(provider, "TRANSPORT", httpx.MockTransport(handler))


def up(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, json={"error": "no key"})  # reachable: the host answers even without a key


def down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused")


def run_probe(step, make_ctx, rules=None, environ_extra=None):
    ctx, _ = make_ctx({})
    run = SpyRun({**VERSION, **(rules or {})})
    ctx = ctx.__class__(**{**ctx.__dict__, "run": run, "environ": {**ctx.environ, **(environ_extra or {})}})
    return OpenCodeAdapter().probe(MAG, step, ctx), run


def test_auth_is_the_presence_of_the_key_variable_never_its_value(make_ctx):
    out, run = run_probe("auth", make_ctx, environ_extra={"MAGNITUDE_API_KEY": KEY})
    assert out.ok and out.detail == {"provider": "magnitude", "host": "192.0.2.10:10100", "key": "present"}
    assert KEY not in json.dumps(out.detail)
    assert not any(c[0][1:2] == ["auth"] for c in run.calls)  # `opencode auth list` knows nothing of a file key


def test_auth_without_the_variable_fails_naming_the_variable(make_ctx):
    out, _ = run_probe("auth", make_ctx)
    assert not out.ok and "MAGNITUDE_API_KEY" in (out.reason or "")


def test_quota_is_skipped(make_ctx):
    out, _ = run_probe("quota", make_ctx)
    assert out.ok and out.skipped


def test_hello_goes_through_the_provider_with_the_key_in_a_file_only(make_ctx, monkeypatch):
    serve(monkeypatch, up)
    ok = CmdResult(0, (OC / "hello-ok-stdin-prompt.jsonl").read_text(), "")
    out, run = run_probe("hello", make_ctx, {("run",): ok}, {"MAGNITUDE_API_KEY": KEY})
    assert out.ok
    call = run.calls[-1]
    assert run.key_text == KEY
    assert "-m" in call[0] and call[0][call[0].index("-m") + 1] == f"magnitude/{MODEL}"
    assert KEY not in json.dumps(call[2]) and KEY not in " ".join(call[0])
    assert "MAGNITUDE_API_KEY" not in call[2]


def test_a_machine_that_is_down_is_unavailable_and_nothing_is_spawned(make_ctx, monkeypatch):
    serve(monkeypatch, down)
    out, run = run_probe("hello", make_ctx, environ_extra={"MAGNITUDE_API_KEY": KEY})
    assert not out.ok and "192.0.2.10:10100" in (out.reason or "") and "unreachable" in (out.reason or "")
    assert not any("run" in c[0][1:2] for c in run.calls)
    assert KEY not in (out.reason or "") and "/inference" not in (out.reason or "")


def test_hello_without_the_key_does_not_spawn_opencode(make_ctx, monkeypatch):
    serve(monkeypatch, up)
    out, run = run_probe("hello", make_ctx)
    assert not out.ok and "MAGNITUDE_API_KEY" in (out.reason or "")
    assert not any("run" in c[0][1:2] for c in run.calls)


def test_reachable_reports_a_401_as_up_and_never_sends_a_credential(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"], seen["url"] = request.headers.get("authorization"), str(request.url)
        return httpx.Response(401)

    serve(monkeypatch, handler)
    ok, why = provider.reachable(URL)
    assert ok and "HTTP 401" in why and seen == {"auth": None, "url": f"{URL}/models"}


def test_reachable_timeout_says_asleep_without_the_url_path(monkeypatch):
    def slow(request):
        raise httpx.ReadTimeout("slow")

    serve(monkeypatch, slow)
    ok, why = provider.reachable(URL)
    assert not ok and "asleep" in why and "/inference" not in why


@pytest.mark.parametrize("env", [{}, {"MAGNITUDE_API_KEY": ""}])
def test_an_empty_key_counts_as_missing(make_ctx, env):
    out, _ = run_probe("auth", make_ctx, environ_extra=env)
    assert not out.ok
