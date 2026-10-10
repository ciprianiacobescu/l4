"""W-D1: `gates.test_timeout`, the limit of one test (SPEC L4-GAT-004)."""

import pytest
from pydantic import ValidationError

from l4.config.schema import GatesCfg


def test_auto_is_ten_minutes_under_the_default_gate_timeout():
    assert GatesCfg().test_timeout_seconds() == 600


def test_auto_is_half_of_a_short_gate_timeout():
    assert GatesCfg(timeout="4m").test_timeout_seconds() == 120


def test_an_explicit_value_is_taken_and_zero_switches_it_off():
    assert GatesCfg(test_timeout="90s").test_timeout_seconds() == 90
    assert GatesCfg(test_timeout="0s").test_timeout_seconds() == 0


@pytest.mark.parametrize("value", ["30m", "45m", "2h"])
def test_a_test_limit_that_is_not_shorter_than_the_gate_is_refused(value):
    with pytest.raises(ValidationError, match="shorter than gates.timeout"):
        GatesCfg(test_timeout=value)


def test_garbage_is_refused():
    with pytest.raises(ValidationError):
        GatesCfg(test_timeout="soon")
