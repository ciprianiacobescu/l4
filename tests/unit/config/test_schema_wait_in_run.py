"""`availability.wait_in_run` and `wait_in_run_max_total` (L4-AVL-011): a bare YAML `0` switches the wait off."""

import pytest
import yaml

from l4.config.schema import AvailabilityCfg, duration_seconds


@pytest.mark.parametrize("text", ["0", '"0"', "0s", "90s", "5m"])
def test_wait_in_run_accepts_zero_as_a_yaml_int_or_a_string_and_durations(text):
    cfg = AvailabilityCfg.model_validate(yaml.safe_load(f"wait_in_run: {text}"))
    assert duration_seconds(cfg.wait_in_run) == (0 if text.strip('"') in ("0", "0s") else duration_seconds(text))


def test_defaults_are_five_and_fifteen_minutes():
    cfg = AvailabilityCfg()
    assert (cfg.wait_in_run, cfg.wait_in_run_max_total) == ("5m", "15m")


@pytest.mark.parametrize("text", ["-1", "1.5", "true", "false", "5 min", "abc"])
def test_wait_in_run_rejects_other_values(text):
    with pytest.raises(ValueError):
        AvailabilityCfg.model_validate(yaml.safe_load(f"wait_in_run: {text}"))
