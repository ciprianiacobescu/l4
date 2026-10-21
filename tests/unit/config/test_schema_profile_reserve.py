"""G15: `profiles.<p>.min_remaining_percent` overrides the global reserve for one profile."""

import pytest
from pydantic import ValidationError

from l4.config.schema import L4Config, Profile


def test_profile_reserve_bounds():
    assert Profile().min_remaining_percent is None
    assert Profile(min_remaining_percent=0).min_remaining_percent == 0
    assert Profile(min_remaining_percent=100).min_remaining_percent == 100
    assert Profile(min_remaining_percent=37.5).min_remaining_percent == 37.5
    for bad in (-0.1, 100.1):
        with pytest.raises(ValidationError):
            Profile(min_remaining_percent=bad)


def test_profile_reserve_loads_from_a_config_mapping_and_the_global_default_is_unchanged():
    cfg = L4Config.model_validate({"profiles": {"c": {"adapter": "codex", "min_remaining_percent": 40}}})
    assert cfg.profiles["c"].min_remaining_percent == 40
    assert cfg.availability.min_remaining_percent == 10
