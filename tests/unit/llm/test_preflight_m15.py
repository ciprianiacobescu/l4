"""Preflight, M1.5 (plan line 38): the e2e gate needs a test writer; a System-One profile needs its engine's keys."""

import pytest

from l4.config.preflight import preflight_run_config
from l4.exitcodes import ExitCode, L4Exit

from .test_agent_judge_roles import app, cfg, roles

E2E = {"gates": {"e2e": {
    "command": "pytest e2e", "reports": ["r.xml"], "format": "junit",
    "serve": {"command": "python app.py", "ready_url": "http://127.0.0.1:8000/"},
}}}  # fmt: skip


def s1_profile(**fields):
    return {"profiles": {
        "claude-c": {"adapter": "claude-code", "model": "sonnet", "auth": "subscription"},
        "codex-a": {"adapter": "codex", "model": "m", "auth": "subscription", "vendor": "openai"},
        "s1": {"backend": "system-one", **fields},
    }, "roles": {"implementer": ["codex-a"], "judges": ["claude-c"], "s1_judge": ["s1"]}}


def refused(tmp_path, config, needle):
    with pytest.raises(L4Exit) as err:
        preflight_run_config(app(tmp_path), config)
    assert err.value.code == ExitCode.USAGE_ERROR and needle in str(err.value)


def test_e2e_with_playwright_needs_a_verifier_agent(tmp_path):
    refused(tmp_path, cfg(**roles(), **E2E), "roles.verifier_agent")
    preflight_run_config(app(tmp_path), cfg(**roles(verifier_agent=["claude-s"]), **E2E))


@pytest.mark.parametrize(
    ("change", "needle"),
    [
        ({"reports": []}, "reports"),
        ({"format": "playwright-json"}, "gates.e2e.format"),
        ({"serve": {"command": "", "ready_url": "http://127.0.0.1:8000/"}}, "serve.command"),
        ({"serve": {"command": "python app.py", "ready_url": ""}}, "serve.ready_url"),
    ],
)
def test_a_half_configured_e2e_gate_is_refused_before_a_run(tmp_path, change, needle):
    e2e = {"gates": {"e2e": {**E2E["gates"]["e2e"], **change}}}
    refused(tmp_path, cfg(**roles(verifier_agent=["claude-s"]), **e2e), needle)


def test_e2e_without_playwright_or_without_a_command_needs_none(tmp_path):
    off = {**E2E, "verifier": {"playwright": {"enabled": False}}}
    preflight_run_config(app(tmp_path), cfg(**roles(), **off))
    preflight_run_config(app(tmp_path), cfg(**roles()))


@pytest.mark.parametrize(
    ("fields", "needle"),
    [
        ({}, "profiles.s1.engine"),
        ({"engine": "gpt"}, "profiles.s1.engine"),
        ({"engine": "remote"}, "profiles.s1.base_url"),
        ({"engine": "jev"}, "profiles.s1.api_key_env"),
    ],
)
def test_a_system_one_profile_needs_its_engine_and_keys(tmp_path, fields, needle):
    refused(tmp_path, cfg(**s1_profile(**fields)), needle)


@pytest.mark.parametrize(
    "fields",
    [
        {"engine": "laya-local"},
        {"engine": "remote", "base_url": "http://127.0.0.1:8790"},
        {"engine": "jev", "api_key_env": "TYPESAFE_API_KEY"},
    ],
)
def test_a_complete_system_one_profile_passes(tmp_path, fields):
    preflight_run_config(app(tmp_path), cfg(**s1_profile(**fields)))
