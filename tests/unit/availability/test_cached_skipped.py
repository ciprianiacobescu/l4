"""M1.12 line 4 (L4-AVL-005/008): a profile skipped on a remembered failure says so."""

import json
import logging

import pytest

from l4.agents import factory as factory_module
from l4.agents.base import ProbeResult
from l4.agents.factory import Factory, WaitingCapacity
from l4.availability.cooldown import AvailabilityStore
from l4.availability.fallback import Skipped, format_skipped_line
from l4.cli import main

from ._selection_helpers import Scripted, Sink, config, fake_profile, later, probe_ctx, world

PROFILE = fake_profile("sonnet", vendor="anthropic", auth="subscription")
FAILED = {"sonnet": {"hello": ProbeResult("hello", False, reason="unexpected reply", failure_class="other")}}


def build(tmp_path, sink=None):
    clock, store = world(tmp_path)
    cfg = config({"claude-sonnet": PROFILE}, implementer=["claude-sonnet"])
    adapter = Scripted(FAILED)
    factory = Factory(
        cfg, probe_ctx(tmp_path), events=sink, adapters={"fake": adapter}, availability=store, clock=clock
    )
    return factory, clock


def test_the_skipped_line_ends_with_the_cached_age_and_the_way_to_reprobe():
    cached = Skipped("p", "hello", "unexpected reply", cached=True, age_s=185)
    assert format_skipped_line("judges", cached) == (
        "[l4] judges: p skipped — hello: unexpected reply (cached 3m ago; l4 probe --no-cache re-probes)"
    )
    assert "cached" not in format_skipped_line("judges", Skipped("p", "hello", "unexpected reply"))


def test_a_run_inside_the_window_prints_cached_and_a_fresh_one_does_not(tmp_path, caplog):
    sink = Sink()
    factory, clock = build(tmp_path, sink)
    with caplog.at_level(logging.INFO, logger="l4"), pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    later(clock, minutes=3)
    with caplog.at_level(logging.INFO, logger="l4"), pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    fresh, second = (r.getMessage() for r in caplog.records)
    assert fresh == "claude-sonnet skipped — hello: unexpected reply"
    assert second == ("claude-sonnet skipped — hello: unexpected reply (cached 3m ago; l4 probe --no-cache re-probes)")
    first_event, second_event = (e["skipped"][0] for e in sink.of("availability.unavailable"))
    assert "cached" not in first_event and "age_s" not in first_event
    assert second_event["cached"] is True and second_event["age_s"] == 180


def test_probe_json_carries_cached_and_age(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "version: 1\nprofiles:\n  b: {adapter: fake, model: sonnet, vendor: anthropic, auth: subscription}\n"
        "roles:\n  implementer: [b]\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(factory_module.ADAPTERS, "fake", lambda: Scripted(FAILED))
    environ = {"L4_CACHE": str(tmp_path / "cache"), "HOME": str(tmp_path), "PATH": "/usr/bin"}
    args = ["probe", "--json", "--config", str(cfg), "--repo", str(repo)]
    main(args, environ=environ)
    first = json.loads(capsys.readouterr().out)["profiles"][0]
    assert first["cached"] is False and first["age_s"] is None
    main(args, environ=environ)
    second = json.loads(capsys.readouterr().out)["profiles"][0]
    assert second["cached"] is True and isinstance(second["age_s"], int | float) and second["age_s"] >= 0
    main([*args[:2], "--no-cache", *args[2:]], environ=environ)
    forced = json.loads(capsys.readouterr().out)["profiles"][0]
    assert forced["cached"] is False and forced["age_s"] is None
    assert AvailabilityStore(tmp_path / "cache").path.exists()
    main(["probe", "--config", str(cfg), "--repo", str(repo)], environ=environ)
    assert "(cached 0m ago; l4 probe --no-cache re-probes)" in capsys.readouterr().out
