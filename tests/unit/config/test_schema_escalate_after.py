"""`implementer.escalate_after` (escalate-and-note 0.1, L4-IMP-017): default 2, `0` is off, below 0 is refused."""

import pytest
import yaml

from l4.config.schema import ImplementerCfg


def test_default_is_two():
    assert ImplementerCfg().escalate_after == 2


def test_zero_loads():
    assert ImplementerCfg.model_validate(yaml.safe_load("escalate_after: 0")).escalate_after == 0


@pytest.mark.parametrize("text", ["-1", "1.5", "abc", '"2"', "true"])
def test_other_values_are_refused(text):
    with pytest.raises(ValueError):
        ImplementerCfg.model_validate(yaml.safe_load(f"escalate_after: {text}"))
