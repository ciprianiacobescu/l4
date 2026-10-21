import pytest
from billing.fees import late_fee_cents


@pytest.mark.l4("C-69d3cfd0", "C-a6a0f5c9")
def test_within_the_grace_period_there_is_no_fee():
    assert late_fee_cents(10000, 3) == 0
    assert late_fee_cents(10000, 5) == 0
    assert late_fee_cents(10000, 9) == 200


@pytest.mark.l4("C-a6a0f5c9")
def test_after_the_grace_period_the_fee_is_a_share_of_the_balance():
    assert late_fee_cents(10000, 9) == 200
    assert late_fee_cents(10000, 6) == 200
