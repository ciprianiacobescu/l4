import pytest
from pricing.tips import tip_cents


@pytest.mark.l4("C-ce541739")
def test_a_tip_that_is_already_whole_cents():
    assert tip_cents(1000, 15) == 150


@pytest.mark.l4("C-c0f2ea95")
def test_a_half_cent_rounds_up():
    assert tip_cents(1005, 10) == 101
    assert tip_cents(1004, 10) == 100
