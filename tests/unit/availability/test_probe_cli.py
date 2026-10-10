"""agent-factory 9.5: `l4 probe [PROFILE...] [--role R] [--json] [--no-cache]`."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from l4.agents import factory as factory_module
from l4.availability.cooldown import AvailabilityStore
from l4.cli import main

from ._selection_helpers import Scripted, exhausted, healthy

CONFIG = """\
version: 1
profiles:
  codex-a: {adapter: fake, model: gpt-6, vendor: openai, auth: subscription}
  claude-b: {adapter: fake, model: sonnet, vendor: anthropic, auth: subscription}
roles:
  implementer: [codex-a, claude-b]
  judges: [claude-b]
"""


@pytest.fixture
def world(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    cache = tmp_path / "cache"
    adapter = Scripted({**healthy("gpt-6", version="0.160.0"), **healthy("sonnet")})
    monkeypatch.setitem(factory_module.ADAPTERS, "fake", lambda: adapter)
    environ = {"L4_CACHE": str(cache), "HOME": str(tmp_path), "PATH": "/usr/bin"}

    def run(*args: str) -> int:
        return main(["probe", *args, "--config", str(cfg), "--repo", str(repo)], environ=environ)

    return run, adapter, AvailabilityStore(cache)


def out_json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_json_lists_every_step_the_cooldowns_and_the_file(world, capsys):
    run, adapter, store = world
    assert run("--json") == 0
    doc = out_json(capsys)
    assert doc["schema"] == "l4/probe@1" and doc["availability_file"] == str(store.path)
    assert [p["profile"] for p in doc["profiles"]] == ["codex-a", "claude-b"]  # every profile any role uses, once
    first = doc["profiles"][0]
    assert first["status"] == "ok" and first["cached"] is False
    assert [s["step"] for s in first["steps"]] == ["binary", "auth", "quota", "hello"]
    assert first["steps"][0]["detail"] == {"version": "0.160.0"} and doc["cooldowns"] == []


def test_the_human_output_uses_the_spec_8_4_style(world, capsys):
    run, _, store = world
    assert run() == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == (
        "[l4] probe: codex-a ok (binary 0.160.0 · auth subscription · quota 49% used (session) · hello 2.1s)"
    )
    assert lines[-1] == f"[l4] probe: availability file {store.path}"


def test_a_second_probe_is_served_from_the_cache_and_no_cache_probes_again(world, capsys):
    run, adapter, _ = world
    run("--json")
    capsys.readouterr()
    calls = len(adapter.calls)
    run("--json")
    again = out_json(capsys)
    assert all(p["cached"] for p in again["profiles"]) and len(adapter.calls) == calls
    run("--json", "--no-cache")
    fresh = out_json(capsys)
    assert not any(p["cached"] for p in fresh["profiles"]) and len(adapter.calls) == calls + 8


def test_a_cooling_profile_is_not_probed_and_the_exit_is_12(world, capsys):
    run, adapter, store = world
    until = datetime.now(UTC) + timedelta(hours=2)
    store.cooldowns.record("codex-a", ("fake", "gpt-6"), until, "usage_limit", "test")
    assert run("codex-a", "--json") == 12
    doc = out_json(capsys)
    assert doc["profiles"][0]["status"] == "cooling" and doc["profiles"][0]["steps"] == []
    assert doc["profiles"][0]["cooling_until"] == until.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert [c["profile"] for c in doc["cooldowns"]] == ["codex-a"] and adapter.calls == []
    assert run("codex-a") == 12
    assert "codex-a skipped — cooling until" in capsys.readouterr().out


def test_no_cache_reprobes_and_json_lists_steps(world, capsys):
    run, adapter, store = world
    store.cooldowns.record(
        "codex-a", ("fake", "gpt-6"), datetime.now(UTC) + timedelta(hours=2), "usage_limit", "forced"
    )
    assert run("codex-a", "--no-cache", "--json") == 0  # a passing ladder ends the cool-down
    doc = out_json(capsys)
    profile = doc["profiles"][0]
    assert profile["status"] == "ok" and profile["cooldown_cleared"] is True
    assert [s["step"] for s in profile["steps"]] == ["binary", "auth", "quota", "hello"]
    assert doc["cooldowns"] == [] and store.cooldowns.entries() == []
    assert adapter.probed("gpt-6") == ["binary", "auth", "quota", "hello"]


def test_a_failing_ladder_with_a_limit_records_a_cooldown_and_exits_12(world, capsys, monkeypatch):
    run, _, store = world
    adapter = Scripted({**exhausted("gpt-6"), **healthy("sonnet")})
    monkeypatch.setitem(factory_module.ADAPTERS, "fake", lambda: adapter)
    assert run("--role", "implementer") == 12
    text = capsys.readouterr().out
    assert (
        "codex-a skipped — quota: 5h window 100% used, 0% remaining (resets 2026-10-03T14:32Z); cool-down recorded"
        in text
    )
    assert "claude-b ok (" in text and "cooling fake|gpt-6 until" in text
    assert [c.profile for c in store.cooldowns.entries(datetime(2026, 10, 3, tzinfo=UTC))] == ["codex-a"]


def test_role_and_profile_arguments_are_validated(world, capsys):
    run, _, _ = world
    assert run("--role", "judges", "--json") == 0
    assert [p["profile"] for p in out_json(capsys)["profiles"]] == ["claude-b"]
    assert run("nope") == 2 and "no such profile: nope" in capsys.readouterr().err
    assert run("--role", "nonsense") == 2 and "not a role" in capsys.readouterr().err


def test_a_profile_no_adapter_can_serve_is_reported_not_a_crash(world, capsys, tmp_path):
    run, _, _ = world
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG.replace("roles:", "  api: {backend: openai-chat, model: x}\nroles:"), encoding="utf-8")
    assert run("api", "--json") == 12
    profile = out_json(capsys)["profiles"][0]
    assert profile["status"] == "unsupported" and "backend" in profile["reason"]


def test_no_cache_text_line_says_the_cooldown_was_cleared(world, capsys):
    run, _, store = world
    store.cooldowns.record(
        "codex-a", ("fake", "gpt-6"), datetime.now(UTC) + timedelta(hours=2), "usage_limit", "forced"
    )
    assert run("codex-a", "--no-cache") == 0
    assert capsys.readouterr().out.splitlines()[0].endswith(" · cool-down cleared")
