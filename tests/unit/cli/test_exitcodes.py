import itertools

import pytest

from l4.exitcodes import SEVERITY_ORDER, ExitCode, L4Exit, most_severe


def test_most_severe_order_exhaustive():
    assert SEVERITY_ORDER == (1, 16, 2, 3, 14, 15, 13, 11, 12, 10, 0)
    assert set(SEVERITY_ORDER) == {int(c) for c in ExitCode}
    for a, b in itertools.product(SEVERITY_ORDER, repeat=2):
        expected = SEVERITY_ORDER[min(SEVERITY_ORDER.index(a), SEVERITY_ORDER.index(b))]
        assert most_severe([a, b]) == expected
    assert most_severe([]) is ExitCode.OK


def test_a_rejected_unit_outranks_a_halted_one():
    """M1.11 W4: a halt is a warning in CI, a rejected unit (an invalid spec on the base) is still a failure, so a run
    with one of each must stay red."""
    assert most_severe([13, 14]) is ExitCode.REJECTED
    assert most_severe([14, 13, 0]) is ExitCode.REJECTED
    assert most_severe([13, 11]) is ExitCode.HALTED  # but a halt still outranks the waiting codes
    assert most_severe([3, 14]) is ExitCode.DOCTOR_FAILED


def test_lower_codes_never_mask_a_higher_one():
    assert most_severe([10, 12, 13, 11]) is ExitCode.HALTED
    assert most_severe([0, 1, 14]) is ExitCode.INTERNAL_ERROR


def test_unknown_code_raises_value_error():
    with pytest.raises(ValueError):
        most_severe([0, 7])


def test_l4exit_carries_code_and_message():
    exc = L4Exit(ExitCode.USAGE_ERROR, "bad")
    assert exc.code is ExitCode.USAGE_ERROR
    assert str(exc) == "bad"


def test_a_regression_outranks_a_halt_and_yields_to_a_rejected_unit():
    """M1.14 D7: 15 (`l4 eval --compare` found a regression) is a failure, not a designed stop."""
    assert most_severe([13, 15]) is ExitCode.REGRESSION
    assert most_severe([14, 15]) is ExitCode.REJECTED
    assert most_severe([0, 15, 10]) is ExitCode.REGRESSION
    assert int(ExitCode.REGRESSION) == 15
