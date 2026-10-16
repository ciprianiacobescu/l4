"""`implementer.heartbeat` and `implementer.idle_timeout` minimums (L4-IMP-023, L4-IMP-024, SCN-IMP-205)."""

import pytest
import yaml

from l4.config.schema import ImplementerCfg


def load(text: str) -> ImplementerCfg:
    return ImplementerCfg.model_validate(yaml.safe_load(text))


def test_an_idle_timeout_below_one_minute_names_the_key_and_the_minimum():
    with pytest.raises(ValueError, match=r"implementer\.idle_timeout.*1m"):
        load("idle_timeout: 30s")


def test_a_heartbeat_below_thirty_seconds_names_the_key_and_the_minimum():
    with pytest.raises(ValueError, match=r"implementer\.heartbeat.*30s"):
        load("heartbeat: 5s")


def test_both_keys_zero_load_as_off_whether_int_or_string():
    for text in ("heartbeat: 0\nidle_timeout: 0", 'heartbeat: "0"\nidle_timeout: 0s'):
        cfg = load(text)
        assert cfg.heartbeat in ("0", "0s") and cfg.idle_timeout in ("0", "0s")


def test_the_defaults_and_the_minimums_themselves_load():
    assert (ImplementerCfg().idle_timeout, ImplementerCfg().heartbeat) == ("10m", "2m")
    cfg = load("idle_timeout: 60s\nheartbeat: 30s")
    assert (cfg.idle_timeout, cfg.heartbeat) == ("60s", "30s")
    assert load("idle_timeout: 1m\nheartbeat: 1h").heartbeat == "1h"
